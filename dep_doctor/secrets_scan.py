import re
from dataclasses import dataclass
from pathlib import Path

SECRET_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "config.json", "secrets.json", "credentials.json", ".npmrc",
}

# (provider label, regex, confidence). High-confidence patterns match a known key shape exactly;
# the generic pattern only flags a NAME=value line that looks secret-ish, so it's marked low confidence.
SECRET_PATTERNS = [
    ("OpenAI", re.compile(r"sk-[A-Za-z0-9]{20,}"), "high"),
    ("Anthropic", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"), "high"),
    ("Google/Gemini", re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "high"),
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}"), "high"),
    ("GitHub Token", re.compile(r"ghp_[A-Za-z0-9]{36}"), "high"),
    (
        "Generic (unverified)",
        re.compile(r"[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN)\s*=\s*[\"']?([^\"'\s]{8,})[\"']?", re.IGNORECASE),
        "low",
    ),
]


@dataclass
class SecretFinding:
    provider: str
    confidence: str
    file_path: Path
    masked_value: str


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


_CONFIDENCE_RANK = {"high": 1, "low": 0}


def find_secrets(project_dir: Path):
    """
    Scan a fixed allowlist of well-known config filenames for key-shaped strings. Never reads or returns raw
    values outside this function. A value matching both a specific pattern (e.g. OpenAI) and the generic
    fallback pattern is reported once, under the more specific, higher-confidence label.
    """
    best_by_value = {}  

    for filename in SECRET_FILENAMES:
        file_path = project_dir / filename
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for provider, pattern, confidence in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1) if match.groups() else match.group(0)
                dedup_key = (file_path, value)
                existing = best_by_value.get(dedup_key)
                if existing is None or _CONFIDENCE_RANK[confidence] > _CONFIDENCE_RANK[existing[1]]:
                    best_by_value[dedup_key] = (provider, confidence)

    return [
        SecretFinding(provider=provider, confidence=confidence, file_path=file_path, masked_value=_mask(value))
        for (file_path, value), (provider, confidence) in best_by_value.items()
    ]
