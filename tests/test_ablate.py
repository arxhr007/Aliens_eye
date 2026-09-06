"""Ablation harness: configuration correctness and the statistics that keep the
resulting table from overclaiming."""

import asyncio

import pytest
from test_corpus import _NullLogger, make_corpus

from aliens_eye.core.detector import Detector
from aliens_eye.core.features import FEATURE_SCHEMA
from aliens_eye.eval.ablate import (
    FEATURE_GROUPS,
    Observation,
    _apply_drop,
    _f1_from_pairs,
    bootstrap_f1,
    build_ablations,
    collect_observations,
    paired_delta_f1,
    run_ablations,
    score_ablation,
)

# --- configuration wiring -------------------------------------------------


def test_feature_groups_reference_real_features():
    """A typo in FEATURE_GROUPS would silently ablate nothing."""
    schema = set(FEATURE_SCHEMA)
    for group, names in FEATURE_GROUPS.items():
        unknown = [n for n in names if n not in schema]
        assert not unknown, f"group {group!r} names features not in FEATURE_SCHEMA: {unknown}"


def test_every_feature_group_is_non_empty():
    for group, names in FEATURE_GROUPS.items():
        assert names, f"group {group!r} is empty"


def test_build_ablations_covers_baselines_judges_and_groups():
    names = {a.name for a in build_ablations(0.6)}
    assert {"status_only", "status_not_404"} <= names
    assert {"heuristic_only", "ml_only", "blended_shipped"} <= names
    assert {f"no_{g}" for g in FEATURE_GROUPS} <= names


def test_shipped_blend_uses_the_model_weight():
    shipped = next(a for a in build_ablations(0.6) if a.name == "blended_shipped")
    # ml_prob=1.0, heuristic_prob=0.0 -> probability should be the ML weight.
    obs = Observation("s", "u", "url", 1, 200, {}, {})
    assert shipped.combine(0.0, 1.0, obs) == pytest.approx(0.6)


def test_judge_ablations_isolate_each_judge():
    ablations = {a.name: a for a in build_ablations(0.6)}
    obs = Observation("s", "u", "url", 1, 200, {}, {})
    assert ablations["heuristic_only"].combine(0.25, 1.0, obs) == pytest.approx(0.25)
    assert ablations["ml_only"].combine(0.25, 1.0, obs) == pytest.approx(1.0)


def test_judge_ablations_degrade_gracefully_without_a_model():
    ablations = {a.name: a for a in build_ablations(None)}
    obs = Observation("s", "u", "url", 1, 200, {}, {})
    assert ablations["ml_only"].combine(0.3, None, obs) == pytest.approx(0.3)


def test_status_only_is_a_pure_status_check():
    ablations = {a.name: a for a in build_ablations(0.6)}
    status_only = ablations["status_only"]
    # Heuristic and ML both scream "found"; the baseline must ignore them.
    assert status_only.combine(1.0, 1.0, Observation("s", "u", "x", 1, 404, {}, {})) == 0.0
    assert status_only.combine(0.0, 0.0, Observation("s", "u", "x", 1, 200, {}, {})) == 1.0


def test_apply_drop_zeroes_only_the_named_group():
    features = {name: 1.0 for name in FEATURE_SCHEMA}
    masked = _apply_drop(features, ("timing",))
    assert masked["response_time"] == 0.0
    assert masked["http_200"] == 1.0
    # The original must not be mutated: every configuration reads the same rows.
    assert features["response_time"] == 1.0


def test_apply_drop_without_groups_is_identity():
    features = {"http_200": 1.0}
    assert _apply_drop(features, ()) is features


# --- statistics -----------------------------------------------------------


def test_f1_from_pairs_matches_hand_calculation():
    # 2 tp, 1 fp, 1 fn -> F1 = 2*2 / (2*2 + 1 + 1) = 0.666...
    pairs = [(1, 1), (1, 1), (0, 1), (1, 0)]
    assert _f1_from_pairs(pairs) == pytest.approx(2 / 3)


def test_f1_is_zero_when_nothing_predicted_positive():
    assert _f1_from_pairs([(1, 0), (0, 0)]) == 0.0


def test_bootstrap_ci_brackets_the_point_estimate():
    pairs = [(1, 1)] * 20 + [(0, 0)] * 20 + [(1, 0)] * 5 + [(0, 1)] * 5
    result = bootstrap_f1(pairs, iterations=500)
    assert result["ci_low"] <= result["f1"] <= result["ci_high"]
    assert 0.0 <= result["ci_low"] <= 1.0


def test_bootstrap_is_seed_reproducible():
    pairs = [(1, 1)] * 10 + [(0, 1)] * 10
    assert bootstrap_f1(pairs, iterations=200) == bootstrap_f1(pairs, iterations=200)


def test_bootstrap_handles_empty_input():
    assert bootstrap_f1([])["iterations"] == 0


def test_identical_configurations_are_not_separable():
    pairs = [(1, 1)] * 10 + [(0, 0)] * 10 + [(1, 0)] * 3
    delta = paired_delta_f1(pairs, pairs, iterations=500)
    assert delta["delta"] == 0.0
    assert delta["separable"] is False


def test_a_clearly_better_configuration_is_separable():
    labels = [1] * 40 + [0] * 40
    bad = [(y, 1) for y in labels]                      # says Found to everything
    good = [(y, y) for y in labels]                     # perfect
    delta = paired_delta_f1(bad, good, iterations=1000)
    assert delta["delta"] > 0
    assert delta["separable"] is True


def test_a_tiny_difference_on_few_rows_is_not_separable():
    """The guard against overclaiming: small corpora cannot resolve small gaps."""
    labels = [1] * 6 + [0] * 6
    a = [(y, y) for y in labels]
    b = list(a)
    b[0] = (1, 0)  # one row worse
    delta = paired_delta_f1(a, b, iterations=1000)
    assert delta["separable"] is False


def test_paired_delta_rejects_mismatched_lengths():
    assert paired_delta_f1([(1, 1)], [(1, 1), (0, 0)])["separable"] is False


# --- end to end over a corpus --------------------------------------------


def _corpus(tmp_path, monkeypatch, found_html, not_found_html):
    urls = {
        "https://github.com/torvalds": (200, found_html),
        "https://github.com/ghost1": (404, not_found_html),
        "https://github.com/ghost2": (404, not_found_html),
        "https://www.reddit.com/user/spez": (200, found_html),
        "https://www.reddit.com/user/ghost3": (404, not_found_html),
    }
    jobs = [
        ("github", "https://github.com/torvalds", "torvalds", 1),
        ("github", "https://github.com/ghost1", "ghost1", 0),
        ("github", "https://github.com/ghost2", "ghost2", 0),
        ("reddit", "https://www.reddit.com/user/spez", "spez", 1),
        ("reddit", "https://www.reddit.com/user/ghost3", "ghost3", 0),
    ]
    root, _ = make_corpus(tmp_path, monkeypatch, urls, jobs)
    return root


def test_run_ablations_over_a_corpus(tmp_path, monkeypatch, found_html, not_found_html, logger):
    root = _corpus(tmp_path, monkeypatch, found_html, not_found_html)
    detector = Detector()
    detector.load_model(logger)

    bundle = asyncio.run(run_ablations(root, detector, logger, bootstrap_iterations=200))
    assert bundle["usable_rows"] == 5
    assert bundle["positives"] == 2
    assert bundle["negatives"] == 3
    assert bundle["reference"] == "blended_shipped"

    names = [r["name"] for r in bundle["results"]]
    assert "status_only" in names and "ml_only" in names
    for row in bundle["results"]:
        assert "bootstrap" in row
        assert "predictions" not in row, "per-row predictions must not leak into the report"
        assert 0.0 <= row["overall"]["maybe_rate"] <= 1.0


def test_run_ablations_is_deterministic(tmp_path, monkeypatch, found_html, not_found_html, logger):
    root = _corpus(tmp_path, monkeypatch, found_html, not_found_html)
    detector = Detector()
    detector.load_model(logger)
    a = asyncio.run(run_ablations(root, detector, logger, bootstrap_iterations=200))
    b = asyncio.run(run_ablations(root, detector, logger, bootstrap_iterations=200))
    assert a == b


def test_run_ablations_rejects_unknown_names(tmp_path, monkeypatch, found_html, not_found_html, logger):
    root = _corpus(tmp_path, monkeypatch, found_html, not_found_html)
    detector = Detector()
    with pytest.raises(ValueError, match="Unknown ablation"):
        asyncio.run(run_ablations(root, detector, logger, names=["nope"]))


def test_status_only_baseline_never_abstains(tmp_path, monkeypatch, found_html, not_found_html, logger):
    """A two-state baseline must not get credit for the tri-state abstain band."""
    root = _corpus(tmp_path, monkeypatch, found_html, not_found_html)
    detector = Detector()
    detector.load_model(logger)
    observations = asyncio.run(collect_observations(root, None, logger))
    ablations = {a.name: a for a in build_ablations(detector.model.ml_weight)}
    result = score_ablation(ablations["status_only"], observations, detector)
    assert result["overall"]["maybe_rate"] == 0.0


def test_site_filter_restricts_the_evaluation(tmp_path, monkeypatch, found_html, not_found_html, logger):
    root = _corpus(tmp_path, monkeypatch, found_html, not_found_html)
    observations = asyncio.run(collect_observations(root, {"github"}, _NullLogger()))
    assert {o.site for o in observations} == {"github"}
