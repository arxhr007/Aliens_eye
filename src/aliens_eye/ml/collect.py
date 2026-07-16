"""Build a labeled training dataset by scanning ground-truth accounts.

Positives come from a curated map of sites to usernames known to exist
(data/selfcheck.json). Negatives are randomized usernames that almost
certainly do not exist. Each scan produces one row of FEATURE_SCHEMA values
plus a label column.
"""

from __future__ import annotations

import asyncio
import csv
import json
import random
import string
from importlib import resources
from pathlib import Path

import aiohttp

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import DEFAULT_HEADERS, ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.features import FEATURE_SCHEMA, vectorize_features
from aliens_eye.core.http import fetch_url
from aliens_eye.core.rate_limit import DomainRateLimiter
from aliens_eye.core.scanner import format_site_url


def load_selfcheck_data() -> dict[str, list[str]]:
    """Map of site name to usernames known to exist there."""
    text = (resources.files("aliens_eye.data") / "selfcheck.json").read_text("utf-8")
    data = json.loads(text)
    return {
        site: [value] if isinstance(value, str) else list(value)
        for site, value in data.items()
    }


def write_rows(output_path: Path, rows: list[list[float]], append: bool = False) -> None:
    """Write labeled rows to a CSV. Writes the header only for a new/overwritten file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not (append and output_path.exists())
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(FEATURE_SCHEMA + ["label"])
        writer.writerows(rows)


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
) -> list[float] | None:
    url = format_site_url(site, url_template, username)
    fetch = await fetch_url(session, url, config, rate_limiter, logger)
    if fetch.error:
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
    bundle.features["heuristic_score"] = Detector()._heuristic_score(bundle.features)
    return vectorize_features(bundle.features) + [float(label)]


async def collect_dataset(
    sites_data: dict[str, str],
    output_path: Path,
    logger,
    negatives_per_site: int = 2,
    concurrency: int = 20,
    seed: int | None = None,
) -> int:
    """Scan ground-truth positives and random negatives, write a labeled CSV."""
    selfcheck = load_selfcheck_data()
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

    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, connector=connector) as session:

        async def run_job(job: tuple[str, str, str, int]) -> None:
            site, template, username, label = job
            async with semaphore:
                row = await _collect_row(
                    session, extractor, rate_limiter, config,
                    site, template, username, label, logger,
                )
            if row is not None:
                rows.append(row)
                logger.debug("Collected %s sample for %s", "positive" if label else "negative", site)

        await asyncio.gather(*(run_job(job) for job in jobs))

    write_rows(output_path, rows, append=False)
    logger.info("Wrote %d labeled samples to %s", len(rows), output_path)
    return len(rows)
