import os
import sys
import datetime
import traceback
import multiprocessing
from dotenv import load_dotenv
import tkinter as tk
from tkinter import font as tkfont
import time
import pythoncom
import win32com.client

from backend.agents.llm_adapter import run_react_loop, generate_text

load_dotenv()


# ================= TOOL DECLARATIONS (OpenAI format — works with ALL providers via LiteLLM) ===

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": (
                "Returns today's date and day of week. "
                "Always call this first so you can correctly resolve dates "
                "like 'tomorrow' or 'next Monday'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user_for_input",
            "description": (
                "Shows a popup dialog and returns what the user typed. "
                "Use this to collect attendee email addresses when they are not "
                "already known from the goal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt_text": {
                        "type": "string",
                        "description": "The question or instruction displayed inside the popup.",
                    },
                    "prefill": {
                        "type": "string",
                        "description": "Optional default text pre-filled in the input box.",
                    },
                },
                "required": ["prompt_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_meeting_agenda",
            "description": (
                "Uses AI to write a professional plain-text meeting email body "
                "with a timeline, task list, and preparation notes. "
                "Always call this BEFORE schedule_teams_meeting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title":            {"type": "string",  "description": "Meeting title."},
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes."},
                    "context":          {"type": "string",  "description": "What the meeting is about — purpose, attendees, background."},
                },
                "required": ["title", "duration_minutes", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_teams_meeting",
            "description": (
                "Creates a Teams meeting request in Outlook via COM and sends it to all attendees. "
                "If the Microsoft Teams add-in is active in Outlook, a Teams join link is embedded automatically. "
                "Call this EXACTLY ONCE with all attendees and the full agenda text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title":       {"type": "string", "description": "Meeting subject / title."},
                    "date":        {"type": "string", "description": "Meeting date in YYYY-MM-DD format."},
                    "start_time":  {"type": "string", "description": "Start time in HH:MM (24-hour) format."},
                    "end_time":    {"type": "string", "description": "End time in HH:MM (24-hour) format."},
                    "attendees":   {"type": "array",  "items": {"type": "string"}, "description": "List of attendee email addresses."},
                    "description": {"type": "string", "description": "Full meeting body — use the text_agenda from generate_meeting_agenda."},
                    "attachment_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Absolute local file paths to attach. Only include paths explicitly provided in the goal.",
                    },
                },
                "required": ["title", "date", "start_time", "end_time"],
            },
        },
    },
]


# ============== TOOL IMPLEMENTATIONS - what actually runs when LLM calls a tool ===================

def _impl_get_current_date() -> dict:
    today = datetime.date.today()
    return {
        "date":        today.isoformat(),
        "day_of_week": today.strftime("%A"),
    }


def _impl_generate_meeting_agenda(
    title: str, duration_minutes: int, context: str
) -> dict:
    """Uses the configured LLM to write a professional plain-text meeting email body."""
    prompt = f"""
Write a professional meeting invitation email body in plain text (no HTML, no markdown).

Meeting: {title}
Duration: {duration_minutes} minutes
Context: {context}

Start with a warm welcome paragraph from AgentOS AI Assistant.
Then include:
1. Meeting Objective
2. Timeline (e.g. 0-5 min: Intro, 5-20 min: ...)
3. Discussion Topics
4. Action Items / Tasks (numbered, with [Owner] placeholders)
5. Preparation Notes

Keep it professional, warm, and detailed. Plain text only — no bullet symbols like *, no markdown.
Use dashes for list items. Keep section headers in ALL CAPS.
"""
    text = generate_text(prompt, max_tokens=800, temperature=0.4)
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    return {"text_agenda": text}


def _impl_ask_user_for_input(prompt_text: str, prefill: str = "") -> dict:
    
    value = {"v": ""}
    root  = tk.Tk()
    root.title("AgentOS - Input Required")
    root.geometry("500x210")
    root.resizable(False, False)
    root.configure(bg="#1e1e2e")
    root.attributes("-topmost", True)
    root.lift()

    f     = tkfont.Font(family="Segoe UI", size=10)
    bold  = tkfont.Font(family="Segoe UI", size=11, weight="bold")

    tk.Label(root, text="Teams Meeting Agent", bg="#1e1e2e", fg="#89b4fa",
             font=bold).pack(pady=(16, 2))

    tk.Label(root, text=prompt_text, bg="#1e1e2e", fg="#cdd6f4",
             font=f, wraplength=460, justify="left").pack(pady=(6, 4), padx=20)

    var   = tk.StringVar(value=prefill)
    entry = tk.Entry(root, textvariable=var, font=f,
                     bg="#313244", fg="#cdd6f4",
                     insertbackground="#cdd6f4",
                     relief="flat", width=56)
    entry.pack(pady=4, ipady=7, padx=20)
    entry.focus_set()

    def confirm():
        value["v"] = var.get().strip()
        root.destroy()

    tk.Button(root, text="Submit", command=confirm, font=f,
              bg="#89b4fa", fg="#1e1e2e", relief="flat",
              padx=14, pady=6, cursor="hand2").pack(pady=12)

    root.bind("<Return>", lambda e: confirm())
    root.bind("<Escape>",  lambda e: root.destroy())
    root.mainloop()

    return {"value": value["v"]}


def _impl_schedule_teams_meeting(
    title:            str,
    date:             str,
    start_time:       str,
    end_time:         str,
    attendees:        list = None,
    description:      str  = "",
    attachment_paths: list = None,
) -> dict:

    pythoncom.CoInitialize()
    

    attendees = [e for e in (attendees or []) if e]

    # -------------- Connect to Outlook (prefer already-running instance) --------------------
    print("[TeamsAgent] Connecting to Outlook...")
    try:
        outlook = win32com.client.GetActiveObject("Outlook.Application")
        print("[TeamsAgent] Connected to running Outlook")
    except Exception:
        print("[TeamsAgent] Launching Outlook...")
        outlook = win32com.client.Dispatch("Outlook.Application")
        time.sleep(4)
        print("[TeamsAgent] Outlook launched")

    namespace = outlook.GetNamespace("MAPI")
    organizer = os.getenv("MICROSOFT_ORGANIZER_EMAIL", "")

    # ------------------ Account check: organizer must be logged into Outlook ------------------
    all_accounts = [a.SmtpAddress for a in namespace.Accounts]
    print(f"[TeamsAgent] Outlook accounts logged in: {all_accounts}")

    send_account = next(
        (a for a in namespace.Accounts if a.SmtpAddress.lower() == organizer.lower()),
        None,
    ) if organizer else None

    if organizer and not send_account:
        raise RuntimeError(
            f"Account '{organizer}' is not logged into Outlook.\n"
            f"Open Outlook → File → Add Account → sign in with {organizer}\n"
            f"Accounts currently available: {all_accounts}"
        )

    print(f"[TeamsAgent] Sending from: {organizer if organizer else 'Outlook default account'}")

    # ------------ Build meeting item ------------------------
    meeting               = outlook.CreateItem(1)  
    meeting.Subject       = title
    meeting.MeetingStatus = 1                 

    meeting.Body = description or f"Meeting scheduled by AgentOS AI Assistant.\n\n{title}"

    fmt           = "%Y-%m-%d %H:%M"
    meeting.Start = datetime.datetime.strptime(f"{date} {start_time}", fmt)
    meeting.End   = datetime.datetime.strptime(f"{date} {end_time}",   fmt)

    for email in attendees:
        r      = meeting.Recipients.Add(email)
        r.Type = 1  # olRequired
    meeting.Recipients.ResolveAll()

    if send_account:
        meeting.SendUsingAccount = send_account

    # ---------------- Attach files ------------------
    attached = []
    for path in (attachment_paths or []):
        if os.path.isfile(path):
            meeting.Attachments.Add(path)
            attached.append(os.path.basename(path))
            print(f"[TeamsAgent] Attached: {path}")
        else:
            print(f"[TeamsAgent] Attachment not found, skipping: {path}")

    # ------------- Open the form live so user can see it before sending ---------------
    print("[TeamsAgent] Opening meeting form (live view)...")
    inspector = meeting.GetInspector
    inspector.Activate()   # brings Outlook meeting window to foreground
    time.sleep(2)          # pause so user can see the filled form

    # ------------ Send -----------
    meeting.Send()
    print(f"[TeamsAgent] Sent: '{title}' on {date} {start_time}-{end_time} | {attendees}")

    # Blocking Send/Receive to flush Outbox immediately
    try:
        namespace.SendAndReceive(True)
        print("[TeamsAgent] Outbox flushed — invite transmitted.")
    except Exception as e:
        print(f"[TeamsAgent] Send/Receive note: {e}")

    return {
        "success":     True,
        "subject":     title,
        "date":        date,
        "time":        f"{start_time} - {end_time}",
        "attendees":   attendees,
        "attachments": attached,
        "note":        f"Meeting sent. {len(attached)} file(s) attached." if attached else "Meeting sent. Check Outlook Sent Items.",
    }


# DISPATCHER - routes LLM tool calls to implementations

def _dispatch(name: str, args: dict) -> dict:
    print(f"[TeamsAgent] Tool called  → {name}({args})")
    if name == "get_current_date":
        result = _impl_get_current_date()
    elif name == "generate_meeting_agenda":
        result = _impl_generate_meeting_agenda(**args)
    elif name == "ask_user_for_input":
        result = _impl_ask_user_for_input(**args)
    elif name == "schedule_teams_meeting":
        result = _impl_schedule_teams_meeting(**args)
    else:
        result = {"error": f"Unknown tool: {name}"}
    print(f"[TeamsAgent] Tool result  ← {result}")
    return result

# REACT LOOP - LLM reasons and acts until the goal is complete

_SYSTEM_PROMPT = """
You are a workplace automation agent that schedules Microsoft Teams meetings via Outlook.
You have four tools. Follow this exact sequence every time:

Step 1 — get_current_date: Always call this first to resolve relative dates.
Step 2 — ask_user_for_input: If ANY attendee email is missing or unknown, call this ONCE listing all missing names. Skip if all emails are already in the goal.
Step 3 — generate_meeting_agenda: Call this to generate the full meeting email body as plain text. The result contains a field called "text_agenda".
Step 4 — schedule_teams_meeting: Call this EXACTLY ONCE. Use the "text_agenda" value from step 3 as the "description" argument. Include ALL attendees.
Step 5 — Reply with a single confirmation sentence.

Critical rules:
- NEVER call schedule_teams_meeting more than once per request.
- The "description" argument to schedule_teams_meeting MUST be the full "text_agenda" text returned by generate_meeting_agenda — not a summary, not a short sentence.
- Collect ALL missing emails before generating the agenda or scheduling.
- Never ask the user a question in plain text — only use tools to collect information.
"""

def _run_react_loop(goal: str) -> str:
    """
    Core ReAct loop — provider-agnostic via llm_adapter.
    Works with OpenAI, Anthropic, Gemini, Vertex AI, Groq, Kimi, Azure.
    """
    return run_react_loop(
        goal=goal,
        tools=_TOOLS,
        dispatch_fn=_dispatch,
        system_prompt=_SYSTEM_PROMPT,
        max_iterations=15,
    )


# GOAL BUILDER - constructs a natural-language goal from the payload

def _build_goal(payload: dict) -> str:
    # Explicit natural-language prompt takes priority
    if "prompt" in payload:
        goal = payload["prompt"]
        paths = payload.get("attachment_paths", [])
        if paths:
            names = ", ".join(os.path.basename(p) for p in paths)
            goal += (
                f"\n\nThe user has uploaded the following files to attach to the meeting invite: {names}. "
                f"Pass these exact paths to schedule_teams_meeting as attachment_paths: {paths}"
            )
        return goal

    # Post-onboarding context build descriptive goal
    name  = payload.get("employee_name", "")
    role  = payload.get("role", "")
    email = payload.get("it_email") or payload.get("employee_email", "")

    # Ignore placeholder / fake domains
    if email and (email.endswith("@agentos.com") or "@" not in email):
        email = ""

    goal = (
        f"An employee named '{name}' (role: {role}) has just completed onboarding. "
        f"Schedule a 30-minute welcome Teams meeting for them on the next business day at 10:00 AM. "
    )

    if email:
        goal += f"Their email address is {email}. "
    else:
        goal += "Ask the user for their email address using the ask_user_for_input tool. "

    goal += (
        f"Use a professional and welcoming title that mentions '{name}'. "
        "Call get_current_date first to determine the correct date."
    )

    return goal


# SUBPROCESS ENTRY POINT

def _run_agent_subprocess(payload: dict):
    try:
        print("[TeamsAgent] ── Starting Teams Meeting AI Agent ──")
        goal = _build_goal(payload)
        print(f"[TeamsAgent] Goal: {goal}\n")

        summary = _run_react_loop(goal)
        print(f"\n[TeamsAgent] Agent summary: {summary}")
        print("[TeamsAgent] ── Done ──")

    except Exception:
        print("[TeamsAgent] ERROR:")
        traceback.print_exc()
        sys.exit(1)


# PUBLIC ENTRYPOINT  (engine.py calls this — signature unchanged)

def execute_teams_agent(payload: dict):
    """
    Called by the orchestrator engine after onboarding completes.
    Spawns an isolated subprocess so the async FastAPI event loop is not blocked.
    """
    p = multiprocessing.Process(target=_run_agent_subprocess, args=(payload,))
    p.start()
    p.join()
    if p.exitcode != 0:
        raise RuntimeError(f"TeamsAgent subprocess failed (exit code {p.exitcode})")
