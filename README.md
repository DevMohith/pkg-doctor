# pkg-doctor

Scan your local projects for known-vulnerable or **hijacked** dependencies, and get guided,
human-approved help rotating any API keys that might be exposed as a result.

```bash
pip install pkg-doctor
pkg-doctor --path ./my-project
```

---

## The problem

Every so often a popular package gets compromised - a maintainer's account is hijacked, or malicious
code slips into a new release. When it happens, the advisory that follows always says the same thing:
**"rotate all your API keys."** Nobody actually knows which of their dozen local projects use the
affected version, so people either panic-rotate everything or ignore the warning and hope for the best.

`pkg-doctor` replaces the guessing with one command: it tells you exactly which local projects are
affected, and walks you through fixing exactly those - nothing more.

---

## What it does

```bash
pkg-doctor --path ~/projects/foo
pkg-doctor --path ~/projects/foo --path ~/projects/bar --include-self
```

1. **Scans the directories you name** for dependency manifests (`requirements.txt`, `package-lock.json`)
   - nothing is scanned unless you pass `--path`.
2. **Checks every pinned package against [OSV.dev](https://osv.dev)** - a free, public vulnerability
   database that also ingests the OpenSSF malicious-packages feed, which is exactly the "a package got
   hijacked" case, not just an ordinary CVE. Results are flagged and clearly distinguished:
   `MALICIOUS PACKAGE` vs. `VULNERABLE`.
3. **If a project is flagged**, it checks that project's `.env`/config files - not by guessing at
   variable names (anyone can name a credential anything), but by surfacing *every* assignment for
   you to judge. A value matching a known shape (OpenAI, Anthropic, Google, AWS, GitHub) gets a
   precise high-confidence label; everything else is still surfaced, just marked low-confidence.
   Values are only ever shown masked (`sk-ab12...wx9y`), never logged or transmitted anywhere.
4. **For each possible exposed key, it asks you first.** Nothing is ever rotated automatically. Say
   yes, and it opens the provider's key-management dashboard in your browser and walks you through
   revoking the old key and generating a new one - then waits for your confirmation before moving on.

No API key, no LLM, no account required. It never sends anything more than a package name, ecosystem,
and version to OSV.dev - never file contents, paths, or secret values.

---

## Install

```bash
pip install pkg-doctor
```

Works on Windows, macOS, and Linux - Python 3.10+, only two dependencies (`click`, `requests`).

---

## Usage

```bash
# Scan one project
pkg-doctor --path ./my-project

# Scan several at once
pkg-doctor --path ~/dev/billing-service --path ~/dev/auth-service

# Also audit pkg-doctor's own installed dependencies
pkg-doctor --path ./my-project --include-self

# Skip the config-file scan entirely (vulnerability check only)
pkg-doctor --path ./my-project --skip-secrets
```

Example output:

```
~/dev/billing-service
  MALICIOUS PACKAGE: some-lib==2.1.0 (MAL-2026-4821)
    https://osv.dev/vulnerability/MAL-2026-4821

  Possible exposed secret (high confidence)
    Provider: OpenAI
    File:     ~/dev/billing-service/.env
    Value:    sk-ab12...wx9y
  Rotate this key now? [y/N]:
```

---

## What it deliberately does not do

- **Never rotates anything without your explicit `y`** - no automation, no "trust me" mode.
- **Never touches secrets managers** (HashiCorp Vault, AWS Secrets Manager, etc.) - it only reads local
  flat files (`.env`, `.env.local`, `.env.production`, `.env.development`, `config.json`, `secrets.json`,
  `credentials.json`, `.npmrc`). If your secrets already live in a real vault, this tool has nothing to
  say about them - but the dependency-vulnerability check still applies regardless of where secrets live.
- **Never scans anything you didn't name** - no default-scan-your-whole-drive behavior.
- **Never calls an LLM** - this is plain text/JSON/TOML/YAML parsing plus one REST API call to OSV.dev.
  Nothing here reads or transmits your files through a language model.

---

## Supported manifests

| Ecosystem | File | Notes |
|---|---|---|
| Python (pip) | `requirements.txt` | Exact-pinned `name==version` lines only - unpinned lines are reported separately, not silently skipped |
| Python (Poetry) | `poetry.lock` | |
| Node (npm) | `package-lock.json` | Lockfile v1/v2/v3 |
| Node (Yarn) | `yarn.lock` | Classic (v1) and Berry (v2+) |
| Node (pnpm) | `pnpm-lock.yaml` | lockfileVersion 5/6/9 key formats |
| Go | `go.sum` | |
| Java/Kotlin (Gradle) | `gradle.lockfile` | Modern single-file dependency locking (opt-in via `dependencyLocking`) |
| Java (Maven) | `pom.xml` | Only literally-pinned `<version>` tags - versions from a parent POM/BOM, a `${property}`, or a range are reported as unverifiable, not guessed at (Maven has no resolved-lockfile equivalent) |

Other manifests found (`Pipfile.lock`, `Gemfile.lock`, `build.gradle`, `build.gradle.kts`) are reported as
"found but not yet supported" rather than silently ignored - `build.gradle`/`.kts` are executable
scripts, not data, so they aren't parsed; enable Gradle dependency locking for accurate scanning instead.

---

## License

MIT - see [LICENSE](LICENSE)
