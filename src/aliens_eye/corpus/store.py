"""On-disk layout for a frozen response corpus.

::

    <corpus>/
        manifest.json                 metadata: tool version, counts, capture run
        records.jsonl                 one JSON object per captured request
        bodies/<aa>/<sha256>.gz       gzipped response bodies, content-addressed

Bodies are content-addressed because error pages repeat heavily: a platform
serves one "no such user" page for every non-existent username, so a corpus of
N negatives per site stores that body once rather than N times.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CORPUS_VERSION = 1
MANIFEST_NAME = "manifest.json"
RECORDS_NAME = "records.jsonl"
BODIES_DIR = "bodies"


class CorpusError(RuntimeError):
    """Raised when a corpus is missing, malformed, or version-mismatched."""


@dataclass
class CorpusRecord:
    """One captured request/response pair.

    ``url`` is the lookup key: it is derived deterministically from
    ``(site, template, username)`` by ``core.scanner.format_site_url``, and it is
    the only identifier ``fetch_url`` receives, so replay must key on it.
    """

    url: str
    site: str
    username: str
    label: int | None
    final_url: str
    status: int
    headers: dict[str, str]
    body_sha256: str
    body_chars: int
    response_time: float
    redirect_count: int
    error: str | None
    captured_at: str
    tool_version: str
    notes: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorpusRecord:
        try:
            return cls(
                url=str(data["url"]),
                site=str(data["site"]),
                username=str(data["username"]),
                label=None if data.get("label") is None else int(data["label"]),
                final_url=str(data.get("final_url") or data["url"]),
                status=int(data.get("status", 0)),
                headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
                body_sha256=str(data.get("body_sha256", "")),
                body_chars=int(data.get("body_chars", 0)),
                response_time=float(data.get("response_time", 0.0)),
                redirect_count=int(data.get("redirect_count", 0)),
                error=data.get("error"),
                captured_at=str(data.get("captured_at", "")),
                tool_version=str(data.get("tool_version", "unknown")),
                notes=dict(data.get("notes") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorpusError(f"Malformed corpus record: {exc}") from exc


def body_digest(content: str) -> str:
    """Content address for a response body. An empty body has no digest."""
    if not content:
        return ""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class CorpusStore:
    """Read/write access to a corpus directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- paths ------------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def records_path(self) -> Path:
        return self.root / RECORDS_NAME

    def body_path(self, digest: str) -> Path:
        return self.root / BODIES_DIR / digest[:2] / f"{digest}.gz"

    # -- writing ----------------------------------------------------------

    def init(self) -> None:
        (self.root / BODIES_DIR).mkdir(parents=True, exist_ok=True)

    def write_body(self, content: str) -> str:
        """Store a body and return its digest. Idempotent for repeated bodies."""
        digest = body_digest(content)
        if not digest:
            return ""
        path = self.body_path(digest)
        if path.exists():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0 so identical bodies produce identical bytes on disk, which
        # keeps a corpus directory itself checksummable across capture runs.
        with path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
                handle.write(content.encode("utf-8"))
        return digest

    def append_records(self, records: list[CorpusRecord]) -> None:
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.records_path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(record.to_json() + "\n")

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        payload = {"corpus_version": CORPUS_VERSION, **manifest}
        self.manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # -- reading ----------------------------------------------------------

    def read_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            raise CorpusError(f"No corpus manifest at {self.manifest_path}")
        try:
            manifest = json.loads(self.manifest_path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise CorpusError(f"Corpus manifest is not valid JSON: {exc}") from exc
        version = manifest.get("corpus_version")
        if version != CORPUS_VERSION:
            raise CorpusError(
                f"Corpus version {version!r} != supported {CORPUS_VERSION}; re-record."
            )
        return manifest

    def iter_records(self) -> Iterator[CorpusRecord]:
        if not self.records_path.exists():
            raise CorpusError(f"No corpus records at {self.records_path}")
        with self.records_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise CorpusError(
                        f"{self.records_path}:{line_no} is not valid JSON: {exc}"
                    ) from exc
                yield CorpusRecord.from_dict(data)

    def read_body(self, digest: str) -> str:
        if not digest:
            return ""
        path = self.body_path(digest)
        if not path.exists():
            raise CorpusError(f"Corpus body {digest} missing at {path}")
        with gzip.open(path, "rb") as handle:
            return handle.read().decode("utf-8")

    def index_by_url(self) -> dict[str, CorpusRecord]:
        """Map url -> record. A later capture of the same url wins."""
        return {record.url: record for record in self.iter_records()}
