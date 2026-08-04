import json
import time
from pathlib import Path

import requests

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
CONFIG_DIR = Path.home() / ".dep_doctor"
CACHE_FILE = CONFIG_DIR / "osv_cache.json"
CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_key(ecosystem: str, name: str, version: str) -> str:
    return f"{ecosystem}:{name}:{version}"


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except OSError:
        pass


def check_packages(pkgs) -> dict:
    """
    pkgs: iterable of scanner.PackageRef.
    Sends only {ecosystem, name, version} to OSV.dev — no file contents, paths, or secrets.
    Returns: {"ecosystem:name:version": [vuln_id, ...]}
    """
    cache = _load_cache()
    now = time.time()

    unique = {}
    for pkg in pkgs:
        unique[_cache_key(pkg.ecosystem, pkg.name, pkg.version)] = pkg

    results = {}
    to_query = []
    query_keys = []

    for key, pkg in unique.items():
        cached = cache.get(key)
        if cached and (now - cached.get("checked_at", 0)) < CACHE_TTL_SECONDS:
            results[key] = cached.get("vuln_ids", [])
            continue
        to_query.append(pkg)
        query_keys.append(key)

    if to_query:
        body = {
            "queries": [
                {"package": {"name": pkg.name, "ecosystem": pkg.ecosystem}, "version": pkg.version}
                for pkg in to_query
            ]
        }
        try:
            resp = requests.post(OSV_BATCH_URL, json=body, timeout=30)
            resp.raise_for_status()
            batch_results = resp.json().get("results", [])
        except (requests.RequestException, ValueError):
            batch_results = [{} for _ in to_query]

        for key, entry in zip(query_keys, batch_results):
            vulns = entry.get("vulns", []) if isinstance(entry, dict) else []
            vuln_ids = [v.get("id") for v in vulns if v.get("id")]
            results[key] = vuln_ids
            cache[key] = {"checked_at": now, "vuln_ids": vuln_ids}

        _save_cache(cache)

    return results


def is_malicious(vuln_id: str) -> bool:
    """OSV ingests the OpenSSF malicious-packages feed with a MAL- prefix — distinct from an ordinary CVE/GHSA advisory."""
    return vuln_id.startswith("MAL-")


def vuln_url(vuln_id: str) -> str:
    return f"https://osv.dev/vulnerability/{vuln_id}"
