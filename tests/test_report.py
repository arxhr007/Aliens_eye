import json

import pytest

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.report import ReportError, diff_reports, load_report, observation


def result(status="Found", code=200, name="Alice", source="opengraph", **extra):
    return {
        "status": status,
        "code": code,
        "confidence": 90,
        "url": "https://example.test/alice",
        "ai_analysis": {"signals": {"profile": {
            "name": name, "name_from_profile": True,
            "field_sources": {"name": source},
        }}},
        **extra,
    }


def report(info):
    return {"variations": {"alice": {"sites": {"example": info}}}}


@pytest.mark.parametrize("status,code,kind", [
    ("Found", 200, "found"), ("Not Found", 404, "absent"),
    ("Not Found", 410, "absent"), ("Not Found", 200, "unavailable"),
    ("Not Found", 403, "unavailable"), ("Found", 503, "unavailable"),
    ("Timeout", 408, "unavailable"), ("Error", 404, "unavailable"),
    ("Maybe", 200, "unavailable"),
])
def test_observations_distinguish_absence_from_failure(status, code, kind):
    assert observation(result(status, code))["kind"] == kind


def test_profile_only_diff_and_legacy_keys():
    delta = diff_reports(report(result()), report(result(name="Alice Smith")))
    assert delta["new"] == delta["gone"] == delta["changed"] == []
    assert delta["profile_changes"][0]["field"] == "name"
    assert delta["profile_changes"][0]["before"] == "Alice"
    assert delta["profile_changes"][0]["after"] == "Alice Smith"


@pytest.mark.parametrize("name,source", [
    (" Alice \n", "opengraph"), ("Alice Smith", "title"),
    ("Alice Smith", "json_ld"), ("", "opengraph"), ("Alice Smith", None),
])
def test_incomparable_profile_values_do_not_produce_changes(name, source):
    assert diff_reports(report(result()), report(result(name=name, source=source)))["profile_changes"] == []


@pytest.mark.parametrize("data", [
    {"variations": []}, {"variations": {"alice": []}},
    {"variations": {"alice": {"sites": []}}},
    {"variations": {"alice": {"sites": {"example": None}}}},
    report({"ai_analysis": {"signals": {"profile": []}}}),
])
def test_loader_rejects_invalid_nested_reports(tmp_path, data):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReportError):
        load_report(path)


def test_profile_sources_preserve_existing_fallback_values():
    extractor = FeatureExtractor()
    bundle = extractor.extract(
        '<html><head><title>Alice</title><meta name="description" content="Bio">'
        '<link rel="apple-touch-icon" href="/icon.png"></head><body></body></html>',
        "https://example.test/alice", "alice", "example", 200, 0.1, {}, 0,
    )
    profile = bundle.signals["profile"]
    assert profile["name"] == "Alice"
    assert profile["bio"] == "Bio"
    assert profile["avatar"] == "https://example.test/icon.png"
    assert profile["name_from_profile"] is False
    assert profile["field_sources"] == {"name": "title", "bio": "meta_description", "avatar": "icon"}


def test_opengraph_profile_sources():
    bundle = FeatureExtractor().extract(
        '<html><head><meta property="og:title" content="Alice">'
        '<meta property="og:description" content="Bio">'
        '<meta property="og:image" content="/avatar.png"></head><body></body></html>',
        "https://example.test/alice", "alice", "example", 200, 0.1, {}, 0,
    )
    assert bundle.signals["profile"]["field_sources"] == dict.fromkeys(("name", "bio", "avatar"), "opengraph")
    assert bundle.signals["profile"]["name_from_profile"] is True


def test_unicode_equivalence_and_confidence_only_changes():
    old, new = result(name="Ren\u00e9e"), result(name="Rene\u0301e", confidence=80)
    delta = diff_reports(report(old), report(new))
    assert delta["profile_changes"] == []
    assert len(delta["changed"]) == 1


def test_avatar_changes_are_url_changes_only():
    old, new = result(), result()
    for info, url in ((old, "https://example.test/a.png?v=1"), (new, "https://example.test/a.png?v=2")):
        profile = info["ai_analysis"]["signals"]["profile"]
        profile.update(avatar=url)
        profile["field_sources"]["avatar"] = "opengraph"
    change = diff_reports(report(old), report(new))["profile_changes"][0]
    assert change["type"] == "avatar_url_changed"


def test_blocked_page_cannot_be_an_absence_even_if_detector_says_not_found():
    info = result("Not Found", 404)
    info["ai_analysis"]["signals"]["title"] = "Verify you are human"
    assert observation(info)["kind"] == "unavailable"


def test_invalid_text_encoding_is_a_report_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfeinvalid")
    with pytest.raises(ReportError):
        load_report(path)
