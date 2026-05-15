#!/usr/bin/python3
import asyncio
import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
LIB_DIR = SCRIPT_DIR / "aliens_eye_lib"
if LIB_DIR.exists():
    sys.path.insert(0, str(LIB_DIR))
else:
    sys.path.insert(0, str(SCRIPT_DIR))

from core.analyzer import FeatureExtractor
from core.browser import BrowserFallback
from core.config import DEFAULT_USER_AGENT, ScannerConfig
from core.detector import Detector
from core.exporter import ResultsExporter
from core.fingerprints import FingerprintStore
from core.scanner import UsernameScanner, load_sites_data
from utils.colors import COLORS
from utils.logger import setup_logger


def display_banner(site_count: int) -> None:
    banner = f"""
  {COLORS['green']} ___   __   _________  ___  ____
 {COLORS['green']} / _ | / /  /  _/ __/ |/ ( )/ __/
{COLORS['green']} / __ |/ /___/ // _//    /|/_\\ \\  
{COLORS['green']}/_/ |_/____/___/___/_/|_/  /___/  
{COLORS['blue']}
    ________  ________        
   {COLORS['blue']}/ ____/\\ \\/ / ____/ {COLORS['red']} _    __{COLORS['white']}__ __
  {COLORS['blue']}/ __/    \\  / __/   {COLORS['red']} | |  / /{COLORS['white']} // /
 {COLORS['blue']}/ /___    / / /___    {COLORS['red']}| | / / {COLORS['white']}// /
{COLORS['blue']}/_____/   /_/_____/  {COLORS['red']}  | |/ /{COLORS['white']}__  __/
                      {COLORS['red']} |___/ {COLORS['white']} /_/  

{COLORS['green']}by {COLORS['yellow']}arxhr007 {COLORS["reset"]}
{COLORS['yellow']}AI-OSINT USERNAME SCANNER{COLORS['reset']}
{COLORS['blue']}Advanced username discovery with ML-ready signals{COLORS['reset']}
{COLORS['purple']}Scanning {site_count} websites{COLORS['reset']}
"""
    print(banner)
    print(f"{COLORS['red']}NOTE: For educational purposes only!{COLORS['reset']}\n")


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="AI-Enhanced Username Scanner - Find usernames across social media platforms"
    )
    parser.add_argument("username", nargs="*", help="Usernames to scan")
    parser.add_argument("-r", "--read", help="Path to JSON file to read and display")
    parser.add_argument("-c", "--concurrent", type=int, help="Max concurrent connections")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "-l",
        "--level",
        choices=["basic", "intermediate", "advanced"],
        help="Scan level",
    )
    parser.add_argument("--timeout", type=float, help="Request timeout in seconds")
    parser.add_argument("--retries", type=int, help="Retry count for failed requests")
    parser.add_argument("--backoff-base", type=float, help="Base backoff in seconds")
    parser.add_argument("--backoff-cap", type=float, help="Max backoff in seconds")
    parser.add_argument("--rate-limit", type=float, help="Min delay per domain")
    parser.add_argument("--max-bytes", type=int, help="Max response bytes to parse")
    parser.add_argument("--config", type=str, help="Path to config JSON file")
    parser.add_argument(
        "--format",
        type=str,
        default=None,
        help="Output formats: json,csv,html,all",
    )
    parser.add_argument(
        "--output", type=str, default=None, help="Output directory"
    )
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Enable Playwright fallback for Maybe results",
    )
    return parser


def parse_formats(value: str) -> list[str]:
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not formats:
        return ["json"]
    if "all" in formats:
        return ["all"]
    return formats


def parse_formats_value(value: Any) -> list[str]:
    if value is None:
        return ["json"]
    if isinstance(value, list):
        return parse_formats(",".join(str(item) for item in value))
    return parse_formats(str(value))


def prompt_yes_no(prompt: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    answer = input(f"{COLORS['green']}{prompt} ({suffix}): {COLORS['yellow']}").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def prompt_int(prompt: str, default: int | None, min_value: int | None = None) -> int | None:
    default_text = "" if default is None else str(default)
    while True:
        value = input(
            f"{COLORS['green']}{prompt} [{default_text}]: {COLORS['yellow']}"
        ).strip()
        if not value:
            return default
        try:
            number = int(value)
        except ValueError:
            print(f"{COLORS['red']}Please enter a whole number.{COLORS['reset']}")
            continue
        if min_value is not None and number < min_value:
            print(f"{COLORS['red']}Minimum is {min_value}.{COLORS['reset']}")
            continue
        return number


def prompt_float(prompt: str, default: float | None, min_value: float | None = None) -> float | None:
    default_text = "" if default is None else str(default)
    while True:
        value = input(
            f"{COLORS['green']}{prompt} [{default_text}]: {COLORS['yellow']}"
        ).strip()
        if not value:
            return default
        try:
            number = float(value)
        except ValueError:
            print(f"{COLORS['red']}Please enter a number.{COLORS['reset']}")
            continue
        if min_value is not None and number < min_value:
            print(f"{COLORS['red']}Minimum is {min_value}.{COLORS['reset']}")
            continue
        return number


def prompt_formats(current: list[str]) -> list[str]:
    default_text = ",".join(current)
    value = input(
        f"{COLORS['green']}Output formats (json,csv,html,all) [{default_text}]: {COLORS['yellow']}"
    ).strip()
    if not value:
        return current
    return parse_formats(value)


def prompt_path(prompt: str, default: Path | None) -> Path | None:
    default_text = "" if default is None else str(default)
    value = input(
        f"{COLORS['green']}{prompt} [{default_text}]: {COLORS['yellow']}"
    ).strip()
    if not value:
        return default
    return Path(value)


def prompt_scan_profile() -> str:
    print(f"\n{COLORS['green']}Select scan profile:")
    print(
        f"{COLORS['white']}1. {COLORS['blue']}Quick{COLORS['white']} - fewer retries, shorter timeouts"
    )
    print(
        f"{COLORS['white']}2. {COLORS['yellow']}Full{COLORS['white']} - balanced defaults"
    )
    print(
        f"{COLORS['white']}3. {COLORS['red']}Aggressive{COLORS['white']} - higher concurrency, Playwright"
    )
    choice = input(
        f"\n{COLORS['green']}Enter choice (1-3) [2]: {COLORS['yellow']}"
    ).strip()
    profile_map = {"1": "quick", "2": "full", "3": "aggressive"}
    return profile_map.get(choice, "full")


def apply_scan_profile(config: ScannerConfig, profile: str, args) -> None:
    presets = {
        "quick": {
            "concurrent": 25,
            "timeout": 6.0,
            "retries": 1,
            "backoff_base": 0.3,
            "backoff_cap": 4.0,
            "rate_limit_delay": 0.1,
            "max_content_bytes": 60_000,
            "use_playwright": False,
        },
        "aggressive": {
            "concurrent": 80,
            "timeout": 15.0,
            "retries": 3,
            "backoff_base": 0.4,
            "backoff_cap": 12.0,
            "rate_limit_delay": 0.05,
            "max_content_bytes": 150_000,
            "use_playwright": True,
        },
    }
    preset = presets.get(profile)
    if not preset:
        return

    if args.concurrent is None:
        config.concurrent = preset["concurrent"]
    if args.timeout is None:
        config.timeout = preset["timeout"]
    if args.retries is None:
        config.retries = preset["retries"]
    if args.backoff_base is None:
        config.backoff_base = preset["backoff_base"]
    if args.backoff_cap is None:
        config.backoff_cap = preset["backoff_cap"]
    if args.rate_limit is None:
        config.rate_limit_delay = preset["rate_limit_delay"]
    if args.max_bytes is None:
        config.max_content_bytes = preset["max_content_bytes"]
    if not args.playwright:
        config.use_playwright = preset["use_playwright"]


def load_config(path_value: str | None, logger) -> dict:
    if path_value:
        candidates = [Path(path_value)]
    else:
        candidates = [
            Path("config.json"),
            SCRIPT_DIR / "config.json",
            Path("/etc/aliens_eye/config.json"),
            Path("/usr/local/etc/aliens_eye/config.json"),
            Path("/data/data/com.termux/files/usr/etc/aliens_eye/config.json"),
        ]

    for path in candidates:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    logger.info("Loaded config from %s", path)
                    return data
            except Exception as exc:
                logger.warning("Failed to read config %s: %s", path, exc)
                return {}
    return {}


def apply_config(config: ScannerConfig, data: dict) -> dict:
    if not isinstance(data, dict):
        return {"level": None, "output_formats": None}

    field_map = {
        "concurrent": "concurrent",
        "timeout": "timeout",
        "max_content_bytes": "max_content_bytes",
        "retries": "retries",
        "backoff_base": "backoff_base",
        "backoff_cap": "backoff_cap",
        "jitter": "jitter",
        "rate_limit_delay": "rate_limit_delay",
        "fingerprints_path": "fingerprints_path",
        "output_dir": "output_dir",
        "use_playwright": "use_playwright",
        "max_fingerprints_per_label": "max_fingerprints_per_label",
    }
    path_fields = {"fingerprints_path", "output_dir"}

    for key, attr in field_map.items():
        if key not in data:
            continue
        value = data.get(key)
        if value is None:
            continue
        if attr in path_fields:
            setattr(config, attr, Path(str(value)))
        else:
            setattr(config, attr, value)

    return {
        "level": data.get("level"),
        "output_formats": data.get("output_formats"),
    }


async def run_scan(args) -> None:
    logger = setup_logger(args.verbose)
    config_data = load_config(args.config, logger)
    config = ScannerConfig()
    defaults = apply_config(config, config_data)

    if args.concurrent:
        config.concurrent = args.concurrent
    if args.timeout:
        config.timeout = args.timeout
    if args.retries is not None:
        config.retries = args.retries
    if args.backoff_base is not None:
        config.backoff_base = args.backoff_base
    if args.backoff_cap is not None:
        config.backoff_cap = args.backoff_cap
    if args.rate_limit is not None:
        config.rate_limit_delay = args.rate_limit
    if args.max_bytes is not None:
        config.max_content_bytes = args.max_bytes
    if args.output:
        config.output_dir = Path(args.output)
    if args.playwright:
        config.use_playwright = True

    exporter = ResultsExporter(config.output_dir)
    if args.read:
        exporter.display_results_from_file(args.read)
        return

    sites_data = load_sites_data()
    if not sites_data:
        logger.error("Could not find sites.json. Make sure it exists in the project.")
        return

    display_banner(len(sites_data))

    if args.username:
        usernames = args.username
    else:
        username = input(f"{COLORS['green']}Enter username to scan: {COLORS['yellow']}")
        usernames = [username]

    detector = Detector()
    detector.load_model(logger)

    extractor = FeatureExtractor()
    fingerprints = FingerprintStore(config.fingerprints_path, config.max_fingerprints_per_label)
    fingerprints.load(logger)

    scan_level = args.level or defaults.get("level")
    if scan_level not in {"basic", "intermediate", "advanced"}:
        scan_level = None
    if not scan_level:
        print(f"\n{COLORS['green']}Select scan level:")
        print(f"{COLORS['white']}1. {COLORS['blue']}Basic{COLORS['white']} - Just the username as entered")
        print(
            f"{COLORS['white']}2. {COLORS['yellow']}Intermediate{COLORS['white']} - Adds variations"
        )
        print(
            f"{COLORS['white']}3. {COLORS['red']}Advanced{COLORS['white']} - Adds common prefixes/suffixes"
        )
        level_choice = input(f"\n{COLORS['green']}Enter choice (1-3): {COLORS['yellow']}")
        level_map = {"1": "basic", "2": "intermediate", "3": "advanced"}
        scan_level = level_map.get(level_choice, "basic")

    formats_value = args.format if args.format is not None else defaults.get("output_formats")
    formats = parse_formats_value(formats_value)

    interactive = sys.stdin.isatty() and not args.read
    if interactive:
        scan_profile = prompt_scan_profile()
        apply_scan_profile(config, scan_profile, args)

    if interactive and prompt_yes_no("Customize scan settings", False):
        if args.concurrent is None:
            config.concurrent = prompt_int(
                "Max concurrent connections", config.concurrent, min_value=1
            )
        if args.timeout is None:
            config.timeout = prompt_float(
                "Request timeout (seconds)", config.timeout, min_value=1.0
            )
        if args.retries is None:
            config.retries = prompt_int("Retries on failure", config.retries, min_value=0)
        if args.backoff_base is None:
            config.backoff_base = prompt_float(
                "Backoff base (seconds)", config.backoff_base, min_value=0.0
            )
        if args.backoff_cap is None:
            config.backoff_cap = prompt_float(
                "Backoff cap (seconds)", config.backoff_cap, min_value=0.0
            )
        if args.rate_limit is None:
            config.rate_limit_delay = prompt_float(
                "Min delay per domain (seconds)", config.rate_limit_delay, min_value=0.0
            )
        if args.max_bytes is None:
            config.max_content_bytes = prompt_int(
                "Max response bytes to parse", config.max_content_bytes, min_value=1024
            )
        if args.output is None:
            config.output_dir = prompt_path("Output directory", config.output_dir)
        if args.format is None:
            formats = prompt_formats(formats)
        if not args.playwright:
            config.use_playwright = prompt_yes_no(
                "Enable Playwright fallback for Maybe results", config.use_playwright
            )

    browser_fallback = None
    if config.use_playwright:
        browser_fallback = BrowserFallback(config.timeout, DEFAULT_USER_AGENT)

    scanner = UsernameScanner(
        sites_data=sites_data,
        config=config,
        extractor=extractor,
        detector=detector,
        fingerprints=fingerprints,
        logger=logger,
        browser_fallback=browser_fallback,
    )

    try:
        for idx, username in enumerate(usernames):
            if not username or len(username) < 2:
                logger.error("Invalid username. Please provide a valid username.")
                continue

            if idx > 0:
                print(
                    f"\n{COLORS['green']}Continue with next username: {COLORS['yellow']}{username}{COLORS['reset']}"
                )

            all_results = await scanner.scan_with_variations(username, scan_level)
            written = exporter.save_results(username, scan_level, all_results, formats)

            files_list = ", ".join(str(path) for path in written)
            print(
                f"\n{COLORS['green']}Results saved to: {COLORS['blue']}{files_list}{COLORS['reset']}"
            )
            total_found = sum(
                sum(1 for r in results if r["status"] == "Found")
                for results in all_results.values()
            )
            print(
                f"\n{COLORS['green']}Summary: Found {total_found} profiles across {len(all_results)} username variations"
            )
    finally:
        fingerprints.save()
        if browser_fallback:
            await browser_fallback.close()

    print(f"\n{COLORS['green']}Thank you for using AI-Enhanced OSINT Username Scanner!{COLORS['reset']}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(run_scan(args))
    except KeyboardInterrupt:
        print(f"\n\n{COLORS['red']}Scan interrupted by user.{COLORS['reset']}")
        sys.exit(0)
    except Exception as exc:
        print(f"{COLORS['red']}Unexpected error: {exc}{COLORS['reset']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
