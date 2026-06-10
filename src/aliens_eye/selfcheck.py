"""Validate detection accuracy against accounts known to exist.

Scans each (site, username) pair from data/selfcheck.json and checks that the
detector reports "Found". Doubles as a rot detector for sites.json and as a
calibration baseline for the ML model.
"""

from __future__ import annotations

import asyncio
import json
from importlib import resources

import aiohttp
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import DEFAULT_HEADERS, ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.http import fetch_url
from aliens_eye.core.rate_limit import DomainRateLimiter
from aliens_eye.utils.console import get_console


def load_selfcheck_data() -> dict[str, str]:
    """Map of site name to one username known to exist there."""
    text = (resources.files("aliens_eye.data") / "selfcheck.json").read_text("utf-8")
    data = json.loads(text)
    return {
        site: value if isinstance(value, str) else value[0]
        for site, value in data.items()
        if value
    }


async def run_selfcheck(
    sites_data: dict[str, str],
    detector: Detector,
    config: ScannerConfig,
    logger,
) -> float:
    """Run the self-check and return accuracy in [0, 1]."""
    console = get_console()
    selfcheck = load_selfcheck_data()
    extractor = FeatureExtractor()
    rate_limiter = DomainRateLimiter()

    checks = [
        (site, sites_data[site], username)
        for site, username in selfcheck.items()
        if site in sites_data
    ]
    skipped = [site for site in selfcheck if site not in sites_data]
    if skipped:
        console.print(f"[yellow]Skipping sites missing from sites.json: {', '.join(skipped)}[/yellow]")
    if not checks:
        console.print("[red]No self-check sites available.[/red]")
        return 0.0

    rows: list[dict] = []
    semaphore = asyncio.Semaphore(min(10, len(checks)))

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, connector=connector) as session:

        async def check(site: str, template: str, username: str) -> None:
            url = template.format(username)
            async with semaphore:
                fetch = await fetch_url(session, url, config, rate_limiter, logger)
            if fetch.error:
                rows.append(
                    {"site": site, "username": username, "status": "Error",
                     "confidence": 0, "ok": False, "note": fetch.error[:60]}
                )
                return
            bundle = extractor.extract(
                fetch.content, fetch.final_url, username, site,
                fetch.status, fetch.response_time, fetch.headers, fetch.redirect_count,
            )
            bundle.features["fingerprint_match_found"] = 0.0
            bundle.features["fingerprint_match_not_found"] = 0.0
            detection = detector.predict(bundle.features)
            rows.append(
                {"site": site, "username": username, "status": detection.status,
                 "confidence": detection.confidence, "ok": detection.status == "Found",
                 "note": detection.method}
            )

        await asyncio.gather(*(check(*c) for c in checks))

    rows.sort(key=lambda r: (not r["ok"], r["site"]))
    table = Table(title="Self-check: accounts known to exist", header_style="bold blue")
    table.add_column("Site", style="yellow")
    table.add_column("Username")
    table.add_column("Detected")
    table.add_column("Confidence", justify="right")
    table.add_column("Result")
    table.add_column("Method", style="dim")
    for r in rows:
        table.add_row(
            r["site"],
            r["username"],
            Text(r["status"], style="green" if r["status"] == "Found" else "red"),
            f"{r['confidence']}%",
            Text("PASS", style="bold green") if r["ok"] else Text("FAIL", style="bold red"),
            r["note"],
        )
    console.print(table)

    passed = sum(1 for r in rows if r["ok"])
    errors = sum(1 for r in rows if r["status"] == "Error")
    accuracy = passed / len(rows)
    style = "green" if accuracy >= 0.8 else "yellow" if accuracy >= 0.6 else "red"
    console.print(
        Panel(
            f"[{style}]Accuracy: {passed}/{len(rows)} ({accuracy:.0%})[/{style}]"
            + (f"   [dim]{errors} network errors[/dim]" if errors else ""),
            border_style=style,
        )
    )
    return accuracy
