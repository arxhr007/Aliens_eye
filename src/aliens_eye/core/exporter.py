import csv
import json
from datetime import datetime
from html import escape as _esc
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.prompt import Prompt

from aliens_eye.utils.console import build_results_table, get_console

KNOWN_FORMATS = {
    "json", "csv", "html", "md", "markdown",
    "gexf", "maltego", "mermaid", "pdf", "all",
}

# Formats that need the correlation graph rather than the flat report.
GRAPH_FORMATS = {"gexf", "maltego", "mermaid"}


def _md_cell(value: Any) -> str:
    """Sanitize a value for use inside a Markdown table cell."""
    return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


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
        correlation: dict[str, Any] | None = None,
        domains: dict[str, Any] | None = None,
    ) -> list[Path]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_data = self._build_results_data(
            base_username, level, all_results, timestamp
        )
        if correlation is not None:
            results_data["correlation"] = correlation
        if domains is not None:
            results_data["domains"] = domains
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

        # Graph and PDF formats are opt-in only (not bundled into "all"), since
        # they are analysis artifacts rather than the standard document report.
        if "gexf" in formats:
            p = self.output_dir / f"{stem}.gexf"
            self._write_gexf(p, results_data)
            written.append(p)
        if "maltego" in formats:
            p = self.output_dir / f"{stem}_maltego.csv"
            self._write_maltego(p, results_data)
            written.append(p)
        if "mermaid" in formats:
            p = self.output_dir / f"{stem}.mmd"
            self._write_mermaid(p, results_data)
            written.append(p)
        if "pdf" in formats:
            p = self.output_dir / f"{stem}.pdf"
            if self._write_pdf(p, results_data):
                written.append(p)

        return written

    def report_dict(
        self,
        base_username: str,
        level: str,
        all_results: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Public accessor for the structured report (used for --json-stdout)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._build_results_data(base_username, level, all_results, timestamp)

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
                profile = info.get("ai_analysis", {}).get("signals", {}).get("profile", {})
                is_hit = info.get("status") in {"Found", "Maybe"}
                avatar_url = profile.get("avatar", "") if is_hit else ""
                avatar_cell = (
                    f"<img src='{_esc(avatar_url, quote=True)}' alt='' style='height:40px;border-radius:4px'>"
                    if avatar_url
                    else ""
                )
                name = _esc(profile.get("name", "")) if is_hit else ""
                bio = _esc(profile.get("bio", "")) if is_hit else ""
                url = info.get("url", "")
                rows.append(
                    f"<tr><td>{_esc(variation)}</td><td>{_esc(site)}</td>"
                    f"<td>{_esc(info.get('status',''))}</td>"
                    f"<td>{_esc(str(info.get('confidence',0)))}</td>"
                    f"<td>{_esc(str(info.get('code',0)))}</td>"
                    f"<td><a href='{_esc(url, quote=True)}'>{_esc(url)}</a></td>"
                    f"<td>{avatar_cell}</td><td>{name}</td><td>{bio}</td></tr>"
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
<p><strong>Base Username:</strong> {_esc(str(summary.get('base_username','')))}</p>
<p><strong>Scan Level:</strong> {_esc(str(summary.get('scan_level','')))}</p>
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
<th>Avatar</th>
<th>Name</th>
<th>Bio</th>
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
                    "| Site | Status | Confidence | HTTP | Name | Bio | URL |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
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
                profile = (
                    site_info.get("ai_analysis", {})
                    .get("signals", {})
                    .get("profile", {})
                )
                name = _md_cell(profile.get("name", ""))
                bio = _md_cell(profile.get("bio", ""))
                lines.append(
                    f"| {site} | {status} | {site_info.get('confidence', 0)}% | "
                    f"{site_info.get('code', 0)} | {name} | {bio} | {site_info.get('url', '')} |"
                )
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    # --- graph exports ----------------------------------------------------

    @staticmethod
    def _graph_model(results_data: dict[str, Any]) -> dict[str, Any]:
        """Build (nodes, edges) from Found/Maybe accounts + correlation clusters."""
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []
        variations = results_data.get("variations", {})
        for variation, block in variations.items():
            has_hit = False
            for site, info in (block.get("sites", {}) or {}).items():
                if info.get("status") not in {"Found", "Maybe"}:
                    continue
                has_hit = True
                acct = f"{variation}:{site}"
                nodes[acct] = {"label": site, "type": "account", "url": info.get("url", "")}
                edges.append({"source": variation, "target": acct, "label": "has-account"})
            if has_hit:
                nodes[variation] = {"label": variation, "type": "username", "url": ""}

        for cluster in results_data.get("correlation", {}).get("clusters", []):
            members = [m["variation"] + ":" + m["site"] for m in cluster.get("members", [])]
            reason = ",".join(cluster.get("reasons", [])) or "same-person"
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    if members[i] in nodes and members[j] in nodes:
                        edges.append({"source": members[i], "target": members[j], "label": reason})
        return {"nodes": nodes, "edges": edges}

    def _write_gexf(self, path: Path, results_data: dict[str, Any]) -> None:
        model = self._graph_model(results_data)
        ids = {name: str(i) for i, name in enumerate(model["nodes"])}
        node_xml = "".join(
            f'<node id="{ids[name]}" label="{_esc(data["label"], quote=True)}"/>'
            for name, data in model["nodes"].items()
        )
        edge_xml = "".join(
            f'<edge id="{i}" source="{ids[e["source"]]}" target="{ids[e["target"]]}" '
            f'label="{_esc(e["label"], quote=True)}"/>'
            for i, e in enumerate(model["edges"])
            if e["source"] in ids and e["target"] in ids
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gexf xmlns="http://gexf.net/1.3" version="1.3">\n'
            '<graph defaultedgetype="undirected">\n'
            f"<nodes>{node_xml}</nodes>\n<edges>{edge_xml}</edges>\n"
            "</graph>\n</gexf>\n"
        )
        path.write_text(xml, encoding="utf-8")

    def _write_maltego(self, path: Path, results_data: dict[str, Any]) -> None:
        model = self._graph_model(results_data)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["SourceEntity", "SourceType", "TargetEntity", "TargetType", "Relationship"])
            for e in model["edges"]:
                src = model["nodes"].get(e["source"], {})
                tgt = model["nodes"].get(e["target"], {})
                if not src or not tgt:
                    continue
                writer.writerow([
                    e["source"], "maltego.Affiliation" if src.get("type") == "account" else "maltego.Alias",
                    e["target"], "maltego.Affiliation" if tgt.get("type") == "account" else "maltego.Alias",
                    e["label"],
                ])

    def _write_mermaid(self, path: Path, results_data: dict[str, Any]) -> None:
        model = self._graph_model(results_data)
        ids = {name: f"n{i}" for i, name in enumerate(model["nodes"])}
        lines = ["```mermaid", "graph TD"]
        for name, data in model["nodes"].items():
            label = data["label"].replace('"', "'")
            shape = f'(["{label}"])' if data["type"] == "username" else f'["{label}"]'
            lines.append(f"    {ids[name]}{shape}")
        for e in model["edges"]:
            if e["source"] in ids and e["target"] in ids:
                lines.append(f"    {ids[e['source']]} -- {e['label']} --- {ids[e['target']]}")
        lines.append("```")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_pdf(self, path: Path, results_data: dict[str, Any]) -> bool:
        """Investigator PDF report. Returns False (with a note) if reportlab is missing."""
        try:
            from aliens_eye.core.pdf_report import write_pdf
        except ImportError:
            self.console.print(
                "[yellow]PDF export needs reportlab: pip install \"aliens-eye\\[pdf]\"[/yellow]"
            )
            return False
        write_pdf(path, results_data)
        return True

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
