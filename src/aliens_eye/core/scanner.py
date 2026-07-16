import asyncio
import json
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

from aliens_eye.utils.console import ScanView, get_console

from .analyzer import FeatureExtractor
from .browser import BrowserFallback
from .config import DEFAULT_HEADERS, ScannerConfig
from .detector import Detector
from .fingerprints import FingerprintStore, build_fingerprint
from .http import fetch_url
from .rate_limit import DomainRateLimiter
from .variations import generate_username_variations


@dataclass
class ScanResult:
    site: str
    url: str
    final_url: str
    status: str
    code: int
    response_time: float
    confidence: int
    ai_analysis: dict[str, Any]


def load_sites_data(path: Path | None = None) -> dict[str, str]:
    """Load site definitions from a custom path or the packaged sites.json."""
    if path is not None:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    text = (resources.files("aliens_eye.data") / "sites.json").read_text("utf-8")
    return json.loads(text)


def load_site_plugins(extra_dirs: list[Path] | None = None) -> dict[str, str]:
    """Merge every ``*.json`` site map found in the plugin directories.

    Looks in ``./sites.d/`` and the user config dir's ``sites.d/`` by default,
    plus any ``extra_dirs``. Each file must be a ``{site_name: url_template}``
    map; later files override earlier ones on name conflicts.
    """
    from platformdirs import user_config_dir

    dirs = [Path("sites.d"), Path(user_config_dir("aliens_eye")) / "sites.d"]
    dirs.extend(extra_dirs or [])
    merged: dict[str, str] = {}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                merged.update({str(k): str(v) for k, v in data.items()})
    return merged


def load_nsfw_sites() -> list[str]:
    """Names of sites flagged as NSFW, shipped as package data."""
    try:
        text = (resources.files("aliens_eye.data") / "nsfw_sites.json").read_text("utf-8")
        return json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def filter_sites(
    sites: dict[str, str],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, str]:
    """Filter sites by case-insensitive substring match on the site name."""
    result = sites
    if include:
        terms = [t.lower() for t in include if t]
        result = {
            name: tmpl
            for name, tmpl in result.items()
            if any(term in name.lower() for term in terms)
        }
    if exclude:
        terms = [t.lower() for t in exclude if t]
        result = {
            name: tmpl
            for name, tmpl in result.items()
            if not any(term in name.lower() for term in terms)
        }
    return result


def format_site_url(site_name: str, url_template: str, username: str) -> str:
    """Substitute a username into a site's URL template, percent-encoded.

    ``quote()`` leaves ASCII letters/digits/``-_.~`` untouched, so ordinary
    handles are unaffected; non-ASCII (CJK, etc.) and otherwise URL-unsafe
    characters (spaces, ``@``, ``#``, ...) are percent-encoded rather than
    pasted into the URL verbatim.
    """
    encoded = quote(username, safe="")
    try:
        url = url_template.format(encoded)
    except (KeyError, IndexError):
        url = url_template.replace("{}", encoded)
        if "{" in url:
            url = f"https://{site_name}.com/{encoded}"
    except Exception:
        url = f"https://{site_name}.com/{encoded}"
    return url


def build_connector(config: ScannerConfig, limit: int) -> aiohttp.BaseConnector:
    """TCP connector, or a SOCKS proxy connector when a socks:// proxy is set."""
    if config.proxy and config.proxy.lower().startswith(("socks4://", "socks5://")):
        from aiohttp_socks import ProxyConnector

        return ProxyConnector.from_url(config.proxy, limit=limit)
    return aiohttp.TCPConnector(limit=limit)


class UsernameScanner:
    """Coordinates async scanning across all platforms."""

    def __init__(
        self,
        sites_data: dict[str, str],
        config: ScannerConfig,
        extractor: FeatureExtractor,
        detector: Detector,
        fingerprints: FingerprintStore,
        logger,
        browser_fallback: BrowserFallback | None = None,
        checkpoint=None,
    ) -> None:
        self.sites_data = sites_data
        self.config = config
        self.extractor = extractor
        self.detector = detector
        self.fingerprints = fingerprints
        self.logger = logger
        self.browser_fallback = browser_fallback
        self.checkpoint = checkpoint
        self.console = get_console()

        self.results_dir = config.output_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)

    async def scan_with_variations(
        self, base_username: str, level: str
    ) -> dict[str, list[dict[str, Any]]]:
        variations = generate_username_variations(base_username, level)
        all_results: dict[str, list[dict[str, Any]]] = {}

        self.console.print(
            f"\n[blue]Scan level:[/blue] [bold yellow]{level.upper()}[/bold yellow]"
            f"  [blue]|[/blue]  [blue]{len(variations)} username variation(s)[/blue]"
        )
        if len(variations) > 1:
            preview = ", ".join(variations[:5])
            more = f" and {len(variations) - 5} more..." if len(variations) > 5 else ""
            self.console.print(f"[dim]Variations: {preview}{more}[/dim]")

        if not base_username.isascii():
            self.console.print(
                "[dim]Note: non-ASCII username. URLs are percent-encoded, but many "
                "platforms key profiles by an internal ID rather than the display "
                "handle, so results on those sites may be unreliable.[/dim]"
            )

        for username in variations:
            results = await self.scan_all_sites(username)
            all_results[username] = results

        return all_results

    async def scan_all_sites(self, username: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not self.sites_data:
            return results

        done: dict[str, dict[str, Any]] = (
            self.checkpoint.results_for(username) if self.checkpoint else {}
        )
        pending = {site: tmpl for site, tmpl in self.sites_data.items() if site not in done}
        results.extend(done.values())
        if done:
            self.console.print(
                f"[dim]Resuming {username}: {len(done)} site(s) from checkpoint, "
                f"{len(pending)} remaining.[/dim]"
            )
        if not pending:
            return results

        conn_limit = max(1, min(self.config.concurrent, len(pending)))
        rate_limiter = DomainRateLimiter()
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        for site, tmpl in pending.items():
            queue.put_nowait((site, tmpl))

        view = ScanView(self.console)
        view.start(username, len(pending))

        connector = build_connector(self.config, conn_limit)
        start_time = time.monotonic()
        try:
            async with aiohttp.ClientSession(
                headers=DEFAULT_HEADERS, connector=connector
            ) as session:
                workers = [
                    asyncio.create_task(
                        self._worker(queue, username, session, rate_limiter, results, view)
                    )
                    for _ in range(conn_limit)
                ]
                await queue.join()
                for worker in workers:
                    worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
        finally:
            view.stop()

        total_time = time.monotonic() - start_time
        view.render_results(results)
        view.render_summary(results, total_time)
        return results

    async def _worker(
        self,
        queue: asyncio.Queue[tuple[str, str]],
        username: str,
        session: aiohttp.ClientSession,
        rate_limiter: DomainRateLimiter,
        results: list[dict[str, Any]],
        view: ScanView,
    ) -> None:
        while True:
            try:
                site, tmpl = await queue.get()
            except asyncio.CancelledError:
                break
            try:
                result = await self._scan_site(
                    site, tmpl, username, session, rate_limiter
                )
                results.append(result)
            except Exception as exc:
                url = self._format_url(site, tmpl, username)
                self.logger.debug("Worker failed for %s: %s", site, exc)
                result = {
                    "site": site,
                    "url": url,
                    "final_url": url,
                    "status": "Error",
                    "code": 0,
                    "response_time": 0.0,
                    "confidence": 0,
                    "ai_analysis": {"error": str(exc)},
                }
                results.append(result)
            if self.checkpoint is not None:
                try:
                    await self.checkpoint.record(username, site, result)
                except Exception as exc:  # noqa: BLE001 - checkpoint is best-effort
                    self.logger.debug("Checkpoint write failed for %s: %s", site, exc)
            found = sum(1 for r in results if r["status"] == "Found")
            view.advance(found)
            queue.task_done()

    async def _scan_site(
        self,
        site_name: str,
        url_template: str,
        username: str,
        session: aiohttp.ClientSession,
        rate_limiter: DomainRateLimiter,
    ) -> dict[str, Any]:
        url = self._format_url(site_name, url_template, username)
        fetch = await fetch_url(session, url, self.config, rate_limiter, self.logger)

        if fetch.error and fetch.status == 408:
            status_text = "Timeout"
        elif fetch.error:
            status_text = "Error"
        else:
            status_text = "Unknown"

        ai_analysis: dict[str, Any] = {}
        confidence = 0
        if not fetch.error:
            try:
                bundle = self.extractor.extract(
                    fetch.content,
                    fetch.final_url,
                    username,
                    site_name,
                    fetch.status,
                    fetch.response_time,
                    fetch.headers,
                    fetch.redirect_count,
                )
            except Exception as exc:
                self.logger.debug("Feature extraction failed for %s: %s", site_name, exc)
                return {
                    "site": site_name,
                    "url": url,
                    "final_url": fetch.final_url or url,
                    "status": "Error",
                    "code": 0,
                    "response_time": round(fetch.response_time, 2),
                    "confidence": 0,
                    "ai_analysis": {"error": str(exc)},
                }

            fingerprint = build_fingerprint(bundle.fingerprint)
            fingerprint_score = self.fingerprints.score(site_name, fingerprint)
            bundle.features["fingerprint_match_found"] = float(
                fingerprint_score["match_found"]
            )
            bundle.features["fingerprint_match_not_found"] = float(
                fingerprint_score["match_not_found"]
            )

            detection = self.detector.predict(bundle.features)
            status_text = detection.status
            confidence = detection.confidence

            ai_analysis = {
                "method": detection.method,
                "score": detection.score,
                "probability": detection.probability,
                "features": bundle.features,
                "signals": bundle.signals,
            }

            if (
                status_text == "Maybe"
                and self.browser_fallback is not None
                and self.config.use_playwright
            ):
                status_text, confidence, ai_analysis = await self._playwright_fallback(
                    site_name,
                    username,
                    url,
                    fetch,
                    ai_analysis,
                    status_text,
                    confidence,
                )

            if status_text in {"Found", "Not Found"} and confidence >= 85:
                label = "found" if status_text == "Found" else "not_found"
                self.fingerprints.add(site_name, label, fingerprint)

        return {
            "site": site_name,
            "url": url,
            "final_url": fetch.final_url,
            "status": status_text,
            "code": fetch.status,
            "response_time": round(fetch.response_time, 2),
            "confidence": confidence,
            "ai_analysis": ai_analysis,
        }

    async def _playwright_fallback(
        self,
        site_name: str,
        username: str,
        url: str,
        fetch,
        ai_analysis: dict[str, Any],
        status_text: str,
        confidence: int,
    ) -> tuple[str, int, dict[str, Any]]:
        try:
            content, final_url = await self.browser_fallback.fetch(url)
        except Exception as exc:
            self.logger.debug("Playwright fallback failed for %s: %s", site_name, exc)
            return status_text, confidence, ai_analysis

        bundle = self.extractor.extract(
            content,
            final_url,
            username,
            site_name,
            fetch.status,
            fetch.response_time,
            fetch.headers,
            fetch.redirect_count,
        )
        fingerprint = build_fingerprint(bundle.fingerprint)
        fingerprint_score = self.fingerprints.score(site_name, fingerprint)
        bundle.features["fingerprint_match_found"] = float(
            fingerprint_score["match_found"]
        )
        bundle.features["fingerprint_match_not_found"] = float(
            fingerprint_score["match_not_found"]
        )

        detection = self.detector.predict(bundle.features)
        if detection.confidence > confidence or detection.status != "Maybe":
            return detection.status, detection.confidence, {
                "method": f"playwright-{detection.method}",
                "score": detection.score,
                "probability": detection.probability,
                "features": bundle.features,
                "signals": bundle.signals,
            }

        return status_text, confidence, ai_analysis

    @staticmethod
    def _format_url(site_name: str, url_template: str, username: str) -> str:
        return format_site_url(site_name, url_template, username)
