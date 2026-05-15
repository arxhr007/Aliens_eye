import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from utils.colors import COLORS


class ResultsExporter:
    """Save scan results in JSON, CSV, or HTML formats."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_results(
        self,
        base_username: str,
        level: str,
        all_results: Dict[str, List[Dict[str, Any]]],
        formats: List[str],
    ) -> List[Path]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_data = self._build_results_data(
            base_username, level, all_results, timestamp
        )
        written: List[Path] = []

        if "json" in formats or "all" in formats:
            json_path = self.output_dir / f"{base_username}_{level}_{timestamp}.json"
            with json_path.open("w", encoding="utf-8") as handle:
                json.dump(results_data, handle, indent=4)
            written.append(json_path)

        if "csv" in formats or "all" in formats:
            csv_path = self.output_dir / f"{base_username}_{level}_{timestamp}.csv"
            self._write_csv(csv_path, base_username, level, all_results)
            written.append(csv_path)

        if "html" in formats or "all" in formats:
            html_path = self.output_dir / f"{base_username}_{level}_{timestamp}.html"
            self._write_html(html_path, results_data)
            written.append(html_path)

        return written

    def _build_results_data(
        self,
        base_username: str,
        level: str,
        all_results: Dict[str, List[Dict[str, Any]]],
        timestamp: str,
    ) -> Dict[str, Any]:
        variations_data: Dict[str, Any] = {}
        scan_summary = {
            "base_username": base_username,
            "scan_level": level,
            "timestamp": timestamp,
            "total_variations": len(all_results),
            "total_sites_scanned": sum(len(results) for results in all_results.values()),
        }

        found_counts: Dict[str, int] = {}
        high_confidence_matches: Dict[str, int] = {}

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
        all_results: Dict[str, List[Dict[str, Any]]],
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

    def _write_html(self, path: Path, results_data: Dict[str, Any]) -> None:
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

    def display_results_from_file(self, file_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)

            if "scan_summary" in data and "variations" in data:
                summary = data["scan_summary"]
                print(f"{COLORS['green']}{'=' * 90}")
                print(
                    f"{COLORS['blue']}SCAN RESULTS SUMMARY: "
                    f"{COLORS['yellow']}{summary.get('base_username', 'Unknown')}"
                )
                print(
                    f"{COLORS['blue']}Scan level: {COLORS['white']}"
                    f"{summary.get('scan_level', 'Unknown')}"
                )
                print(
                    f"{COLORS['blue']}Total Variations: {COLORS['white']}"
                    f"{summary.get('total_variations', 0)}"
                )
                print(
                    f"{COLORS['blue']}Total Sites Scanned: {COLORS['white']}"
                    f"{summary.get('total_sites_scanned', 0)}"
                )
                print(
                    f"{COLORS['blue']}Total Found: {COLORS['green']}"
                    f"{summary.get('total_found', 0)}"
                )
                print(
                    f"{COLORS['blue']}Total High Confidence: {COLORS['green']}"
                    f"{summary.get('total_high_confidence', 0)}"
                )
                print(f"{COLORS['green']}{'=' * 90}")
                print(f"{COLORS['blue']}Best Variations:")
                for username, count in summary.get("best_variations", []):
                    print(
                        f"{COLORS['yellow']}{username}: {COLORS['green']}{count} profiles found"
                    )
                print(f"{COLORS['green']}{'=' * 90}")
                print(f"{COLORS['blue']}Available variations:")
                for i, username in enumerate(data["variations"].keys(), 1):
                    print(f"{COLORS['white']}{i}. {COLORS['yellow']}{username}")

                choice = input(
                    f"\n{COLORS['green']}Enter number to see details (or 'all' for all, or press Enter to exit): {COLORS['yellow']}"
                )
                if choice.lower() == "all":
                    for username, variation_data in data["variations"].items():
                        self._display_variation_results(username, variation_data)
                elif choice.isdigit():
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(data["variations"]):
                        username = list(data["variations"].keys())[choice_idx]
                        self._display_variation_results(
                            username, data["variations"][username]
                        )
                return

            scan_info = data.get("scan_info", {})
            print(f"{COLORS['green']}{'=' * 90}")
            print(
                f"{COLORS['blue']}SCAN RESULTS: {COLORS['yellow']}"
                f"{scan_info.get('username', 'Unknown')}"
            )
            print(
                f"{COLORS['blue']}Date: {COLORS['white']}"
                f"{scan_info.get('timestamp', 'Unknown')}"
            )
            print(
                f"{COLORS['blue']}Sites Scanned: {COLORS['white']}"
                f"{scan_info.get('sites_scanned', 0)}"
            )
            print(
                f"{COLORS['blue']}Found: {COLORS['green']}"
                f"{scan_info.get('found', 0)} | "
                f"{COLORS['blue']}Maybe: {COLORS['yellow']}"
                f"{scan_info.get('maybe', 0)} | "
                f"{COLORS['blue']}Not Found: {COLORS['red']}"
                f"{scan_info.get('not_found', 0)} | "
                f"{COLORS['blue']}Errors: {COLORS['red']}"
                f"{scan_info.get('errors', 0)}"
            )
            high_conf = scan_info.get("high_confidence_matches", 0)
            if high_conf > 0:
                print(
                    f"{COLORS['blue']}High Confidence Matches: {COLORS['green']}{high_conf}"
                )
            print(f"{COLORS['green']}{'=' * 90}")
            self._print_table_header()

            def sort_key(item):
                status_priority = {"Found": 0, "Maybe": 1, "Not Found": 2}.get(
                    item[1].get("status", ""), 3
                )
                confidence = item[1].get("confidence", 0)
                return (-confidence, status_priority)

            sorted_sites = sorted(data.get("sites", {}).items(), key=sort_key)
            for site_name, info in sorted_sites:
                status = info.get("status", "Unknown")
                code = info.get("code", 0)
                url = info.get("url", "")
                response_time = info.get("response_time", 0)
                confidence = info.get("confidence", 0)
                if status == "Found":
                    status_color = COLORS["green"]
                elif status == "Maybe":
                    status_color = COLORS["yellow"]
                else:
                    status_color = COLORS["red"]
                code_color = COLORS["green"] if code == 200 else COLORS["red"]
                url_color = status_color
                display_site = site_name[:20]
                confidence_str = f" ({confidence}%)" if confidence > 0 else ""
                print(
                    f"{COLORS['green']}# {COLORS['yellow']}{display_site:20}{COLORS['white']}| "
                    f"{status_color}{status:10}{confidence_str:8}{COLORS['white']}| "
                    f"{code_color}{str(code):^10}{COLORS['white']}| "
                    f"{url_color}{url}{COLORS['reset']} "
                    f"({response_time:.2f}s)"
                )
            print(f"{COLORS['green']}{'=' * 90}{COLORS['reset']}")
        except FileNotFoundError:
            print(f"{COLORS['red']}File not found: {file_path}{COLORS['reset']}")
        except json.JSONDecodeError:
            print(f"{COLORS['red']}Invalid JSON file: {file_path}{COLORS['reset']}")
        except Exception as exc:
            print(f"{COLORS['red']}Error reading file: {exc}{COLORS['reset']}")

    def _display_variation_results(self, username: str, variation_data: Dict[str, Any]) -> None:
        scan_info = variation_data.get("scan_info", {})
        print(f"{COLORS['green']}{'=' * 90}")
        print(
            f"{COLORS['blue']}SCAN RESULTS FOR VARIATION: {COLORS['yellow']}{username}"
        )
        print(
            f"{COLORS['blue']}Found: {COLORS['green']}"
            f"{scan_info.get('found', 0)} | "
            f"{COLORS['blue']}Maybe: {COLORS['yellow']}"
            f"{scan_info.get('maybe', 0)} | "
            f"{COLORS['blue']}Not Found: {COLORS['red']}"
            f"{scan_info.get('not_found', 0)} | "
            f"{COLORS['blue']}Errors: {COLORS['red']}"
            f"{scan_info.get('errors', 0)}"
        )
        high_conf = scan_info.get("high_confidence_matches", 0)
        if high_conf > 0:
            print(
                f"{COLORS['blue']}High Confidence Matches: {COLORS['green']}{high_conf}"
            )
        print(f"{COLORS['green']}{'=' * 90}")
        self._print_table_header()

        def sort_key(item):
            site_info = item[1]
            status_priority = {"Found": 0, "Maybe": 1, "Not Found": 2}.get(
                site_info.get("status", ""), 3
            )
            confidence = site_info.get("confidence", 0)
            return (-confidence, status_priority)

        sites = variation_data.get("sites", {})
        sorted_sites = sorted(sites.items(), key=sort_key)
        for site_name, info in sorted_sites:
            status = info.get("status", "Unknown")
            code = info.get("code", 0)
            url = info.get("url", "")
            response_time = info.get("response_time", 0)
            confidence = info.get("confidence", 0)
            if status == "Found":
                status_color = COLORS["green"]
            elif status == "Maybe":
                status_color = COLORS["yellow"]
            else:
                status_color = COLORS["red"]
            code_color = COLORS["green"] if code == 200 else COLORS["red"]
            url_color = status_color
            display_site = site_name[:20]
            confidence_str = f" ({confidence}%)" if confidence > 0 else ""
            print(
                f"{COLORS['green']}# {COLORS['yellow']}{display_site:20}{COLORS['white']}| "
                f"{status_color}{status:10}{confidence_str:8}{COLORS['white']}| "
                f"{code_color}{str(code):^10}{COLORS['white']}| "
                f"{url_color}{url}{COLORS['reset']} "
                f"({response_time:.2f}s)"
            )
        print(f"{COLORS['green']}{'=' * 90}{COLORS['reset']}")

    def _print_table_header(self) -> None:
        print(
            f"{COLORS['blue']}# {COLORS['yellow']}{'SITE':20}{COLORS['blue']}| "
            f"{COLORS['yellow']}{'STATUS + CONFIDENCE':18}{COLORS['blue']}| "
            f"{COLORS['yellow']}{'HTTP CODE':10}{COLORS['blue']}| "
            f"{COLORS['yellow']}URL (RESPONSE TIME){COLORS['reset']}"
        )
        print(f"{COLORS['green']}{'#' * 90}{COLORS['reset']}")
