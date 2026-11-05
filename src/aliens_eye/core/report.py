"""Shared helpers for loading and comparing saved scan reports.

A report is the JSON structure written by :class:`ResultsExporter`
(``{"scan_summary": ..., "variations": {v: {"sites": {s: {...}}}}}``). These
helpers are the single place that knows that shape, reused by watch mode, the
``diff`` command, and anything else that consumes prior results from disk.
"""

from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path
from typing import Any


class ReportError(ValueError):
    """Raised when a file is not a recognizable Aliens Eye report."""


def load_report(path: str | Path) -> dict[str, Any]:
    """Load and validate a saved report JSON. Raises ReportError on bad input."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"File not found: {p}") from exc
    except (OSError, ValueError) as exc:
        raise ReportError(f"Invalid JSON file: {p}") from exc
    validate_report(data)
    return data


def validate_report(data: Any) -> None:
    def mapping(value):
        if not isinstance(value, dict):
            raise ReportError("Unrecognized results file: expected nested report objects.")
        return value

    root = mapping(data)
    if "variations" not in root:
        raise ReportError("Unrecognized results file: missing variations.")
    mapping(root.get("scan_summary", {}))
    for block in mapping(root["variations"]).values():
        mapping(block)
        mapping(block.get("scan_info", {}))
        for info in mapping(block.get("sites", {})).values():
            mapping(info)
            for field in ("status", "url", "final_url"):
                if field in info and not isinstance(info[field], str):
                    raise ReportError(f"Invalid result field: {field}.")
            for field in ("confidence", "code", "response_time"):
                if field in info and (
                    type(info[field]) not in (int, float) or not math.isfinite(info[field])
                ):
                    raise ReportError(f"Invalid numeric result field: {field}.")
            analysis = mapping(info.get("ai_analysis", {}))
            signals = mapping(analysis.get("signals", {}))
            samples = signals.get("meta_samples", [])
            if not isinstance(samples, list) or any(not isinstance(s, str) for s in samples):
                raise ReportError("Invalid metadata samples.")
            profile = mapping(signals.get("profile", {}))
            for field in ("name", "bio", "avatar"):
                if field in profile and not isinstance(profile[field], str):
                    raise ReportError(f"Invalid profile field: {field}.")
            if "name_from_profile" in profile and type(profile["name_from_profile"]) is not bool:
                raise ReportError("Invalid profile name provenance.")
            mapping(profile.get("field_sources", {}))
            if "explanation" in analysis:
                explanation = mapping(analysis["explanation"])
                checks = mapping(explanation.get("checks", {}))
                for check in checks.values():
                    mapping(check)
                if explanation.get("detector") is not None:
                    mapping(explanation["detector"])


def iter_sites(report: dict[str, Any]):
    """Yield ``(variation, site, site_info)`` triples from a report dict."""
    for variation, block in report.get("variations", {}).items():
        for site, info in (block.get("sites", {}) or {}).items():
            yield variation, site, info


def found_keys(report: dict[str, Any]) -> set[str]:
    """Set of ``variation:site`` keys with status ``Found`` in a report."""
    return {
        f"{variation}:{site}"
        for variation, site, info in iter_sites(report)
        if info.get("status") == "Found"
    }


def status_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map ``variation:site`` -> ``{status, confidence, url}`` for every site."""
    result: dict[str, dict[str, Any]] = {}
    for variation, site, info in iter_sites(report):
        result[f"{variation}:{site}"] = {
            "status": info.get("status", ""),
            "confidence": info.get("confidence", 0),
            "url": info.get("url", ""),
        }
    return result


def diff_reports(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Compare two reports.

    Returns ``new`` / ``gone`` (Found membership changes) and ``changed``
    (status or confidence moved for a key present in both).
    """
    validate_report(old)
    validate_report(new)
    old_found = found_keys(old)
    new_found = found_keys(new)
    old_map = status_map(old)
    new_map = status_map(new)

    changed: list[dict[str, Any]] = []
    for key in sorted(set(old_map) & set(new_map)):
        before, after = old_map[key], new_map[key]
        if before["status"] != after["status"] or before["confidence"] != after["confidence"]:
            changed.append({"key": key, "before": before, "after": after})

    return {
        "new": [{"key": k, "url": new_map.get(k, {}).get("url", "")} for k in sorted(new_found - old_found)],
        "gone": [{"key": k, "url": old_map.get(k, {}).get("url", "")} for k in sorted(old_found - new_found)],
        "changed": changed,
        "profile_changes": compare_profiles(old, new),
    }


PROFILE_FIELDS = ("name", "bio", "avatar")
_PROFILE_SOURCES = {
    "name": {"opengraph", "json_ld", "site_selector"},
    "bio": {"opengraph", "meta_description", "site_selector"},
    "avatar": {"opengraph", "json_ld", "site_selector"},
}


def profile_snapshot(info: dict[str, Any]) -> dict[str, dict[str, str]]:
    profile = (info.get("ai_analysis") or {}).get("signals", {}).get("profile") or {}
    sources = profile.get("field_sources") or {}
    snapshot = {}
    for field in PROFILE_FIELDS:
        value, source = profile.get(field), sources.get(field)
        if not isinstance(value, str) or not isinstance(source, str) or source not in _PROFILE_SOURCES[field]:
            continue
        if field == "name" and not profile.get("name_from_profile"):
            continue
        value = value.strip() if field == "avatar" else " ".join(unicodedata.normalize("NFC", value).split())
        if value:
            snapshot[field] = {"value": value, "source": source}
    return snapshot


def observation(info: dict[str, Any]) -> dict[str, Any]:
    from .scanner import _looks_like_bot_wall

    code, status = info.get("code", 0), info.get("status")
    analysis = info.get("ai_analysis") or {}
    signals = analysis.get("signals") or {}
    checks = (analysis.get("explanation") or {}).get("checks") or {}
    blocked = _looks_like_bot_wall(signals) or checks.get("bot_wall", {}).get("outcome") == "detected"
    unavailable = (
        blocked or bool(analysis.get("error"))
        or checks.get("http", {}).get("outcome") == "unavailable"
        or type(code) is not int
    )
    kind = "unavailable"
    if not unavailable:
        if status == "Found" and 200 <= code < 400:
            kind = "found"
        elif status == "Not Found" and code in (404, 410):
            kind = "absent"
    return {"kind": kind, "profile": profile_snapshot(info) if kind == "found" else {}}


def profile_change(key: str, field: str, before: dict, after: dict) -> dict[str, str] | None:
    if before["source"] != after["source"] or before["value"] == after["value"]:
        return None
    return {
        "key": key, "field": field, "before": before["value"], "after": after["value"],
        "source": after["source"], "type": "avatar_url_changed" if field == "avatar" else f"{field}_changed",
    }


def compare_profiles(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, str]]:
    before = {f"{v}:{s}": observation(info) for v, s, info in iter_sites(old)}
    after = {f"{v}:{s}": observation(info) for v, s, info in iter_sites(new)}
    changes = []
    for key in sorted(before.keys() & after.keys()):
        a, b = before[key], after[key]
        if a["kind"] != "found" or b["kind"] != "found":
            continue
        for field in PROFILE_FIELDS:
            if field in a["profile"] and field in b["profile"]:
                change = profile_change(key, field, a["profile"][field], b["profile"][field])
                if change:
                    changes.append(change)
    return changes
