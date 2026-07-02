"""Domain availability check for a username.

For a username, test ``<username>.<tld>`` across a handful of common TLDs:
DNS resolution says whether the domain is registered/points somewhere, and an
HTTP request says whether it serves a live site. No third-party whois service or
API key is used — just DNS + HTTP.
"""

from __future__ import annotations

import asyncio
import re
import socket
from typing import Any

import aiohttp

from .config import DEFAULT_HEADERS, ScannerConfig
from .scanner import build_connector

DEFAULT_TLDS = ["com", "io", "net", "org", "dev", "me", "co", "app"]

_LABEL_RE = re.compile(r"[^a-z0-9-]")


def domain_label(username: str) -> str:
    """Reduce a username to a valid DNS label (lowercase alnum + hyphen)."""
    label = _LABEL_RE.sub("", username.lower().replace("_", "-").replace(".", "-"))
    return label.strip("-")


async def _resolves(host: str) -> bool:
    loop = asyncio.get_event_loop()
    try:
        await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return True
    except (socket.gaierror, OSError):
        return False


async def _is_live(session: aiohttp.ClientSession, host: str, timeout: float) -> bool:
    for scheme in ("https", "http"):
        try:
            async with session.get(
                f"{scheme}://{host}",
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            continue
    return False


async def check_domains(
    username: str,
    tlds: list[str] | None = None,
    proxy: str | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Check ``<username>.<tld>`` registration + liveness for each TLD."""
    label = domain_label(username)
    tlds = tlds or DEFAULT_TLDS
    results: list[dict[str, Any]] = []
    if not label:
        return {"username": username, "label": label, "results": results}

    hosts = [f"{label}.{tld}" for tld in tlds]
    resolved = dict(zip(hosts, await asyncio.gather(*(_resolves(h) for h in hosts)), strict=False))

    connector = build_connector(ScannerConfig(proxy=proxy), len(hosts))
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, connector=connector) as session:
        live_flags = await asyncio.gather(
            *(
                _is_live(session, host, timeout) if resolved[host] else _false()
                for host in hosts
            )
        )

    for host, live in zip(hosts, live_flags, strict=False):
        results.append(
            {"domain": host, "registered": resolved[host], "live": bool(live)}
        )
    return {"username": username, "label": label, "results": results}


async def _false() -> bool:
    return False
