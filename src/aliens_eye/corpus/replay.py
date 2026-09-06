"""Serve a frozen corpus through the ``fetch_url`` interface.

Replay makes an evaluation reproducible: the same corpus yields the same report,
today and in a year, whatever the platforms have since done to their markup.

Determinism requires more than returning stored bytes:

* No network, no rate limiting, no retries -- the rate limiter is not consulted,
  so replay does not sleep and wall-clock timing cannot leak into results.
* ``response_time`` is the recorded value, not a fresh measurement, so the
  ``response_time`` feature is stable across runs.
* Fingerprints must be neutralised by the caller. ``core.fingerprints.FingerprintStore``
  accumulates signatures *during* a scan and scores against what it has seen so
  far, which makes its contribution depend on worker completion order. Pass a
  read-only store (see :class:`aliens_eye.core.fingerprints.FingerprintStore`) or
  results will vary run to run even off a frozen corpus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp

from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.http import FetchResult
from aliens_eye.core.rate_limit import DomainRateLimiter

from .store import CorpusError, CorpusRecord, CorpusStore

MISSING_ERROR = "not in corpus"


class ReplayFetcher:
    """A ``fetch_url``-compatible callable backed by a recorded corpus.

    ``strict=True`` raises on a URL the corpus does not contain, which is what an
    evaluation wants: a silently-missing response would be scored as a network
    error and quietly bias the metrics. ``strict=False`` returns an error
    ``FetchResult`` instead, matching how a real failed fetch behaves.
    """

    def __init__(self, root: Path, strict: bool = True, cache_bodies: bool = True) -> None:
        self.store = CorpusStore(Path(root))
        self.manifest = self.store.read_manifest()
        self.strict = strict
        self.cache_bodies = cache_bodies
        self.records: dict[str, CorpusRecord] = self.store.index_by_url()
        self._bodies: dict[str, str] = {}
        self.hits = 0
        self.misses: list[str] = []

    # -- corpus introspection --------------------------------------------

    def __len__(self) -> int:
        return len(self.records)

    @property
    def sites(self) -> list[str]:
        return sorted({r.site for r in self.records.values() if r.site})

    def labels_by_url(self) -> dict[str, int | None]:
        return {url: record.label for url, record in self.records.items()}

    def eval_jobs(self, sites: set[str] | None = None) -> list[tuple[str, str, str, int]]:
        """The labelled evaluation set held by this corpus.

        Returns ``(site, url, username, label)`` for every labelled record, in a
        stable order. Callers must evaluate *these* rows rather than regenerating
        usernames: freshly generated negatives were never captured, so they would
        all miss the corpus and leave the negative class empty -- yielding a
        false-positive rate computed over nothing.
        """
        jobs = [
            (r.site, r.url, r.username, int(r.label))
            for r in self.records.values()
            if r.label is not None and (sites is None or r.site in sites)
        ]
        return sorted(jobs, key=lambda j: (j[0], j[3], j[2]))

    def stats(self) -> dict[str, Any]:
        records = list(self.records.values())
        positives = sum(1 for r in records if r.label == 1)
        negatives = sum(1 for r in records if r.label == 0)
        errors = sum(1 for r in records if r.error)
        return {
            "records": len(records),
            "sites": len(self.sites),
            "positives": positives,
            "negatives": negatives,
            "unlabeled": len(records) - positives - negatives,
            "capture_errors": errors,
            "distinct_bodies": len({r.body_sha256 for r in records if r.body_sha256}),
            "tool_version": self.manifest.get("tool_version"),
            "created_at": self.manifest.get("created_at"),
        }

    # -- fetch ------------------------------------------------------------

    def _body(self, record: CorpusRecord) -> str:
        if not self.cache_bodies:
            return self.store.read_body(record.body_sha256)
        if record.body_sha256 not in self._bodies:
            self._bodies[record.body_sha256] = self.store.read_body(record.body_sha256)
        return self._bodies[record.body_sha256]

    async def __call__(
        self,
        session: aiohttp.ClientSession | None,
        url: str,
        config: ScannerConfig,
        rate_limiter: DomainRateLimiter,
        logger,
    ) -> FetchResult:
        record = self.records.get(url)
        if record is None:
            self.misses.append(url)
            if self.strict:
                raise CorpusError(
                    f"{url} is not in the corpus at {self.store.root}. "
                    "Re-record, or pass strict=False to score it as a fetch error."
                )
            logger.debug("Corpus miss for %s", url)
            return FetchResult(
                url=url, final_url=url, status=0, content="", response_time=0.0,
                headers={}, error=MISSING_ERROR, redirect_count=0,
            )

        self.hits += 1
        return FetchResult(
            url=record.url,
            final_url=record.final_url,
            status=record.status,
            content="" if record.error else self._body(record),
            response_time=record.response_time,
            headers=dict(record.headers),
            error=record.error,
            redirect_count=record.redirect_count,
        )
