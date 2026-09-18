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
    from aliens_eye import api

    # stdio carries the MCP protocol, so nothing may reach stdout.
    return await api.scan(
        username,
        level,
        sites=api.load_sites(path=Path(sites) if sites else None),
        use_ml=not no_ml,
        quiet=True,
    )


async def serve(args) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        from aliens_eye.utils.console import get_console

        get_console().print(
            "[yellow]The MCP server needs the mcp package: pip install \"aliens-eye\\[serve]\"[/yellow]"
        )
        return

    from aliens_eye.utils.console import set_plain

    # stdout carries the MCP protocol for the life of the process; route any
    # stray console output to stderr so nothing can corrupt the stream.
    set_plain(True, stderr=True)

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
        from aliens_eye import api

        return await api.correlate(report)

    @mcp.tool()
    def read_report(path: str) -> dict[str, Any]:
        """Load a previously saved Aliens Eye report JSON from disk."""
        from aliens_eye.core.report import ReportError, load_report

        try:
            return load_report(path)
        except ReportError as exc:
            return {"error": str(exc)}

    await mcp.run_stdio_async()
