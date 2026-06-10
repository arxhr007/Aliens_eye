import hashlib
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _hash_text(text: str) -> str:
    normalized = _normalize(text)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_fingerprint(raw: dict[str, Any]) -> dict[str, str]:
    """Convert raw fingerprint inputs into hashed signatures."""
    title_hash = _hash_text(str(raw.get("title", "")))
    meta_hash = _hash_text(str(raw.get("meta_text", "")))
    dom_signature = str(raw.get("dom_signature", ""))
    server = str(raw.get("server", ""))
    return {
        "title_hash": title_hash,
        "meta_hash": meta_hash,
        "dom_signature": dom_signature,
        "server": server,
    }


class FingerprintStore:
    """Persist lightweight fingerprints per site."""

    def __init__(self, path: Path, max_entries_per_label: int = 50) -> None:
        self.path = path
        self.max_entries_per_label = max_entries_per_label
        self.data: dict[str, Any] = {"sites": {}}

    def load(self, logger=None) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self.data = json.load(handle)
        except JSONDecodeError as exc:
            self.data = {"sites": {}}
            if logger:
                logger.warning(
                    "Fingerprint cache is invalid; starting fresh: %s", exc
                )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, ensure_ascii=True)

    def _ensure_site(self, site: str) -> dict[str, list[dict[str, str]]]:
        sites = self.data.setdefault("sites", {})
        return sites.setdefault(site, {"found": [], "not_found": []})

    def add(self, site: str, label: str, fingerprint: dict[str, str]) -> None:
        if label not in {"found", "not_found"}:
            return
        site_entry = self._ensure_site(site)
        entries = site_entry[label]
        key = self._fingerprint_key(fingerprint)
        if any(self._fingerprint_key(item) == key for item in entries):
            return
        entries.append(fingerprint)
        if len(entries) > self.max_entries_per_label:
            site_entry[label] = entries[-self.max_entries_per_label :]

    def score(self, site: str, fingerprint: dict[str, str]) -> dict[str, int]:
        site_entry = self.data.get("sites", {}).get(site, {})
        found_entries = site_entry.get("found", [])
        missing_entries = site_entry.get("not_found", [])

        match_found = self._count_matches(found_entries, fingerprint)
        match_missing = self._count_matches(missing_entries, fingerprint)

        return {
            "match_found": match_found,
            "match_not_found": match_missing,
            "score": match_found - match_missing,
        }

    def _count_matches(
        self, entries: list[dict[str, str]], fingerprint: dict[str, str]
    ) -> int:
        score = 0
        for entry in entries:
            if entry.get("title_hash") and entry.get("title_hash") == fingerprint.get("title_hash"):
                score += 2
            if entry.get("meta_hash") and entry.get("meta_hash") == fingerprint.get("meta_hash"):
                score += 1
            if entry.get("dom_signature") and entry.get("dom_signature") == fingerprint.get("dom_signature"):
                score += 1
            if entry.get("server") and entry.get("server") == fingerprint.get("server"):
                score += 1
        return score

    @staticmethod
    def _fingerprint_key(fingerprint: dict[str, str]) -> str:
        return "|".join(
            [
                fingerprint.get("title_hash", ""),
                fingerprint.get("meta_hash", ""),
                fingerprint.get("dom_signature", ""),
                fingerprint.get("server", ""),
            ]
        )
