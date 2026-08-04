import json
from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from pkg_doctor import osv_client


@dataclass
class FakePackageRef:
    ecosystem: str
    name: str
    version: str


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Never touch the real ~/.pkg_doctor cache during tests."""
    monkeypatch.setattr(osv_client, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(osv_client, "CACHE_FILE", tmp_path / "osv_cache.json")


def _fake_response(results):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = {"results": results}
    return resp


def test_is_malicious_mal_prefix():
    assert osv_client.is_malicious("MAL-2026-1234") is True
    assert osv_client.is_malicious("GHSA-xxxx-yyyy-zzzz") is False


def test_vuln_url_format():
    assert osv_client.vuln_url("GHSA-abcd") == "https://osv.dev/vulnerability/GHSA-abcd"


def test_check_packages_returns_vuln_ids(monkeypatch):
    pkg = FakePackageRef(ecosystem="PyPI", name="urllib3", version="1.24.1")
    monkeypatch.setattr(
        osv_client.requests, "post",
        Mock(return_value=_fake_response([{"vulns": [{"id": "GHSA-2xpw-w6gg-jr37"}]}])),
    )

    results = osv_client.check_packages([pkg])
    assert results["PyPI:urllib3:1.24.1"] == ["GHSA-2xpw-w6gg-jr37"]


def test_check_packages_dedupes_identical_packages(monkeypatch):
    pkg_a = FakePackageRef(ecosystem="npm", name="lodash", version="4.17.21")
    pkg_b = FakePackageRef(ecosystem="npm", name="lodash", version="4.17.21")
    post_mock = Mock(return_value=_fake_response([{"vulns": []}]))
    monkeypatch.setattr(osv_client.requests, "post", post_mock)

    osv_client.check_packages([pkg_a, pkg_b])

    sent_body = post_mock.call_args.kwargs["json"]
    assert len(sent_body["queries"]) == 1  # only one query for the duplicate pair


def test_check_packages_second_call_hits_cache_not_network(monkeypatch):
    pkg = FakePackageRef(ecosystem="PyPI", name="requests", version="2.0.0")
    post_mock = Mock(return_value=_fake_response([{"vulns": [{"id": "GHSA-aaaa"}]}]))
    monkeypatch.setattr(osv_client.requests, "post", post_mock)

    first = osv_client.check_packages([pkg])
    second = osv_client.check_packages([pkg])

    assert first == second
    assert post_mock.call_count == 1  # second call served entirely from cache


def test_check_packages_writes_cache_file(monkeypatch, tmp_path):
    pkg = FakePackageRef(ecosystem="PyPI", name="requests", version="2.0.0")
    monkeypatch.setattr(osv_client.requests, "post", Mock(return_value=_fake_response([{"vulns": []}])))

    osv_client.check_packages([pkg])

    cache_file = tmp_path / "osv_cache.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text())
    assert "PyPI:requests:2.0.0" in cached


def test_check_packages_network_error_returns_empty_not_raises(monkeypatch):
    import requests as requests_module

    pkg = FakePackageRef(ecosystem="PyPI", name="requests", version="2.0.0")
    monkeypatch.setattr(
        osv_client.requests, "post",
        Mock(side_effect=requests_module.exceptions.ConnectionError("no network")),
    )

    results = osv_client.check_packages([pkg])
    assert results["PyPI:requests:2.0.0"] == []


def test_check_packages_empty_input(monkeypatch):
    post_mock = Mock()
    monkeypatch.setattr(osv_client.requests, "post", post_mock)

    assert osv_client.check_packages([]) == {}
    post_mock.assert_not_called()
