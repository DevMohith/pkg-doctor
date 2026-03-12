import sys
import os
import click
from agentos_cli import __version__
from agentos_cli.config import (
    load_config,
    save_config,
    apply_config_to_env,
    config_is_valid,
    get_server_url,
    CONFIG_FILE,
    DEFAULT_SERVER_URL,
)
from backend.agents.teams_agent import execute_teams_agent
from backend.agents.llm_adapter import PROVIDER_DEFAULTS
import requests
import json

PURPLE = "\033[95m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

BANNER = f"""
{PURPLE}{BOLD}
  █████╗  ██████╗ ███████╗███╗   ██╗████████╗ ██████╗ ███████╗
 ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝██╔═══██╗██╔════╝
 ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ██║   ██║███████╗
 ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ██║   ██║╚════██║
 ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ╚██████╔╝███████║
 ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚══════╝
{RESET}{CYAN}  Runtime v{__version__} - AI Agent CLI for local agents excution by Mohith Tummala{RESET}
"""


# Root group
@click.group()
@click.version_option(version=__version__, prog_name="agentos", message="%(prog)s %(version)s")
def cli():
    """AgentOS Runtime - schedule meetings, generate workflows, automate let AI work for you."""
    pass


# agentos init
@cli.command()
def init():
    """First-time setup wizard - configure your API keys and organizer email."""
    print(BANNER)
    click.echo(f"{BOLD}Welcome to AgentOS Runtime Engine Setup{RESET}\n")
    click.echo("This wizard will save your settings to: " + str(CONFIG_FILE))
    click.echo("─" * 58)

    config = load_config()

    # LLM provider
    click.echo(f"\n{CYAN}[1] LLM Provider{RESET}")
    click.echo("  1) openai      — OpenAI GPT-4o, GPT-4-turbo  (api key)")
    click.echo("  2) anthropic   — Claude Sonnet, Claude Opus   (api key)")
    click.echo("  3) gemini      — Google Gemini API            (api key, no GCP project)")
    click.echo("  4) vertex_ai   — Google Vertex AI             (GCP service account JSON)")
    click.echo("  5) groq        — Groq LLaMA / Mixtral         (api key, fast + free tier)")
    click.echo("  6) moonshot    — Kimi / Moonshot               (api key)")
    click.echo("  7) azure       — Azure OpenAI                  (api key + endpoint)")

    _PROVIDERS = ["openai", "anthropic", "gemini", "vertex_ai", "groq", "moonshot", "azure"]
    provider = click.prompt(
        "  Choose provider",
        default=config.get("llm_provider", "vertex_ai"),
        type=click.Choice(_PROVIDERS),
    )
    config["llm_provider"] = provider

    # Model
    default_model = PROVIDER_DEFAULTS.get(provider, "")
    click.echo(f"\n{CYAN}[2] Model (press Enter for default: {default_model}){RESET}")
    model = click.prompt("  Model name", default=config.get("llm_model", default_model))
    config["llm_model"] = model

    # Credentials
    if provider == "vertex_ai":
        click.echo(f"\n{CYAN}[3] Google Cloud / Vertex AI credentials{RESET}")
        creds = click.prompt(
            "  Path to GCP service account JSON file",
            default=config.get("gcp_credentials_file", ""),
        )
        project = click.prompt("  GCP Project ID", default=config.get("gcp_project_id", ""))
        region  = click.prompt("  GCP Region",     default=config.get("gcp_region", "us-central1"))
        config["gcp_credentials_file"] = creds
        config["gcp_project_id"]       = project
        config["gcp_region"]           = region

    elif provider == "azure":
        click.echo(f"\n{CYAN}[3] Azure OpenAI credentials{RESET}")
        key     = click.prompt("  Azure API key",           default=config.get("api_key", ""),        hide_input=True)
        base    = click.prompt("  Azure endpoint URL",      default=config.get("azure_base", ""))
        version = click.prompt("  Azure API version",       default=config.get("azure_version", "2024-02-01"))
        config["api_key"]       = key
        config["azure_base"]    = base
        config["azure_version"] = version

    else:
        key_hints = {
            "openai":    "platform.openai.com/api-keys",
            "anthropic": "console.anthropic.com/settings/keys",
            "gemini":    "aistudio.google.com/app/apikey",
            "groq":      "console.groq.com/keys",
            "moonshot":  "platform.moonshot.cn/api-keys",
        }
        hint = key_hints.get(provider, "your provider's dashboard")
        click.echo(f"\n{CYAN}[3] API Key  (get yours at: {hint}){RESET}")
        key = click.prompt("  API key", default=config.get("api_key", ""), hide_input=True)
        config["api_key"] = key

    #Outlook organizer
    click.echo(f"\n{CYAN}[3] Outlook Organizer Email{RESET}")
    click.echo("  This is the email account that will SEND meeting invites.")
    click.echo("  It must be logged into your Outlook desktop app.")
    email = click.prompt(
        "  Your Outlook email",
        default=config.get("organizer_email", ""),
    )
    config["organizer_email"] = email

    # AgentOS Server URL
    click.echo(f"\n{CYAN}[4] AgentOS Server URL{RESET}")
    click.echo("  Used by: agentos workflow (needs a running AgentOS backend)")
    click.echo(f"  Leave default if running locally.  Set to cloud URL if deployed.")
    server_url = click.prompt(
        "  Server URL",
        default=config.get("server_url", DEFAULT_SERVER_URL),
    )
    config["server_url"] = server_url

    #save
    save_config(config)
    click.echo(f"\n{GREEN}✓ Config saved to {CONFIG_FILE}{RESET}")

    local = server_url.startswith("http://127") or server_url.startswith("http://localhost")
    if local:
        click.echo(f"  {CYAN}agentos workflow{RESET} needs the local server running: python run.py")
    else:
        click.echo(f"  {CYAN}agentos workflow{RESET} will call: {server_url}")

    click.echo(f"  {CYAN}agentos schedule{RESET} runs fully locally — no server needed")
    click.echo(f"\n{BOLD}Try:{RESET}")
    click.echo(f'  agentos schedule "invite john@company.com to onboarding sync tomorrow at 2pm"')
    click.echo(f'  agentos workflow "onboard new employee with HR, IT and procurement steps"')
    click.echo()



# agentos schedule
@cli.command()
@click.argument("prompt")
@click.option(
    "--attach", "-a",
    multiple=True,
    type=click.Path(exists=True),
    help="Attach a file to the meeting invite. Can be used multiple times.",
)
@click.option(
    "--interactive", "-i",
    is_flag=True,
    default=False,
    help="Enter prompt interactively (ignores PROMPT argument).",
)
def schedule(prompt, attach, interactive):
    """
    Schedule a Teams meeting using natural language.

    Examples:\n
      agentos schedule "invite sarah@co.com to 1:1 sync tomorrow at 3pm"\n
      agentos schedule "onboarding meeting for John on 15/04 at 10am" -a welcome.pdf\n
      agentos schedule -i
    """
    _ensure_config()

    if interactive:
        click.echo(f"\n{CYAN}Teams Meeting Agent — Interactive Mode{RESET}")
        prompt = click.prompt("Your request")

    attach_paths = list(attach)

    click.echo(f"\n{PURPLE}[AgentOS]{RESET} Starting Teams Meeting Agent...")
    if attach_paths:
        click.echo(f"{PURPLE}[AgentOS]{RESET} Attachments: {', '.join(os.path.basename(p) for p in attach_paths)}")

    try:
        # Import here so CLI starts fast even if deps are slow to load
        execute_teams_agent({"prompt": prompt, "attachment_paths": attach_paths})
        click.echo(f"\n{GREEN}✓ Agent completed. Check Outlook Sent Items.{RESET}\n")
    except Exception as e:
        click.echo(f"\n{RED}✗ Agent error: {e}{RESET}\n", err=True)
        sys.exit(1)


# agentos workflow
@cli.command()
@click.argument("prompt")
@click.option("--name", "-n", default="", help="Workflow name (auto-generated if blank).")
def workflow(prompt, name):
    """
    Generate an agentic workflow definition from natural language.

    Examples:\n
      agentos workflow "onboard a new employee with HR, IT and procurement"\n
      agentos workflow "laptop procurement with manager approval" --name laptop_flow
    """
    cfg = _ensure_config()
    server_url = get_server_url(cfg).rstrip("/")

    workflow_name = name or prompt.split()[:4]
    if isinstance(workflow_name, list):
        workflow_name = "_".join(workflow_name).replace("/", "").replace("\\", "")

    click.echo(f"\n{PURPLE}[AgentOS]{RESET} Generating workflow '{workflow_name}'...")
    click.echo(f"{PURPLE}[AgentOS]{RESET} Server: {server_url}")

    try:
        res = requests.post(
            f"{server_url}/workflows/generate",
            json={"name": workflow_name, "prompt": prompt},
            timeout=30,
        )
        data = res.json()
        if res.status_code == 200:
            import json
            click.echo(f"\n{GREEN}✓ Workflow created — ID: {data['workflow_id']}{RESET}")
            click.echo(json.dumps(data["definition"], indent=2))
        else:
            click.echo(f"\n{RED}✗ Server error: {data}{RESET}", err=True)
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        is_local = "127.0.0.1" in server_url or "localhost" in server_url
        if is_local:
            click.echo(
                f"\n{RED}✗ Cannot reach local AgentOS server at {server_url}{RESET}\n"
                f"  Start the server first:  python run.py\n"
                f"  Or point to a cloud deployment:  agentos config set server_url https://your-api.com\n",
                err=True,
            )
        else:
            click.echo(
                f"\n{RED}✗ Cannot reach AgentOS server at {server_url}{RESET}\n"
                f"  Check that the server is deployed and the URL is correct.\n"
                f"  Update it with:  agentos config set server_url https://your-api.com\n",
                err=True,
            )
        sys.exit(1)



# agentos config
@cli.group()
def config():
    """Show or update AgentOS config settings."""
    pass


@config.command("show")
def config_show():
    """Print current config (API keys are masked)."""
    cfg = load_config()
    if not cfg:
        click.echo("No config found. Run: agentos init")
        return

    display = dict(cfg)
    for key in ("gemini_api_key",):
        if key in display and display[key]:
            display[key] = display[key][:6] + "..." + display[key][-4:]

    click.echo(f"\n{BOLD}AgentOS Config{RESET} ({CONFIG_FILE})\n")
    click.echo(json.dumps(display, indent=2))
    click.echo()


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Update a single config value. Example: agentos config set organizer_email me@outlook.com"""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
    click.echo(f"{GREEN}✓ Set {key} = {value}{RESET}")


# helper---------------------------
def _ensure_config() -> dict:
    """Load config, validate it, apply to env. Exit with message if invalid. Returns config."""
    cfg = load_config()
    valid, err = config_is_valid(cfg)
    if not valid:
        click.echo(f"{RED}✗ {err}{RESET}", err=True)
        sys.exit(1)
    apply_config_to_env(cfg)
    return cfg


if __name__ == "__main__":
    cli()
