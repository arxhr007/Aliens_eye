import json

from aliens_eye.eval.external import ENGINES, FOUND, NOT_FOUND, UNKNOWN


def engine(tmp_path, sites, engines=None):
    path = tmp_path / "maigret.json"
    path.write_text(json.dumps({"sites": sites, "engines": engines or {}}), encoding="utf-8")
    return ENGINES["maigret"].load(path)


def test_real_nested_database_and_engine_rules(tmp_path):
    checker = engine(tmp_path, {"Forum": {"urlMain": "https://forum.example", "engine": "ForumEngine"}}, {
        "ForumEngine": {"site": {
            "url": "{urlMain}/u/{username}",
            "checkType": "message",
            "presenseStrs": ["profile-header"],
            "absenceStrs": ["missing-user"],
        }},
    })
    url = "https://forum.example/u/alice"
    assert checker.source["usable_rules"] == 1
    assert checker.decide(url, url, 200, "profile-header") == FOUND
    assert checker.decide(url, url, 200, "missing-user") == NOT_FOUND
    assert checker.decide(url, url, 200, "neither marker") == NOT_FOUND
    assert checker.decide(url, url, 403, "profile-header") is UNKNOWN


def test_profile_response_cannot_stand_in_for_api_probe(tmp_path):
    checker = engine(tmp_path, {"API": {
        "url": "https://example.org/{username}",
        "urlProbe": "https://api.example.org/users/{username}",
        "checkType": "status_code",
    }})
    assert checker.decide("https://example.org/alice", "https://example.org/alice", 200, "") is UNKNOWN
    probe = "https://api.example.org/users/alice"
    assert checker.decide(probe, probe, 200, "") == FOUND


def test_distinct_endpoint_rules_on_one_host(tmp_path):
    checker = engine(tmp_path, {
        "First": {"url": "https://example.org/first/{username}", "checkType": "message", "absenceStrs": ["first missing"]},
        "Second": {"url": "https://example.org/second/{username}", "checkType": "message", "absenceStrs": ["second missing"]},
    })
    first, second = "https://example.org/first/alice", "https://example.org/second/alice"
    assert checker.decide(first, first, 200, "first missing") == NOT_FOUND
    assert checker.decide(second, second, 200, "second missing") == NOT_FOUND


def test_unknown_request_policy_is_not_scored(tmp_path):
    checker = engine(tmp_path, {"Redirect": {
        "url": "https://example.org/{username}", "checkType": "response_url",
    }})
    url = "https://example.org/alice"
    assert checker.decide(url, url, 200, "profile") is UNKNOWN
