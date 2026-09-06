"""Cross-sourced ground-truth construction: provenance, split discipline, and
the circularity guard that keeps a tool from being scored on its own tuning set."""

import json

import pytest

from aliens_eye.eval.groundtruth import (
    CURATED,
    PLACEHOLDER_HANDLES,
    SHERLOCK,
    WHATSMYNAME,
    GroundTruthEntry,
    _index_catalogue,
    assign_splits,
    cross_source,
    read_sherlock_accounts,
    read_whatsmyname_accounts,
    verify_positives,
    write_splits,
)
from aliens_eye.ml.collect import load_selfcheck_data

CATALOGUE = {
    "github": "https://github.com/{}",
    "reddit": "https://www.reddit.com/user/{}",
    "vimeo": "https://vimeo.com/{}",
    "bandcamp": "https://bandcamp.com/{}",
}


@pytest.fixture
def catalogue():
    return _index_catalogue(CATALOGUE)


# --- importing ------------------------------------------------------------


def test_sherlock_import_matches_by_host(tmp_path, catalogue):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({
        "GitHub": {"url": "https://www.github.com/{}", "username_claimed": "torvalds"},
        "Nowhere": {"url": "https://nowhere.example/{}", "username_claimed": "x"},
        "NoHandle": {"url": "https://vimeo.com/{}"},
    }), encoding="utf-8")
    accounts = read_sherlock_accounts(path, catalogue)
    assert accounts == {"github": ["torvalds"]}


def test_whatsmyname_import_keeps_all_known_accounts(tmp_path, catalogue):
    path = tmp_path / "w.json"
    path.write_text(json.dumps({"sites": [
        {"name": "Bandcamp", "uri_check": "https://bandcamp.com/{account}", "known": ["a", "b"]},
        {"name": "NoKnown", "uri_check": "https://vimeo.com/{account}", "known": []},
    ]}), encoding="utf-8")
    assert read_whatsmyname_accounts(path, catalogue) == {"bandcamp": ["a", "b"]}


def test_catalogue_index_ignores_www(catalogue):
    assert catalogue["reddit.com"] == "reddit"


# --- cross-sourcing -------------------------------------------------------


def test_existing_sites_keep_curated_provenance():
    entries = cross_source({"github": ["torvalds"]}, {"github": ["blue"]}, {"github": ["x"]})
    assert entries["github"].source == CURATED
    assert entries["github"].usernames == ["torvalds"]
    assert entries["github"].verified is True


def test_overlapping_sites_alternate_between_sources():
    """Both tools must end up with sites they can be scored on."""
    sherlock = {f"s{i}": [f"sh{i}"] for i in range(10)}
    whatsmyname = {f"s{i}": [f"wm{i}"] for i in range(10)}
    entries = cross_source({}, sherlock, whatsmyname)
    sources = [entries[f"s{i}"].source for i in range(10)]
    assert sources.count(SHERLOCK) == 5
    assert sources.count(WHATSMYNAME) == 5


def test_entry_usernames_come_from_its_recorded_source():
    entries = cross_source({}, {"a": ["from_sherlock"]}, {"a": ["from_wmn"]})
    entry = entries["a"]
    expected = "from_wmn" if entry.source == WHATSMYNAME else "from_sherlock"
    assert entry.usernames == [expected]


def test_single_source_sites_take_that_source():
    entries = cross_source({}, {"only_s": ["x"]}, {"only_w": ["y"]})
    assert entries["only_s"].source == SHERLOCK
    assert entries["only_w"].source == WHATSMYNAME


def test_placeholder_handles_are_flagged():
    entries = cross_source({}, {"a": ["blue"], "b": ["realperson"]}, {})
    assert entries["a"].notes["placeholder_handles"] == ["blue"]
    assert "placeholder_handles" not in entries["b"].notes


def test_cross_source_is_deterministic():
    sherlock = {f"s{i}": [f"a{i}"] for i in range(20)}
    whatsmyname = {f"s{i}": [f"b{i}"] for i in range(20)}
    first = {k: v.source for k, v in cross_source({}, sherlock, whatsmyname).items()}
    second = {k: v.source for k, v in cross_source({}, sherlock, whatsmyname).items()}
    assert first == second


def test_imported_entries_are_unverified():
    entries = cross_source({}, {"a": ["x"]}, {})
    assert entries["a"].verified is False


# --- splits ---------------------------------------------------------------


def test_existing_split_placement_is_preserved():
    entries = {s: GroundTruthEntry(s, ["u"], CURATED) for s in ("keep_t", "keep_h", "new")}
    splits = assign_splits(entries, {"keep_t"}, {"keep_h"})
    assert splits["keep_t"] == "train"
    assert splits["keep_h"] == "holdout"


def test_new_sites_are_split_in_both_directions():
    entries = {f"s{i}": GroundTruthEntry(f"s{i}", ["u"], SHERLOCK) for i in range(20)}
    splits = assign_splits(entries, set(), set())
    assert set(splits.values()) == {"train", "holdout"}
    assert 0 < sum(1 for v in splits.values() if v == "holdout") < 20


def test_splits_cover_every_site():
    entries = {f"s{i}": GroundTruthEntry(f"s{i}", ["u"], SHERLOCK) for i in range(7)}
    assert set(assign_splits(entries, set(), set())) == set(entries)


def test_write_splits_round_trips_through_the_loader(tmp_path):
    entries = cross_source({"github": ["torvalds"]}, {"vimeo": ["blue"]}, {"bandcamp": ["x", "y"]})
    splits = assign_splits(entries, {"github"}, set())
    train, holdout = tmp_path / "train.json", tmp_path / "holdout.json"
    summary = write_splits(entries, splits, train, holdout)

    assert summary["total_sites"] == 3
    loaded = load_selfcheck_data(path=train)
    loaded.update(load_selfcheck_data(path=holdout))
    assert loaded["github"] == ["torvalds"]
    assert loaded["bandcamp"] == ["x", "y"]


def test_written_splits_are_site_disjoint(tmp_path):
    entries = {f"s{i}": GroundTruthEntry(f"s{i}", ["u"], SHERLOCK) for i in range(30)}
    splits = assign_splits(entries, set(), set())
    train, holdout = tmp_path / "t.json", tmp_path / "h.json"
    write_splits(entries, splits, train, holdout)
    t = set(json.loads(train.read_text("utf-8")))
    h = set(json.loads(holdout.read_text("utf-8")))
    assert not (t & h)
    assert t | h == set(entries)


def test_written_form_carries_provenance(tmp_path):
    entries = cross_source({}, {"vimeo": ["blue"]}, {})
    splits = assign_splits(entries, set(), set())
    train, holdout = tmp_path / "t.json", tmp_path / "h.json"
    write_splits(entries, splits, train, holdout)
    merged = {**json.loads(train.read_text("utf-8")), **json.loads(holdout.read_text("utf-8"))}
    assert merged["vimeo"]["source"] == SHERLOCK
    assert merged["vimeo"]["usernames"] == ["blue"]


# --- verification ---------------------------------------------------------


class _Engine:
    def __init__(self, verdict):
        self.verdict = verdict

    def decide(self, url, final_url, status, body):
        return self.verdict


def _obs(site, label=1, username="u"):
    from aliens_eye.eval.ablate import Observation

    return Observation(site, username, f"https://{site}.example/{username}", label, 200, {}, {})


def test_positive_rejected_when_every_independent_rule_says_absent():
    result = verify_positives(
        [_obs("a")],
        {"sherlock": _Engine("Not Found"), "whatsmyname": _Engine("Not Found")},
        {"a": CURATED},
    )
    assert result["suspect"] == 1
    assert result["corroborated"] == 0


def test_positive_kept_when_any_rule_says_found():
    result = verify_positives(
        [_obs("a")],
        {"sherlock": _Engine("Found"), "whatsmyname": _Engine("Not Found")},
        {"a": CURATED},
    )
    assert result["suspect"] == 0
    assert result["corroborated"] == 1


def test_the_accounts_own_source_is_never_consulted():
    """Sherlock agreeing with Sherlock's own tuning set is not evidence."""
    result = verify_positives(
        [_obs("a")],
        {"sherlock": _Engine("Found")},
        {"a": SHERLOCK},
    )
    assert result["checked"] == 0
    assert result["no_independent_rule"] == 1


def test_rows_with_no_independent_ruling_are_not_counted():
    result = verify_positives([_obs("a")], {"sherlock": _Engine(None)}, {"a": CURATED})
    assert result["no_independent_rule"] == 1
    assert result["checked"] == 0


def test_negatives_and_errors_are_ignored():
    from aliens_eye.eval.ablate import Observation

    rows = [
        _obs("a", label=0),
        Observation("b", "u", "https://b.example/u", 1, 0, {}, {}, "timeout"),
    ]
    result = verify_positives(rows, {"sherlock": _Engine("Not Found")}, {})
    assert result["checked"] == 0


def test_suspects_report_source_and_placeholder_status():
    result = verify_positives(
        [_obs("a", username="blue")],
        {"whatsmyname": _Engine("Not Found")},
        {"a": SHERLOCK},
    )
    assert result["suspect_by_source"] == {SHERLOCK: 1}
    assert result["suspect_placeholder_handles"] == 1
    assert "blue" in PLACEHOLDER_HANDLES
