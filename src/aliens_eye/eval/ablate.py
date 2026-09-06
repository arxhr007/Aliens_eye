"""Ablation harness: which parts of the detector actually earn their place.

Every configuration is scored over the *same* frozen corpus, so differences are
attributable to the configuration and nothing else. Feature extraction runs once
per response and is shared across configurations -- extracting separately would
let a change in the harness masquerade as a change in the detector.

Three families of configuration:

* **Baselines** -- what the README implicitly claims to beat. ``status_only``
  is the naive check (HTTP 200 means the account exists) that most username
  enumerators still use.
* **Judges** -- heuristic alone, ML alone, and the shipped blend, to separate
  each judge's contribution from the blend's.
* **Feature groups** -- zero out one group of ``FEATURE_SCHEMA`` at a time and
  re-score, which shows what each family of signals is worth.

Reported per configuration: precision, recall, F1, false-positive rate, and the
**Maybe rate**. The Maybe rate matters because the detector is tri-state: a
configuration can flatter its precision by abstaining on everything hard, and
that shows up here rather than hiding inside the confusion matrix.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import (
    FOUND_THRESHOLD,
    NOT_FOUND_THRESHOLD,
    Detector,
)
from aliens_eye.core.fingerprints import FingerprintStore, build_fingerprint
from aliens_eye.corpus.replay import ReplayFetcher
from aliens_eye.selfcheck import _metrics

# Families of signal, for the group ablations. Names must exist in
# FEATURE_SCHEMA; validated by tests/test_ablate.py.
FEATURE_GROUPS: dict[str, list[str]] = {
    "status": ["http_200", "http_3xx", "http_404", "http_4xx", "http_5xx"],
    "keywords": [
        "error_keyword_count",
        "positive_keyword_count",
        "meta_error_keyword_count",
        "meta_positive_keyword_count",
    ],
    "dom": [
        "profile_section_count",
        "error_section_count",
        "img_count",
        "input_count",
        "form_count",
        "link_count",
    ],
    "structured_data": ["og_type_profile", "has_json_ld_person", "username_in_canonical"],
    "url_shape": ["has_username_in_path", "is_homepage", "has_auth_pattern", "username_in_canonical"],
    "timing": ["response_time"],
    "size": ["content_length", "text_length"],
}


@dataclass
class Observation:
    """One corpus row, with features extracted once and reused by every config."""

    site: str
    username: str
    url: str
    label: int
    status_code: int
    features: dict[str, float]
    fingerprint: dict[str, str]
    error: str | None = None
    #: Raw response body. Kept so external rule engines (aliens_eye.eval.external)
    #: can be scored on exactly the same responses, rather than on a second fetch.
    body: str = ""
    final_url: str = ""


@dataclass
class Ablation:
    """A detector configuration to score."""

    name: str
    description: str
    #: Maps (heuristic_prob, ml_prob, observation) -> probability in [0, 1].
    combine: Callable[[float, float | None, Observation], float]
    #: Feature groups zeroed before scoring.
    drop_groups: tuple[str, ...] = ()
    #: Tri-state thresholds; None means take them from the loaded model.
    thresholds: tuple[float, float] | None = None
    #: Force a hard two-state decision (no Maybe band).
    binary: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


def _blend(weight: float) -> Callable[[float, float | None, Observation], float]:
    def combine(heuristic_prob: float, ml_prob: float | None, _obs: Observation) -> float:
        if ml_prob is None:
            return heuristic_prob
        return weight * ml_prob + (1.0 - weight) * heuristic_prob

    return combine


def _status_only(_h: float, _m: float | None, obs: Observation) -> float:
    """The naive baseline: HTTP 200 means the profile exists."""
    return 1.0 if obs.status_code == 200 else 0.0


def _status_and_not_404(_h: float, _m: float | None, obs: Observation) -> float:
    """Slightly less naive: anything that is not an explicit 404 counts."""
    return 0.0 if obs.status_code in (0, 404, 410) else 1.0


def build_ablations(model_weight: float | None) -> list[Ablation]:
    """The standard configuration set. ``model_weight`` is the shipped blend."""
    shipped = model_weight if model_weight is not None else 0.4
    ablations = [
        Ablation(
            "status_only",
            "HTTP 200 means found. The naive check most enumerators use.",
            _status_only, binary=True, tags=("baseline",),
        ),
        Ablation(
            "status_not_404",
            "Anything that is not an explicit 404/410 counts as found.",
            _status_and_not_404, binary=True, tags=("baseline",),
        ),
        Ablation(
            "heuristic_only",
            "Weighted structural scoring, no ML (equivalent to --no-ml).",
            _blend(0.0), tags=("judge",),
        ),
        Ablation(
            "ml_only",
            "Logistic regression alone, heuristic used only as an input feature.",
            _blend(1.0), tags=("judge",),
        ),
        Ablation(
            "blended_shipped",
            f"The system as released: {shipped:g} ML + {1 - shipped:g} heuristic.",
            _blend(shipped), tags=("judge", "shipped"),
        ),
    ]
    for group in sorted(FEATURE_GROUPS):
        ablations.append(
            Ablation(
                f"no_{group}",
                f"Shipped blend with the {group} feature group zeroed.",
                _blend(shipped),
                drop_groups=(group,),
                tags=("feature_group",),
            )
        )
    return ablations


#: Names of the standard set, for CLI validation and docs.
ABLATIONS = [a.name for a in build_ablations(None)]


def _apply_drop(features: dict[str, float], groups: tuple[str, ...]) -> dict[str, float]:
    if not groups:
        return features
    masked = dict(features)
    for group in groups:
        for name in FEATURE_GROUPS.get(group, ()):
            masked[name] = 0.0
    return masked


async def collect_observations(
    corpus: Path,
    sites: set[str] | None,
    logger,
    use_fingerprints: bool = False,
) -> list[Observation]:
    """Extract features once per corpus row, in a fixed order.

    Fingerprints are off by default. A live fingerprint store accumulates
    signatures during a run and scores each response against whatever came
    before, so it is order-dependent; here the order is fixed and explicit, which
    makes the ``fingerprints`` ablation reproducible rather than merely stable.
    """
    replay = ReplayFetcher(corpus, strict=True)
    extractor = FeatureExtractor()
    jobs = replay.eval_jobs(sites)
    store = FingerprintStore(Path("unused"), read_only=not use_fingerprints)
    config = ScannerConfig()

    observations: list[Observation] = []
    for site, url, username, label in jobs:
        fetch = await replay(None, url, config, None, logger)
        if fetch.error:
            observations.append(
                Observation(site, username, url, label, fetch.status, {}, {}, fetch.error)
            )
            continue
        try:
            bundle = extractor.extract(
                fetch.content, fetch.final_url, username, site,
                fetch.status, fetch.response_time, fetch.headers, fetch.redirect_count,
            )
        except Exception as exc:  # noqa: BLE001 - a broken page is a data point, not a crash
            logger.debug("Extraction failed for %s: %s", url, exc)
            observations.append(
                Observation(site, username, url, label, fetch.status, {}, {}, str(exc))
            )
            continue

        fingerprint = build_fingerprint(bundle.fingerprint)
        scored = store.score(site, fingerprint)
        bundle.features["fingerprint_match_found"] = float(scored["match_found"])
        bundle.features["fingerprint_match_not_found"] = float(scored["match_not_found"])
        if use_fingerprints:
            store.add(site, "found" if label == 1 else "not_found", fingerprint)
        observations.append(
            Observation(
                site, username, url, label, fetch.status, bundle.features, fingerprint,
                body=fetch.content, final_url=fetch.final_url,
            )
        )
    return observations


def score_ablation(
    ablation: Ablation,
    observations: list[Observation],
    detector: Detector,
) -> dict[str, Any]:
    """Score one configuration over pre-extracted observations."""
    if ablation.thresholds is not None:
        found_thr, not_found_thr = ablation.thresholds
    elif detector.model is not None:
        found_thr = detector.model.found_threshold
        not_found_thr = detector.model.not_found_threshold
    else:
        found_thr, not_found_thr = FOUND_THRESHOLD, NOT_FOUND_THRESHOLD

    tp = fp = fn = tn = maybe = scored = 0
    per_site: dict[str, dict[str, int]] = {}
    # (label, predicted) per scored row, in a fixed order, so configurations can
    # be compared row-for-row by a paired bootstrap.
    predictions: list[tuple[int, int]] = []
    for obs in observations:
        if obs.error:
            continue
        features = _apply_drop(obs.features, ablation.drop_groups)
        _, heuristic_prob, ml_prob = detector.judges(features)
        probability = ablation.combine(heuristic_prob, ml_prob, obs)

        if ablation.binary:
            status = "Found" if probability >= 0.5 else "Not Found"
        else:
            status, _confidence = detector._status_from_probability(
                probability, found_thr, not_found_thr
            )
        if status == "Maybe":
            maybe += 1
        # Maybe counts as "not Found", matching how the tool reports a scan:
        # only Found is an assertion the user acts on.
        predicted = 1 if status == "Found" else 0

        predictions.append((obs.label, predicted))
        cell = per_site.setdefault(obs.site, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        if obs.label == 1 and predicted == 1:
            key = "tp"
        elif obs.label == 1:
            key = "fn"
        elif predicted == 1:
            key = "fp"
        else:
            key = "tn"
        cell[key] += 1
        tp += key == "tp"
        fp += key == "fp"
        fn += key == "fn"
        tn += key == "tn"
        scored += 1

    overall = _metrics(tp, fp, fn, tn)
    overall["maybe_rate"] = round(maybe / scored, 4) if scored else 0.0
    return {
        "name": ablation.name,
        "description": ablation.description,
        "tags": list(ablation.tags),
        "dropped_groups": list(ablation.drop_groups),
        "samples": scored,
        "overall": overall,
        "per_site": {
            s: _metrics(c["tp"], c["fp"], c["fn"], c["tn"]) for s, c in per_site.items()
        },
        "predictions": predictions,
    }


def _f1_from_pairs(pairs: list[tuple[int, int]]) -> float:
    tp = sum(1 for label, pred in pairs if label == 1 and pred == 1)
    fp = sum(1 for label, pred in pairs if label == 0 and pred == 1)
    fn = sum(1 for label, pred in pairs if label == 1 and pred == 0)
    denominator = 2 * tp + fp + fn
    return (2 * tp / denominator) if denominator else 0.0


def bootstrap_f1(
    predictions: list[tuple[int, int]],
    iterations: int = 2000,
    seed: int = 1234,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Percentile bootstrap CI for F1 over the scored rows.

    With a few dozen rows and a handful of positives, point estimates of F1 are
    extremely unstable: resampling shows how much of an apparent gap between two
    configurations is sampling noise rather than signal.
    """
    if not predictions:
        return {"f1": 0.0, "ci_low": 0.0, "ci_high": 0.0, "iterations": 0}
    rng = random.Random(seed)
    n = len(predictions)
    draws = []
    for _ in range(iterations):
        sample = [predictions[rng.randrange(n)] for _ in range(n)]
        draws.append(_f1_from_pairs(sample))
    draws.sort()
    low = draws[int((alpha / 2) * iterations)]
    high = draws[min(iterations - 1, int((1 - alpha / 2) * iterations))]
    return {
        "f1": round(_f1_from_pairs(predictions), 4),
        "ci_low": round(low, 4),
        "ci_high": round(high, 4),
        "iterations": iterations,
    }


def paired_delta_f1(
    baseline: list[tuple[int, int]],
    candidate: list[tuple[int, int]],
    iterations: int = 2000,
    seed: int = 1234,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Paired bootstrap on the F1 difference (candidate - baseline).

    Paired, because both configurations score the *same* rows: resampling the
    rows jointly removes the between-row variance that would otherwise swamp the
    comparison. A CI spanning zero means the corpus cannot distinguish the two.
    """
    if not baseline or len(baseline) != len(candidate):
        return {"delta": 0.0, "ci_low": 0.0, "ci_high": 0.0, "separable": False}
    rng = random.Random(seed)
    n = len(baseline)
    draws = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        draws.append(
            _f1_from_pairs([candidate[i] for i in idx])
            - _f1_from_pairs([baseline[i] for i in idx])
        )
    draws.sort()
    low = draws[int((alpha / 2) * iterations)]
    high = draws[min(iterations - 1, int((1 - alpha / 2) * iterations))]
    return {
        "delta": round(_f1_from_pairs(candidate) - _f1_from_pairs(baseline), 4),
        "ci_low": round(low, 4),
        "ci_high": round(high, 4),
        "separable": bool(low > 0 or high < 0),
    }


async def run_ablations(
    corpus: Path,
    detector: Detector,
    logger,
    sites: set[str] | None = None,
    names: list[str] | None = None,
    use_fingerprints: bool = False,
    bootstrap_iterations: int = 2000,
) -> dict[str, Any]:
    """Score every configuration over one corpus. Returns a result bundle."""
    observations = await collect_observations(corpus, sites, logger, use_fingerprints)
    model_weight = getattr(detector.model, "ml_weight", None)
    ablations = build_ablations(model_weight)
    if names:
        wanted = set(names)
        unknown = wanted - {a.name for a in ablations}
        if unknown:
            raise ValueError(
                f"Unknown ablation(s): {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(a.name for a in ablations)}"
            )
        ablations = [a for a in ablations if a.name in wanted]

    results = [score_ablation(a, observations, detector) for a in ablations]

    # Uncertainty, not just point estimates. On a corpus this small an apparent
    # F1 gap of a few points is usually indistinguishable from noise, and saying
    # so is the difference between a finding and an overclaim.
    reference = next(
        (r for r in results if "shipped" in r["tags"]),
        results[0] if results else None,
    )
    # Snapshot the reference rows before the loop: the loop drops each row's
    # per-row predictions once used, and the reference is itself one of the rows.
    reference_predictions = list(reference["predictions"]) if reference is not None else None
    for row in results:
        row["bootstrap"] = bootstrap_f1(row["predictions"], iterations=bootstrap_iterations)
        if reference_predictions is not None and row is not reference:
            row["vs_reference"] = paired_delta_f1(
                reference_predictions, row["predictions"],
                iterations=bootstrap_iterations,
            )
        row.pop("predictions", None)

    usable = sum(1 for o in observations if not o.error)
    return {
        "corpus": str(corpus),
        "sites": sorted({o.site for o in observations}),
        "rows": len(observations),
        "usable_rows": usable,
        "excluded_rows": len(observations) - usable,
        "positives": sum(1 for o in observations if o.label == 1 and not o.error),
        "negatives": sum(1 for o in observations if o.label == 0 and not o.error),
        "fingerprints": use_fingerprints,
        "model_ml_weight": model_weight,
        "reference": reference["name"] if reference else None,
        "bootstrap_iterations": bootstrap_iterations,
        "results": results,
    }


def run_ablations_sync(*args, **kwargs) -> dict[str, Any]:
    return asyncio.run(run_ablations(*args, **kwargs))
