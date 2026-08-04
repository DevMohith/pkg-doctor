import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml

EXCLUDE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", ".next", "target",
}

SUPPORTED_MANIFESTS = {
    "requirements.txt", "package-lock.json",
    "poetry.lock", "yarn.lock", "pnpm-lock.yaml", "go.sum",
    "gradle.lockfile", "pom.xml",
}
KNOWN_UNSUPPORTED_MANIFESTS = {"Pipfile.lock", "Gemfile.lock", "build.gradle", "build.gradle.kts"}


@dataclass
class PackageRef:
    ecosystem: str 
    name: str
    version: str
    manifest_path: Path


@dataclass
class ProjectManifest:
    project_dir: Path
    packages: list = field(default_factory=list) 
    unparsed_pinned: list = field(default_factory=list)      
    unsupported_manifests: list = field(default_factory=list)  


def _parse_requirements_txt(path: Path):
    packages = []
    unpinned = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return packages, unpinned

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split(" #", 1)[0].strip()
        if "==" in line:
            name, _, version = line.partition("==")
            name = name.strip().split(";")[0].strip().split("[")[0].strip()
            version = version.strip().split(";")[0].strip()
            if name and version:
                packages.append(PackageRef(ecosystem="PyPI", name=name, version=version, manifest_path=path))
        else:
            unpinned.append((line, path))
    return packages, unpinned


def _parse_package_lock_json(path: Path):
    packages = []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return packages

    pkgs = data.get("packages")
    if isinstance(pkgs, dict):
        # npm lockfile v2/v3: {"": {...root...}, "node_modules/foo": {"version": "1.2.3"}, ...}
        for key, entry in pkgs.items():
            if not key or not isinstance(entry, dict):
                continue
            version = entry.get("version")
            if not version:
                continue
            name = key.rsplit("node_modules/", 1)[-1]
            packages.append(PackageRef(ecosystem="npm", name=name, version=version, manifest_path=path))
    else:
        # npm lockfile v1: {"dependencies": {"foo": {"version": "1.2.3", ...}}}
        deps = data.get("dependencies")
        if isinstance(deps, dict):
            for name, entry in deps.items():
                if isinstance(entry, dict) and entry.get("version"):
                    packages.append(PackageRef(ecosystem="npm", name=name, version=entry["version"], manifest_path=path))
    return packages


def _parse_poetry_lock(path: Path):
    packages = []
    try:
        with path.open("rb") as f:
            data = toml.load(f)
    except (OSError, ValueError):
        return packages

    for entry in data.get("package", []):
        name = entry.get("name")
        version = entry.get("version")
        if name and version:
            packages.append(PackageRef(ecosystem="PyPI", name=name, version=version, manifest_path=path))
    return packages


_YARN_VERSION_RE = re.compile(r'^\s*version:?\s*"?([^"\s]+)"?\s*$')


def _yarn_pkg_name(spec: str):
    spec = spec.strip().strip('"').strip("'")
    if not spec:
        return None
    # Scoped packages (@scope/name@range) have a leading @ that isn't the range separator —
    # skip it before searching for the @ that actually splits name from range.
    at_index = spec.find("@", 1) if spec.startswith("@") else spec.find("@")
    if at_index == -1:
        return None
    return spec[:at_index]


def _parse_yarn_lock(path: Path):
    """Handles both classic yarn.lock (v1, custom format) and Berry (v2+, YAML-flavored) stanzas."""
    packages = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return packages

    current_names = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if not line[0].isspace() and line.rstrip().endswith(":"):
            header = line.rstrip()[:-1]
            current_names = [n for spec in header.split(", ") if (n := _yarn_pkg_name(spec))]
            continue

        if current_names:
            match = _YARN_VERSION_RE.match(line)
            if match:
                version = match.group(1)
                for name in current_names:
                    packages.append(PackageRef(ecosystem="npm", name=name, version=version, manifest_path=path))
                current_names = []  

    return packages


def _parse_pnpm_key(key: str):
    key = key.strip()
    paren_index = key.find("(")
    if paren_index != -1:
        key = key[:paren_index]

    if key.startswith("/"):
        # lockfileVersion 5/6: "/name/version" or "/@scope/name/version"
        parts = key[1:].split("/")
        if len(parts) < 2:
            return None, None
        version = parts[-1].split("_")[0]
        name = "/".join(parts[:-1])
        return name, version

    # lockfileVersion 9: "name@version" or "@scope/name@version"
    at_index = key.find("@", 1) if key.startswith("@") else key.find("@")
    if at_index == -1:
        return None, None
    name = key[:at_index]
    version = key[at_index + 1:].split("_")[0]
    return name, version


def _parse_pnpm_lock_yaml(path: Path):
    packages = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, yaml.YAMLError):
        return packages

    if not isinstance(data, dict):
        return packages
    pkgs = data.get("packages")
    if not isinstance(pkgs, dict):
        return packages

    for key in pkgs:
        name, version = _parse_pnpm_key(key)
        if name and version:
            packages.append(PackageRef(ecosystem="npm", name=name, version=version, manifest_path=path))
    return packages


def _parse_go_sum(path: Path):
    packages = []
    seen = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return packages

    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        module, version = parts[0], parts[1].split("/go.mod")[0]
        key = (module, version)
        if key in seen:
            continue
        seen.add(key)
        packages.append(PackageRef(ecosystem="Go", name=module, version=version, manifest_path=path))
    return packages


def _parse_gradle_lockfile(path: Path):
    """Gradle's own dependency-locking output (opt-in via `dependencyLocking { lockAllConfigurations() }`).
    Covers the modern single-file convention, not the legacy per-configuration `gradle/dependency-locks/*.lockfile` files."""
    packages = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return packages

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("empty="):
            continue
        coord = line.split("=", 1)[0]  # strip trailing "=compileClasspath,runtimeClasspath"
        parts = coord.split(":")
        if len(parts) != 3:
            continue
        group_id, artifact_id, version = parts
        packages.append(PackageRef(ecosystem="Maven", name=f"{group_id}:{artifact_id}", version=version, manifest_path=path))
    return packages


def _strip_xml_namespaces(root):
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _parse_pom_xml(path: Path):
    """
    pom.xml is Maven's project definition, not a resolved lockfile — it has no equivalent of
    package-lock.json. Only directly-declared <dependency> blocks with a literal <version> are checked;
    versions inherited from a parent POM/BOM, driven by a ${property}, or expressed as a range are
    reported as unverifiable rather than guessed at.
    """
    packages = []
    unpinned = []
    try:
        root = _strip_xml_namespaces(ET.parse(path).getroot())
    except (OSError, ET.ParseError):
        return packages, unpinned

    for dependencies_el in root.iter("dependencies"):
        for dep in dependencies_el.findall("dependency"):
            group_id = (dep.findtext("groupId") or "").strip()
            artifact_id = (dep.findtext("artifactId") or "").strip()
            if not group_id or not artifact_id:
                continue
            name = f"{group_id}:{artifact_id}"
            version = (dep.findtext("version") or "").strip()
            if not version or version.startswith("${") or any(ch in version for ch in "[](),"):
                unpinned.append((f"{name} ({version or 'version managed elsewhere'})", path))
                continue
            packages.append(PackageRef(ecosystem="Maven", name=name, version=version, manifest_path=path))
    return packages, unpinned


def discover_projects(paths):
    """Walk each path in `paths`, find dependency manifests, and return a ProjectManifest per directory that has one."""
    projects = {}

    for root_path in paths:
        root = Path(root_path).expanduser().resolve()
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            current_dir = Path(dirpath)
            filenames_set = set(filenames)

            found_supported = filenames_set & SUPPORTED_MANIFESTS
            found_unsupported = filenames_set & KNOWN_UNSUPPORTED_MANIFESTS
            if not found_supported and not found_unsupported:
                continue

            manifest = projects.setdefault(current_dir, ProjectManifest(project_dir=current_dir))

            if "requirements.txt" in found_supported:
                pkgs, unpinned = _parse_requirements_txt(current_dir / "requirements.txt")
                manifest.packages.extend(pkgs)
                manifest.unparsed_pinned.extend(unpinned)

            if "package-lock.json" in found_supported:
                manifest.packages.extend(_parse_package_lock_json(current_dir / "package-lock.json"))

            if "poetry.lock" in found_supported:
                manifest.packages.extend(_parse_poetry_lock(current_dir / "poetry.lock"))

            if "yarn.lock" in found_supported:
                manifest.packages.extend(_parse_yarn_lock(current_dir / "yarn.lock"))

            if "pnpm-lock.yaml" in found_supported:
                manifest.packages.extend(_parse_pnpm_lock_yaml(current_dir / "pnpm-lock.yaml"))

            if "go.sum" in found_supported:
                manifest.packages.extend(_parse_go_sum(current_dir / "go.sum"))

            if "gradle.lockfile" in found_supported:
                manifest.packages.extend(_parse_gradle_lockfile(current_dir / "gradle.lockfile"))

            if "pom.xml" in found_supported:
                pkgs, unpinned = _parse_pom_xml(current_dir / "pom.xml")
                manifest.packages.extend(pkgs)
                manifest.unparsed_pinned.extend(unpinned)

            for name in found_unsupported:
                manifest.unsupported_manifests.append(current_dir / name)

    return list(projects.values())
