import click

from dep_doctor import __version__
from dep_doctor.scanner import discover_projects, PackageRef, ProjectManifest
from dep_doctor import osv_client
from dep_doctor.secrets_scan import find_secrets
from dep_doctor.remediation import run_remediation

PURPLE = "\033[95m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


BANNER = f"{PURPLE}{BOLD}dep-doctor{RESET} {CYAN}v{__version__} - local supply-chain & exposed-secret triage{RESET}"


@click.command()
@click.version_option(version=__version__, prog_name="dep-doctor", message="%(prog)s %(version)s")
@click.option(
    "--path", "paths",
    multiple=True,
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Directory to scan for dependency manifests. Can be used multiple times.",
)
@click.option(
    "--include-self", "include_self",
    is_flag=True,
    default=False,
    help="Also audit dep-doctor's own installed dependencies.",
)
@click.option(
    "--skip-secrets", "skip_secrets",
    is_flag=True,
    default=False,
    help="Only check for vulnerable/malicious packages - skip scanning config files for exposed keys.",
)
def cli(paths, include_self, skip_secrets):
    """
    dep-doctor - scan local projects for known-vulnerable or malicious dependencies (via OSV.dev),
    and flag likely-exposed API keys in affected projects for guided, human-approved rotation.

    Nothing is scanned unless you pass --path, and nothing is ever rotated automatically -
    every rotation opens the provider's dashboard and waits for your confirmation.

    Examples:\n
      dep-doctor --path ./my-project\n
      dep-doctor --path ~/projects/foo --path ~/projects/bar --include-self
    """
    click.echo(BANNER)
    click.echo(f"{PURPLE}[dep-doctor]{RESET} Scanning {len(paths)} path(s)...")
    projects = discover_projects(list(paths))

    if include_self:
        import importlib.metadata as importlib_metadata
        from pathlib import Path

        self_pkgs = [
            PackageRef(ecosystem="PyPI", name=dist.metadata["Name"], version=dist.version, manifest_path=None)
            for dist in importlib_metadata.distributions()
            if dist.metadata.get("Name")
        ]
        projects.append(ProjectManifest(project_dir=Path("<dep-doctor (self)>"), packages=self_pkgs))

    if not projects:
        click.echo(f"{GREEN}No dependency manifests found under the given path(s).{RESET}")
        return

    all_packages = [pkg for proj in projects for pkg in proj.packages]
    click.echo(f"{CYAN}Checking {len(all_packages)} package(s) against OSV.dev...{RESET}")
    vuln_map = osv_client.check_packages(all_packages)

    flagged_projects = 0
    total_findings = 0
    rotated = 0
    skipped_secrets = 0

    for proj in projects:
        proj_findings = []
        for pkg in proj.packages:
            key = f"{pkg.ecosystem}:{pkg.name}:{pkg.version}"
            vuln_ids = vuln_map.get(key, [])
            if vuln_ids:
                proj_findings.append((pkg, vuln_ids))

        if not (proj_findings or proj.unsupported_manifests or proj.unparsed_pinned):
            continue

        click.echo(f"\n{BOLD}{proj.project_dir}{RESET}")

        if proj.unsupported_manifests:
            names = ", ".join(p.name for p in proj.unsupported_manifests)
            click.echo(f"  {CYAN}found but not yet supported: {names}{RESET}")

        if proj.unparsed_pinned:
            click.echo(f"  {CYAN}{len(proj.unparsed_pinned)} unpinned requirement(s) - cannot verify version{RESET}")

        if not proj_findings:
            continue

        flagged_projects += 1
        for pkg, vuln_ids in proj_findings:
            for vuln_id in vuln_ids:
                total_findings += 1
                malicious = osv_client.is_malicious(vuln_id)
                tag = f"{RED}MALICIOUS PACKAGE{RESET}" if malicious else f"{YELLOW}VULNERABLE{RESET}"
                click.echo(f"  {tag}: {pkg.name}=={pkg.version} ({vuln_id})")
                click.echo(f"    {osv_client.vuln_url(vuln_id)}")

        if skip_secrets or not proj.project_dir.exists():
            continue

        for finding in find_secrets(proj.project_dir):
            status = run_remediation(finding, proj.project_dir)
            if status == "rotated":
                rotated += 1
            else:
                skipped_secrets += 1

    click.echo(f"\n{BOLD}Summary{RESET}")
    click.echo(f"  Projects scanned:         {len(projects)}")
    click.echo(f"  Packages checked:         {len(all_packages)}")
    click.echo(f"  Projects with findings:   {flagged_projects}")
    click.echo(f"  Advisory findings:        {total_findings}")
    click.echo(f"  Keys rotated (confirmed): {rotated}")
    click.echo(f"  Keys skipped:             {skipped_secrets}")
    click.echo()


if __name__ == "__main__":
    cli()
