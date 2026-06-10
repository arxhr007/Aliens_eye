import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.prompt import Prompt

from aliens_eye.utils.console import build_results_table, get_console

KNOWN_FORMATS = {"json", "csv", "html", "md", "markdown", "all"}


class ResultsExporter:
    """Save scan results in JSON, CSV, HTML, or Markdown formats."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.console = get_console()

    def save_results(
        self,
        base_username: str,
        level: str,
        all_results: dict[str, list[dict[str, Any]]],
        formats: list[str],
    ) -> list[Path]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_data = self._build_results_data(
            base_username, level, all_results, timestamp
        )
        written: list[Path] = []
        stem = f"{base_username}_{level}_{timestamp}"

        if "json" in formats or "all" in formats:
            json_path = self.output_dir / f"{stem}.json"
            with json_path.open("w", encoding="utf-8") as handle:
                json.dump(results_data, handle, indent=4)
            written.append(json_path)

        if "csv" in formats or "all" in formats:
            csv_path = self.output_dir / f"{stem}.csv"
            self._write_csv(csv_path, base_username, level, all_results)
            written.append(csv_path)

        if "html" in formats or "all" in formats:
            html_path = self.output_dir / f"{stem}.html"
            self._write_html(html_path, results_data)
            written.append(html_path)

        if "md" in formats or "markdown" in formats or "all" in formats:
            md_path = self.output_dir / f"{stem}.md"
            self._write_markdown(md_path, results_data)
            written.append(md_path)

        return written

    def _build_results_data(
        self,
        base_username: str,
        level: str,
        all_results: dict[str, list[dict[str, Any]]],
        timestamp: str,
    ) -> dict[str, Any]:
        variations_data: dict[str, Any] = {}
        scan_summary = {
            "base_username": base_username,
            "scan_level": level,
            "timestamp": timestamp,
            "total_variations": len(all_results),
            "total_sites_scanned": sum(len(results) for results in all_results.values()),
        }

        found_counts: dict[str, int] = {}
        high_confidence_matches: dict[str, int] = {}

        for username, results in all_results.items():
            found_counts[username] = sum(1 for r in results if r["status"] == "Found")
            high_confidence_matches[username] = sum(
                1
                for r in results
                if r.get("confidence", 0) >= 85 and r["status"] == "Found"
            )
            variations_data[username] = {
                "scan_info": {
                    "username": username,
                    "sites_scanned": len(results),
                    "found": found_counts[username],
                    "maybe": sum(1 for r in results if r["status"] == "Maybe"),
                    "not_found": sum(
                        1 for r in results if r["status"] == "Not Found"
                    ),
                    "errors": sum(
                        1
                        for r in results
                        if r["status"] not in {"Found", "Not Found", "Maybe"}
                    ),
                    "high_confidence_matches": high_confidence_matches[username],
                },
                "sites": {
                    r["site"]: {
                        "status": r["status"],
                        "code": r["code"],
                        "url": r["url"],
                        "final_url": r.get("final_url", ""),
                        "response_time": r["response_time"],
                        "confidence": r.get("confidence", 0),
                        "ai_analysis": r.get("ai_analysis", {}),
                    }
                    for r in results
                },
            }

        scan_summary["total_found"] = sum(found_counts.values())
        scan_summary["total_high_confidence"] = sum(high_confidence_matches.values())
        scan_summary["best_variations"] = sorted(
            found_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]

        return {"scan_summary": scan_summary, "variations": variations_data}

    def _write_csv(
        self,
        path: Path,
        base_username: str,
        level: str,
        all_results: dict[str, list[dict[str, Any]]],
    ) -> None:
        fieldnames = [
            "base_username",
            "variation",
            "site",
            "status",
            "confidence",
            "http_code",
            "url",
            "final_url",
            "response_time",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for variation, results in all_results.items():
                for item in results:
                    writer.writerow(
                        {
                            "base_username": base_username,
                            "variation": variation,
                            "site": item["site"],
                            "status": item["status"],
                            "confidence": item.get("confidence", 0),
                            "http_code": item.get("code", 0),
                            "url": item.get("url", ""),
                            "final_url": item.get("final_url", ""),
                            "response_time": item.get("response_time", 0),
                        }
                    )

    def _write_html(self, path: Path, results_data: dict[str, Any]) -> None:
        summary = results_data.get("scan_summary", {})
        variations = results_data.get("variations", {})

        rows = []
        for variation, data in variations.items():
            for site, info in data.get("sites", {}).items():
                rows.append(
                    f"<tr><td>{variation}</td><td>{site}</td><td>{info.get('status','')}</td>"
                    f"<td>{info.get('confidence',0)}</td><td>{info.get('code',0)}</td>"
                    f"<td><a href='{info.get('url','')}'>{info.get('url','')}</a></td></tr>"
                )

        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Aliens Eye Report</title>
<style>
body {{ font-family: Arial, sans-serif; padding: 20px; }}
summary, table {{ margin-top: 20px; }}

table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 12px; }}
th {{ background-color: #f2f2f2; text-align: left; }}
</style>
</head>
<body>
<h1>Aliens Eye Report</h1>
<p><strong>Base Username:</strong> {summary.get('base_username','')}</p>
<p><strong>Scan Level:</strong> {summary.get('scan_level','')}</p>
<p><strong>Total Variations:</strong> {summary.get('total_variations',0)}</p>
<p><strong>Total Sites Scanned:</strong> {summary.get('total_sites_scanned',0)}</p>
<p><strong>Total Found:</strong> {summary.get('total_found',0)}</p>
<p><strong>Total High Confidence:</strong> {summary.get('total_high_confidence',0)}</p>

<table>
<thead>
<tr>
<th>Variation</th>
<th>Site</th>
<th>Status</th>
<th>Confidence</th>
<th>HTTP Code</th>
<th>URL</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body>
</html>
"""
        with path.open("w", encoding="utf-8") as handle:
            handle.write(html)

    def _write_markdown(self, path: Path, results_data: dict[str, Any]) -> None:
        summary = results_data.get("scan_summary", {})
        variations = results_data.get("variations", {})

        lines = [
            "# Aliens Eye Report",
            "",
            f"- **Base username:** `{summary.get('base_username', '')}`",
            f"- **Scan level:** {summary.get('scan_level', '')}",
            f"- **Timestamp:** {summary.get('timestamp', '')}",
            f"- **Variations scanned:** {summary.get('total_variations', 0)}",
            f"- **Sites scanned:** {summary.get('total_sites_scanned', 0)}",
            f"- **Total found:** {summary.get('total_found', 0)}",
            f"- **High confidence:** {summary.get('total_high_confidence', 0)}",
            "",
        ]

        for variation, data in variations.items():
            info = data.get("scan_info", {})
            lines.extend(
                [
                    f"## `{variation}`",
                    "",
                    f"Found: {info.get('found', 0)} | Maybe: {info.get('maybe', 0)} | "
                    f"Not Found: {info.get('not_found', 0)} | Errors: {info.get('errors', 0)}",
                    "",
                    "| Site | Status | Confidence | HTTP | URL |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            sites = sorted(
                data.get("sites", {}).items(),
                key=lambda item: (
                    {"Found": 0, "Maybe": 1}.get(item[1].get("status", ""), 2),
                    -item[1].get("confidence", 0),
                ),
            )
            for site, site_info in sites:
                status = site_info.get("status", "")
                if status not in {"Found", "Maybe"}:
                    continue
                lines.append(
                    f"| {site} | {status} | {site_info.get('confidence', 0)}% | "
                    f"{site_info.get('code', 0)} | {site_info.get('url', '')} |"
                )
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    def display_results_from_file(self, file_path: str) -> None:
        try:
            with open(file_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            self.console.print(f"[red]File not found: {file_path}[/red]")
            return
        except json.JSONDecodeError:
            self.console.print(f"[red]Invalid JSON file: {file_path}[/red]")
            return

        if "scan_summary" not in data or "variations" not in data:
            self.console.print(f"[red]Unrecognized results file: {file_path}[/red]")
            return

        summary = data["scan_summary"]
        body = (
            f"[blue]Base username:[/blue] [bold yellow]{summary.get('base_username', 'Unknown')}[/bold yellow]\n"
            f"[blue]Scan level:[/blue] {summary.get('scan_level', 'Unknown')}\n"
            f"[blue]Variations:[/blue] {summary.get('total_variations', 0)}    "
            f"[blue]Sites scanned:[/blue] {summary.get('total_sites_scanned', 0)}\n"
            f"[bold green]Found: {summary.get('total_found', 0)}[/bold green]    "
            f"[green]High confidence: {summary.get('total_high_confidence', 0)}[/green]"
        )
        self.console.print(Panel(body, title="Scan Results", border_style="green"))

        best = summary.get("best_variations", [])
        if best:
            self.console.print("[blue]Best variations:[/blue]")
            for username, count in best:
                self.console.print(f"  [yellow]{username}[/yellow]: [green]{count} profiles found[/green]")

        names = list(data["variations"].keys())
        self.console.print("\n[blue]Available variations:[/blue]")
        for i, username in enumerate(names, 1):
            self.console.print(f"  {i}. [yellow]{username}[/yellow]")

        choice = Prompt.ask(
            "\nEnter number for details ('all' for all, Enter to exit)",
            default="",
            console=self.console,
        ).strip()
        if choice.lower() == "all":
            for username, variation_data in data["variations"].items():
                self._display_variation_results(username, variation_data)
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                self._display_variation_results(names[idx], data["variations"][names[idx]])

    def _display_variation_results(self, username: str, variation_data: dict[str, Any]) -> None:
        scan_info = variation_data.get("scan_info", {})
        body = (
            f"[bold green]Found: {scan_info.get('found', 0)}[/bold green]   "
            f"[yellow]Maybe: {scan_info.get('maybe', 0)}[/yellow]   "
            f"[red]Not Found: {scan_info.get('not_found', 0)}[/red]   "
            f"[dim]Errors: {scan_info.get('errors', 0)}[/dim]"
        )
        self.console.print(Panel(body, title=f"Variation: {username}", border_style="blue"))

        rows = [
            {
                "site": site,
                "status": info.get("status", "Unknown"),
                "confidence": info.get("confidence", 0),
                "code": info.get("code", 0),
                "url": info.get("url", ""),
                "response_time": info.get("response_time", 0),
            }
            for site, info in variation_data.get("sites", {}).items()
        ]
        rows.sort(
            key=lambda r: (
                {"Found": 0, "Maybe": 1, "Not Found": 2}.get(r["status"], 3),
                -r["confidence"],
            )
        )
        self.console.print(build_results_table(rows))
