"""Build a labeled training dataset by scanning ground-truth accounts.

Positives come from a curated map of sites to usernames known to exist.
Negatives are randomized usernames that almost certainly do not exist. Each
scan produces one row of FEATURE_SCHEMA values plus a label column.

The ground truth is split **site-disjoint** into two files:

* ``data/selfcheck.json``     -- the train split; the only split training reads.
* ``data/eval_holdout.json``  -- held out; never seen by training.

The split is site-disjoint rather than account-disjoint because the detector
learns per-site page structure: holding out only accounts from a site whose
layout the model already trained on would overstate generalization.
"""

from __future__ import annotations

import asyncio
import csv
import json
import random
import string
from importlib import resources
from pathlib import Path
from typing import Any

import aiohttp

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.features import FEATURE_SCHEMA, vectorize_features
from aliens_eye.core.http import fetch_url
from aliens_eye.core.rate_limit import DomainRateLimiter
from aliens_eye.core.scanner import build_session, format_site_url
from aliens_eye.core.sites import training_group

TRAIN_SPLIT_RESOURCE = "selfcheck.json"
HOLDOUT_SPLIT_RESOURCE = "eval_holdout.json"
SPLIT_RESOURCES = {"train": TRAIN_SPLIT_RESOURCE, "holdout": HOLDOUT_SPLIT_RESOURCE}


def _read_split(split: str, path: Path | None) -> dict[str, Any]:
    if path is not None:
        text = Path(path).read_text("utf-8")
    else:
        try:
            resource = SPLIT_RESOURCES[split]
        except KeyError:
            raise ValueError(
                f"Unknown ground-truth split {split!r}; expected one of "
                f"{', '.join(sorted(SPLIT_RESOURCES))} or 'all'."
            ) from None
        text = (resources.files("aliens_eye.data") / resource).read_text("utf-8")
    return json.loads(text)


def load_selfcheck_data(
    split: str = "train",
    path: Path | None = None,
) -> dict[str, list[str]]:
    """Map of site name to usernames known to exist there.

    ``split`` selects the ground-truth file: ``"train"`` (default, the only
    split training may read), ``"holdout"``, or ``"all"`` to merge both. Pass
    ``path`` to load an arbitrary ground-truth JSON instead.
    """
    if path is None and split == "all":
        data: dict[str, Any] = {}
        for name in SPLIT_RESOURCES:
            data.update(_read_split(name, None))
    else:
        data = _read_split(split, path)
    return {site: _usernames_of(value) for site, value in data.items()}


def _usernames_of(value: Any) -> list[str]:
    """Accept all three ground-truth shapes.

    Historically a site mapped to a username string or a list of them. Entries
    imported from an external project also carry provenance, so a site may map
    to {"usernames": [...], "source": ...} instead; see eval/groundtruth.py.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(u) for u in value.get("usernames", [])]
    return [str(u) for u in value]


def load_ground_truth_sources(
    split: str = "train",
    path: Path | None = None,
) -> dict[str, str]:
    """Map site -> the project its accounts came from.

    Used to keep an external tool from being scored on the accounts its own
    rules were tuned against. Sites without recorded provenance are reported as
    "curated", which is scoreable against every tool.
    """
    if path is None and split == "all":
        data: dict[str, Any] = {}
        for name in SPLIT_RESOURCES:
            data.update(_read_split(name, None))
    else:
        data = _read_split(split, path)
    return {
        site: (value.get("source", "curated") if isinstance(value, dict) else "curated")
        for site, value in data.items()
    }


def write_rows(
    output_path: Path, rows: list[list[float]], append: bool = False,
    metadata: list[dict[str, str]] | None = None,
) -> None:
    """Write labeled rows to a CSV. Writes the header only for a new/overwritten file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not (append and output_path.exists())
    metadata_fields = ["site", "site_group", "label_source", "split"] if metadata is not None else []
    fields = FEATURE_SCHEMA + ["label"] + metadata_fields
    if metadata is not None and len(metadata) != len(rows):
        raise ValueError("Training metadata must align with every feature row")
    if not write_header:
        with output_path.open(encoding="utf-8", newline="") as handle:
            if next(csv.reader(handle), None) != fields:
                raise ValueError("Training CSV schemas differ; use a new output file")
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(fields)
        for index, row in enumerate(rows):
            writer.writerow(row + ([metadata[index].get(key, "") for key in metadata_fields] if metadata is not None else []))


def random_username(rng: random.Random) -> str:
    length = rng.randint(14, 20)
    return "".join(rng.choices(string.ascii_lowercase + string.digits, k=length))


async def _collect_row(
    session: aiohttp.ClientSession,
    extractor: FeatureExtractor,
    rate_limiter: DomainRateLimiter,
    config: ScannerConfig,
    site: str,
    url_template: str,
    username: str,
    label: int,
    logger,
    fetch=fetch_url,
) -> list[float] | None:
    url = format_site_url(site, url_template, username)
    fetch = await fetch(session, url, config, rate_limiter, logger)
    return _labeled_features(fetch, extractor, site, username, label)


def _labeled_features(fetch, extractor, site, username, label):
    from aliens_eye.core.scanner import _looks_like_bot_wall

    if fetch.error or fetch.status not in {200, 203, 204, 404, 410} or label == 1 and fetch.status in (404, 410):
        return None
    if fetch.content.lstrip().startswith(("{", "[")):
        return None
    try:
        bundle = extractor.extract(
            fetch.content,
            fetch.final_url,
            username,
            site,
            fetch.status,
            fetch.response_time,
            fetch.headers,
            fetch.redirect_count,
        )
    except Exception:
        return None
    if _looks_like_bot_wall(bundle.signals):
        return None
    bundle.features["heuristic_score"] = Detector()._heuristic_score(bundle.features)
    return vectorize_features(bundle.features) + [float(label)]


def training_sites(sites_data: dict[str, str], split: str, ground_truth_path=None) -> dict[str, list[str]]:
    from aliens_eye.core.scanner import load_sites_data

    sites = load_selfcheck_data(split, ground_truth_path)
    if split == "train":
        templates = {**load_sites_data(), **sites_data}
        holdout_groups = {
            training_group(site, templates.get(site)) for site in load_selfcheck_data("holdout")
        }
        sites = {
            site: names for site, names in sites.items()
            if training_group(site, templates.get(site)) not in holdout_groups
        }
    return sites


def collect_from_corpus(
    corpus_path: Path, sites_data: dict[str, str], output_path: Path, logger, split: str = "train",
    ground_truth_path: Path | None = None,
) -> int:
    from aliens_eye.corpus.replay import ReplayFetcher

    replay = ReplayFetcher(Path(corpus_path))
    allowed = training_sites(sites_data, split, ground_truth_path)
    sources = load_ground_truth_sources(split, ground_truth_path)
    extractor = FeatureExtractor()
    rows, metadata = [], []
    for site, url, username, label in replay.eval_jobs(set(allowed)):
        record = replay.records[url]
        template = sites_data.get(site)
        if not template or record.error:
            continue
        from aliens_eye.core.http import FetchResult

        response = FetchResult(
            record.url, record.final_url, record.status, replay.store.read_body(record.body_sha256),
            record.response_time, record.headers, record.error, record.redirect_count,
        )
        row = _labeled_features(response, extractor, site, username, label)
        if row is not None:
            rows.append(row)
            metadata.append({
                "site": site, "site_group": training_group(site, template),
                "label_source": sources.get(site, "curated") if label else "generated-negative",
                "split": split,
            })
    write_rows(output_path, rows, metadata=metadata)
    logger.info("Replayed %d HTML training samples from the corpus (no network)", len(rows))
    return len(rows)


async def collect_dataset(
    sites_data: dict[str, str],
    output_path: Path,
    logger,
    negatives_per_site: int = 2,
    concurrency: int = 20,
    seed: int | None = None,
    split: str = "train",
    ground_truth_path: Path | None = None,
    fetch=fetch_url,
) -> int:
    """Scan ground-truth positives and random negatives, write a labeled CSV.

    Reads the train split by default. Training must never read the holdout:
    doing so reintroduces the train/eval leak the split exists to remove.
    """
    from aliens_eye.core.sites import SiteCatalog

    if isinstance(sites_data, SiteCatalog):
        raise ValueError("HTML model collection requires a legacy URL map; JSON/probe models need a separate labeled corpus")
    selfcheck = training_sites(sites_data, split, ground_truth_path)
    sources = load_ground_truth_sources(split, ground_truth_path)
    rng = random.Random(seed)
    config = ScannerConfig(retries=1, timeout=10.0)
    extractor = FeatureExtractor()
    rate_limiter = DomainRateLimiter()

    jobs: list[tuple[str, str, str, int]] = []
    for site, usernames in selfcheck.items():
        template = sites_data.get(site)
        if not template:
            continue
        for username in usernames:
            jobs.append((site, template, username, 1))
        for _ in range(negatives_per_site):
            jobs.append((site, template, random_username(rng), 0))

    rng.shuffle(jobs)
    semaphore = asyncio.Semaphore(concurrency)
    rows: list[list[float]] = []
    metadata: list[dict[str, str]] = []

    async with build_session(config, concurrency) as session:

        async def run_job(job: tuple[str, str, str, int]) -> None:
            site, template, username, label = job
            async with semaphore:
                row = await _collect_row(
                    session, extractor, rate_limiter, config,
                    site, template, username, label, logger, fetch,
                )
            if row is not None:
                rows.append(row)
                metadata.append({
                    "site": site, "site_group": training_group(site, template),
                    "label_source": sources.get(site, "curated") if label else "generated-negative",
                    "split": split,
                })
                logger.debug("Collected %s sample for %s", "positive" if label else "negative", site)

        await asyncio.gather(*(run_job(job) for job in jobs))

    write_rows(output_path, rows, append=False, metadata=metadata)
    logger.info("Wrote %d labeled samples to %s", len(rows), output_path)
    return len(rows)
