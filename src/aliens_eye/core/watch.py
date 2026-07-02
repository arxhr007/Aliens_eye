"""Watch / monitor mode: re-scan on an interval and alert on changes.

Reuses the existing scanner and exporter. Each cycle runs a full scan, saves a
timestamped report, and diffs the set of Found accounts against the previous
cycle (seeded from the most recent report on disk, if any).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp

from .report import ReportError, found_keys, load_report

_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_duration(value: str) -> float:
    """Parse a duration like ``30s``/``15m``/``6h``/``1d`` into seconds.

    A bare number is treated as seconds. Raises ValueError on bad input.
    """
    text = str(value).strip().lower()
    if not text:
        raise ValueError("empty duration")
    unit = text[-1]
    if unit in _UNITS:
        number = text[:-1]
        factor = _UNITS[unit]
    else:
        number = text
        factor = 1.0
    seconds = float(number) * factor
    if seconds <= 0:
        raise ValueError(f"duration must be positive: {value!r}")
    return seconds


def found_set(all_results: dict[str, list[dict[str, Any]]]) -> set[str]:
    """Set of ``variation:site`` keys currently detected as Found."""
    keys: set[str] = set()
    for variation, results in all_results.items():
        for item in results:
            if item.get("status") == "Found":
                keys.add(f"{variation}:{item.get('site', '')}")
    return keys


def diff_found(prev: set[str], curr: set[str]) -> dict[str, list[str]]:
    """New and disappeared Found accounts between two cycles."""
    return {
        "new": sorted(curr - prev),
        "gone": sorted(prev - curr),
    }


def _baseline(output_dir: Path, username: str, level: str) -> set[str]:
    reports = sorted(output_dir.glob(f"{username}_{level}_*.json"))
    if not reports:
        return set()
    try:
        return found_keys(load_report(reports[-1]))
    except ReportError:
        return set()


async def _notify(webhook_url: str, payload: dict[str, Any], logger) -> None:
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(webhook_url, json=payload, timeout=15)
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        logger.warning("Webhook notify failed: %s", exc)


async def run_watch(
    scanner,
    exporter,
    usernames: list[str],
    scan_level: str,
    formats: list[str],
    interval: float,
    logger,
    console,
    output_dir: Path,
    notify_url: str | None = None,
) -> None:
    """Re-scan the given usernames every ``interval`` seconds until interrupted."""
    previous: dict[str, set[str]] = {
        username: _baseline(output_dir, username, scan_level) for username in usernames
    }
    console.print(
        f"[blue]Watch mode:[/blue] re-scanning every [yellow]{interval:.0f}s[/yellow] "
        f"(Ctrl-C to stop)"
    )

    cycle = 0
    while True:
        cycle += 1
        console.print(f"\n[dim]--- watch cycle {cycle} ---[/dim]")
        for username in usernames:
            if not username or len(username) < 2:
                continue
            all_results = await scanner.scan_with_variations(username, scan_level)
            exporter.save_results(username, scan_level, all_results, formats)

            current = found_set(all_results)
            delta = diff_found(previous.get(username, set()), current)
            previous[username] = current

            if delta["new"] or delta["gone"]:
                for key in delta["new"]:
                    console.print(f"[bold green]+ NEW:[/bold green] {key}")
                for key in delta["gone"]:
                    console.print(f"[bold red]- GONE:[/bold red] {key}")
                if notify_url:
                    await _notify(
                        notify_url,
                        {"username": username, "level": scan_level, **delta},
                        logger,
                    )
            else:
                console.print(f"[dim]No change for {username} ({len(current)} found).[/dim]")

        await asyncio.sleep(interval)
