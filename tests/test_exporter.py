import csv
import json

import pytest

from aliens_eye.core.exporter import ResultsExporter


@pytest.fixture
def results():
    return {
        "alice": [
            {
                "site": "github",
                "url": "https://github.com/alice",
                "final_url": "https://github.com/alice",
                "status": "Found",
                "code": 200,
                "response_time": 0.5,
                "confidence": 95,
                "ai_analysis": {"method": "ml+heuristic"},
            },
            {
                "site": "reddit",
                "url": "https://reddit.com/user/alice",
                "final_url": "https://reddit.com/user/alice",
                "status": "Not Found",
                "code": 404,
                "response_time": 0.3,
                "confidence": 90,
                "ai_analysis": {},
            },
        ],
        "alice_": [
            {
                "site": "github",
                "url": "https://github.com/alice_",
                "final_url": "https://github.com/alice_",
                "status": "Maybe",
                "code": 200,
                "response_time": 0.4,
                "confidence": 60,
                "ai_analysis": {},
            },
        ],
    }


def test_save_all_formats(tmp_path, results):
    exporter = ResultsExporter(tmp_path)
    written = exporter.save_results("alice", "basic", results, ["all"])
    suffixes = {p.suffix for p in written}
    assert suffixes == {".json", ".csv", ".html", ".md"}
    for path in written:
        assert path.exists()


def test_json_structure(tmp_path, results):
    exporter = ResultsExporter(tmp_path)
    written = exporter.save_results("alice", "basic", results, ["json"])
    data = json.loads(written[0].read_text(encoding="utf-8"))
    summary = data["scan_summary"]
    assert summary["base_username"] == "alice"
    assert summary["total_variations"] == 2
    assert summary["total_sites_scanned"] == 3
    assert summary["total_found"] == 1
    assert summary["total_high_confidence"] == 1
    assert data["variations"]["alice"]["scan_info"]["found"] == 1
    assert data["variations"]["alice"]["scan_info"]["not_found"] == 1


def test_csv_rows(tmp_path, results):
    exporter = ResultsExporter(tmp_path)
    written = exporter.save_results("alice", "basic", results, ["csv"])
    rows = list(csv.DictReader(written[0].open(encoding="utf-8")))
    assert len(rows) == 3
    assert rows[0]["base_username"] == "alice"
    assert {r["variation"] for r in rows} == {"alice", "alice_"}


def test_markdown_contains_found_and_maybe_only(tmp_path, results):
    exporter = ResultsExporter(tmp_path)
    written = exporter.save_results("alice", "basic", results, ["md"])
    text = written[0].read_text(encoding="utf-8")
    assert "# Aliens Eye Report" in text
    assert "https://github.com/alice" in text
    assert "| github | Found | 95% |" in text
    assert "| reddit |" not in text
    assert "Not Found: 1" in text


def test_markdown_format_alias(tmp_path, results):
    exporter = ResultsExporter(tmp_path)
    written = exporter.save_results("alice", "basic", results, ["markdown"])
    assert written and written[0].suffix == ".md"


def test_html_contains_rows(tmp_path, results):
    exporter = ResultsExporter(tmp_path)
    written = exporter.save_results("alice", "basic", results, ["html"])
    text = written[0].read_text(encoding="utf-8")
    assert "<td>github</td>" in text
    assert "https://github.com/alice" in text
