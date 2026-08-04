# Contributing to pkg-doctor

## Workflow

All changes go through a pull request against `main` — nobody, including maintainers, pushes directly.

1. **Fork** this repo (button top-right on GitHub) — you'll push your changes to your own fork, not here.
2. Clone your fork and set up the dev environment:
   ```bash
   git clone https://github.com/<your-username>/pkg-doctor.git
   cd pkg-doctor
   pip install -e ".[dev]"
   pytest tests/
   ```
3. Create a branch for your change: `git checkout -b add-cargo-lock-support`
4. Make your change, add tests, commit.
5. Push to **your fork**: `git push origin add-cargo-lock-support`
6. Open a PR from your fork's branch against `DevMohith/pkg-doctor:main`. GitHub shows a
   "Compare & pull request" button after you push — that's the easiest way to start it.
7. CI (`.github/workflows/tests.yml`) runs automatically on the PR across Windows/macOS/Linux —
   it needs to be green before merge.

## Adding support for a new manifest format

This is the most useful contribution and doesn't require touching anything else in the codebase.
`pkg_doctor/scanner.py` has one parser function per format, all following the same shape:

```python
def _parse_something(path: Path):
    packages = []
    try:
        # read + parse path
    except (OSError, ValueError):
        return packages
    # for each resolved dependency:
    packages.append(PackageRef(ecosystem="...", name="...", version="...", manifest_path=path))
    return packages
```

(`requirements.txt` and `pom.xml` also return a second list of `(description, path)` tuples for
entries that can't be resolved to an exact version — see `_parse_requirements_txt` for the pattern.)

To wire in a new format:

1. Write `_parse_<format>(path: Path)` in `scanner.py`, following an existing parser as a template —
   `_parse_go_sum` for a simple line-based format, `_parse_pnpm_lock_yaml` for YAML,
   `_parse_poetry_lock` for TOML.
2. Add the filename to `SUPPORTED_MANIFESTS`.
3. Add the dispatch branch in `discover_projects()`.
4. Use the correct [OSV.dev ecosystem name](https://ossf.github.io/osv-schema/#affectedpackage-field)
   for the `ecosystem` field (e.g. `"PyPI"`, `"npm"`, `"Go"`, `"Maven"`, `"crates.io"`, `"RubyGems"`).
5. Add tests to `tests/test_scanner.py` — copy the shape of an existing test, use `tmp_path` to write
   a realistic fixture file and assert on the parsed `PackageRef`s.
6. Update the "Supported manifests" table in `README.md`.

**Formats currently in the "found but not yet supported" bucket** (a good place to start):
`Pipfile.lock`, `Gemfile.lock`. Anything else discovered without a parser is reported the same way —
never silently ignored.

## Ground rules

- **Never filter detection by name-guessing.** The one time this project did that (matching env var
  names like `*_API_KEY`), it missed a real, live credential in testing. Manifest parsers extract
  every resolved dependency; the secrets scanner (`secrets_scan.py`) surfaces every assignment. Let
  the human judge, don't decide for them.
- **No auto-rotation, ever.** Every credential rotation in `remediation.py` requires an explicit `y`
  from the user before anything happens (opening a dashboard, nothing more automated than that).
- **Nothing gets scanned without `--path`, nothing leaves the machine except `{ecosystem, name,
  version}` sent to OSV.dev.** Don't add telemetry, don't add a default scan scope.
- Keep dependencies minimal. Adding one should be a deliberate call (see the `pyyaml`/`tomli`
  additions in git history for the reasoning), not a convenience import.

## Tests

`pytest tests/` runs fully offline — `test_osv_client.py` mocks `requests.post` and redirects the
cache directory to a temp path, so it never hits the network or your real `~/.pkg_doctor`. Keep new
tests offline the same way.

## Pull requests

Small, focused PRs are easiest to review — one manifest format or one bug fix per PR. Explain the
*why* in the description if it's not obvious from the diff.
