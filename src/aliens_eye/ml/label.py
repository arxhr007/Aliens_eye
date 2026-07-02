"""Active-learning loop: hand-label uncertain results and grow the dataset.

Reads a saved report, walks the low-confidence band (Maybe by default), and asks
you to confirm each hit. Confirmed labels are vectorized from the features already
stored in the report and appended to a training CSV, so a later ``train fit`` can
learn from your corrections.
"""

from __future__ import annotations

from aliens_eye.core.features import vectorize_features
from aliens_eye.core.report import ReportError, iter_sites, load_report
from aliens_eye.ml.collect import write_rows
from aliens_eye.utils.console import get_console
from aliens_eye.utils.logger import setup_logger


async def label_report(args) -> None:
    from pathlib import Path

    from rich.prompt import Prompt

    console = get_console()
    logger = setup_logger(getattr(args, "verbose", False))
    try:
        report = load_report(args.report)
    except ReportError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    band = (args.band or "Maybe").lower()
    statuses = {"found", "maybe", "not found"} if band == "all" else {"maybe"}

    candidates = [
        (variation, site, info)
        for variation, site, info in iter_sites(report)
        if info.get("status", "").lower() in statuses
    ]
    if not candidates:
        console.print(f"[yellow]No '{band}' results to label in {args.report}.[/yellow]")
        return

    console.print(
        f"[blue]Labeling {len(candidates)} result(s).[/blue] "
        "[dim]y = exists, n = does not exist, s = skip, q = quit[/dim]\n"
    )

    rows: list[list[float]] = []
    for variation, site, info in candidates:
        features = info.get("ai_analysis", {}).get("features")
        if not isinstance(features, dict) or not features:
            continue
        profile = info.get("ai_analysis", {}).get("signals", {}).get("profile", {})
        name = profile.get("name", "")
        console.print(
            f"[yellow]{site}[/yellow] / [bold]{variation}[/bold]  "
            f"status={info.get('status')} conf={info.get('confidence', 0)}%  "
            f"{info.get('url', '')}"
            + (f"\n  [dim]name: {name}[/dim]" if name else "")
        )
        choice = Prompt.ask("  label", choices=["y", "n", "s", "q"], default="s", console=console)
        if choice == "q":
            break
        if choice == "s":
            continue
        label = 1 if choice == "y" else 0
        rows.append(vectorize_features(features) + [float(label)])

    if not rows:
        console.print("[dim]No labels recorded.[/dim]")
        return

    write_rows(Path(args.out), rows, append=True)
    console.print(f"[green]Appended {len(rows)} labeled sample(s) -> {args.out}[/green]")
    logger.info("Appended %d samples to %s", len(rows), args.out)
