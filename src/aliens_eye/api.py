"""Stable programmatic API.

Everything else in the package is an implementation detail and may change between
minor releases. These functions are what other tools should build on: they take
plain arguments, return plain dicts in the same shape as a saved JSON report, and
never print to the terminal unless asked to.

    from aliens_eye import api

    sites = api.load_sites(exclude_nsfw=True)
    report = await api.scan("someone", sites=sites)
    correlation = await api.correlate(report)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

__all__ = [
    "LEVELS",
    "ProfileMatch",
    "ResultHook",
    "correlate",
    "fetch_page",
    "load_sites",
    "match_profile_url",
    "profile_url",
    "scan",
]

from aliens_eye.core.urlmatch import ProfileMatch

LEVELS = ("basic", "intermediate", "advanced")

#: ``on_result(username, result)`` -- called once per site as it completes. May be
#: sync or async. ``result`` is one entry of a report's per-site results.
ResultHook = Callable[[str, dict[str, Any]], "Awaitable[None] | None"]


def _cache_root() -> Path:
    """Aliens Eye's cache directory -- the same one the CLI uses."""
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("aliens_eye"))


def _quiet_console():
    from rich.console import Console

    return Console(quiet=True)


def load_sites(
    exclude_nsfw: bool = False,
    path: Path | None = None,
) -> dict[str, str]:
    """The site catalogue as ``{site_name: url_template}``.

    Load it once and pass it to :func:`scan` to know the total up front (for a
    progress bar) or to filter it before scanning.
    """
    from aliens_eye.core.scanner import filter_sites, load_nsfw_sites, load_sites_data

    sites = load_sites_data(Path(path) if path else None)
    if exclude_nsfw:
        sites = filter_sites(sites, None, load_nsfw_sites())
    return sites


async def scan(
    username: str,
    level: str = "basic",
    *,
    sites: dict[str, str] | None = None,
    use_ml: bool = True,
    proxy: str | None = None,
    on_result: ResultHook | None = None,
    quiet: bool = True,
) -> dict[str, Any]:
    """Scan ``username`` across ``sites`` and return the structured report.

    The return value has the same shape as the JSON report the CLI writes, so it
    can be passed straight to :func:`correlate`. ``sites`` defaults to the full
    catalogue. ``quiet`` (the default) suppresses all terminal output.
    """
    if not isinstance(username, str) or len(username.strip()) < 2:
        raise ValueError("username must be at least 2 characters")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")

    from aliens_eye.core.analyzer import FeatureExtractor
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.detector import Detector
    from aliens_eye.core.exporter import ResultsExporter
    from aliens_eye.core.fingerprints import FingerprintStore
    from aliens_eye.core.scanner import UsernameScanner
    from aliens_eye.utils.logger import setup_logger

    logger = setup_logger(False)
    cache = _cache_root()
    # Scratch space instead of ./results in the caller's cwd; fingerprints shared
    # with the CLI so signatures learned in one improve the other.
    config = ScannerConfig(
        proxy=proxy,
        output_dir=cache / "api",
        fingerprints_path=cache / "fingerprints.json",
    )
    sites_data = dict(sites) if sites is not None else load_sites()

    detector = Detector()
    if use_ml:
        detector.load_model(logger)
    fingerprints = FingerprintStore(config.fingerprints_path, config.max_fingerprints_per_label)
    fingerprints.load(logger)

    scanner = UsernameScanner(
        sites_data=sites_data,
        config=config,
        extractor=FeatureExtractor(),
        detector=detector,
        fingerprints=fingerprints,
        logger=logger,
        on_result=on_result,
        # Scoped to this scan: the process-wide console is left untouched, so a
        # quiet library call cannot silence anything else in the same process.
        console=_quiet_console() if quiet else None,
    )
    try:
        all_results = await scanner.scan_with_variations(username.strip(), level)
    finally:
        fingerprints.save()
    return ResultsExporter(config.output_dir).report_dict(username.strip(), level, all_results)


async def correlate(
    report: dict[str, Any],
    *,
    proxy: str | None = None,
    timeout: float = 10.0,
    allow_private_avatars: bool = False,
) -> dict[str, Any]:
    """Cluster the report's Found profiles that look like the same person.

    Returns ``clusters`` (multi-site groups with the reasons they linked) and
    ``profiles`` -- every profile considered, with its avatar hash -- so callers
    can apply their own, stricter linkage on top.

    Avatar URLs are scraped from the pages themselves, so they are fetched only
    when they resolve to public addresses. ``allow_private_avatars`` lifts that,
    for deliberately scanning a network you own.
    """
    from aliens_eye.core.correlate import correlate_report

    return await correlate_report(
        report,
        proxy=proxy,
        timeout=timeout,
        allow_private_avatars=allow_private_avatars,
        include_profiles=True,
    )


def match_profile_url(url: str, sites: dict[str, str] | None = None) -> list[ProfileMatch]:
    """Which catalogue profiles a URL could be, most specific first.

    ``match_profile_url("https://www.instagram.com/_arx_/")`` gives
    ``[ProfileMatch(site="instagram", username="_arx_")]``. A URL that is not a
    profile on a known site -- a repository, a navigation page, an unknown host
    -- gives ``[]``.
    """
    from aliens_eye.core.urlmatch import matcher_for

    return matcher_for(sites if sites is not None else load_sites()).match(url)


def profile_url(site: str, username: str, sites: dict[str, str] | None = None) -> str:
    """The profile URL for ``username`` on ``site``. Raises KeyError for an unknown site."""
    from aliens_eye.core.scanner import format_site_url

    catalogue = sites if sites is not None else load_sites()
    return format_site_url(site, catalogue[site], username)


async def fetch_page(
    url: str,
    *,
    proxy: str | None = None,
    timeout: float = 20.0,
    max_bytes: int = 1_000_000,
    allow_private: bool = False,
) -> dict[str, Any]:
    """Fetch one page whose address came from somewhere you do not control.

    For reading a profile or personal site to see what it links to. Only http(s)
    is fetched, and only from public addresses: the URL and every redirect hop
    are validated, and the connection itself is pinned to a public address, so a
    link cannot steer the request at an internal service. ``allow_private`` lifts
    that for a network you own. Through a ``proxy`` the proxy does the resolving,
    and the pinning does not apply.

    Never raises for a bad or unreachable URL: returns ``{"url", "final_url",
    "status", "html", "error"}`` with ``error`` set and ``html`` empty. A refusal
    says why: "host does not resolve", "host resolves to a non-public address" or
    "not an http(s) address".
    """
    from aliens_eye.core import netguard
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.scanner import build_session

    result: dict[str, Any] = {"url": url, "final_url": url, "status": 0, "html": "", "error": None}
    http_proxy = proxy if proxy and proxy.lower().startswith(("http://", "https://")) else None
    resolver = None if (allow_private or proxy) else netguard.PublicOnlyResolver()
    try:
        async with build_session(ScannerConfig(proxy=proxy), 2, resolver=resolver) as session:
            response = await netguard.guarded_get(
                session, url, timeout=timeout, max_bytes=max_bytes,
                allow_private=allow_private, proxy=http_proxy,
            )
    except netguard.GuardError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001 - reported to the caller, never raised
        result["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return result
    result["final_url"] = response.final_url
    result["status"] = response.status
    try:
        result["html"] = response.body.decode(response.charset or "utf-8", errors="ignore")
    except LookupError:  # a charset name Python does not know
        result["html"] = response.body.decode("utf-8", errors="ignore")
    return result
