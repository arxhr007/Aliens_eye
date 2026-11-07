"""Check, site by site, whether catalog entries still work.

Two stages:

  record  (live network) For every enabled site, request one username an
          upstream project or the curated ground truth says exists, and one
          generated username that should not exist. Responses go into a frozen
          corpus. Interrupted runs resume: rerun with the same --corpus.
  report  (offline) Replay the corpus through the scanner's own per-site check,
          the same code a real scan runs, and classify each site.
  apply   (offline) Disable sites found broken: false positives at once, failures
          only when a second report over them agrees. Dry run unless --write.

Verdicts:

  working            known account Found, fake account Not Found
  alive_no_test_user no known account to test; fake account Not Found
  misses_known_user  known account not Found; fake Not Found (account gone or rule broken)
  accepts_anything   fake account reported Found: the site's results cannot be trusted
  uncertain          the known or the fake account only reached Maybe
  blocked            401/403/429/5xx or a challenge page
  unreachable        every request failed (DNS, connection, TLS, timeout)

Example:

  .venv/Scripts/python.exe scripts/verify_catalog.py record --corpus runs/verify \
      --upstream-data path/to/data.json
  .venv/Scripts/python.exe scripts/verify_catalog.py report --corpus runs/verify --out runs/verify-report
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

BLOCKED_CODES = {401, 403, 429}


def _log(verbose: bool) -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("aiohttp", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger("verify_catalog")


def test_usernames(catalog, upstream_path: Path | None) -> dict[str, str]:
    """One asserted-existing username per site: upstream, then curated train and holdout.

    The holdout is fine here: verification measures sites, it trains nothing.
    """
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.core.sites import canonical_template
    from aliens_eye.ml.collect import load_selfcheck_data
    from aliens_eye.ml.expanded import upstream_examples

    by_identity = {canonical_template(site.url): name for name, site in catalog.definitions.items()}
    standard = load_sites_data()
    examples = upstream_examples(catalog, upstream_path)
    examples += [
        {"url": standard[site], "username": name}
        for site, names in load_selfcheck_data("holdout").items() if site in standard for name in names
    ]
    chosen: dict[str, str] = {}
    for example in examples:
        name = by_identity.get(canonical_template(example["url"]))
        if name and name not in chosen and catalog.definitions[name].accepts(example["username"]):
            chosen[name] = example["username"]
    return chosen


def plan(catalog, usernames: dict[str, str], seed: int):
    from aliens_eye.core.site_rules import negative_username

    jobs = []
    for name in sorted(catalog):
        site = catalog.definitions[name]
        known = usernames.get(name)
        if known:
            jobs.append((name, known, 1, {"positive_kind": "upstream"}))
        fake = negative_username(site, known or "aliceexample", random.Random(f"{seed}:{name}"))
        if fake:
            jobs.append((name, fake, 0, {"negative_kind": "random"}))
    return jobs


async def record(args, log) -> None:
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.netguard import PublicOnlyResolver
    from aliens_eye.core.rate_limit import DomainRateLimiter
    from aliens_eye.core.scanner import build_session, load_sites_data
    from aliens_eye.corpus.record import RecordingFetcher
    from aliens_eye.corpus.store import CorpusStore

    catalog = load_sites_data(Path(args.sites) if args.sites else None, catalog=args.catalog)
    usernames = test_usernames(catalog, Path(args.upstream_data) if args.upstream_data else None)
    jobs = plan(catalog, usernames, args.seed)
    store = CorpusStore(Path(args.corpus))
    store.init()
    # Resume: keep successful captures, retry the ones that failed (a later
    # capture of the same URL wins on replay).
    done = {url for url, r in store.index_by_url().items() if not r.error} if store.records_path.exists() else set()
    requests = {}
    recorder = RecordingFetcher(store)
    pending = []
    for name, username, label, notes in jobs:
        request = catalog.definitions[name].request(username)
        notes = {**notes, "site_fingerprint": catalog.definitions[name].fingerprint,
                 "request_role": "probe" if catalog.definitions[name].probe_url else "profile"}
        if request.url in done:
            continue
        recorder.register(request.url, name, username, label, notes)
        requests[request.url] = request
        pending.append(request.url)
    log.info(
        "%d enabled sites, %d with a known account; %d requests (%d already captured)",
        len(catalog), len(usernames), len(pending), len(done),
    )
    config = ScannerConfig(retries=1, timeout=args.timeout)
    limiter = DomainRateLimiter()
    semaphore = asyncio.Semaphore(args.concurrency)
    finished = 0
    async with build_session(config, args.concurrency, resolver=PublicOnlyResolver()) as session:

        async def run(url: str) -> None:
            nonlocal finished
            async with semaphore:
                try:
                    await recorder(session, url, replace(config, request=requests[url]), limiter, log)
                except Exception as exc:  # noqa: BLE001 - one bad host must not stop the run
                    log.debug("capture failed for %s: %s", url, exc)
            finished += 1
            if await recorder.maybe_flush(200) or finished % 1000 == 0:
                log.info("progress %d/%d", finished, len(pending))

        await asyncio.gather(*(run(url) for url in pending))
    recorder.flush()
    from datetime import datetime, timezone

    from aliens_eye import __version__

    records = list(store.iter_records())
    store.write_manifest({
        "tool_version": __version__, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "catalog verification", "catalog": args.catalog, "seed": args.seed,
        "records": len(records), "errors": sum(1 for r in records if r.error),
        "sites": sorted({r.site for r in records}), "skipped_sites": [],
    })
    log.info("Corpus complete: %d records -> %s", len(records), args.corpus)


def _reasons(result) -> str:
    analysis = result.get("ai_analysis") or {}
    codes = (analysis.get("explanation") or {}).get("reason_codes") or []
    if codes:
        return ",".join(codes)
    probability = analysis.get("probability")
    return f"detector probability {probability:.2f}" if isinstance(probability, float) else "no reason recorded"


def classify(known, fake) -> tuple[str, str]:
    """``known``/``fake`` are (scan result, raw record) pairs or None."""
    rows = [row for row in (known, fake) if row is not None]
    if not rows:
        return "unreachable", "nothing recorded"
    if all(record.error for _, record in rows):
        return "unreachable", rows[0][1].error[:120]

    def blocked(pair):
        result, record = pair
        return not record.error and (
            record.status in BLOCKED_CODES or record.status >= 500 or "bot_wall" in _reasons(result)
        )

    for pair in rows:
        if blocked(pair):
            return "blocked", f"HTTP {pair[1].status}"
    fake_status = None if fake is None or fake[1].error else fake[0]["status"]
    if fake_status == "Found":
        return "accepts_anything", f"fake user -> Found (HTTP {fake[1].status})"
    if known is None:
        if fake_status == "Not Found":
            return "alive_no_test_user", "fake user Not Found"
        return "uncertain", f"no known user; fake user -> {fake_status or 'not captured'}"
    if known[1].error:
        return "unreachable", known[1].error[:120]
    status = known[0]["status"]
    if status == "Maybe":
        return "uncertain", f"known user -> Maybe: {_reasons(known[0])}"
    if fake_status == "Maybe":
        return "uncertain", f"known user -> {status}, fake user -> Maybe: {_reasons(fake[0])}"
    if status == "Found":
        return "working", "known Found, fake Not Found" if fake_status else "known Found, fake not captured"
    return "misses_known_user", f"known user -> {status} (HTTP {known[1].status})"


async def report(args, log) -> None:
    from aliens_eye.core.analyzer import FeatureExtractor
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.detector import Detector
    from aliens_eye.core.fingerprints import FingerprintStore
    from aliens_eye.core.rate_limit import DomainRateLimiter
    from aliens_eye.core.scanner import UsernameScanner, build_session, load_sites_data
    from aliens_eye.corpus.replay import ReplayFetcher

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    catalog = load_sites_data(Path(args.sites) if args.sites else None, catalog=args.catalog)
    replay = ReplayFetcher(Path(args.corpus), strict=False)
    detector = Detector()
    detector.load_model(log)
    config = ScannerConfig(output_dir=out / "scan-tmp")
    # The fake account is judged without the control check: its control would
    # be the fake account itself, which turns every Found into Maybe.
    scanners = {
        label: UsernameScanner(
            catalog, replace(config, control_check=bool(label)), FeatureExtractor(), detector,
            FingerprintStore(config.fingerprints_path, read_only=True), log, fetch=replay,
        )
        for label in (0, 1)
    }
    by_site: dict[str, dict[int, object]] = {}
    for record_ in replay.records.values():
        if record_.label is not None and record_.site in catalog:
            by_site.setdefault(record_.site, {})[int(record_.label)] = record_
    limiter = DomainRateLimiter()
    rows = []
    async with build_session(config, 1) as session:
        for index, name in enumerate(sorted(catalog)):
            pair = {}
            for label, record_ in by_site.get(name, {}).items():
                result = await scanners[label]._scan_site(name, catalog[name], record_.username, session, limiter)
                pair[label] = (result, record_)
            verdict, detail = classify(pair.get(1), pair.get(0))
            site = catalog.definitions[name]
            rows.append({
                "site": name, "verdict": verdict, "detail": detail, "url": site.url,
                "source": site.source, "also_in": "+".join(site.also_in), "probe": bool(site.probe_url),
                "nsfw": site.nsfw, "known_user": pair[1][1].username if 1 in pair else "",
                "known_status": pair[1][0]["status"] if 1 in pair else "",
                "known_http": pair[1][1].status if 1 in pair else "",
                "fake_status": pair[0][0]["status"] if 0 in pair else "",
                "fake_http": pair[0][1].status if 0 in pair else "",
            })
            if index and index % 1000 == 0:
                log.info("judged %d/%d sites", index, len(catalog))
    counts = Counter(row["verdict"] for row in rows)
    summary = {
        "corpus": str(args.corpus), "catalog": args.catalog, "sites": len(rows),
        "verdicts": dict(counts.most_common()),
        "by_source": {
            source: dict(Counter(r["verdict"] for r in rows if r["source"] == source).most_common())
            for source in sorted({r["source"] for r in rows})
        },
        "corpus_misses": len(replay.misses),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (out / "sites.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, indent=2))


DISABLE_NOW = {"accepts_anything"}
DISABLE_IF_CONFIRMED = {"misses_known_user", "unreachable"}


def _verdicts(path: Path) -> dict[str, dict]:
    with (Path(path) / "sites.csv").open(encoding="utf-8", newline="") as handle:
        return {row["site"]: row for row in csv.DictReader(handle)}


def broken_sites(first: dict[str, dict], recheck: dict[str, dict] | None) -> dict[str, dict]:
    """Sites to stop scanning: false positives at once, failures only when a recheck agrees."""
    broken = {}
    for name, row in first.items():
        if row["verdict"] in DISABLE_NOW:
            broken[name] = row
        elif row["verdict"] in DISABLE_IF_CONFIRMED and recheck is not None:
            again = recheck.get(name)
            if again is not None and again["verdict"] in DISABLE_IF_CONFIRMED:
                broken[name] = again
    return broken


def apply(args, log) -> None:
    """Disable broken sites in the packaged catalogs.

    Extended definitions are disabled, not deleted, so provenance stays and a
    later verification can re-enable them. The legacy default map has no
    disabled flag, so entries are removed there, except sites the ground-truth
    splits use: deleting those would silently change every evaluation.
    """
    from aliens_eye.core.sites import canonical_template
    from aliens_eye.ml.collect import load_selfcheck_data

    broken = broken_sites(_verdicts(args.report), _verdicts(args.recheck) if args.recheck else None)
    identities = {canonical_template(row["url"]) for row in broken.values()}
    # The repository's data files, not an installed copy: this edits the source.
    data = Path(__file__).resolve().parents[1] / "src" / "aliens_eye" / "data"
    changes = Counter()
    for name in ("extended_sites.json", "community_sites.json"):
        path = data / name
        catalog = json.loads(path.read_text("utf-8"))
        for site in catalog["sites"].values():
            if canonical_template(site["url"]) in identities and not site.get("disabled"):
                site["disabled"] = True
                changes[name] += 1
        if args.write:
            path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    legacy_path = data / "sites.json"
    legacy = json.loads(legacy_path.read_text("utf-8"))
    ground_truth = set(load_selfcheck_data("all"))
    kept = sorted(n for n, url in legacy.items() if canonical_template(url) in identities and n in ground_truth)
    removed = sorted(n for n, url in legacy.items() if canonical_template(url) in identities and n not in ground_truth)
    nsfw_path = data / "nsfw_sites.json"
    nsfw = json.loads(nsfw_path.read_text("utf-8"))
    if args.write:
        legacy = {n: url for n, url in legacy.items() if n not in removed}
        legacy_path.write_text(json.dumps(legacy, ensure_ascii=False, indent=4), encoding="utf-8", newline="\n")
        nsfw_path.write_text(
            json.dumps([n for n in nsfw if n not in removed], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    summary = {
        "broken_sites": len(broken),
        "by_verdict": dict(Counter(row["verdict"] for row in broken.values()).most_common()),
        "disabled_definitions": dict(changes),
        "removed_from_default": removed,
        "kept_in_default_for_ground_truth": kept,
        "written": bool(args.write),
    }
    print(json.dumps(summary, indent=2))
    if not args.write:
        log.info("Dry run; pass --write to change the packaged catalogs")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    for name in ("record", "report"):
        child = sub.add_parser(name)
        child.add_argument("--corpus", required=True)
        child.add_argument("--catalog", choices=["standard", "extended"], default="extended")
        child.add_argument("--sites", help="Custom catalog JSON instead of --catalog")
        child.add_argument("-v", "--verbose", action="store_true")
    rec = sub.choices["record"]
    rec.add_argument("--upstream-data", help="Upstream data.json snapshot the catalog was built from")
    rec.add_argument("--concurrency", type=int, default=24)
    rec.add_argument("--timeout", type=float, default=15.0)
    rec.add_argument("--seed", type=int, default=1234)
    sub.choices["report"].add_argument("--out", required=True, help="New directory for summary.json and sites.csv")
    fix = sub.add_parser("apply", help="Disable sites a report (and a recheck) found broken")
    fix.add_argument("--report", required=True, help="Report directory from the first pass")
    fix.add_argument("--recheck", help="Report directory from a second pass over the failures")
    fix.add_argument("--write", action="store_true", help="Change the packaged catalogs (default: dry run)")
    fix.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    log = _log(args.verbose)
    if args.stage == "apply":
        apply(args, log)
        return
    asyncio.run(record(args, log) if args.stage == "record" else report(args, log))


if __name__ == "__main__":
    sys.exit(main())
