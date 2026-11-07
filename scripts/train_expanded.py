"""Train a candidate detection model that has seen the expanded catalog's sites.

Stages, each resumable on its own and each writing into one work directory:

  prepare  Build ground truth from upstream-asserted and curated usernames
           for trainable expanded-catalog sites. Offline.
  record   Capture those profile pages plus generated negatives into a frozen
           corpus. This is the only stage that touches the network.
  collect  Replay the corpus into a site-grouped feature CSV. Offline.
  fit      Fit a candidate model with site-grouped validation. Offline.
  compare  Score the shipped and candidate models on the holdout corpus. Offline.
  all      Run every stage in order.

The shipped model is never replaced. Promote a candidate by hand, and only when
it beats the shipped model on the holdout: training and CV scores alone measure
sites the model has already seen.

Example:

  .venv/Scripts/python.exe scripts/train_expanded.py all --work runs/expanded-1 \
      --upstream-data path/to/data.json --max-sites 600 \
      --holdout-corpus paper/corpus/v3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
from pathlib import Path

GROUND_TRUTH = "ground_truth.json"
SITES = "training_sites.json"
CORPUS = "corpus"
DATASET = "dataset.csv"
MODEL = "candidate_model.json"
COMPARISON = "comparison.json"


def _logger(verbose: bool) -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    return logging.getLogger("train_expanded")


def _require_absent(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"{path} already exists; use a new --work directory or delete it first")


def _require(path: Path, stage: str) -> None:
    if not path.exists():
        raise SystemExit(f"{path} is missing; run the '{stage}' stage first")


def prepare(args, log) -> None:
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.core.sites import SiteCatalog
    from aliens_eye.ml.expanded import (
        build_ground_truth,
        upstream_examples,
        write_ground_truth,
        write_training_catalog,
    )

    work = Path(args.work)
    _require_absent(work / GROUND_TRUTH)
    _require_absent(work / SITES)
    catalog = load_sites_data(catalog="extended")
    if args.upstream_data is None:
        log.warning("No --upstream-data given: only bundled and curated usernames are available")
    examples = upstream_examples(catalog, Path(args.upstream_data) if args.upstream_data else None)
    truth, subset, skipped = build_ground_truth(
        catalog, examples, max_per_site=args.positives_per_site, include_nsfw=args.include_nsfw,
    )
    if args.max_sites and len(truth) > args.max_sites:
        # Sample sites, not rows: the model generalizes across sites, so a
        # smaller spread of sites is the honest way to bound the scan.
        keep = sorted(random.Random(args.seed).sample(sorted(truth), args.max_sites))
        truth = {site: truth[site] for site in keep}
        subset = SiteCatalog({site: subset.definitions[site] for site in keep}, subset.sources)
    work.mkdir(parents=True, exist_ok=True)
    write_ground_truth(work / GROUND_TRUTH, truth)
    write_training_catalog(work / SITES, subset)
    positives = sum(len(entry["usernames"]) for entry in truth.values())
    log.info("Prepared %d sites, %d asserted positives -> %s", len(truth), positives, work)
    for reason, count in sorted(skipped.items(), key=lambda item: -item[1]):
        log.info("  skipped %5d  %s", count, reason)


def record(args, log) -> None:
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.corpus.record import record_corpus
    from aliens_eye.ml.collect import load_selfcheck_data

    work = Path(args.work)
    _require(work / GROUND_TRUTH, "prepare")
    _require_absent(work / CORPUS)
    sites = load_sites_data(work / SITES)
    truth = load_selfcheck_data(path=work / GROUND_TRUTH)
    log.info(
        "Recording %d positives + %d negatives/site across %d sites (live network)",
        sum(map(len, truth.values())), args.negatives, len(truth),
    )
    manifest = asyncio.run(record_corpus(
        sites, truth, work / CORPUS, log,
        negatives_per_site=args.negatives, concurrency=args.concurrency, seed=args.seed,
        split="train", config=ScannerConfig(retries=2, timeout=args.timeout),
    ))
    log.info("Captured %d records (%d fetch errors)", manifest["records"], manifest["errors"])


def collect(args, log) -> None:
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.ml.collect import collect_from_corpus

    work = Path(args.work)
    _require(work / CORPUS, "record")
    _require_absent(work / DATASET)
    count = collect_from_corpus(
        work / CORPUS, load_sites_data(work / SITES), work / DATASET, log,
        split="train", ground_truth_path=work / GROUND_TRUTH,
    )
    if not count:
        raise SystemExit("The corpus produced no usable HTML training rows")


def fit(args, log) -> None:
    from aliens_eye.ml.train import train_model

    work = Path(args.work)
    _require(work / DATASET, "collect")
    _require_absent(work / MODEL)
    model = train_model(work / DATASET, work / MODEL, log, max_fpr=args.max_fpr)
    training = model["training"]
    log.info(
        "Candidate: %d rows (%d positive) over %s site groups; selection CV F1 %s",
        training["samples"], training["positives"], training["site_groups"],
        f"{training['cv_f1']:.3f}" if training["cv_f1"] is not None else "n/a",
    )


def compare(args, log) -> None:
    from aliens_eye.core.detector import Detector
    from aliens_eye.eval.ablate import run_ablations
    from aliens_eye.ml.collect import load_selfcheck_data

    work = Path(args.work)
    _require(work / MODEL, "fit")
    _require_absent(work / COMPARISON)
    if not args.holdout_corpus:
        raise SystemExit("compare needs --holdout-corpus (record one with: aliens_eye corpus record --split holdout)")
    holdout = set(load_selfcheck_data("holdout"))
    results = {}
    for label, model_path in (("shipped", None), ("candidate", work / MODEL)):
        detector = Detector()
        detector.load_model(log, model_path)
        if detector.model is None:
            raise SystemExit(f"Could not load the {label} model; refusing to compare against heuristics only")
        bundle = asyncio.run(run_ablations(
            Path(args.holdout_corpus), detector, log, sites=holdout,
            names=["blended_shipped"], bootstrap_iterations=args.bootstrap,
        ))
        row = bundle["results"][0]
        results[label] = {"overall": row["overall"], "bootstrap": row["bootstrap"],
                          "positives": bundle["positives"], "negatives": bundle["negatives"]}
    shipped, candidate = results["shipped"]["overall"], results["candidate"]["overall"]
    results["verdict"] = (
        "candidate better on holdout F1 without more false positives"
        if candidate["f1"] > shipped["f1"] and candidate["fp"] <= shipped["fp"]
        else "keep the shipped model"
    )
    with (work / COMPARISON).open("x", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    print(f"{'holdout':<10} {'F1':>6} {'prec':>6} {'recall':>6} {'TP':>4} {'FP':>4} {'FN':>4}")
    for label in ("shipped", "candidate"):
        m = results[label]["overall"]
        print(f"{label:<10} {m['f1']:>6.3f} {m['precision']:>6.3f} {m['recall']:>6.3f} {m['tp']:>4} {m['fp']:>4} {m['fn']:>4}")
    print(f"Verdict: {results['verdict']} (details: {work / COMPARISON})")


STAGES = {"prepare": prepare, "record": record, "collect": collect, "fit": fit, "compare": compare}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=[*STAGES, "all"])
    parser.add_argument("--work", required=True, help="Work directory for every artifact of this run")
    parser.add_argument("--upstream-data", help="Local upstream data.json (the snapshot the extended catalog was built from)")
    parser.add_argument("--max-sites", type=int, default=0, help="Sample at most this many sites (0 = all)")
    parser.add_argument("--positives-per-site", type=int, default=2)
    parser.add_argument("--include-nsfw", action="store_true")
    parser.add_argument("--negatives", type=int, default=4, help="Generated negatives per site")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--max-fpr", type=float, default=0.02)
    parser.add_argument("--holdout-corpus", help="Frozen corpus containing the holdout split, e.g. paper/corpus/v3")
    parser.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap iterations for F1 intervals")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    log = _logger(args.verbose)
    for stage in STAGES if args.stage == "all" else [args.stage]:
        log.info("== %s ==", stage)
        STAGES[stage](args, log)


if __name__ == "__main__":
    sys.exit(main())
