import json
import re
from dataclasses import dataclass
from pathlib import Path

ENV_STYLE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".npmrc",
}
JSON_STYLE_FILENAMES = {"config.json", "secrets.json", "credentials.json"}
SECRET_FILENAMES = ENV_STYLE_FILENAMES | JSON_STYLE_FILENAMES

# Value-shape patterns for well-known providers. These exist only to give a flagged value a more
# specific, confident label when it happens to match — they are NOT the thing that decides whether
# to flag a value in the first place. Variable/key names are never used as a filter: anyone can name
# a credential anything, so every assignment in an env-style file (and every string value in a JSON
# config file) is surfaced and left for the human to judge.
KNOWN_SHAPES = [
    ("OpenAI", re.compile(r"^sk-[A-Za-z0-9]{20,}$")),
    ("Anthropic", re.compile(r"^sk-ant-[A-Za-z0-9\-]{20,}$")),
    ("Google/Gemini", re.compile(r"^AIza[0-9A-Za-z_\-]{35}$")),
    ("AWS Access Key", re.compile(r"^AKIA[0-9A-Z]{16}$")),
    ("GitHub Token", re.compile(r"^ghp_[A-Za-z0-9]{36}$")),
]

_ENV_LINE_RE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.:/-]*)\s*=\s*(.*)$')


@dataclass
class SecretFinding:
    provider: str        # a known provider name, or the variable/key name it was found under
    confidence: str       # "high" (matched a known key shape) | "low" (unverified — surfaced regardless)
    file_path: Path
    masked_value: str


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _classify(value: str):
    for provider, pattern in KNOWN_SHAPES:
        if pattern.match(value):
            return provider, "high"
    return None, "low"


def _parse_env_style(text: str):
    """Every NAME=VALUE assignment line, comments/blanks skipped, quotes stripped. No name filtering."""
    pairs = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            pairs.append((name, value))
    return pairs


def _walk_json_strings(node, path=""):
    """Every string leaf value in a JSON document, paired with its dotted key path. No key filtering."""
    pairs = []
    if isinstance(node, dict):
        for key, value in node.items():
            pairs.extend(_walk_json_strings(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            pairs.extend(_walk_json_strings(value, f"{path}[{i}]"))
    elif isinstance(node, str) and node:
        pairs.append((path, node))
    return pairs


def find_secrets(project_dir: Path):
    """
    Scan a fixed allowlist of well-known config filenames. Every assignment in an env-style file, and
    every string value in a JSON config file, is surfaced — nothing is filtered by variable/key name.
    Never reads or returns raw values outside this function.
    """
    best_by_value = {}  # (file_path, raw_value) -> (label, confidence)

    for filename in SECRET_FILENAMES:
        file_path = project_dir / filename
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        if filename in ENV_STYLE_FILENAMES:
            pairs = _parse_env_style(text)
        else:
            try:
                pairs = _walk_json_strings(json.loads(text))
            except (ValueError, TypeError):
                pairs = []

        for name, value in pairs:
            provider, confidence = _classify(value)
            label = provider or name
            dedup_key = (file_path, value)
            existing = best_by_value.get(dedup_key)
            if existing is None or (confidence == "high" and existing[1] == "low"):
                best_by_value[dedup_key] = (label, confidence)

    return [
        SecretFinding(provider=label, confidence=confidence, file_path=file_path, masked_value=_mask(value))
        for (file_path, value), (label, confidence) in best_by_value.items()
    ]
