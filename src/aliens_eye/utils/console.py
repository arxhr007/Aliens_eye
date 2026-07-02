"""Rich-based terminal rendering for scans and reports."""

from __future__ import annotations

import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

_console: Console | None = None

STATUS_STYLES = {
    "Found": "bold green",
    "Maybe": "yellow",
    "Not Found": "red",
    "Error": "dim red",
    "Timeout": "dim red",
    "Unknown": "dim",
}


def get_console(plain: bool = False) -> Console:
    global _console
    if _console is None:
        no_color = plain or not sys.stdout.isatty()
        _console = Console(no_color=no_color, highlight=False)
    return _console


def set_plain(plain: bool, stderr: bool = False) -> None:
    global _console
    no_color = plain or not sys.stdout.isatty()
    # Route rich output to stderr so stdout can carry machine-readable JSON.
    _console = Console(no_color=no_color, highlight=False, stderr=stderr)


def status_text(status: str, confidence: int = 0) -> Text:
    style = STATUS_STYLES.get(status, "dim")
    label = f"{status} ({confidence}%)" if confidence > 0 else status
    return Text(label, style=style)


class ScanView:
    """Progress bar during a scan plus final result table and summary panel."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or get_console()
        self._progress: Progress | None = None
        self._task_id = None

    def start(self, username: str, total: int) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("[green]{task.fields[found]} found[/green]"),
            console=self.console,
            transient=False,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(
            f"Scanning [bold yellow]{username}[/bold yellow]", total=total, found=0
        )

    def advance(self, found_count: int) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, advance=1, found=found_count)

    def stop(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task_id = None

    def render_results(self, results: list[dict[str, Any]], max_rows: int = 0) -> None:
        interesting = [r for r in results if r["status"] in {"Found", "Maybe"}]
        interesting.sort(
            key=lambda r: (
                0 if r["status"] == "Found" else 1,
                -r.get("confidence", 0),
            )
        )
        if max_rows:
            interesting = interesting[:max_rows]
        if not interesting:
            self.console.print("[dim]No profiles found.[/dim]")
            return
        self.console.print(build_results_table(interesting))

    def render_summary(self, results: list[dict[str, Any]], elapsed: float) -> None:
        found = sum(1 for r in results if r["status"] == "Found")
        maybe = sum(1 for r in results if r["status"] == "Maybe")
        not_found = sum(1 for r in results if r["status"] == "Not Found")
        errors = len(results) - found - maybe - not_found
        body = (
            f"[bold green]Found: {found}[/bold green]   "
            f"[yellow]Maybe: {maybe}[/yellow]   "
            f"[red]Not Found: {not_found}[/red]   "
            f"[dim]Errors: {errors}[/dim]\n"
            f"[blue]Scanned {len(results)} sites in {elapsed:.1f}s[/blue]"
        )
        self.console.print(Panel(body, title="Scan Summary", border_style="green"))


def build_results_table(results: list[dict[str, Any]], title: str | None = None) -> Table:
    table = Table(title=title, header_style="bold blue", border_style="dim")
    table.add_column("Site", style="yellow", no_wrap=True)
    table.add_column("Status")
    table.add_column("HTTP", justify="center")
    table.add_column("Name", overflow="ellipsis", max_width=24)
    table.add_column("URL", overflow="fold")
    table.add_column("Time", justify="right")
    for r in results:
        code = r.get("code", 0)
        name = (
            r.get("ai_analysis", {})
            .get("signals", {})
            .get("profile", {})
            .get("name", "")
        )
        table.add_row(
            str(r.get("site", ""))[:30],
            status_text(r.get("status", "Unknown"), r.get("confidence", 0)),
            Text(str(code), style="green" if code == 200 else "red"),
            str(name)[:24],
            r.get("url", ""),
            f"{r.get('response_time', 0):.2f}s",
        )
    return table
