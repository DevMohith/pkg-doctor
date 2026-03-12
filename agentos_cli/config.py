import os
import json
from pathlib import Path

CONFIG_DIR  = Path.home() / ".agentos"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_SERVER_URL = "http://127.0.0.1:8003"

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def apply_config_to_env(config: dict):
    """
    Push config values into environment variables so llm_adapter.py picks them up.
    Sets: AGENTOS_LLM_PROVIDER, AGENTOS_LLM_MODEL, AGENTOS_API_KEY
    Plus provider-specific vars (GCP creds, Azure base URL, etc.)
    """
    provider = config.get("llm_provider", "vertex_ai")
    model    = config.get("llm_model", "")
    api_key  = config.get("api_key", "")

    os.environ["AGENTOS_LLM_PROVIDER"] = provider
    if model:
        os.environ["AGENTOS_LLM_MODEL"] = model
    if api_key:
        os.environ["AGENTOS_API_KEY"] = api_key

    # provider specific extras
    if provider == "vertex_ai":
        creds = config.get("gcp_credentials_file", "")
        if creds and os.path.isfile(creds):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds
        if config.get("gcp_project_id"):
            os.environ["GCP_PROJECT_ID"] = config["gcp_project_id"]
        os.environ["GCP_REGION"] = config.get("gcp_region", "us-central1")

    elif provider == "azure":
        if config.get("azure_base"):
            os.environ["AGENTOS_AZURE_BASE"]    = config["azure_base"]
        if config.get("azure_version"):
            os.environ["AGENTOS_AZURE_VERSION"] = config["azure_version"]

    if config.get("organizer_email"):
        os.environ["MICROSOFT_ORGANIZER_EMAIL"] = config["organizer_email"]


def get_server_url(config: dict) -> str:
    """Returns the AgentOS server URL - local fallback if not set."""
    return config.get("server_url", DEFAULT_SERVER_URL)


def config_is_valid(config: dict) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if not config:
        return False, "No config found. Run: agentos init"

    provider = config.get("llm_provider", "vertex_ai")

    if provider == "vertex_ai":
        creds = config.get("gcp_credentials_file", "")
        if not creds or not os.path.isfile(creds):
            return False, f"GCP credentials file not found: '{creds}'. Run: agentos init"
        if not config.get("gcp_project_id"):
            return False, "GCP project ID missing. Run: agentos init"

    elif provider in ("openai", "anthropic", "gemini", "groq", "moonshot", "kimi", "azure"):
        if not config.get("api_key"):
            return False, f"API key missing for provider '{provider}'. Run: agentos init"

    if not config.get("organizer_email"):
        return False, "Organizer email missing. Run: agentos init"

    return True, ""
