"""MCP server exposing Aliens Eye as tools for LLM agents (optional ``[serve]`` extra: mcp).

Runs over stdio and exposes:
- ``scan_username`` — scan a username across all sites, return the structured report
- ``correlate`` — run cross-site correlation over a report and return clusters
- ``read_report`` — load a previously saved report JSON from disk

Start it with ``aliens_eye serve`` and point an MCP client (e.g. Claude) at the
command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def _run_scan(username: str, level: str, sites: str | None, no_ml: bool) -> dict[str, Any]:
    from aliens_eye.core.analyzer import FeatureExtractor
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.detector import Detector
    from aliens_eye.core.exporter import ResultsExporter
    from aliens_eye.core.fingerprints import FingerprintStore
    from aliens_eye.core.scanner import UsernameScanner, load_sites_data
    from aliens_eye.utils.console import set_plain
    from aliens_eye.utils.logger import setup_logger

    set_plain(True, stderr=True)
    logger = setup_logger(False)
    config = ScannerConfig()
    sites_data = load_sites_data(Path(sites) if sites else None)
    detector = Detector()
    if not no_ml:
        detector.load_model(logger)
    extractor = FeatureExtractor()
    fingerprints = FingerprintStore(config.fingerprints_path, config.max_fingerprints_per_label)
    fingerprints.load(logger)
    scanner = UsernameScanner(
        sites_data=sites_data, config=config, extractor=extractor,
        detector=detector, fingerprints=fingerprints, logger=logger,
    )
    try:
        all_results = await scanner.scan_with_variations(username, level)
    finally:
        fingerprints.save()
    return ResultsExporter(config.output_dir).report_dict(username, level, all_results)


async def serve(args) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        from aliens_eye.utils.console import get_console

        get_console().print(
            "[yellow]The MCP server needs the mcp package: pip install \"aliens-eye\\[serve]\"[/yellow]"
        )
        return

    sites = getattr(args, "sites", None)
    no_ml = getattr(args, "no_ml", False)
    mcp = FastMCP("aliens-eye")

    @mcp.tool()
    async def scan_username(username: str, level: str = "basic") -> dict[str, Any]:
        """Scan a username across all known sites. level: basic|intermediate|advanced."""
        if not username or len(username) < 2:
            return {"error": "username must be at least 2 characters"}
        if level not in {"basic", "intermediate", "advanced"}:
            level = "basic"
        return await _run_scan(username, level, sites, no_ml)

    @mcp.tool()
    async def correlate(report: dict[str, Any]) -> dict[str, Any]:
        """Cluster the profiles in a scan report that look like the same person."""
        from aliens_eye.core.correlate import correlate_report

        return await correlate_report(report)

    @mcp.tool()
    def read_report(path: str) -> dict[str, Any]:
        """Load a previously saved Aliens Eye report JSON from disk."""
        from aliens_eye.core.report import ReportError, load_report

        try:
            return load_report(path)
        except ReportError as exc:
            return {"error": str(exc)}

    await mcp.run_stdio_async()
