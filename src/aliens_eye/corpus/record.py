"""Capture live responses into a frozen corpus.

The recorder wraps :func:`aliens_eye.core.http.fetch_url` rather than reimplementing
it, so captured responses go through the same retry, backoff, rate-limit and proxy
behaviour as a normal scan. Whatever the scanner would have seen is what lands on
disk.
"""

from __future__ import annotations

import asyncio
import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from aliens_eye import __version__
from aliens_eye.core.config import DEFAULT_HEADERS, ScannerConfig
from aliens_eye.core.http import FetchResult, fetch_url
from aliens_eye.core.rate_limit import DomainRateLimiter
from aliens_eye.core.scanner import build_connector, format_site_url

from .store import CorpusRecord, CorpusStore

# Ordinary-looking handle morphology, for negatives that are not trivially
# distinguishable from real usernames. A negative pool of random 16-character
# strings is an artificially easy class: a detector can separate it on length and
# character distribution alone, which inflates every metric.
_ADJECTIVES = [
    "quiet", "amber", "rapid", "hollow", "silver", "brave", "narrow", "lunar",
    "cobalt", "gentle", "rustic", "vivid", "solar", "hidden", "copper", "swift",
]
_NOUNS = [
    "falcon", "harbor", "meadow", "lantern", "cipher", "willow", "canyon", "ember",
    "pixel", "otter", "vector", "thicket", "beacon", "marlin", "quartz", "atlas",
]


def random_negative(rng: random.Random) -> str:
    """A high-entropy handle that is very unlikely to exist anywhere."""
    length = rng.randint(14, 20)
    return "".join(rng.choices(string.ascii_lowercase + string.digits, k=length))


def plausible_negative(rng: random.Random) -> str:
    """A handle with realistic morphology, which still probably does not exist.

    Plausible negatives are *not* verified absent by construction -- on large
    platforms one may collide with a real account. Records tag their negative
    kind so a later labelling pass can check them; see WORKING.md.
    """
    word = f"{rng.choice(_ADJECTIVES)}{rng.choice(_NOUNS)}"
    style = rng.randint(0, 3)
    if style == 0:
        return word
    if style == 1:
        return f"{word}{rng.randint(1, 9999)}"
    if style == 2:
        return f"{word}_{rng.randint(10, 99)}"
    return f"{word[: len(word) // 2]}_{word[len(word) // 2 :]}"


class RecordingFetcher:
    """A ``fetch_url``-compatible callable that persists what it fetches.

    Context (site / username / label) cannot be recovered from the URL alone, so
    the driver registers it up front with :meth:`register`. That keeps the call
    signature identical to ``fetch_url``, which is what makes the recorder
    droppable into the scanner without touching the scan path.
    """

    def __init__(self, store: CorpusStore, tool_version: str = __version__) -> None:
        self.store = store
        self.tool_version = tool_version
        self._context: dict[str, dict[str, Any]] = {}
        self._records: list[CorpusRecord] = []
        self._lock = asyncio.Lock()
        self.flushed = 0

    def register(
        self,
        url: str,
        site: str,
        username: str,
        label: int | None = None,
        notes: dict[str, Any] | None = None,
    ) -> None:
        self._context[url] = {
            "site": site,
            "username": username,
            "label": label,
            "notes": notes or {},
        }

    @property
    def records(self) -> list[CorpusRecord]:
        return list(self._records)

    async def __call__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        config: ScannerConfig,
        rate_limiter: DomainRateLimiter,
        logger,
    ) -> FetchResult:
        result = await fetch_url(session, url, config, rate_limiter, logger)
        context = self._context.get(url, {})
        async with self._lock:
            digest = self.store.write_body(result.content)
            self._records.append(
                CorpusRecord(
                    url=url,
                    site=str(context.get("site", "")),
                    username=str(context.get("username", "")),
                    label=context.get("label"),
                    final_url=result.final_url,
                    status=result.status,
                    headers=dict(result.headers),
                    body_sha256=digest,
                    body_chars=len(result.content),
                    response_time=result.response_time,
                    redirect_count=result.redirect_count,
                    error=result.error,
                    captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    tool_version=self.tool_version,
                    notes=dict(context.get("notes") or {}),
                )
            )
        return result

    def flush(self) -> int:
        """Append buffered records to disk in a stable order. Returns the count."""
        records = sorted(self._records, key=lambda r: (r.site, r.label or 0, r.username))
        self.store.append_records(records)
        count = len(records)
        self._records.clear()
        self.flushed += count
        return count

    async def maybe_flush(self, every: int) -> int:
        """Flush once the buffer reaches every records.

        A long capture buffered entirely in memory loses everything if the run
        dies partway; incremental flushing bounds that loss. Records are sorted
        within each flush rather than globally, so the file is grouped rather
        than fully ordered -- readers index by URL, and the corpus is a set, not
        a sequence.
        """
        if every <= 0 or len(self._records) < every:
            return 0
        async with self._lock:
            return self.flush()


def build_jobs(
    sites_data: dict[str, str],
    ground_truth: dict[str, list[str]],
    negatives_per_site: int,
    rng: random.Random,
    plausible_ratio: float = 0.5,
) -> list[tuple[str, str, str, int, dict[str, Any]]]:
    """Expand ground truth into ``(site, url, username, label, notes)`` jobs."""
    jobs: list[tuple[str, str, str, int, dict[str, Any]]] = []
    for site in sorted(ground_truth):
        template = sites_data.get(site)
        if not template:
            continue
        for username in ground_truth[site]:
            jobs.append(
                (site, format_site_url(site, template, username), username, 1,
                 {"positive_kind": "ground_truth"})
            )
        n_plausible = int(round(negatives_per_site * plausible_ratio))
        for index in range(negatives_per_site):
            if index < n_plausible:
                username = plausible_negative(rng)
                kind = "plausible"
            else:
                username = random_negative(rng)
                kind = "random"
            jobs.append(
                (site, format_site_url(site, template, username), username, 0,
                 {"negative_kind": kind})
            )
    return jobs


async def record_corpus(
    sites_data: dict[str, str],
    ground_truth: dict[str, list[str]],
    out_dir: Path,
    logger,
    negatives_per_site: int = 4,
    concurrency: int = 20,
    seed: int = 1234,
    split: str = "all",
    plausible_ratio: float = 0.5,
    config: ScannerConfig | None = None,
    flush_every: int = 100,
    skip_urls: set[str] | None = None,
) -> dict[str, Any]:
    """Capture every ground-truth positive plus generated negatives to ``out_dir``."""
    store = CorpusStore(Path(out_dir))
    store.init()
    rng = random.Random(seed)
    config = config or ScannerConfig(retries=2, timeout=15.0)
    rate_limiter = DomainRateLimiter()
    recorder = RecordingFetcher(store)

    jobs = build_jobs(sites_data, ground_truth, negatives_per_site, rng, plausible_ratio)
    skipped = sorted(set(ground_truth) - set(sites_data))
    if skip_urls:
        # Resume: negatives are seed-derived, so regenerating the job list
        # reproduces the same URLs and already-captured ones can be dropped.
        jobs = [job for job in jobs if job[1] not in skip_urls]
    for site, url, username, label, notes in jobs:
        recorder.register(url, site, username, label, notes)

    conn_limit = max(1, min(concurrency, len(jobs) or 1))
    semaphore = asyncio.Semaphore(conn_limit)
    connector = build_connector(config, conn_limit)

    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, connector=connector) as session:

        async def run(url: str) -> None:
            async with semaphore:
                try:
                    await recorder(session, url, config, rate_limiter, logger)
                except Exception as exc:  # noqa: BLE001 - one bad host must not abort a capture
                    logger.debug("Capture failed for %s: %s", url, exc)
            written = await recorder.maybe_flush(flush_every)
            if written:
                logger.info("Captured %d records so far", recorder.flushed)

        await asyncio.gather(*(run(job[1]) for job in jobs))

    written = recorder.flush()
    total_written = recorder.flushed
    # Read back from disk, not from the buffer: incremental flushing clears
    # recorder.records as it goes, so summarising the buffer would describe only
    # whatever happened to remain in the final batch.
    persisted = list(store.iter_records())
    errors = sum(1 for r in persisted if r.error)

    manifest = {
        "tool_version": __version__,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "split": split,
        "seed": seed,
        "negatives_per_site": negatives_per_site,
        "plausible_ratio": plausible_ratio,
        "requested": len(jobs),
        "records": total_written,
        "records_final_flush": written,
        "errors": errors,
        "sites": sorted({r.site for r in persisted if r.site}),
        "skipped_sites": skipped,
    }
    store.write_manifest(manifest)
    logger.info("Captured %d records (%d errors) to %s", total_written, errors, out_dir)
    return manifest
