"""Resumable scan checkpoints.

Each completed ``(variation, site)`` result is appended as one JSON line to a
checkpoint file. On resume, previously completed sites are skipped and their
results are reused, so a scan interrupted by Ctrl-C or a crash continues where it
left off instead of re-hitting every site.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


class Checkpoint:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        # (variation, site) -> stored result dict
        self._done: dict[tuple[str, str], dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                self._done[(entry["variation"], entry["site"])] = entry["result"]
        except (OSError, json.JSONDecodeError, KeyError):
            # A corrupt/partial checkpoint is treated as empty rather than fatal.
            self._done = {}

    def is_done(self, variation: str, site: str) -> bool:
        return (variation, site) in self._done

    def results_for(self, variation: str) -> dict[str, dict[str, Any]]:
        """site -> result for every completed site of this variation."""
        return {
            site: result
            for (var, site), result in self._done.items()
            if var == variation
        }

    async def record(self, variation: str, site: str, result: dict[str, Any]) -> None:
        key = (variation, site)
        async with self._lock:
            if key in self._done:
                return
            self._done[key] = result
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"variation": variation, "site": site, "result": result}) + "\n")

    def finalize(self) -> None:
        """Remove the checkpoint file once the scan has completed successfully."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
