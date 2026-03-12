# AgentOS Runtime

AI Agent CLI for workplace automation — schedule meetings, generate workflows, and automate repetitive tasks using natural language.

```bash
pip install agentos-runtime
agentos init
agentos schedule "invite john@company.com to onboarding sync tomorrow at 2pm"
agentos workflow "Create a Workflow Definition for AgentOS Website to execute Enterprise Process Automation"
```

---

## What it does

AgentOS Runtime gives you a terminal command (`agentos`) that uses an AI agent (ReAct loop with LLM function calling) to:

- **Schedule Teams meetings** from plain English — the agent reasons about your request, generates a rich meeting agenda, opens Outlook, and sends the invite
- **Attach files** (PDF, Word, invoices) to meeting invites
- **Generate agentic workflows** for multi-step enterprise processes (requires AgentOS backend)

---

## Requirements

- Python 3.10+
- Windows (Outlook COM automation requires Outlook desktop installed and logged in)
- One of: Gemini API key, OpenAI API key, Anthropic API key, GCP service account, or any LiteLLM-supported provider

---

## Install

```bash
pip install agentos-runtime
```

---

## Setup

```bash
agentos init
```

The setup wizard asks you:
1. Which LLM provider (OpenAI, Anthropic, Gemini, Vertex AI, Groq, Azure, Kimi...)
2. Your API key or GCP service account path
3. Your Outlook email (must be logged into Outlook desktop)
4. AgentOS server URL (leave default if running locally)

Config is saved to `~/.agentos/config.json` — your keys stay on your machine.

---

## Usage

### Schedule a Teams meeting

```bash
agentos schedule "invite sarah@company.com to 1:1 sync tomorrow at 3pm"

agentos schedule "onboarding kickoff for John on April 20 at 10am for 2 hours"

agentos schedule "PROCESS.AI discussion with team@co.com on 15/04 from 14:00 to 16:00" \
  -a project_brief.pdf \
  -a onboarding_checklist.docx
```

The agent will:
1. Resolve the date and time
2. Ask for any missing attendee emails via a popup
3. Generate a full meeting agenda using the LLM
4. Open Outlook and send the invite with all attachments

### Generate a workflow

```bash
# Requires AgentOS backend running: python run.py
agentos workflow "onboard a new employee with HR, IT and procurement steps"
agentos workflow "laptop procurement with manager approval" --name laptop_flow
```

### Manage config

```bash
agentos config show                          
agentos config set organizer_email x@co.com  
agentos config set server_url https://api.yourdomain.com
```

### commands sheet
```bash
agentos --help
```

---

## Supported LLM Providers

| Provider | How to configure |
|---|---|
| OpenAI (GPT-4o, GPT-4-turbo) | API key from platform.openai.com |
| Anthropic (Claude Sonnet/Opus) | API key from console.anthropic.com |
| Google Gemini | API key from aistudio.google.com |
| Google Vertex AI | GCP service account JSON + project ID |
| Groq (LLaMA, Mixtral) | API key from console.groq.com |
| Kimi / Moonshot | API key from platform.moonshot.cn |
| Azure OpenAI | API key + endpoint URL |

Switch provider anytime: `agentos config set llm_provider openai`

---

## How it works

```
agentos schedule "..."
       │
       ▼
CLI loads ~/.agentos/config.json → sets env vars
       │
       ▼
ReAct Loop (LLM reasons + calls tools):
  1. get_current_date      → resolves relative dates
  2. ask_user_for_input    → popup for missing emails
  3. generate_agenda       → LLM writes meeting email body
  4. schedule_meeting      → Outlook COM creates + sends invite
       │
       ▼
Outlook opens live → invite delivered to attendees
```

---

## License

MIT — see [LICENSE](LICENSE)
