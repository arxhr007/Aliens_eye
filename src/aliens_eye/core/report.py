"""Shared helpers for loading and comparing saved scan reports.

A report is the JSON structure written by :class:`ResultsExporter`
(``{"scan_summary": ..., "variations": {v: {"sites": {s: {...}}}}}``). These
helpers are the single place that knows that shape, reused by watch mode, the
``diff`` command, and anything else that consumes prior results from disk.
"""

from __future__ import annotations

import json
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
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"Invalid JSON file: {p}") from exc
    if not isinstance(data, dict) or "variations" not in data:
        raise ReportError(f"Unrecognized results file: {p}")
    return data


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
    }
