import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import aiohttp

from .analyzer import FeatureExtractor
from .browser import BrowserFallback
from .config import DEFAULT_HEADERS, ScannerConfig
from .detector import Detector
from .fingerprints import FingerprintStore, build_fingerprint
from .http import fetch_url
from .rate_limit import DomainRateLimiter
from .variations import generate_username_variations
from utils.colors import COLORS


@dataclass
class ScanResult:
    site: str
    url: str
    final_url: str
    status: str
    code: int
    response_time: float
    confidence: int
    ai_analysis: Dict[str, Any]


def load_sites_data() -> Dict[str, str]:
    """Load sites data from common locations."""
    base_dir = Path(__file__).resolve().parents[1]
    bin_dir = Path(__file__).resolve().parents[2]
    possible_paths = [
        Path("/usr/local/bin/sites.json"),
        Path("/usr/local/etc/aliens_eye/sites.json"),
        Path("/etc/aliens_eye/sites.json"),
        Path("/data/data/com.termux/files/usr/bin/sites.json"),
        bin_dir / "sites.json",
        base_dir / "sites.json",
        Path("sites.json"),
    ]
    for path in possible_paths:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
    return {}


class UsernameScanner:
    """Coordinates async scanning across all platforms."""

    def __init__(
        self,
        sites_data: Dict[str, str],
        config: ScannerConfig,
        extractor: FeatureExtractor,
        detector: Detector,
        fingerprints: FingerprintStore,
        logger,
        browser_fallback: BrowserFallback | None = None,
    ) -> None:
        self.sites_data = sites_data
        self.config = config
        self.extractor = extractor
        self.detector = detector
        self.fingerprints = fingerprints
        self.logger = logger
        self.browser_fallback = browser_fallback

        self.results_dir = config.output_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)

    async def scan_with_variations(
        self, base_username: str, level: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        variations = generate_username_variations(base_username, level)
        all_results: Dict[str, List[Dict[str, Any]]] = {}

        print(
            f"\n{COLORS['blue']}Scan level: {COLORS['yellow']}{level.upper()}"
        )
        print(
            f"{COLORS['blue']}Generated {len(variations)} username variations to scan"
        )
        if len(variations) > 1:
            preview = ", ".join(variations[:5])
            more = f" and {len(variations) - 5} more..." if len(variations) > 5 else ""
            print(f"{COLORS['yellow']}Variations: {preview}{more}")

        for username in variations:
            print(
                f"\n{COLORS['purple']}Scanning variation: {COLORS['yellow']}{username}{COLORS['reset']}"
            )
            results = await self.scan_all_sites(username)
            all_results[username] = results

        return all_results

    async def scan_all_sites(self, username: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if not self.sites_data:
            return results

        conn_limit = max(1, min(self.config.concurrent, len(self.sites_data)))
        rate_limiter = DomainRateLimiter()
        queue: asyncio.Queue[Tuple[str, str]] = asyncio.Queue()
        for site, tmpl in self.sites_data.items():
            queue.put_nowait((site, tmpl))

        print(
            f"\n{COLORS['purple']}Scanning '{COLORS['yellow']}{username}{COLORS['purple']}' across "
            f"{len(self.sites_data)} sites (max {conn_limit} concurrent connections)...{COLORS['reset']}\n"
        )
        self._print_table_header()

        connector = aiohttp.TCPConnector(limit=conn_limit)
        start_time = time.monotonic()
        async with aiohttp.ClientSession(
            headers=DEFAULT_HEADERS, connector=connector
        ) as session:
            workers = [
                asyncio.create_task(
                    self._worker(queue, username, session, rate_limiter, results)
                )
                for _ in range(conn_limit)
            ]
            await queue.join()
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        total_time = time.monotonic() - start_time
        print(f"\n{COLORS['green']}Scan completed in {total_time:.2f} seconds")
        self._print_summary(results)
        return results

    async def _worker(
        self,
        queue: asyncio.Queue[Tuple[str, str]],
        username: str,
        session: aiohttp.ClientSession,
        rate_limiter: DomainRateLimiter,
        results: List[Dict[str, Any]],
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
                self._print_result_line(site, "Error", 0, 0, url, 0.0)
                results.append(
                    {
                        "site": site,
                        "url": url,
                        "final_url": url,
                        "status": "Error",
                        "code": 0,
                        "response_time": 0.0,
                        "confidence": 0,
                        "ai_analysis": {"error": str(exc)},
                    }
                )
            finally:
                queue.task_done()

    async def _scan_site(
        self,
        site_name: str,
        url_template: str,
        username: str,
        session: aiohttp.ClientSession,
        rate_limiter: DomainRateLimiter,
    ) -> Dict[str, Any]:
        url = self._format_url(site_name, url_template, username)
        fetch = await fetch_url(session, url, self.config, rate_limiter, self.logger)

        if fetch.error and fetch.status == 408:
            status_text = "Timeout"
        elif fetch.error:
            status_text = "Error"
        else:
            status_text = "Unknown"

        ai_analysis: Dict[str, Any] = {}
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
                status_text = "Error"
                fetch.status = 0
                fetch.final_url = fetch.final_url or url
                ai_analysis = {"error": str(exc)}
                self._print_result_line(
                    site_name,
                    status_text,
                    confidence,
                    fetch.status,
                    fetch.final_url or url,
                    fetch.response_time,
                )
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

        self._print_result_line(
            site_name,
            status_text,
            confidence,
            fetch.status,
            fetch.final_url or url,
            fetch.response_time,
        )

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
        ai_analysis: Dict[str, Any],
        status_text: str,
        confidence: int,
    ) -> Tuple[str, int, Dict[str, Any]]:
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
        try:
            url = url_template.format(username)
        except (KeyError, IndexError):
            url = url_template.replace("{}", username)
            if "{" in url:
                url = f"https://{site_name}.com/{username}"
        except Exception:
            url = f"https://{site_name}.com/{username}"
        return url

    def _print_table_header(self) -> None:
        print(
            f"{COLORS['blue']}# {COLORS['yellow']}{'SITE':20}{COLORS['blue']}| "
            f"{COLORS['yellow']}{'STATUS + CONFIDENCE':18}{COLORS['blue']}| "
            f"{COLORS['yellow']}{'HTTP CODE':10}{COLORS['blue']}| "
            f"{COLORS['yellow']}URL (RESPONSE TIME){COLORS['reset']}"
        )
        print(f"{COLORS['green']}{'#' * 90}{COLORS['reset']}")

    def _print_result_line(
        self,
        site_name: str,
        status_text: str,
        confidence: int,
        code: int,
        url: str,
        response_time: float,
    ) -> None:
        if status_text == "Found":
            status_color = COLORS["green"]
        elif status_text == "Maybe":
            status_color = COLORS["yellow"]
        else:
            status_color = COLORS["red"]

        code_color = COLORS["green"] if code == 200 else COLORS["red"]
        url_color = status_color
        display_site = site_name[:20]
        confidence_str = f" ({confidence}%)" if confidence > 0 else ""

        print(
            f"{COLORS['green']}# {COLORS['yellow']}{display_site:20}{COLORS['white']}| "
            f"{status_color}{status_text:10}{confidence_str:8}{COLORS['white']}| "
            f"{code_color}{str(code):^10}{COLORS['white']}| "
            f"{url_color}{url}{COLORS['reset']} "
            f"({response_time:.2f}s)"
        )

    def _print_summary(self, results: List[Dict[str, Any]]) -> None:
        found_count = sum(1 for r in results if r["status"] == "Found")
        maybe_count = sum(1 for r in results if r["status"] == "Maybe")
        not_found_count = sum(1 for r in results if r["status"] == "Not Found")
        error_count = sum(
            1
            for r in results
            if r["status"] not in {"Found", "Not Found", "Maybe"}
        )
        high_confidence = [
            r
            for r in results
            if r.get("confidence", 0) >= 85 and r["status"] == "Found"
        ]

        print(
            f"\n{COLORS['green']}Found: {found_count} | "
            f"{COLORS['yellow']}Maybe: {maybe_count} | "
            f"{COLORS['red']}Not Found: {not_found_count} | Errors: {error_count}"
            f"{COLORS['reset']}"
        )
        if high_confidence:
            print(
                f"\n{COLORS['green']}High confidence matches ({len(high_confidence)}):"
                f"{COLORS['reset']}"
            )
            for result in high_confidence[:5]:
                print(
                    f"{COLORS['yellow']}{result['site']}: {COLORS['green']}{result['url']}"
                    f"{COLORS['reset']} ({result['confidence']}% confidence)"
                )
            if len(high_confidence) > 5:
                print(
                    f"{COLORS['yellow']}... and {len(high_confidence) - 5} more"
                    f"{COLORS['reset']}"
                )
