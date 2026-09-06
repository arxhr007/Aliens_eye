"""External rule engines: faithfulness of the reimplemented semantics, and the
coverage accounting that keeps the comparison fair."""

import json

import pytest

from aliens_eye.eval.ablate import Observation
from aliens_eye.eval.external import (
    FOUND,
    NOT_FOUND,
    UNKNOWN,
    SherlockEngine,
    WhatsMyNameEngine,
    _netloc,
    score_engine,
)

SHERLOCK_RULES = {
    "StatusSite": {"errorType": "status_code", "url": "https://status.example/{}"},
    "CodedSite": {"errorType": "status_code", "errorCode": 202, "url": "https://coded.example/{}"},
    "MessageSite": {
        "errorType": "message",
        "errorMsg": "nobody goes by that name",
        "url": "https://msg.example/{}",
    },
    "MultiMessageSite": {
        "errorType": "message",
        "errorMsg": ["no such user", "not found here"],
        "url": "https://multi.example/{}",
    },
    "RedirectSite": {"errorType": "response_url", "url": "https://redir.example/{}"},
    "WwwSite": {"errorType": "status_code", "url": "https://www.wwwsite.example/{}"},
    "NoUrl": {"errorType": "status_code"},
}

WMN_RULES = {
    "license": ["test"],
    "sites": [
        {
            "name": "StrictSite",
            "uri_check": "https://strict.example/{account}",
            "e_code": 200,
            "e_string": "profile-header",
            "m_code": 404,
            "m_string": "not found",
        },
        {
            "name": "CodeOnlySite",
            "uri_check": "https://codeonly.example/{account}",
            "e_code": 200,
            "e_string": "",
            "m_code": 404,
            "m_string": "",
        },
    ],
}


@pytest.fixture
def sherlock(tmp_path):
    path = tmp_path / "sherlock.json"
    path.write_text(json.dumps(SHERLOCK_RULES), encoding="utf-8")
    return SherlockEngine.load(path)


@pytest.fixture
def wmn(tmp_path):
    path = tmp_path / "wmn.json"
    path.write_text(json.dumps(WMN_RULES), encoding="utf-8")
    return WhatsMyNameEngine.load(path)


# --- host matching --------------------------------------------------------


def test_netloc_ignores_www():
    assert _netloc("https://www.github.com/x") == _netloc("https://github.com/x")


def test_netloc_is_case_insensitive():
    assert _netloc("https://GitHub.COM/x") == "github.com"


def test_www_prefixed_rule_matches_bare_host(sherlock):
    assert sherlock.rule_for("https://wwwsite.example/bob") is not None


def test_entries_without_a_url_are_skipped(sherlock):
    assert all(rule.site_name != "NoUrl" for rule in sherlock.rules.values())


def test_unknown_host_has_no_rule(sherlock):
    assert sherlock.rule_for("https://nowhere.example/bob") is None
    assert sherlock.decide("https://nowhere.example/bob", "", 200, "") is UNKNOWN


# --- Sherlock semantics ---------------------------------------------------


def test_status_code_rule_treats_2xx_as_found(sherlock):
    url = "https://status.example/bob"
    assert sherlock.decide(url, url, 200, "") == FOUND
    assert sherlock.decide(url, url, 204, "") == FOUND
    assert sherlock.decide(url, url, 404, "") == NOT_FOUND
    assert sherlock.decide(url, url, 500, "") == NOT_FOUND


def test_explicit_error_code_means_absent(sherlock):
    """A 202 is 2xx, but this site's rule declares 202 to mean 'no such user'."""
    url = "https://coded.example/bob"
    assert sherlock.decide(url, url, 202, "") == NOT_FOUND
    assert sherlock.decide(url, url, 200, "") == FOUND


def test_message_rule_is_absence_of_the_error_string(sherlock):
    url = "https://msg.example/bob"
    assert sherlock.decide(url, url, 200, "welcome to bob's page") == FOUND
    assert sherlock.decide(url, url, 200, "sorry, nobody goes by that name") == NOT_FOUND


def test_message_rule_ors_multiple_messages(sherlock):
    url = "https://multi.example/bob"
    assert sherlock.decide(url, url, 200, "no such user") == NOT_FOUND
    assert sherlock.decide(url, url, 200, "not found here") == NOT_FOUND
    assert sherlock.decide(url, url, 200, "all good") == FOUND


def test_message_rule_ignores_status(sherlock):
    """Upstream checks the body, not the code, for message-type sites."""
    url = "https://msg.example/bob"
    assert sherlock.decide(url, url, 404, "welcome to bob's page") == FOUND


def test_response_url_rule_detects_redirect_away(sherlock):
    url = "https://redir.example/bob"
    assert sherlock.decide(url, url, 200, "") == FOUND
    assert sherlock.decide(url, "https://redir.example/login", 200, "") == NOT_FOUND


def test_response_url_rule_tolerates_trailing_slash(sherlock):
    url = "https://redir.example/bob"
    assert sherlock.decide(url, url + "/", 200, "") == FOUND


def test_source_records_provenance(sherlock):
    assert sherlock.source["engine"] == "sherlock"
    assert len(sherlock.source["sha256"]) == 64
    assert sherlock.source["usable_rules"] == len(sherlock.rules)


# --- WhatsMyName semantics ------------------------------------------------


def test_wmn_requires_both_code_and_string(wmn):
    url = "https://strict.example/bob"
    assert wmn.decide(url, url, 200, "<div class=profile-header>") == FOUND
    # Right code, missing marker -> the format does not let us conclude.
    assert wmn.decide(url, url, 200, "<div class=something-else>") is UNKNOWN


def test_wmn_missing_rule_marks_absent(wmn):
    url = "https://strict.example/bob"
    assert wmn.decide(url, url, 404, "user not found") == NOT_FOUND


def test_wmn_returns_unknown_when_neither_side_matches(wmn):
    """The format is two-sided; forcing a verdict would misrepresent the tool."""
    url = "https://strict.example/bob"
    assert wmn.decide(url, url, 503, "gateway error") is UNKNOWN


def test_wmn_code_only_rules_skip_string_matching(wmn):
    url = "https://codeonly.example/bob"
    assert wmn.decide(url, url, 200, "anything at all") == FOUND
    assert wmn.decide(url, url, 404, "") == NOT_FOUND


def test_wmn_records_upstream_license(wmn):
    assert wmn.source["license"] == ["test"]


# --- scoring and coverage accounting --------------------------------------


def _obs(site, url, label, status, body=""):
    return Observation(site, "u", url, label, status, {}, {}, None, body, url)


def test_rows_without_a_rule_are_excluded_not_penalised(sherlock):
    observations = [
        _obs("status", "https://status.example/a", 1, 200),
        _obs("elsewhere", "https://nowhere.example/a", 1, 404),
    ]
    result = score_engine(sherlock, observations)
    assert result["samples"] == 1
    assert result["rows_without_rule"] == 1
    # The uncovered row must not appear as a false negative.
    assert result["overall"]["fn"] == 0


def test_undecided_rows_are_excluded_not_penalised(wmn):
    observations = [
        _obs("strict", "https://strict.example/a", 1, 200, "profile-header"),
        _obs("strict", "https://strict.example/b", 1, 503, "gateway error"),
    ]
    result = score_engine(wmn, observations)
    assert result["samples"] == 1
    assert result["rows_rule_undecided"] == 1
    assert result["overall"]["tp"] == 1


def test_capture_error_rows_are_skipped(sherlock):
    observations = [
        _obs("status", "https://status.example/a", 1, 200),
        Observation("status", "u", "https://status.example/b", 0, 0, {}, {}, "timeout"),
    ]
    assert score_engine(sherlock, observations)["samples"] == 1


def test_scoring_builds_a_correct_confusion_matrix(sherlock):
    observations = [
        _obs("status", "https://status.example/a", 1, 200),   # tp
        _obs("status", "https://status.example/b", 0, 200),   # fp
        _obs("status", "https://status.example/c", 1, 404),   # fn
        _obs("status", "https://status.example/d", 0, 404),   # tn
    ]
    m = score_engine(sherlock, observations)["overall"]
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["precision"] == 0.5
    assert m["recall"] == 0.5


def test_external_engines_never_abstain(sherlock):
    """External tools are two-state; their Maybe rate must read as zero."""
    observations = [_obs("status", "https://status.example/a", 1, 200)]
    assert score_engine(sherlock, observations)["overall"]["maybe_rate"] == 0.0


def test_predictions_align_with_covered_urls(sherlock):
    observations = [
        _obs("status", "https://status.example/a", 1, 200),
        _obs("elsewhere", "https://nowhere.example/a", 1, 200),
        _obs("status", "https://status.example/b", 0, 404),
    ]
    result = score_engine(sherlock, observations)
    assert len(result["predictions"]) == len(result["covered_urls"])
    assert result["covered_urls"] == [
        "https://status.example/a",
        "https://status.example/b",
    ]
