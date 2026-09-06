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
    load_site_plugins,
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
    parser.add_argument(
        "--watch",
        type=str,
        help="Re-scan on an interval and alert on changes (e.g. 30m, 6h, 1d)",
    )
    parser.add_argument("--notify", type=str, help="Webhook URL to POST watch-mode changes to")
    parser.add_argument(
        "--correlate",
        action="store_true",
        help="Cluster Found/Maybe profiles that look like the same person (avatar/bio/links)",
    )
    parser.add_argument(
        "--domains",
        action="store_true",
        help="Check whether <username>.{com,io,net,...} domains are registered/live",
    )
    parser.add_argument(
        "--recurse-depth",
        type=int,
        default=0,
        help="Extract linked usernames from found profiles and re-scan, up to N hops",
    )
    parser.add_argument("--sites-dir", type=str, help="Directory of extra *.json site maps to merge")
    parser.add_argument("--resume", type=str, help="Checkpoint file to resume an interrupted scan from")
    parser.add_argument("--from-email", type=str, help="Seed usernames from an email address")
    parser.add_argument("--from-name", type=str, help="Seed usernames from a real name")
    parser.add_argument("--from-phone", type=str, help="Seed usernames from a phone number")
    parser.add_argument(
        "--only-found", action="store_true", help="Report only Found/Maybe results"
    )
    parser.add_argument(
        "--json-stdout", action="store_true", help="Print results JSON to stdout (implies --plain)"
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
    parser.add_argument(
        "--negatives", type=int, default=1, help="Random non-existent usernames to test per site"
    )
    parser.add_argument(
        "--report", choices=["table", "json"], default="table",
        help="Output format: rich table (default) or machine-readable JSON",
    )
    parser.add_argument(
        "--split", choices=["train", "holdout", "all"], default="train",
        help="Ground-truth split to score: train (default), holdout (sites the "
             "model never trained on), or all",
    )
    parser.add_argument(
        "--ground-truth", type=str,
        help="Path to a custom ground-truth JSON (overrides --split)",
    )
    parser.add_argument(
        "--corpus", type=str,
        help="Score against a frozen response corpus instead of the live web "
             "(reproducible; see 'aliens_eye corpus record')",
    )
    parser.add_argument(
        "--allow-corpus-misses", action="store_true",
        help="With --corpus, score URLs absent from the corpus as fetch errors "
             "instead of failing loudly",
    )
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
    collect.add_argument(
        "--split", choices=["train", "holdout", "all"], default="train",
        help="Ground-truth split to collect from. Defaults to train; anything "
             "else reintroduces train/eval leakage and requires --allow-leakage",
    )
    collect.add_argument(
        "--allow-leakage", action="store_true",
        help="Permit collecting training data from a non-train split (research use only)",
    )
    collect.add_argument("-v", "--verbose", action="store_true")

    fit = sub.add_parser("fit", help="Train the model from a labeled dataset CSV")
    fit.add_argument("--data", type=str, required=True, help="Labeled dataset CSV")
    fit.add_argument("--out", type=str, default="model.json", help="Output model JSON path")
    fit.add_argument("-v", "--verbose", action="store_true")
    return parser


def build_corpus_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye corpus",
        description="Record and inspect a frozen response corpus for reproducible evaluation",
    )
    sub = parser.add_subparsers(dest="corpus_command", required=True)

    record = sub.add_parser("record", help="Capture live responses for the ground-truth accounts")
    record.add_argument("--out", type=str, required=True, help="Corpus directory to write")
    record.add_argument(
        "--split", choices=["train", "holdout", "all"], default="all",
        help="Ground-truth split to capture (default: all)",
    )
    record.add_argument("--ground-truth", type=str, help="Custom ground-truth JSON (overrides --split)")
    record.add_argument("--negatives", type=int, default=4, help="Negative usernames per site")
    record.add_argument(
        "--plausible-ratio", type=float, default=0.5,
        help="Fraction of negatives with realistic handle morphology rather than random strings",
    )
    record.add_argument("--seed", type=int, default=1234, help="Seed for negative generation")
    record.add_argument("--concurrency", type=int, default=20)
    record.add_argument("--timeout", type=float, default=15.0)
    record.add_argument("--sites", type=str, help="Path to a custom sites JSON")
    record.add_argument("-v", "--verbose", action="store_true")

    stats = sub.add_parser("stats", help="Summarise a recorded corpus")
    stats.add_argument("path", type=str, help="Corpus directory")
    stats.add_argument("--json", action="store_true", dest="json_out", help="Machine-readable output")
    stats.add_argument("-v", "--verbose", action="store_true")
    return parser


def build_eval_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye eval",
        description="Reproducible detector evaluation over a frozen corpus",
    )
    sub = parser.add_subparsers(dest="eval_command", required=True)

    ablate = sub.add_parser(
        "ablate", help="Score detector configurations over a corpus (baselines, judges, feature groups)"
    )
    ablate.add_argument("--corpus", type=str, required=True, help="Corpus directory")
    ablate.add_argument(
        "--split", choices=["train", "holdout", "all"], default="holdout",
        help="Ground-truth split to score (default: holdout)",
    )
    ablate.add_argument("--ground-truth", type=str, help="Custom ground-truth JSON")
    ablate.add_argument("--model", type=str, help="Path to a custom ML model JSON")
    ablate.add_argument(
        "--only", type=str,
        help="Comma-separated ablation names to run (default: all)",
    )
    ablate.add_argument(
        "--fingerprints", action="store_true",
        help="Enable the fingerprint store, populated in a fixed order",
    )
    ablate.add_argument("--out", type=str, help="Write the full result bundle as JSON here")
    ablate.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    ablate.add_argument("-v", "--verbose", action="store_true")

    external = sub.add_parser(
        "external",
        help="Compare against external tool rule sets (Sherlock / Maigret / WhatsMyName) over the corpus",
    )
    external.add_argument("--corpus", type=str, required=True, help="Corpus directory")
    external.add_argument(
        "--split", choices=["train", "holdout", "all"], default="all",
        help="Ground-truth split to score (default: all)",
    )
    external.add_argument("--ground-truth", type=str, help="Custom ground-truth JSON")
    external.add_argument("--model", type=str, help="Path to a custom ML model JSON")
    external.add_argument(
        "--sherlock", type=str,
        help="Path to Sherlock's data.json (MIT; fetch it yourself, it is not vendored)",
    )
    external.add_argument(
        "--maigret", type=str,
        help="Path to Maigret's data.json (MIT); read with the Sherlock rule semantics",
    )
    external.add_argument(
        "--whatsmyname", type=str,
        help="Path to wmn-data.json (CC BY-SA 4.0, (C) Micah Hoffman et al.)",
    )
    external.add_argument("--out", type=str, help="Write the result bundle as JSON here")
    external.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    external.add_argument("-v", "--verbose", action="store_true")
    return parser


def build_diff_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye diff",
        description="Compare two saved scan reports and show what changed",
    )
    parser.add_argument("old", help="Path to the older report JSON")
    parser.add_argument("new", help="Path to the newer report JSON")
    parser.add_argument("--plain", action="store_true", help="Plain output")
    parser.add_argument(
        "--json-stdout", action="store_true", help="Print the diff as JSON to stdout"
    )
    return parser


def build_serve_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye serve",
        description="Run an MCP server exposing scan tools over stdio",
    )
    parser.add_argument("--sites", type=str, help="Path to a custom sites JSON")
    parser.add_argument("--no-ml", action="store_true", help="Disable ML detection")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def build_tui_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye tui",
        description="Interactive terminal UI for scanning",
    )
    parser.add_argument("username", nargs="?", help="Username to scan")
    parser.add_argument("-l", "--level", choices=["basic", "intermediate", "advanced"], default="basic")
    parser.add_argument("--sites", type=str, help="Path to a custom sites JSON")
    parser.add_argument("--no-ml", action="store_true", help="Disable ML detection")
    return parser


def build_label_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="aliens_eye label",
        description="Interactively label low-confidence results and append them to a dataset",
    )
    parser.add_argument("report", help="Path to a saved report JSON to label")
    parser.add_argument("--out", type=str, default="labeled.csv", help="Dataset CSV to append to")
    parser.add_argument(
        "--band", type=str, default="Maybe",
        help="Which statuses to review: 'Maybe' (default) or 'all'",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
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


def seed_usernames_from_lookups(args) -> list[str]:
    """Expand --from-email/--from-name/--from-phone into candidate usernames."""
    from aliens_eye.core.variations import usernames_from_email, usernames_from_name

    seeds: list[str] = []
    if getattr(args, "from_email", None):
        seeds.extend(usernames_from_email(args.from_email))
    if getattr(args, "from_name", None):
        seeds.extend(usernames_from_name(args.from_name))
    if getattr(args, "from_phone", None):
        digits = "".join(ch for ch in args.from_phone if ch.isdigit())
        if len(digits) >= 4:
            seeds.append(digits)
    return seeds


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
    if args.only_found:
        config.only_found = True
    if args.json_stdout:
        config.json_stdout = True
        config.plain_output = True
    if args.plain:
        config.plain_output = True


def prepare_sites(config: ScannerConfig, logger, sites_dir: str | None = None) -> dict:
    sites_data = load_sites_data(config.sites_path)
    if not sites_data:
        logger.error("Could not load sites.json.")
        return {}

    extra_dirs = [Path(sites_dir)] if sites_dir else None
    plugins = load_site_plugins(extra_dirs)
    if plugins:
        logger.info("Merged %d plugin site(s) from sites.d directories", len(plugins))
        sites_data = {**sites_data, **plugins}

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
    if config.json_stdout:
        set_plain(True, stderr=True)
    elif config.plain_output:
        set_plain(True)
    console = get_console()

    exporter_dir = config.output_dir
    if args.read:
        ResultsExporter(exporter_dir).display_results_from_file(args.read)
        return

    sites_data = prepare_sites(config, logger, sites_dir=args.sites_dir)
    if not sites_data:
        return

    if not config.json_stdout:
        display_banner(len(sites_data))

    usernames = list(args.username)
    usernames.extend(seed_usernames_from_lookups(args))
    usernames = list(dict.fromkeys(usernames))
    if not usernames:
        if config.json_stdout:
            logger.error("No username provided.")
            return
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

    interactive = sys.stdin.isatty() and not args.read and not config.json_stdout

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

    checkpoint = None
    if args.resume:
        from aliens_eye.core.checkpoint import Checkpoint

        checkpoint = Checkpoint(args.resume)

    exporter = ResultsExporter(config.output_dir)
    scanner = UsernameScanner(
        sites_data=sites_data,
        config=config,
        extractor=extractor,
        detector=detector,
        fingerprints=fingerprints,
        logger=logger,
        browser_fallback=browser_fallback,
        checkpoint=checkpoint,
    )

    if args.watch:
        from aliens_eye.core import watch as watch_mod

        try:
            interval = watch_mod.parse_duration(args.watch)
        except ValueError as exc:
            logger.error("Invalid --watch interval: %s", exc)
            return
        try:
            await watch_mod.run_watch(
                scanner=scanner,
                exporter=exporter,
                usernames=usernames,
                scan_level=scan_level,
                formats=formats,
                interval=interval,
                logger=logger,
                console=console,
                output_dir=config.output_dir,
                notify_url=args.notify,
            )
        finally:
            fingerprints.save()
            if browser_fallback:
                await browser_fallback.close()
        return

    try:
        for username in usernames:
            if not username or len(username) < 2:
                logger.error("Invalid username. Please provide a valid username.")
                continue

            all_results = await scanner.scan_with_variations(username, scan_level)

            if args.recurse_depth and args.recurse_depth > 0:
                await _recurse_scan(
                    scanner, all_results, username, scan_level, args.recurse_depth, console
                )

            correlation = None
            if args.correlate:
                from aliens_eye.core.correlate import correlate_report

                report = exporter.report_dict(username, scan_level, all_results)
                correlation = await correlate_report(report, proxy=config.proxy, timeout=config.timeout)
                _print_clusters(console, correlation)

            domains = None
            if args.domains:
                from aliens_eye.core.domains import check_domains

                domains = await check_domains(username, proxy=config.proxy)
                _print_domains(console, domains)

            written = exporter.save_results(
                username, scan_level, all_results, formats,
                correlation=correlation, domains=domains,
            )

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
        if checkpoint is not None:
            checkpoint.finalize()
    finally:
        fingerprints.save()
        if browser_fallback:
            await browser_fallback.close()


async def _recurse_scan(scanner, all_results, base_username, scan_level, depth, console) -> None:
    """Extract linked usernames from found profiles and scan them, up to `depth` hops."""
    from aliens_eye.core.expand import candidate_usernames_from_results

    seen = {base_username.lower()}
    frontier = candidate_usernames_from_results(all_results, exclude=seen)
    for hop in range(depth):
        frontier = [u for u in frontier if u.lower() not in seen]
        if not frontier:
            break
        console.print(
            f"[blue]Recursion hop {hop + 1}:[/blue] {len(frontier)} linked username(s): "
            f"[dim]{', '.join(frontier[:8])}{'...' if len(frontier) > 8 else ''}[/dim]"
        )
        next_frontier: list[str] = []
        for uname in frontier:
            seen.add(uname.lower())
            sub = await scanner.scan_all_sites(uname)
            all_results[uname] = sub
            next_frontier.extend(
                candidate_usernames_from_results({uname: sub}, exclude=seen)
            )
        frontier = list(dict.fromkeys(next_frontier))


def _print_clusters(console, correlation: dict) -> None:
    clusters = correlation.get("clusters", [])
    if not clusters:
        console.print("[dim]Correlation: no cross-site clusters found.[/dim]")
        return
    from rich.table import Table

    table = Table(title="Correlation: likely same person", header_style="bold blue")
    table.add_column("#", justify="right")
    table.add_column("Sites", style="yellow")
    table.add_column("Linked by")
    for i, cluster in enumerate(clusters, 1):
        sites = ", ".join(f"{m['site']}" for m in cluster["members"])
        table.add_row(str(i), sites, ", ".join(cluster.get("reasons", [])))
    console.print(table)
    if not correlation.get("avatar_hashing"):
        console.print(
            "[dim]Tip: install \"aliens-eye\\[correlate]\" for avatar-image matching.[/dim]"
        )


def _print_domains(console, domains: dict) -> None:
    from rich.table import Table

    table = Table(title="Domain check", header_style="bold blue")
    table.add_column("Domain", style="yellow")
    table.add_column("Registered")
    table.add_column("Live")
    for entry in domains.get("results", []):
        table.add_row(
            entry["domain"],
            "[green]yes[/green]" if entry["registered"] else "[dim]no[/dim]",
            "[green]yes[/green]" if entry["live"] else "[dim]no[/dim]",
        )
    console.print(table)


async def run_selfcheck_command(args) -> None:
    from aliens_eye.core.http import fetch_url
    from aliens_eye.selfcheck import run_selfcheck

    console = get_console()
    if args.report == "json":
        set_plain(True, stderr=True)
    elif args.plain:
        set_plain(True)
    logger = setup_logger(args.verbose)
    config = ScannerConfig(retries=1)
    sites_data = load_sites_data(Path(args.sites) if args.sites else None)
    detector = Detector()
    if not args.no_ml:
        detector.load_model(logger, Path(args.model) if args.model else None)
    fetch = fetch_url
    jobs = None
    if args.corpus:
        from aliens_eye.corpus.replay import ReplayFetcher
        from aliens_eye.ml.collect import load_selfcheck_data

        replay = ReplayFetcher(Path(args.corpus), strict=not args.allow_corpus_misses)
        fetch = replay
        # The corpus supplies the evaluation set, filtered to the requested
        # split. Regenerating negatives here would miss the corpus entirely and
        # leave the negative class empty.
        sites = None
        if args.split != "all":
            sites = set(
                load_selfcheck_data(
                    args.split, Path(args.ground_truth) if args.ground_truth else None
                )
            )
        jobs = replay.eval_jobs(sites)
        if not jobs:
            console.print(
                f"[red]Corpus at {args.corpus} holds no labelled records for split "
                f"{args.split!r}.[/red]"
            )
            return
        positives = sum(1 for j in jobs if j[3] == 1)
        if args.report != "json":
            console.print(
                f"[dim]Replaying {len(jobs)} corpus rows "
                f"({positives} positive / {len(jobs) - positives} negative) "
                f"from {args.corpus} — no network.[/dim]"
            )

    await run_selfcheck(
        sites_data, detector, config, logger,
        negatives=args.negatives, report_format=args.report,
        split=args.split,
        ground_truth_path=Path(args.ground_truth) if args.ground_truth else None,
        fetch=fetch,
        jobs=jobs,
    )


async def run_train_command(args) -> None:
    logger = setup_logger(args.verbose)
    console = get_console()
    if args.train_command == "collect":
        from aliens_eye.ml.collect import collect_dataset

        if args.split != "train" and not args.allow_leakage:
            console.print(
                f"[red]Refusing to collect training data from the '{args.split}' split:[/red] "
                "it overlaps the evaluation holdout. Pass --allow-leakage to override."
            )
            return
        sites_data = load_sites_data(Path(args.sites) if args.sites else None)
        count = await collect_dataset(
            sites_data,
            Path(args.out),
            logger,
            negatives_per_site=args.negatives,
            seed=args.seed,
            split=args.split,
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


async def run_corpus_command(args) -> None:
    logger = setup_logger(args.verbose)
    console = get_console()

    if args.corpus_command == "record":
        from aliens_eye.corpus.record import record_corpus
        from aliens_eye.ml.collect import load_selfcheck_data

        sites_data = load_sites_data(Path(args.sites) if args.sites else None)
        ground_truth = load_selfcheck_data(
            args.split, Path(args.ground_truth) if args.ground_truth else None
        )
        console.print(
            f"[blue]Recording[/blue] {sum(len(v) for v in ground_truth.values())} positives + "
            f"{args.negatives}/site negatives across {len(ground_truth)} sites -> {args.out}"
        )
        manifest = await record_corpus(
            sites_data,
            ground_truth,
            Path(args.out),
            logger,
            negatives_per_site=args.negatives,
            concurrency=args.concurrency,
            seed=args.seed,
            split=args.split,
            plausible_ratio=args.plausible_ratio,
            config=ScannerConfig(retries=2, timeout=args.timeout),
        )
        console.print(
            f"[green]Captured {manifest['records']} records[/green] "
            f"({manifest['errors']} fetch errors) across {len(manifest['sites'])} sites"
        )
        if manifest["skipped_sites"]:
            console.print(
                f"[yellow]Skipped (missing from sites.json):[/yellow] "
                f"{', '.join(manifest['skipped_sites'])}"
            )
        return

    from rich.table import Table

    from aliens_eye.corpus.replay import ReplayFetcher

    replay = ReplayFetcher(Path(args.path), strict=False)
    stats = replay.stats()
    if args.json_out:
        print(json.dumps(stats, indent=2))
        return
    table = Table(title=f"Corpus: {args.path}", header_style="bold blue")
    table.add_column("Field", style="yellow")
    table.add_column("Value", justify="right")
    for key, value in stats.items():
        table.add_row(key, str(value))
    console.print(table)


async def run_eval_command(args) -> None:
    from rich.table import Table

    from aliens_eye.eval.ablate import run_ablations

    if args.eval_command == "external":
        await run_eval_external_command(args)
        return

    if args.json_out:
        set_plain(True, stderr=True)
    logger = setup_logger(args.verbose)
    console = get_console()

    detector = Detector()
    detector.load_model(logger, Path(args.model) if args.model else None)
    if detector.model is None:
        console.print("[yellow]No ML model loaded; ml_only and blended rows will match heuristic_only.[/yellow]")

    sites = None
    if args.split != "all":
        from aliens_eye.ml.collect import load_selfcheck_data

        sites = set(
            load_selfcheck_data(
                args.split, Path(args.ground_truth) if args.ground_truth else None
            )
        )

    bundle = await run_ablations(
        Path(args.corpus),
        detector,
        logger,
        sites=sites,
        names=[n.strip() for n in args.only.split(",")] if args.only else None,
        use_fingerprints=args.fingerprints,
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json_out:
        print(json.dumps(bundle, indent=2, sort_keys=True))
        return

    console.print(
        f"[blue]Corpus[/blue] {bundle['corpus']}  "
        f"[blue]split[/blue] {args.split}  "
        f"[blue]rows[/blue] {bundle['usable_rows']} usable "
        f"({bundle['positives']} pos / {bundle['negatives']} neg, "
        f"{bundle['excluded_rows']} excluded)"
    )
    table = Table(title="Ablation results", header_style="bold blue")
    table.add_column("Configuration", style="yellow")
    for col in ("P", "R", "F1", "F1 95% CI", "FPR", "Maybe", "vs shipped"):
        table.add_column(col, justify="right")
    for row in bundle["results"]:
        m = row["overall"]
        f1 = m["f1"]
        style = "green" if f1 >= 0.8 else "yellow" if f1 >= 0.6 else "red"
        boot = row.get("bootstrap", {})
        ci = f"{boot.get('ci_low', 0):.2f}-{boot.get('ci_high', 0):.2f}" if boot else "-"
        delta = row.get("vs_reference")
        if delta is None:
            vs = "[dim]reference[/dim]"
        elif delta["separable"]:
            vs = f"[bold]{delta['delta']:+.3f}[/bold]"
        else:
            vs = f"[dim]{delta['delta']:+.3f} ns[/dim]"
        table.add_row(
            row["name"],
            f"{m['precision']:.3f}", f"{m['recall']:.3f}",
            f"[{style}]{f1:.3f}[/{style}]", ci,
            f"{m['false_positive_rate']:.3f}", f"{m['maybe_rate']:.3f}", vs,
        )
    console.print(table)
    console.print(
        "[dim]ns = 95% paired-bootstrap CI on the F1 difference spans zero: "
        "this corpus cannot distinguish that configuration from the shipped blend.[/dim]"
    )
    if args.out:
        console.print(f"[dim]Full bundle written to {args.out}[/dim]")


async def run_eval_external_command(args) -> None:
    from rich.table import Table

    from aliens_eye.eval.external import compare_external

    if args.json_out:
        set_plain(True, stderr=True)
    logger = setup_logger(args.verbose)
    console = get_console()

    rule_paths = {
        name: Path(value)
        for name, value in (
            ("sherlock", args.sherlock),
            ("maigret", args.maigret),
            ("whatsmyname", args.whatsmyname),
        )
        if value
    }
    if not rule_paths:
        console.print(
            "[red]No rule sets given.[/red] Pass at least one of --sherlock / --maigret / "
            "--whatsmyname. The rule data is not vendored; fetch it from the upstream "
            "project and mind its licence."
        )
        return
    missing = [str(p) for p in rule_paths.values() if not p.exists()]
    if missing:
        console.print(f"[red]Rule file(s) not found:[/red] {', '.join(missing)}")
        return

    detector = Detector()
    detector.load_model(logger, Path(args.model) if args.model else None)

    sites = None
    if args.split != "all":
        from aliens_eye.ml.collect import load_selfcheck_data

        sites = set(
            load_selfcheck_data(
                args.split, Path(args.ground_truth) if args.ground_truth else None
            )
        )

    bundle = await compare_external(
        Path(args.corpus), detector, logger, rule_paths, sites=sites
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json_out:
        print(json.dumps(bundle, indent=2, sort_keys=True))
        return

    console.print(
        f"[blue]Corpus[/blue] {bundle['corpus']}  "
        f"[blue]usable rows[/blue] {bundle['usable_rows']}"
    )
    for entry in bundle["external"]:
        m = entry["overall"]
        console.print(
            f"\n[bold]{entry['name']}[/bold]  "
            f"rules {entry['source']['usable_rules']}  "
            f"covered {entry['samples']} rows ({entry['site_coverage']:.0%})  "
            f"no rule {entry['rows_without_rule']}  undecided {entry['rows_rule_undecided']}"
        )
        table = Table(header_style="bold blue")
        table.add_column("Detector", style="yellow")
        for col in ("P", "R", "F1", "FPR", "vs this tool", "95% CI"):
            table.add_column(col, justify="right")
        table.add_row(
            entry["name"],
            f"{m['precision']:.3f}", f"{m['recall']:.3f}", f"{m['f1']:.3f}",
            f"{m['false_positive_rate']:.3f}", "[dim]reference[/dim]", "",
        )
        for our_name, cmp in entry["vs_ours"].items():
            verdict = "[bold]separable[/bold]" if cmp["separable"] else "[dim]ns[/dim]"
            table.add_row(
                f"ours: {our_name}", "", "",
                f"{cmp['our_f1_on_covered_rows']:.3f}", "",
                f"{cmp['delta']:+.3f} {verdict}",
                f"[{cmp['ci_low']:+.3f}, {cmp['ci_high']:+.3f}]",
            )
        console.print(table)
    console.print(
        "\n[dim]External verdicts come from reimplemented rule semantics applied to the "
        "same stored responses, not from running the upstream tools. Rows a tool has no "
        "rule for are excluded from its score rather than counted against it.[/dim]"
    )
    if args.out:
        console.print(f"[dim]Full bundle written to {args.out}[/dim]")


def run_diff_command(args) -> None:
    from aliens_eye.core.report import ReportError, diff_reports, load_report

    if args.json_stdout:
        set_plain(True, stderr=True)
    elif args.plain:
        set_plain(True)
    console = get_console()
    try:
        old = load_report(args.old)
        new = load_report(args.new)
    except ReportError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    delta = diff_reports(old, new)
    if args.json_stdout:
        print(json.dumps(delta, indent=2))
        return

    from rich.table import Table

    if not (delta["new"] or delta["gone"] or delta["changed"]):
        console.print("[dim]No differences between the two reports.[/dim]")
        return

    table = Table(title="Report diff", header_style="bold blue")
    table.add_column("Change")
    table.add_column("Account (variation:site)", style="yellow")
    table.add_column("Detail")
    for item in delta["new"]:
        table.add_row("[green]+ NEW[/green]", item["key"], item.get("url", ""))
    for item in delta["gone"]:
        table.add_row("[red]- GONE[/red]", item["key"], item.get("url", ""))
    for item in delta["changed"]:
        before, after = item["before"], item["after"]
        detail = (
            f"{before['status']} ({before['confidence']}%) -> "
            f"{after['status']} ({after['confidence']}%)"
        )
        table.add_row("[yellow]~ CHANGED[/yellow]", item["key"], detail)
    console.print(table)


async def run_serve_command(args) -> None:
    from aliens_eye.mcp_server import serve

    await serve(args)


def run_tui_command(args) -> None:
    from aliens_eye.tui.app import run_tui

    run_tui(args)


async def run_label_command(args) -> None:
    from aliens_eye.ml.label import label_report

    await label_report(args)


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
        elif argv and argv[0] == "corpus":
            args = build_corpus_parser().parse_args(argv[1:])
            asyncio.run(run_corpus_command(args))
        elif argv and argv[0] == "eval":
            args = build_eval_parser().parse_args(argv[1:])
            asyncio.run(run_eval_command(args))
        elif argv and argv[0] == "diff":
            args = build_diff_parser().parse_args(argv[1:])
            run_diff_command(args)
        elif argv and argv[0] == "serve":
            args = build_serve_parser().parse_args(argv[1:])
            asyncio.run(run_serve_command(args))
        elif argv and argv[0] == "tui":
            args = build_tui_parser().parse_args(argv[1:])
            run_tui_command(args)
        elif argv and argv[0] == "label":
            args = build_label_parser().parse_args(argv[1:])
            asyncio.run(run_label_command(args))
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
