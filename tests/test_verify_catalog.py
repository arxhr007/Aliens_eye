"""Catalog verification: recording against a fake network and per-site verdicts."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from aliens_eye.core.http import FetchResult

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_catalog.py"


@pytest.fixture
def verify():
    spec = importlib.util.spec_from_file_location("verify_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profile(username):
    return (
        f"<html><head><title>{username} profile</title></head><body><h1>{username}</h1>"
        f"<p>Joined 2019 followers 10</p><img class=avatar src=/a.png></body></html>"
    )


def test_each_site_gets_a_verdict_from_one_known_and_one_fake_account(tmp_path, monkeypatch, verify):
    from aliens_eye.catalog import write_catalog
    from aliens_eye.core.sites import SiteCatalog, SiteDefinition
    from aliens_eye.corpus import record as record_mod

    def site(name, **extra):
        return SiteDefinition.from_dict(name, {"url": f"https://{name}.example/u/{{}}", "source": "upstream", **extra})

    rule = {"check_type": "message", "presence": ["data-profile"], "absence": ["No such user"]}
    sites = {
        "good": site("good", **rule), "gone": site("gone", **rule), "lenient": site("lenient", **rule),
        "walled": site("walled", **rule), "dead": site("dead", **rule), "untested": site("untested", **rule),
    }
    catalog = tmp_path / "catalog.json"
    write_catalog(catalog, SiteCatalog(sites))
    known = {name: f"{name}user" for name in sites if name != "untested"}
    monkeypatch.setattr(verify, "test_usernames", lambda catalog, upstream: known)
    calls = []

    async def network(session, url, config, limiter, logger):
        calls.append(url)
        host = url.split("//")[1].split(".")[0]
        user = url.rsplit("/", 1)[1]
        if host == "dead":
            return FetchResult(url, url, 0, "", 0.1, {}, "Cannot connect to host", 0)
        if host == "walled":
            return FetchResult(url, url, 403, "Forbidden", 0.1, {}, None, 0)
        exists = host == "lenient" or (host == "good" and user == known["good"])
        body = f"<div data-profile>{profile(user)}</div>" if exists else "<html><title>x</title>No such user</html>"
        return FetchResult(url, url, 200, body, 0.1, {"Content-Type": "text/html"}, None, 0)

    monkeypatch.setattr(record_mod, "fetch_url", network)
    corpus = tmp_path / "corpus"
    verify.main(["record", "--corpus", str(corpus), "--sites", str(catalog), "--concurrency", "2"])
    assert len(calls) == 11  # five known + six fake accounts

    calls.clear()
    verify.main(["record", "--corpus", str(corpus), "--sites", str(catalog)])
    # Resuming retries only the failed captures: both requests to the dead host.
    assert len(calls) == 2 and "https://dead.example/u/deaduser" in calls
    assert all(url.startswith("https://dead.example/u/") for url in calls)

    verify.main(["report", "--corpus", str(corpus), "--sites", str(catalog), "--out", str(tmp_path / "out")])
    with (tmp_path / "out" / "sites.csv").open(encoding="utf-8") as handle:
        verdicts = {row["site"]: row["verdict"] for row in csv.DictReader(handle)}
    assert verdicts == {
        "good": "working", "gone": "misses_known_user", "lenient": "accepts_anything",
        "walled": "blocked", "dead": "unreachable", "untested": "alive_no_test_user",
    }
    summary = json.loads((tmp_path / "out" / "summary.json").read_text("utf-8"))
    assert summary["sites"] == 6 and summary["corpus_misses"] == 0
    with pytest.raises(FileExistsError):
        verify.main(["report", "--corpus", str(corpus), "--sites", str(catalog), "--out", str(tmp_path / "out")])


def test_false_positives_are_disabled_at_once_but_failures_need_a_recheck(verify):
    first = {
        "fp": {"verdict": "accepts_anything"}, "gone": {"verdict": "misses_known_user"},
        "flaky": {"verdict": "unreachable"}, "ok": {"verdict": "working"}, "walled": {"verdict": "blocked"},
        "unchecked": {"verdict": "unreachable"},
    }
    assert set(verify.broken_sites(first, None)) == {"fp"}
    recheck = {"gone": {"verdict": "misses_known_user"}, "flaky": {"verdict": "working"}}
    assert set(verify.broken_sites(first, recheck)) == {"fp", "gone"}
