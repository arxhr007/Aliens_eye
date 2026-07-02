"""Tests for the feature-expansion batch: report diff, correlation, expansion,
domains, checkpoint, graph export, dataset append, and selfcheck metrics."""

import json

from aliens_eye.core import report as report_mod
from aliens_eye.core.checkpoint import Checkpoint
from aliens_eye.core.correlate import (
    Profile,
    cluster_profiles,
    profiles_from_report,
)
from aliens_eye.core.domains import domain_label
from aliens_eye.core.expand import candidate_usernames_from_results
from aliens_eye.core.exporter import ResultsExporter
from aliens_eye.ml.collect import write_rows
from aliens_eye.selfcheck import _metrics


def _profile_result(site, variation, status="Found", name="", bio="", avatar="", url=""):
    return {
        "site": site,
        "url": url or f"https://{site}.com/{variation}",
        "final_url": url,
        "status": status,
        "code": 200,
        "response_time": 0.1,
        "confidence": 90,
        "ai_analysis": {
            "features": {"http_200": 1.0},
            "signals": {"profile": {"name": name, "bio": bio, "avatar": avatar}},
        },
    }


def _report(results):
    return ResultsExporter.__new__(ResultsExporter)._build_results_data(
        "alice", "basic", results, "20260101_000000"
    )


# --- report loader + diff -------------------------------------------------

def test_load_report_roundtrip_and_diff(tmp_path):
    old_results = {"alice": [_profile_result("github", "alice")]}
    new_results = {
        "alice": [
            _profile_result("github", "alice"),
            _profile_result("reddit", "alice"),
        ]
    }
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(_report(old_results)), encoding="utf-8")
    new_path.write_text(json.dumps(_report(new_results)), encoding="utf-8")

    old = report_mod.load_report(old_path)
    new = report_mod.load_report(new_path)
    delta = report_mod.diff_reports(old, new)
    new_keys = [item["key"] for item in delta["new"]]
    assert "alice:reddit" in new_keys
    assert delta["gone"] == []


def test_load_report_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    try:
        report_mod.load_report(bad)
    except report_mod.ReportError:
        pass
    else:
        raise AssertionError("expected ReportError")


def test_diff_detects_status_change():
    old = _report({"alice": [_profile_result("github", "alice", status="Maybe")]})
    new = _report({"alice": [_profile_result("github", "alice", status="Found")]})
    changed = report_mod.diff_reports(old, new)["changed"]
    assert changed and changed[0]["key"] == "alice:github"


# --- correlation ----------------------------------------------------------

def test_cluster_by_shared_name():
    profiles = [
        Profile("alice", "github", name="Alice Smith", bio="", avatar="", url="", status="Found"),
        Profile("alice", "gitlab", name="Alice Smith", bio="", avatar="", url="", status="Found"),
        Profile("bob", "reddit", name="Bob Jones", bio="", avatar="", url="", status="Found"),
    ]
    clusters = cluster_profiles(profiles)
    assert len(clusters) == 1
    assert clusters[0]["size"] == 2
    assert "name" in clusters[0]["reasons"]


def test_cluster_by_shared_link():
    profiles = [
        Profile("a", "s1", name="", bio="see https://me.example/x", avatar="", url="", status="Found"),
        Profile("a", "s2", name="", bio="also https://me.example/x here", avatar="", url="", status="Maybe"),
    ]
    clusters = cluster_profiles(profiles)
    assert len(clusters) == 1
    assert "shared-link" in clusters[0]["reasons"]


def test_no_cluster_when_unrelated():
    profiles = [
        Profile("a", "s1", name="Zoe", bio="cats", avatar="", url="", status="Found"),
        Profile("b", "s2", name="Max", bio="dogs", avatar="", url="", status="Found"),
    ]
    assert cluster_profiles(profiles) == []


def test_profiles_from_report_skips_not_found():
    rep = _report({
        "alice": [
            _profile_result("github", "alice", status="Found", name="A"),
            _profile_result("reddit", "alice", status="Not Found"),
        ]
    })
    profiles = profiles_from_report(rep)
    assert [p.site for p in profiles] == ["github"]


# --- expansion ------------------------------------------------------------

def test_candidate_usernames_from_bio():
    results = {
        "alice": [
            _profile_result(
                "github", "alice", status="Found",
                bio="I'm @bob_dev, also https://twitter.com/charlie",
            )
        ]
    }
    candidates = candidate_usernames_from_results(results, exclude={"alice"})
    assert "bob_dev" in candidates
    assert "charlie" in candidates
    assert "alice" not in [c.lower() for c in candidates]


# --- domains --------------------------------------------------------------

def test_domain_label_sanitizes():
    assert domain_label("John_Doe.99") == "john-doe-99"
    assert domain_label("!!!") == ""


# --- checkpoint -----------------------------------------------------------

async def test_checkpoint_roundtrip(tmp_path):
    path = tmp_path / "ck.jsonl"
    ck = Checkpoint(path)
    result = _profile_result("github", "alice")
    await ck.record("alice", "github", result)
    assert ck.is_done("alice", "github")

    reloaded = Checkpoint(path)
    assert reloaded.is_done("alice", "github")
    assert reloaded.results_for("alice")["github"]["site"] == "github"

    reloaded.finalize()
    assert not path.exists()


# --- graph export ---------------------------------------------------------

def test_graph_exports_written(tmp_path):
    exporter = ResultsExporter(tmp_path)
    results = {"alice": [_profile_result("github", "alice", name="Alice")]}
    written = exporter.save_results("alice", "basic", results, ["gexf", "mermaid", "maltego"])
    suffixes = {p.suffix for p in written}
    assert ".gexf" in suffixes
    assert ".mmd" in suffixes
    assert any(p.name.endswith("_maltego.csv") for p in written)
    gexf = next(p for p in written if p.suffix == ".gexf")
    assert "github" in gexf.read_text(encoding="utf-8")


def test_all_format_excludes_graph_and_pdf(tmp_path):
    exporter = ResultsExporter(tmp_path)
    results = {"alice": [_profile_result("github", "alice")]}
    written = exporter.save_results("alice", "basic", results, ["all"])
    suffixes = {p.suffix for p in written}
    assert suffixes == {".json", ".csv", ".html", ".md"}


# --- dataset append -------------------------------------------------------

def test_write_rows_append(tmp_path):
    from aliens_eye.core.features import FEATURE_SCHEMA

    path = tmp_path / "ds.csv"
    row = [0.0] * len(FEATURE_SCHEMA) + [1.0]
    write_rows(path, [row], append=True)
    write_rows(path, [row], append=True)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("http_200")  # single header
    assert len(lines) == 3  # header + 2 rows


# --- selfcheck metrics ----------------------------------------------------

def test_metrics_math():
    m = _metrics(tp=8, fp=2, fn=2, tn=8)
    assert m["precision"] == 0.8
    assert m["recall"] == 0.8
    assert round(m["f1"], 2) == 0.8
    assert m["false_positive_rate"] == 0.2
