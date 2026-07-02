"""Interactive terminal UI for browsing scan results (optional ``[tui]`` extra: textual).

The scan runs first (in plain mode so its progress does not fight the TUI), then a
Textual app presents a filterable, searchable table of every result. Keybindings:
``f`` toggle Found/Maybe only, ``/`` search, ``o`` open the selected URL in a
browser, ``q`` quit.
"""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from typing import Any


def _install_hint() -> None:
    from aliens_eye.utils.console import get_console

    get_console().print(
        "[yellow]The TUI needs Textual: pip install \"aliens-eye\\[tui]\"[/yellow]"
    )


def _flatten(all_results: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for variation, results in all_results.items():
        for r in results:
            profile = r.get("ai_analysis", {}).get("signals", {}).get("profile", {}) or {}
            rows.append({
                "variation": variation,
                "site": r.get("site", ""),
                "status": r.get("status", ""),
                "confidence": r.get("confidence", 0),
                "name": profile.get("name", ""),
                "url": r.get("url", ""),
            })
    rows.sort(key=lambda x: (x["status"] != "Found", x["status"] != "Maybe", -x["confidence"]))
    return rows


async def _scan(args) -> dict[str, list[dict[str, Any]]]:
    from aliens_eye.core.analyzer import FeatureExtractor
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.detector import Detector
    from aliens_eye.core.fingerprints import FingerprintStore
    from aliens_eye.core.scanner import UsernameScanner, load_sites_data
    from aliens_eye.utils.console import set_plain
    from aliens_eye.utils.logger import setup_logger

    set_plain(True)
    logger = setup_logger(False)
    config = ScannerConfig()
    sites_data = load_sites_data(Path(args.sites) if args.sites else None)
    detector = Detector()
    if not args.no_ml:
        detector.load_model(logger)
    extractor = FeatureExtractor()
    fingerprints = FingerprintStore(config.fingerprints_path, config.max_fingerprints_per_label)
    fingerprints.load(logger)
    scanner = UsernameScanner(
        sites_data=sites_data, config=config, extractor=extractor,
        detector=detector, fingerprints=fingerprints, logger=logger,
    )
    try:
        return await scanner.scan_with_variations(args.username, args.level)
    finally:
        fingerprints.save()


def run_tui(args) -> None:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Vertical
        from textual.widgets import DataTable, Footer, Header, Input
    except ImportError:
        _install_hint()
        return

    from aliens_eye.utils.console import get_console

    username = args.username or get_console().input("Enter username to scan: ").strip()
    if not username or len(username) < 2:
        get_console().print("[red]Invalid username.[/red]")
        return
    args.username = username

    all_results = asyncio.run(_scan(args))
    rows = _flatten(all_results)

    class ResultsApp(App):
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("f", "toggle_found", "Found/Maybe only"),
            ("o", "open_url", "Open URL"),
            ("slash", "focus_search", "Search"),
        ]
        CSS = "Input { dock: top; }"

        def __init__(self) -> None:
            super().__init__()
            self.found_only = False
            self.query_text = ""

        def compose(self) -> ComposeResult:
            yield Header()
            yield Vertical(
                Input(placeholder="Filter by site / name / url…", id="search"),
                DataTable(id="table"),
            )
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#table", DataTable)
            table.add_columns("Site", "Variation", "Status", "Conf", "Name", "URL")
            table.cursor_type = "row"
            self._refresh()

        def _visible(self) -> list[dict[str, Any]]:
            out = rows
            if self.found_only:
                out = [r for r in out if r["status"] in {"Found", "Maybe"}]
            if self.query_text:
                q = self.query_text.lower()
                out = [
                    r for r in out
                    if q in r["site"].lower() or q in str(r["name"]).lower() or q in r["url"].lower()
                ]
            return out

        def _refresh(self) -> None:
            table = self.query_one("#table", DataTable)
            table.clear()
            for r in self._visible():
                table.add_row(
                    r["site"], r["variation"], r["status"], f"{r['confidence']}%",
                    str(r["name"])[:30], r["url"],
                )
            found = sum(1 for r in rows if r["status"] == "Found")
            self.title = f"Aliens Eye — @{username}"
            self.sub_title = f"{found} found / {len(rows)} results" + (
                "  [Found/Maybe only]" if self.found_only else ""
            )

        def on_input_changed(self, event: Input.Changed) -> None:
            self.query_text = event.value
            self._refresh()

        def action_toggle_found(self) -> None:
            self.found_only = not self.found_only
            self._refresh()

        def action_focus_search(self) -> None:
            self.query_one("#search", Input).focus()

        def action_open_url(self) -> None:
            table = self.query_one("#table", DataTable)
            visible = self._visible()
            if 0 <= table.cursor_row < len(visible):
                webbrowser.open(visible[table.cursor_row]["url"])

    ResultsApp().run()
