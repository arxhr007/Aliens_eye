"""Validate detection accuracy against accounts known to exist (and to not exist).

Scans each known ``(site, username)`` positive plus a few random negatives per
site, then reports precision / recall / F1 / false-positive rate overall and per
site. Doubles as a rot detector for sites.json and a calibration baseline for
the ML model.

Ground truth is split site-disjoint (see ``aliens_eye.ml.collect``). Scoring the
``holdout`` split measures generalization to platforms the model never trained
on; scoring ``train`` measures fit and will read optimistically high.
"""

from __future__ import annotations

import asyncio
import json
import random
import string
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.http import fetch_url
from aliens_eye.core.rate_limit import DomainRateLimiter
from aliens_eye.core.scanner import build_session, format_site_url
from aliens_eye.utils.console import get_console


def load_selfcheck_data(
    split: str = "train",
    path: Path | None = None,
) -> dict[str, str]:
    """Map of site name to one username known to exist there.

    Thin wrapper over :func:`aliens_eye.ml.collect.load_selfcheck_data` that
    keeps one username per site; see there for the ``split`` values.
    """
    from aliens_eye.ml.collect import load_selfcheck_data as load_ground_truth

    return {
        site: usernames[0]
        for site, usernames in load_ground_truth(split, path).items()
        if usernames
    }


def _random_username(rng: random.Random) -> str:
    length = rng.randint(14, 20)
    return "".join(rng.choices(string.ascii_lowercase + string.digits, k=length))


def _metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


async def run_selfcheck(
    sites_data: dict[str, str],
    detector: Detector,
    config: ScannerConfig,
    logger,
    negatives: int = 1,
    report_format: str | None = None,
    seed: int | None = 1234,
    split: str = "train",
    ground_truth_path: Path | None = None,
    fetch=fetch_url,
    jobs: list[tuple[str, str, str, int]] | None = None,
) -> dict[str, Any]:
    """Run the self-check. Returns a metrics dict; renders a report unless report_format='json'."""
    console = get_console()
    jobs_supplied = jobs is not None
    selfcheck = load_selfcheck_data(split, ground_truth_path)
    extractor = FeatureExtractor()
    rate_limiter = DomainRateLimiter()
    rng = random.Random(seed)

    # Build (site, url, username, expected_label) jobs. label 1 = should be Found.
    # A caller replaying a frozen corpus passes `jobs` instead: the corpus is
    # the evaluation set, and regenerating usernames here would produce rows the
    # corpus never captured.
    if jobs is None:
        jobs = []
        for site, username in selfcheck.items():
            if site not in sites_data:
                continue
            url = format_site_url(site, sites_data[site], username)
            jobs.append((site, url, username, 1))
            for _ in range(max(0, negatives)):
                negative = _random_username(rng)
                jobs.append(
                    (site, format_site_url(site, sites_data[site], negative), negative, 0)
                )
        skipped = [site for site in selfcheck if site not in sites_data]
    else:
        jobs = list(jobs)
        skipped = []
    if skipped and report_format != "json":
        console.print(f"[yellow]Skipping sites missing from sites.json: {', '.join(skipped)}[/yellow]")
    if not jobs:
        if report_format != "json":
            console.print("[red]No self-check sites available.[/red]")
        return {"overall": _metrics(0, 0, 0, 0), "per_site": {}, "errors": 0}

    rows: list[dict] = []
    semaphore = asyncio.Semaphore(min(10, len(jobs)))
    async with build_session(config, 10) as session:

        fetch_result = fetch

        async def check(site: str, url: str, username: str, label: int) -> None:
            async with semaphore:
                fetch = await fetch_result(session, url, config, rate_limiter, logger)
            if fetch.error:
                rows.append({"site": site, "username": username, "label": label,
                             "status": "Error", "confidence": 0, "predicted": None,
                             "note": fetch.error[:60]})
                return
            bundle = extractor.extract(
                fetch.content, fetch.final_url, username, site,
                fetch.status, fetch.response_time, fetch.headers, fetch.redirect_count,
            )
            bundle.features["fingerprint_match_found"] = 0.0
            bundle.features["fingerprint_match_not_found"] = 0.0
            detection = detector.predict(bundle.features)
            rows.append({"site": site, "username": username, "label": label,
                         "status": detection.status, "confidence": detection.confidence,
                         "predicted": 1 if detection.status == "Found" else 0,
                         "note": detection.method})

        await asyncio.gather(*(check(*j) for j in jobs))

    # Aggregate confusion matrix overall + per site (ignoring network errors).
    per_site: dict[str, dict[str, int]] = {}
    tp = fp = fn = tn = 0
    for r in rows:
        if r["predicted"] is None:
            continue
        cell = per_site.setdefault(r["site"], {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        if r["label"] == 1 and r["predicted"] == 1:
            key = "tp"
        elif r["label"] == 1 and r["predicted"] == 0:
            key = "fn"
        elif r["label"] == 0 and r["predicted"] == 1:
            key = "fp"
        else:
            key = "tn"
        cell[key] += 1
        tp += key == "tp"
        fp += key == "fp"
        fn += key == "fn"
        tn += key == "tn"

    overall = _metrics(tp, fp, fn, tn)
    errors = sum(1 for r in rows if r["status"] == "Error")
    result = {
        "split": "corpus" if jobs_supplied else ("custom" if ground_truth_path else split),
        "overall": overall,
        "per_site": {s: _metrics(c["tp"], c["fp"], c["fn"], c["tn"]) for s, c in per_site.items()},
        "errors": errors,
        "samples": len([r for r in rows if r["predicted"] is not None]),
    }

    if report_format == "json":
        print(json.dumps(result, indent=2))
        return result

    _render(console, rows, result)
    return result


def _render(console, rows: list[dict], result: dict[str, Any]) -> None:
    rows.sort(key=lambda r: (r["label"] == r.get("predicted"), r["site"]))
    table = Table(title="Self-check: known accounts + random negatives", header_style="bold blue")
    table.add_column("Site", style="yellow")
    table.add_column("Username")
    table.add_column("Expect")
    table.add_column("Detected")
    table.add_column("Confidence", justify="right")
    table.add_column("Result")
    for r in rows:
        expect = "exists" if r["label"] == 1 else "absent"
        if r["predicted"] is None:
            outcome = Text("ERROR", style="dim red")
        else:
            correct = r["label"] == r["predicted"]
            outcome = Text("PASS" if correct else "FAIL", style="bold green" if correct else "bold red")
        table.add_row(
            r["site"], r["username"], expect,
            Text(r["status"], style="green" if r["status"] == "Found" else "red"),
            f"{r['confidence']}%", outcome,
        )
    console.print(table)

    # Per-site metrics table.
    site_table = Table(title="Per-site metrics", header_style="bold blue")
    site_table.add_column("Site", style="yellow")
    for col in ("Precision", "Recall", "F1", "FPR"):
        site_table.add_column(col, justify="right")
    for site, m in sorted(result["per_site"].items()):
        site_table.add_row(
            site, f"{m['precision']:.0%}", f"{m['recall']:.0%}",
            f"{m['f1']:.2f}", f"{m['false_positive_rate']:.0%}",
        )
    console.print(site_table)

    o = result["overall"]
    f1 = o["f1"]
    style = "green" if f1 >= 0.8 else "yellow" if f1 >= 0.6 else "red"
    console.print(
        Panel(
            f"[{style}]Precision {o['precision']:.0%}  Recall {o['recall']:.0%}  "
            f"F1 {o['f1']:.2f}  FPR {o['false_positive_rate']:.0%}[/{style}]  "
            f"[dim]({result['samples']} samples"
            + (f", {result['errors']} network errors" if result["errors"] else "")
            + ")[/dim]",
            border_style=style,
        )
    )
