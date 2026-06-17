"""Command-line interface for Aliens Eye."""

from __future__ import annotations

import asyncio
import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt

from aliens_eye import __version__
from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.browser import BrowserFallback
from aliens_eye.core.config import DEFAULT_USER_AGENT, ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.exporter import ResultsExporter
from aliens_eye.core.fingerprints import FingerprintStore
from aliens_eye.core.scanner import (
    UsernameScanner,
    filter_sites,
    load_nsfw_sites,
    load_sites_data,
)
from aliens_eye.utils.console import get_console, set_plain
from aliens_eye.utils.logger import setup_logger

TOR_PROXY = "socks5://127.0.0.1:9050"

def display_banner(site_count: int) -> None:
    console = get_console()
    banner = rf"""[yellow]
"[blue]New AI detection
  feature improves
   accuracy by 40%[/blue][yellow]"        "[blue]Scans {site_count} websites[/blue][yellow]"
       [red]★   [white]\\[yellow]  _.-'~~~~'-._  [white] /[yellow]
   [blue]☾[yellow]      .-~ [green]\__/[magenta]  \__/[yellow] ~-.         .
        .-~  [green] ([red]oo[green]) [magenta] ([red]oo[magenta])    [yellow]~-.
       (_____[green]//~~\\[magenta]_//~~\\[yellow]______)       [magenta]☆[yellow]
  _.-~`                         `~-._
 /[magenta]O[blue]=[green]O[red]=[yellow]O[white]=[magenta]O[blue]=[green]O[red]=[yellow]O[white]=[green]O[red]=[yellow]=[green]O[red]=[yellow]O[white]O[white]=[magenta]O[blue]=[green]O[red]=[green]O[red]=[yellow]O[white]=[yellow]O[white]=[magenta]O[blue]=[green]O[red]=[yellow]O[yellow]\     [white]✴
[yellow] \___________________________________/
            \x [white]x[yellow] x [white]x[yellow] x [white]x[yellow] x/    [blue]✫[yellow]
    .  [white]*[yellow]     \\[white]x[yellow]_[white]x[yellow]_[white]x[yellow]_[white]x[yellow]_[white]x[yellow]_[white]x[yellow]/
              [red]AI-POWERED[green]
   ___   __   _________  ___  ____
  / _ | / /  /  _/ __/ |/ ( )/ __/
 / __ |/ /___/ // _//    /|/_\ \
/_/ |_/____/___/___/_/|_/  /___/
[blue]
    ________  ________
   [blue]/ ____/\ \/ / ____/ [red] _    __[white]  ___
  [blue]/ __/    \  / __/   [red] | |  / /[white] |__ \
 [blue]/ /___    / / /___    [red]| | / /[white]  _/ /
[blue]/_____/   /_/_____/  [red]  | |/ /[white] / __/
                      [red] |___/ [white]/____/

[green]by [yellow]arxhr007  [dim]v{__version__}[/dim]"""
    console.print(banner)
    console.print("[yellow]AI-OSINT USERNAME SCANNER[/yellow]")
    console.print("[red]NOTE: For educational purposes only!\n[/red]")


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye",
        description="AI-Enhanced Username Scanner - Find usernames across social media platforms",
    )
    parser.add_argument("username", nargs="*", help="Usernames to scan")
    parser.add_argument("-V", "--version", action="version", version=f"aliens-eye {__version__}")
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
        help="Output formats: json,csv,html,md,all",
    )
    parser.add_argument("--output", type=str, default=None, help="Output directory")
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Enable Playwright fallback for Maybe results (requires aliens-eye[browser])",
    )
    parser.add_argument("--proxy", type=str, help="Proxy URL (http://, socks4://, or socks5://)")
    parser.add_argument(
        "--tor", action="store_true", help=f"Route traffic through Tor ({TOR_PROXY})"
    )
    parser.add_argument(
        "--site",
        type=str,
        help="Only scan sites whose name matches (comma-separated, substring match)",
    )
    parser.add_argument(
        "--exclude-site",
        type=str,
        help="Skip sites whose name matches (comma-separated, substring match)",
    )
    parser.add_argument("--no-nsfw", action="store_true", help="Skip NSFW sites")
    parser.add_argument("--no-ml", action="store_true", help="Disable ML detection, heuristics only")
    parser.add_argument("--model", type=str, help="Path to a custom ML model JSON")
    parser.add_argument("--sites", type=str, help="Path to a custom sites JSON")
    parser.add_argument("--plain", action="store_true", help="Plain output (no colors/progress)")
    parser.add_argument(
        "--profile",
        choices=["quick", "full", "aggressive"],
        help="Scan profile preset (skips interactive prompt)",
    )
    return parser


def build_selfcheck_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye selfcheck",
        description="Validate detection accuracy against accounts known to exist",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--no-ml", action="store_true", help="Disable ML detection")
    parser.add_argument("--model", type=str, help="Path to a custom ML model JSON")
    parser.add_argument("--sites", type=str, help="Path to a custom sites JSON")
    parser.add_argument("--plain", action="store_true", help="Plain output")
    return parser


def build_train_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye train",
        description="Collect training data and fit the detection model",
    )
    sub = parser.add_subparsers(dest="train_command", required=True)

    collect = sub.add_parser("collect", help="Scan ground-truth accounts to build a labeled dataset")
    collect.add_argument("--out", type=str, default="seed_dataset.csv", help="Output CSV path")
    collect.add_argument("--negatives", type=int, default=2, help="Negative samples per site")
    collect.add_argument("--seed", type=int, default=None, help="Random seed")
    collect.add_argument("--sites", type=str, help="Path to a custom sites JSON")
    collect.add_argument("-v", "--verbose", action="store_true")

    fit = sub.add_parser("fit", help="Train the model from a labeled dataset CSV")
    fit.add_argument("--data", type=str, required=True, help="Labeled dataset CSV")
    fit.add_argument("--out", type=str, default="model.json", help="Output model JSON path")
    fit.add_argument("-v", "--verbose", action="store_true")
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


def parse_site_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def prompt_scan_profile() -> str:
    console = get_console()
    console.print("\n[green]Select scan profile:[/green]")
    console.print("  1. [blue]Quick[/blue] - fewer retries, shorter timeouts")
    console.print("  2. [yellow]Full[/yellow] - balanced defaults")
    console.print("  3. [red]Aggressive[/red] - higher concurrency, Playwright")
    choice = Prompt.ask("Enter choice", choices=["1", "2", "3"], default="2", console=console)
    return {"1": "quick", "2": "full", "3": "aggressive"}[choice]


def prompt_scan_level() -> str:
    console = get_console()
    console.print("\n[green]Select scan level:[/green]")
    console.print("  1. [blue]Basic[/blue] - Just the username as entered")
    console.print("  2. [yellow]Intermediate[/yellow] - Adds variations")
    console.print("  3. [red]Advanced[/red] - Adds common prefixes/suffixes")
    choice = Prompt.ask("Enter choice", choices=["1", "2", "3"], default="1", console=console)
    return {"1": "basic", "2": "intermediate", "3": "advanced"}[choice]


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
            Path(user_config_dir("aliens_eye")) / "config.json",
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
        "proxy": "proxy",
        "use_ml": "use_ml",
        "exclude_nsfw": "exclude_nsfw",
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


def apply_cli_overrides(config: ScannerConfig, args) -> None:
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
    if args.tor:
        config.proxy = TOR_PROXY
    elif args.proxy:
        config.proxy = args.proxy
    if args.no_ml:
        config.use_ml = False
    if args.model:
        config.model_path = Path(args.model)
    if args.sites:
        config.sites_path = Path(args.sites)
    if args.no_nsfw:
        config.exclude_nsfw = True
    config.include_sites = parse_site_list(args.site)
    config.exclude_sites = parse_site_list(args.exclude_site)
    if args.plain:
        config.plain_output = True


def prepare_sites(config: ScannerConfig, logger) -> dict:
    sites_data = load_sites_data(config.sites_path)
    if not sites_data:
        logger.error("Could not load sites.json.")
        return {}

    exclude = list(config.exclude_sites or [])
    if config.exclude_nsfw:
        exclude.extend(load_nsfw_sites())
    sites_data = filter_sites(sites_data, config.include_sites, exclude or None)
    if not sites_data:
        logger.error("Site filters matched no sites.")
    return sites_data


def customize_config_interactive(config: ScannerConfig, formats: list[str], args) -> list[str]:
    console = get_console()
    if args.concurrent is None:
        config.concurrent = IntPrompt.ask(
            "Max concurrent connections", default=config.concurrent, console=console
        )
    if args.timeout is None:
        config.timeout = FloatPrompt.ask(
            "Request timeout (seconds)", default=config.timeout, console=console
        )
    if args.retries is None:
        config.retries = IntPrompt.ask("Retries on failure", default=config.retries, console=console)
    if args.backoff_base is None:
        config.backoff_base = FloatPrompt.ask(
            "Backoff base (seconds)", default=config.backoff_base, console=console
        )
    if args.backoff_cap is None:
        config.backoff_cap = FloatPrompt.ask(
            "Backoff cap (seconds)", default=config.backoff_cap, console=console
        )
    if args.rate_limit is None:
        config.rate_limit_delay = FloatPrompt.ask(
            "Min delay per domain (seconds)", default=config.rate_limit_delay, console=console
        )
    if args.max_bytes is None:
        config.max_content_bytes = IntPrompt.ask(
            "Max response bytes to parse", default=config.max_content_bytes, console=console
        )
    if args.output is None:
        value = Prompt.ask("Output directory", default=str(config.output_dir), console=console)
        config.output_dir = Path(value)
    if args.format is None:
        value = Prompt.ask(
            "Output formats (json,csv,html,md,all)",
            default=",".join(formats),
            console=console,
        )
        formats = parse_formats(value)
    if not args.playwright:
        config.use_playwright = Confirm.ask(
            "Enable Playwright fallback for Maybe results",
            default=config.use_playwright,
            console=console,
        )
    return formats


async def run_scan(args) -> None:
    logger = setup_logger(args.verbose)
    config_data = load_config(args.config, logger)
    config = ScannerConfig()
    defaults = apply_config(config, config_data)
    apply_cli_overrides(config, args)
    if config.plain_output:
        set_plain(True)
    console = get_console()

    exporter_dir = config.output_dir
    if args.read:
        ResultsExporter(exporter_dir).display_results_from_file(args.read)
        return

    sites_data = prepare_sites(config, logger)
    if not sites_data:
        return

    display_banner(len(sites_data))

    if args.username:
        usernames = args.username
    else:
        username = Prompt.ask("[green]Enter username to scan[/green]", console=console)
        usernames = [username]

    detector = Detector()
    if config.use_ml:
        detector.load_model(logger, config.model_path)
        if detector.model is None:
            console.print("[dim]ML model unavailable; falling back to heuristics.[/dim]")
    extractor = FeatureExtractor()
    fingerprints = FingerprintStore(config.fingerprints_path, config.max_fingerprints_per_label)
    fingerprints.load(logger)

    interactive = sys.stdin.isatty() and not args.read

    scan_level = args.level or defaults.get("level")
    if scan_level not in {"basic", "intermediate", "advanced"}:
        scan_level = None
    if not scan_level:
        scan_level = prompt_scan_level() if interactive else "basic"

    formats_value = args.format if args.format is not None else defaults.get("output_formats")
    formats = parse_formats_value(formats_value)

    profile = args.profile
    if interactive and not profile:
        profile = prompt_scan_profile()
    if profile:
        apply_scan_profile(config, profile, args)

    if interactive and not args.profile and Confirm.ask(
        "Customize scan settings", default=False, console=console
    ):
        formats = customize_config_interactive(config, formats, args)

    browser_fallback = None
    if config.use_playwright:
        browser_fallback = BrowserFallback(config.timeout, DEFAULT_USER_AGENT)

    exporter = ResultsExporter(config.output_dir)
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
        for username in usernames:
            if not username or len(username) < 2:
                logger.error("Invalid username. Please provide a valid username.")
                continue

            all_results = await scanner.scan_with_variations(username, scan_level)
            written = exporter.save_results(username, scan_level, all_results, formats)

            files_list = ", ".join(str(path) for path in written)
            console.print(f"\n[green]Results saved to:[/green] [blue]{files_list}[/blue]")
            total_found = sum(
                sum(1 for r in results if r["status"] == "Found")
                for results in all_results.values()
            )
            console.print(
                f"[green]Summary: Found {total_found} profiles across "
                f"{len(all_results)} username variations[/green]"
            )
    finally:
        fingerprints.save()
        if browser_fallback:
            await browser_fallback.close()


async def run_selfcheck_command(args) -> None:
    from aliens_eye.selfcheck import run_selfcheck

    if args.plain:
        set_plain(True)
    logger = setup_logger(args.verbose)
    config = ScannerConfig(retries=1)
    sites_data = load_sites_data(Path(args.sites) if args.sites else None)
    detector = Detector()
    if not args.no_ml:
        detector.load_model(logger, Path(args.model) if args.model else None)
    await run_selfcheck(sites_data, detector, config, logger)


async def run_train_command(args) -> None:
    logger = setup_logger(args.verbose)
    console = get_console()
    if args.train_command == "collect":
        from aliens_eye.ml.collect import collect_dataset

        sites_data = load_sites_data(Path(args.sites) if args.sites else None)
        count = await collect_dataset(
            sites_data,
            Path(args.out),
            logger,
            negatives_per_site=args.negatives,
            seed=args.seed,
        )
        console.print(f"[green]Collected {count} labeled samples -> {args.out}[/green]")
    elif args.train_command == "fit":
        from aliens_eye.ml.train import train_model

        model = train_model(Path(args.data), Path(args.out), logger)
        cv = model["training"].get("cv_accuracy")
        console.print(
            f"[green]Model trained on {model['training']['samples']} samples"
            + (f" (cv accuracy {cv:.1%})" if cv is not None else "")
            + f" -> {args.out}[/green]"
        )


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    argv = sys.argv[1:]
    console = get_console()
    try:
        if argv and argv[0] == "selfcheck":
            args = build_selfcheck_parser().parse_args(argv[1:])
            asyncio.run(run_selfcheck_command(args))
        elif argv and argv[0] == "train":
            args = build_train_parser().parse_args(argv[1:])
            asyncio.run(run_train_command(args))
        else:
            args = build_parser().parse_args(argv)
            asyncio.run(run_scan(args))
    except KeyboardInterrupt:
        console.print("\n[red]Interrupted by user.[/red]")
        sys.exit(0)
    except Exception as exc:
        console.print(f"[red]Unexpected error: {exc}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
