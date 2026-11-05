"""Watch / monitor mode: re-scan on an interval and alert on changes.

Reuses the existing scanner and exporter. Each cycle runs a fresh scan and saves
a timestamped report. Scoped state confirms absence and optional profile changes;
failures do not erase the last stable observation.
"""

from __future__ import annotations

import asyncio
import json
import math
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from rich.text import Text

from .report import PROFILE_FIELDS, ReportError, found_keys, load_report, observation
from .watch_state import MonitorState, WatchStore, scope_key

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
    # NaN defeats every ordering comparison, so `seconds <= 0` alone lets it
    # through and the watch loop ends up in asyncio.sleep(nan). Infinity passes
    # the same check and sleeps forever.
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"duration must be a positive, finite number: {value!r}")
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
            async with session.post(webhook_url, json=payload, timeout=15, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    logger.warning("Webhook notify failed: HTTP %s (delivery is best-effort).", response.status)
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        logger.warning("Webhook notify failed: %s (delivery is best-effort).", type(exc).__name__)


def parse_profile_fields(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    fields = [field.strip().lower() for field in value.split(",")]
    if not fields or any(field not in PROFILE_FIELDS for field in fields) or len(fields) != len(set(fields)):
        raise ValueError("--watch-profile must contain name, bio, or avatar without duplicates")
    return tuple(field for field in PROFILE_FIELDS if field in fields)


def validate_watch_options(args) -> tuple[float | None, int, tuple[str, ...]]:
    confirmations = getattr(args, "watch_confirmations", None)
    profile = getattr(args, "watch_profile", None)
    if not args.watch:
        if confirmations is not None or profile is not None:
            raise ValueError("--watch-confirmations and --watch-profile require --watch")
        return None, 2, ()
    if args.resume:
        raise ValueError("--watch cannot be combined with --resume; each cycle needs fresh results")
    if args.read:
        raise ValueError("--watch cannot be combined with --read")
    interval = parse_duration(args.watch)
    confirmations = 2 if confirmations is None else confirmations
    fields = parse_profile_fields(profile)
    MonitorState(confirmations, fields)
    if args.notify:
        parsed = urlsplit(args.notify)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("--notify requires an HTTP(S) URL")
    return interval, confirmations, fields


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
    confirmations: int = 2,
    profile_fields: tuple[str, ...] = (),
    json_stdout: bool = False,
) -> None:
    """Re-scan the given usernames every ``interval`` seconds until interrupted."""
    MonitorState(confirmations, profile_fields)
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("watch interval must be positive and finite")
    if getattr(scanner, "checkpoint", None) is not None:
        raise ValueError("watch cannot reuse a resume checkpoint")
    usernames = list(dict.fromkeys(usernames))
    if not usernames or any(not isinstance(name, str) or len(name.strip()) < 2 for name in usernames):
        raise ValueError("watch usernames must be at least 2 characters")
    console.print(
        f"[blue]Watch mode:[/blue] re-scanning every [yellow]{interval:.0f}s[/yellow] "
        f"(Ctrl-C to stop). First conclusive observations establish a baseline; "
        f"absence/profile changes need {confirmations} consecutive observations. "
        "Notifications are best-effort."
    )

    with ExitStack() as stack:
        stores, states = {}, {}
        for username in usernames:
            scope = scope_key(scanner, username, scan_level, confirmations, profile_fields)
            store = stack.enter_context(WatchStore(output_dir, scope))
            stores[username] = store
            states[username] = store.load(confirmations, profile_fields)

        cycle = 0
        while True:
            cycle += 1
            scanner.reset_cycle()
            console.print(f"\n[dim]--- watch cycle {cycle} ---[/dim]")
            for username in usernames:
                all_results = await scanner.scan_with_variations(username, scan_level)
                observed_at = datetime.now(timezone.utc).isoformat()
                current = {
                    f"{variation}:{item['site']}": observation(item)
                    for variation, results in all_results.items() for item in results
                }
                delta = states[username].observe(current, observed_at)
                exporter.save_results(username, scan_level, all_results, formats)
                stores[username].save(states[username])
                if json_stdout:
                    print(json.dumps(exporter.report_dict(username, scan_level, all_results), separators=(",", ":")), flush=True)

                for key in delta["new"]:
                    console.print(Text(f"+ NEW POSITIVE OBSERVATION: {key}", style="green"))
                for key in delta["gone"]:
                    console.print(Text(
                        f"- {key}: profile no longer observed after repeated HTTP 404/410 responses.",
                        style="red",
                    ))
                for change in delta["profile_changes"]:
                    console.print(Text(
                        f"~ {change['key']} {change['type']}: {change['before']} -> {change['after']}",
                        style="yellow",
                    ))
                if delta["unavailable"]:
                    console.print(Text(
                        f"{len(delta['unavailable'])} unavailable/not-observed result(s) for {username}; "
                        "no absence inferred.", style="yellow",
                    ))
                changed = bool(delta["new"] or delta["gone"] or delta["profile_changes"])
                if not changed:
                    console.print(Text(f"No confirmed change for {username}.", style="dim"))
                if notify_url and changed:
                    await _notify(
                        notify_url,
                        {
                            "schema_version": 2, "observed_at": observed_at,
                            "username": username, "level": scan_level,
                            "new": delta["new"], "gone": delta["gone"],
                            **({"profile_changes": delta["profile_changes"]} if profile_fields else {}),
                        },
                        logger,
                    )

            await asyncio.sleep(interval)
