import webbrowser

import click

PROVIDER_DASHBOARDS = {
    "OpenAI": "https://platform.openai.com/api-keys",
    "Anthropic": "https://console.anthropic.com/settings/keys",
    "Google/Gemini": "https://aistudio.google.com/app/apikey",
    "AWS Access Key": "https://console.aws.amazon.com/iam/home#/security_credentials",
    "GitHub Token": "https://github.com/settings/tokens",
}

RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"


def run_remediation(finding, project_dir) -> str:
    """
    Present one secret finding to the user and, only on explicit confirmation, walk them through
    a browser-guided manual rotation. Never rotates anything automatically. Returns "rotated" or "skipped".
    """
    label = "Provider" if finding.confidence == "high" else "Variable"
    click.echo(f"\n  {YELLOW}Possible exposed secret{RESET} ({finding.confidence} confidence)")
    click.echo(f"    {label}:  {finding.provider}")
    click.echo(f"    File:     {finding.file_path}")
    click.echo(f"    Value:    {finding.masked_value}")

    if not click.confirm("  Rotate this key now?", default=False):
        return "skipped"

    url = PROVIDER_DASHBOARDS.get(finding.provider)
    if url:
        click.echo(f"  Opening {url} ...")
        try:
            webbrowser.open(url)
        except Exception:
            click.echo(f"  Could not open a browser automatically - visit: {url}")
    else:
        click.echo("  No known dashboard for this provider - check where this key was issued and revoke it there.")

    click.echo("    1. Revoke/delete the old key in the dashboard.")
    click.echo("    2. Generate a new key.")
    click.echo(f"    3. Update it in {project_dir}")
    click.prompt("  Press Enter once you've rotated the key", default="", show_default=False)
    click.echo(f"  {GREEN}Marked as rotated (confirmed by you).{RESET}")
    return "rotated"
