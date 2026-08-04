from pkg_doctor.secrets_scan import find_secrets, _mask, _classify, _parse_env_style, _walk_json_strings


# ---------- masking ----------

def test_mask_short_value_fully_masked():
    assert _mask("abc") == "***"


def test_mask_long_value_shows_prefix_and_suffix():
    assert _mask("sk-abcdefghijklmnopqrstuvwxyz") == "sk-abc...wxyz"


# ---------- classification (known key shapes) ----------

def test_classify_openai_shape():
    provider, confidence = _classify("sk-" + "a" * 20)
    assert provider == "OpenAI"
    assert confidence == "high"


def test_classify_unknown_shape_is_low_confidence():
    provider, confidence = _classify("just-some-value")
    assert provider is None
    assert confidence == "low"


# ---------- env-style parsing ----------

def test_parse_env_style_flags_everything_no_name_filter():
    text = (
        "STOCK_API=abcdefghij1234567890\n"
        "URL=https://finnhub.io/api/v1\n"
        "DEBUG=true\n"
        "# a comment\n"
        "\n"
        "export EXPORTED_VAR=some-value\n"
        'QUOTED="quoted-value"\n'
    )
    pairs = dict(_parse_env_style(text))
    # the whole point of the redesign: STOCK_API is caught even though its name
    # doesn't contain API_KEY/SECRET/TOKEN
    assert pairs["STOCK_API"] == "abcdefghij1234567890"
    assert pairs["URL"] == "https://finnhub.io/api/v1"
    assert pairs["DEBUG"] == "true"
    assert pairs["EXPORTED_VAR"] == "some-value"
    assert pairs["QUOTED"] == "quoted-value"  # surrounding quotes stripped


# ---------- JSON walking ----------

def test_walk_json_strings_finds_nested_values_only():
    data = {
        "database": {"password": "nested-secret-value"},
        "featureFlags": {"betaMode": True},
        "port": 3000,
        "webhookUrl": "https://example.com/hook",
    }
    pairs = dict(_walk_json_strings(data))
    assert pairs["database.password"] == "nested-secret-value"
    assert pairs["webhookUrl"] == "https://example.com/hook"
    # booleans and numbers can't be credentials — excluded by type, not by name
    assert "featureFlags.betaMode" not in pairs
    assert "port" not in pairs


# ---------- find_secrets end-to-end ----------

def test_find_secrets_catches_unnamed_pattern_env_var(tmp_path):
    (tmp_path / ".env").write_text("STOCK_API=abcdefghij1234567890\n")
    findings = find_secrets(tmp_path)
    assert len(findings) == 1
    assert findings[0].provider == "STOCK_API"
    assert findings[0].confidence == "low"
    assert "abcdefghij1234567890" not in findings[0].masked_value  # never the raw value


def test_find_secrets_labels_known_shape_high_confidence(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-" + "a" * 20 + "\n")
    findings = find_secrets(tmp_path)
    assert len(findings) == 1
    assert findings[0].provider == "OpenAI"
    assert findings[0].confidence == "high"


def test_find_secrets_dedupes_same_value_prefers_high_confidence(tmp_path):
    # a value that satisfies a known shape AND would otherwise be a generic finding
    # must only be reported once, under the specific label
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-" + "a" * 20 + "\n")
    findings = find_secrets(tmp_path)
    assert len(findings) == 1


def test_find_secrets_json_file(tmp_path):
    (tmp_path / "secrets.json").write_text('{"database": {"password": "nested-secret-value"}}')
    findings = find_secrets(tmp_path)
    assert len(findings) == 1
    assert findings[0].provider == "database.password"


def test_find_secrets_no_matching_files_returns_empty(tmp_path):
    (tmp_path / "README.md").write_text("nothing to see here\n")
    assert find_secrets(tmp_path) == []


def test_find_secrets_never_returns_raw_value(tmp_path):
    (tmp_path / ".env").write_text("SECRET_TOKEN=super-secret-raw-value-12345\n")
    findings = find_secrets(tmp_path)
    for finding in findings:
        assert "super-secret-raw-value-12345" not in finding.masked_value
