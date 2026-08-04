from pkg_doctor.scanner import (
    discover_projects,
    _parse_requirements_txt,
    _parse_package_lock_json,
    _parse_poetry_lock,
    _parse_yarn_lock,
    _parse_pnpm_lock_yaml,
    _parse_go_sum,
    _parse_gradle_lockfile,
    _parse_pom_xml,
)


def _pkgs_as_tuples(pkgs):
    return {(p.ecosystem, p.name, p.version) for p in pkgs}


# ---------- requirements.txt ----------

def test_requirements_txt_pinned_and_unpinned(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text(
        "urllib3==1.24.1\n"
        "# a comment\n"
        "\n"
        "click==8.1.7  # inline comment\n"
        "flask\n"
        "requests>=2.0\n"
    )
    packages, unpinned = _parse_requirements_txt(path)

    assert _pkgs_as_tuples(packages) == {
        ("PyPI", "urllib3", "1.24.1"),
        ("PyPI", "click", "8.1.7"),
    }
    assert [line for line, _ in unpinned] == ["flask", "requests>=2.0"]


def test_requirements_txt_missing_file(tmp_path):
    packages, unpinned = _parse_requirements_txt(tmp_path / "missing.txt")
    assert packages == []
    assert unpinned == []


# ---------- package-lock.json ----------

def test_package_lock_json_v2v3(tmp_path):
    path = tmp_path / "package-lock.json"
    path.write_text('{"packages": {"": {}, "node_modules/lodash": {"version": "4.17.21"}}}')
    packages = _parse_package_lock_json(path)
    assert _pkgs_as_tuples(packages) == {("npm", "lodash", "4.17.21")}


def test_package_lock_json_v1(tmp_path):
    path = tmp_path / "package-lock.json"
    path.write_text('{"dependencies": {"lodash": {"version": "4.17.21"}}}')
    packages = _parse_package_lock_json(path)
    assert _pkgs_as_tuples(packages) == {("npm", "lodash", "4.17.21")}


def test_package_lock_json_malformed(tmp_path):
    path = tmp_path / "package-lock.json"
    path.write_text("{not valid json")
    assert _parse_package_lock_json(path) == []


# ---------- poetry.lock ----------

def test_poetry_lock(tmp_path):
    path = tmp_path / "poetry.lock"
    path.write_text(
        '[[package]]\n'
        'name = "certifi"\n'
        'version = "2023.7.22"\n'
        '\n'
        '[[package]]\n'
        'name = "charset-normalizer"\n'
        'version = "3.2.0"\n'
        '\n'
        '[package.dependencies]\n'
        'some-dep = ">=1.0"\n'
    )
    packages = _parse_poetry_lock(path)
    assert _pkgs_as_tuples(packages) == {
        ("PyPI", "certifi", "2023.7.22"),
        ("PyPI", "charset-normalizer", "3.2.0"),
    }
    # the [package.dependencies] sub-table must not be mistaken for its own package
    assert not any(p.name == "some-dep" for p in packages)


# ---------- yarn.lock ----------

def test_yarn_lock_classic_multi_alias(tmp_path):
    path = tmp_path / "yarn.lock"
    path.write_text(
        "# yarn lockfile v1\n\n"
        '"@babel/code-frame@^7.0.0", "@babel/code-frame@^7.1.0":\n'
        '  version "7.22.13"\n'
        '  resolved "https://registry.yarnpkg.com/@babel/code-frame/-/code-frame-7.22.13.tgz"\n'
        "  dependencies:\n"
        '    "@babel/highlight" "^7.22.13"\n\n'
        "lodash@^4.17.0, lodash@^4.17.21:\n"
        '  version "4.17.21"\n'
    )
    packages = _pkgs_as_tuples(_parse_yarn_lock(path))
    assert ("npm", "@babel/code-frame", "7.22.13") in packages
    assert ("npm", "lodash", "4.17.21") in packages
    # the nested "dependencies:" line must not be mistaken for a version line
    assert not any(name == "@babel/highlight" for _, name, _ in packages)


def test_yarn_lock_berry(tmp_path):
    path = tmp_path / "yarn.lock"
    path.write_text(
        "__metadata:\n  version: 6\n\n"
        '"lodash@npm:^4.17.21":\n'
        "  version: 4.17.21\n"
        '  resolution: "lodash@npm:4.17.21"\n\n'
        '"@babel/core@npm:^7.22.9":\n'
        "  version: 7.22.9\n"
    )
    packages = _pkgs_as_tuples(_parse_yarn_lock(path))
    assert packages == {
        ("npm", "lodash", "4.17.21"),
        ("npm", "@babel/core", "7.22.9"),
    }


# ---------- pnpm-lock.yaml ----------

def test_pnpm_lock_v5_v6_style(tmp_path):
    path = tmp_path / "pnpm-lock.yaml"
    path.write_text(
        "lockfileVersion: 5.4\n"
        "packages:\n"
        "  /lodash/4.17.21:\n"
        "    resolution: {integrity: sha512-abc}\n"
        "  /@babel/core/7.22.9:\n"
        "    resolution: {integrity: sha512-def}\n"
    )
    packages = _pkgs_as_tuples(_parse_pnpm_lock_yaml(path))
    assert packages == {
        ("npm", "lodash", "4.17.21"),
        ("npm", "@babel/core", "7.22.9"),
    }


def test_pnpm_lock_v9_style_with_peer_dep_suffix(tmp_path):
    path = tmp_path / "pnpm-lock.yaml"
    path.write_text(
        "lockfileVersion: '9.0'\n"
        "packages:\n"
        "  lodash@4.17.21:\n"
        "    resolution: {integrity: sha512-abc}\n"
        "  react-dom@18.2.0(react@18.2.0):\n"
        "    resolution: {integrity: sha512-ghi}\n"
    )
    packages = _pkgs_as_tuples(_parse_pnpm_lock_yaml(path))
    assert packages == {
        ("npm", "lodash", "4.17.21"),
        ("npm", "react-dom", "18.2.0"),
    }


# ---------- go.sum ----------

def test_go_sum_dedupes_go_mod_lines(tmp_path):
    path = tmp_path / "go.sum"
    path.write_text(
        "github.com/pkg/errors v0.9.1 h1:FEBLx1zS214owpjy7qsBeixbURkuhQAwrK5UwLGTwt4=\n"
        "github.com/pkg/errors v0.9.1/go.mod h1:bwawxfHBFNV+L2hUp1rHADufV3IMtnDRdf1r5NINEl0=\n"
    )
    packages = _parse_go_sum(path)
    assert _pkgs_as_tuples(packages) == {("Go", "github.com/pkg/errors", "v0.9.1")}
    assert len(packages) == 1  # the two lines are the same module@version, deduped


# ---------- gradle.lockfile ----------

def test_gradle_lockfile(tmp_path):
    path = tmp_path / "gradle.lockfile"
    path.write_text(
        "# This is a Gradle generated file for dependency locking.\n"
        "com.google.guava:guava:31.1-jre=compileClasspath,runtimeClasspath\n"
        "empty=annotationProcessor,testCompileClasspath\n"
    )
    packages = _pkgs_as_tuples(_parse_gradle_lockfile(path))
    assert packages == {("Maven", "com.google.guava:guava", "31.1-jre")}


# ---------- pom.xml ----------

def test_pom_xml_pinned_vs_unverifiable(tmp_path):
    path = tmp_path / "pom.xml"
    path.write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <dependencies>\n"
        "    <dependency>\n"
        "      <groupId>com.fasterxml.jackson.core</groupId>\n"
        "      <artifactId>jackson-databind</artifactId>\n"
        "      <version>2.13.0</version>\n"
        "    </dependency>\n"
        "    <dependency>\n"
        "      <groupId>org.apache.commons</groupId>\n"
        "      <artifactId>commons-lang3</artifactId>\n"
        "      <version>${commons.version}</version>\n"
        "    </dependency>\n"
        "    <dependency>\n"
        "      <groupId>org.springframework</groupId>\n"
        "      <artifactId>spring-core</artifactId>\n"
        "    </dependency>\n"
        "  </dependencies>\n"
        "</project>\n"
    )
    packages, unpinned = _parse_pom_xml(path)
    assert _pkgs_as_tuples(packages) == {("Maven", "com.fasterxml.jackson.core:jackson-databind", "2.13.0")}
    assert len(unpinned) == 2  # the ${property} one and the no-version one


# ---------- discover_projects ----------

def test_discover_projects_excludes_node_modules(tmp_path):
    (tmp_path / "requirements.txt").write_text("urllib3==1.24.1\n")
    nested = tmp_path / "node_modules" / "some-pkg"
    nested.mkdir(parents=True)
    (nested / "requirements.txt").write_text("should-not-be-scanned==1.0.0\n")

    projects = discover_projects([str(tmp_path)])
    assert len(projects) == 1
    assert _pkgs_as_tuples(projects[0].packages) == {("PyPI", "urllib3", "1.24.1")}


def test_discover_projects_reports_unsupported_manifests(tmp_path):
    (tmp_path / "Gemfile.lock").write_text("GEM\n")
    projects = discover_projects([str(tmp_path)])
    assert len(projects) == 1
    assert [p.name for p in projects[0].unsupported_manifests] == ["Gemfile.lock"]
    assert projects[0].packages == []


def test_discover_projects_combines_multiple_manifests_in_one_dir(tmp_path):
    (tmp_path / "requirements.txt").write_text("urllib3==1.24.1\n")
    (tmp_path / "package-lock.json").write_text('{"dependencies": {"lodash": {"version": "4.17.21"}}}')

    projects = discover_projects([str(tmp_path)])
    assert len(projects) == 1
    assert _pkgs_as_tuples(projects[0].packages) == {
        ("PyPI", "urllib3", "1.24.1"),
        ("npm", "lodash", "4.17.21"),
    }


def test_discover_projects_no_manifests_returns_empty(tmp_path):
    (tmp_path / "README.md").write_text("hello\n")
    assert discover_projects([str(tmp_path)]) == []


def test_discover_projects_nonexistent_path_skipped():
    assert discover_projects([r"C:\definitely\does\not\exist"]) == []
