import os
import json
import logging
import litellm
import vertexai
from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration, Part


log = logging.getLogger(__name__)


# Default model dictionary per provider

PROVIDER_DEFAULTS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-20241022",
    "gemini": "gemini/gemini-2.0-flash-001",
    "vertex_ai": "vertex_ai/gemini-2.0-flash-001",
    "azure": "azure/gpt-4o",
    "groq": "groq/llama-3.3-70b-versatile",
    "moonshot": "moonshot/moonshot-v1-8k",
    "kimi": "moonshot/moonshot-v1-8k",
}

ALL_PROVIDERS = list(PROVIDER_DEFAULTS.keys())


def get_model_string() -> str:
    provider = os.environ.get("AGENTOS_LLM_PROVIDER", "vertex_ai")
    default  = PROVIDER_DEFAULTS.get(provider, "vertex_ai/gemini-2.0-flash-001")
    return os.environ.get("AGENTOS_LLM_MODEL", default)


# ----  -- Public interface----------------------------------------
def generate_text(prompt: str, max_tokens: int = 800, temperature: float = 0.4) -> str:
    """
    Simple prompt → text generation. No tools. Uses configured provider.
    Falls back to Vertex AI SDK if litellm not installed.
    """
    try:
        _configure_litellm()
        litellm.suppress_debug_info = True
        response = litellm.completion(
            model=get_model_string(),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()
    except ImportError:
        log.warning("[LLMAdapter] litellm not installed — using Vertex AI fallback for text")
        return _vertexai_generate_text(prompt, max_tokens, temperature)


def run_react_loop(
    goal: str,
    tools:list, 
    dispatch_fn,             
    system_prompt: str,
    max_iterations: int = 15,
) -> str:
    try:
        return _litellm_loop(goal, tools, dispatch_fn, system_prompt, max_iterations)
    except ImportError:
        log.warning("[LLMAdapter] litellm not installed — using Vertex AI fallback for ReAct loop")
        return _vertexai_loop(goal, tools, dispatch_fn, system_prompt, max_iterations)


# ----LiteLLM implementation (primary path)----------------------------
def _configure_litellm():
    """
    Map AgentOS env vars (set by apply_config_to_env) → provider-specific env vars
    that LiteLLM reads internally.
    """
    provider = os.environ.get("AGENTOS_LLM_PROVIDER", "vertex_ai")
    api_key  = os.environ.get("AGENTOS_API_KEY", "")

    if provider == "vertex_ai":
        litellm.vertex_project  = os.environ.get("GCP_PROJECT_ID", "")
        litellm.vertex_location = os.environ.get("GCP_REGION", "us-central1")

    elif provider == "openai" and api_key:
        os.environ.setdefault("OPENAI_API_KEY", api_key)

    elif provider == "anthropic" and api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", api_key)

    elif provider == "gemini" and api_key:
        os.environ.setdefault("GEMINI_API_KEY",  api_key)
        os.environ.setdefault("GOOGLE_API_KEY",  api_key)

    elif provider == "groq" and api_key:
        os.environ.setdefault("GROQ_API_KEY", api_key)

    elif provider in ("moonshot", "kimi") and api_key:
        os.environ.setdefault("MOONSHOT_API_KEY", api_key)

    elif provider == "azure" and api_key:
        os.environ.setdefault("AZURE_API_KEY", api_key)
        if os.environ.get("AGENTOS_AZURE_BASE"):
            os.environ.setdefault("AZURE_API_BASE", os.environ["AGENTOS_AZURE_BASE"])
        if os.environ.get("AGENTOS_AZURE_VERSION"):
            os.environ.setdefault("AZURE_API_VERSION", os.environ["AGENTOS_AZURE_VERSION"])


def _litellm_loop(goal, tools, dispatch_fn, system_prompt, max_iterations):
    litellm.suppress_debug_info = True
    _configure_litellm()

    model    = get_model_string()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": goal},
    ]

    print(f"[LLMAdapter] Provider: {os.environ.get('AGENTOS_LLM_PROVIDER', 'vertex_ai')} | Model: {model}")

    for iteration in range(max_iterations):
        response = litellm.completion(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        # No tool calls → final answer
        if not msg.tool_calls:
            return (msg.content or "").strip()

        # Append assistant turn (with tool_calls)
        messages.append({
            "role":       "assistant",
            "content":    msg.content or "",
            "tool_calls": msg.tool_calls,
        })

        # Execute each tool, append results
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            result  = dispatch_fn(fn_name, fn_args)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      json.dumps(result),
            })

    return "Agent completed- successfully followed ReAct loop"


# --------- Vertex AI fallback (no litellm needed) ------------------
def _vertexai_generate_text(prompt: str, max_tokens: int, temperature: float) -> str:
    vertexai.init(
        project=os.getenv("GCP_PROJECT_ID"),
        location=os.getenv("GCP_REGION", "us-central1"),
    )
    model = GenerativeModel("gemini-2.0-flash-001")
    resp  = model.generate_content(
        prompt,
        generation_config={"max_output_tokens": max_tokens, "temperature": temperature},
    )
    return resp.text.strip()


def _vertexai_loop(goal, tools, dispatch_fn, system_prompt, max_iterations):
    """
    Fallback ReAct loop using Vertex AI SDK directly.
    Converts OpenAI-format tool dicts → FunctionDeclaration objects.
    """
    vertexai.init(
        project=os.getenv("GCP_PROJECT_ID"),
        location=os.getenv("GCP_REGION", "us-central1"),
    )

    # Convert OpenAI tool format → Vertex AI FunctionDeclarations
    declarations = [
        FunctionDeclaration(
            name=t["function"]["name"],
            description=t["function"]["description"],
            parameters=t["function"]["parameters"],
        )
        for t in tools
    ]

    vtool    = Tool(function_declarations=declarations)
    model    = GenerativeModel(
        "gemini-2.0-flash-001",
        tools=[vtool],
        system_instruction=system_prompt,
    )
    chat     = model.start_chat()
    response = chat.send_message(goal)

    print("[LLMAdapter] Using Vertex AI fallback | Model: gemini-2.0-flash-001")

    for _ in range(max_iterations):
        parts = response.candidates[0].content.parts
        calls = [p for p in parts if p.function_call and p.function_call.name]

        if not calls:
            return " ".join(
                p.text for p in parts if hasattr(p, "text") and p.text
            ).strip()

        tool_responses = []
        for part in calls:
            fc     = part.function_call
            result = dispatch_fn(fc.name, dict(fc.args))
            tool_responses.append(
                Part.from_function_response(name=fc.name, response=result)
            )
        response = chat.send_message(tool_responses)

    return "Agent completed (reached iteration limit)"
