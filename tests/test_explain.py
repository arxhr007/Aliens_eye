import asyncio
import io
import json
from types import SimpleNamespace

import pytest
import test_scanner
from rich.console import Console
from test_scanner import make_scanner, server_sites

from aliens_eye import cli
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import DetectionResult, Detector
from aliens_eye.core.explain import explanation_lines
from aliens_eye.core.exporter import ResultsExporter
from aliens_eye.core.http import FetchResult
from aliens_eye.utils.console import render_explanations

site_server = test_scanner.site_server


def test_detector_records_effective_parameters_without_changing_prediction(logger):
    detector = Detector()
    detector.load_model(logger)
    result = detector.predict({"http_200": 1.0, "meta_has_username": 1.0})
    details = result.diagnostics
    assert details["found_threshold"] == detector.model.found_threshold
    assert details["not_found_threshold"] == detector.model.not_found_threshold
    assert details["ml_weight"] == detector.model.ml_weight
    expected = details["ml_weight"] * details["ml_probability"]
    expected += (1 - details["ml_weight"]) * details["heuristic_probability"]
    assert round(expected, 4) == result.probability
    assert detector._status_from_probability(
        expected, details["found_threshold"], details["not_found_threshold"]
    ) == (result.status, result.confidence)


async def test_every_result_has_an_explanation(site_server, tmp_path, logger):
    scanner = make_scanner(server_sites(site_server), tmp_path, logger)
    results = await scanner.scan_all_sites("torvalds")
    for result in results:
        evidence = result["ai_analysis"]["explanation"]
        assert evidence["schema_version"] == 1
        assert evidence["final"]["status"] == result["status"]
        assert evidence["final"]["confidence"] == result["confidence"]
        json.dumps(evidence, allow_nan=False)
    found = next(r for r in results if r["status"] == "Found")
    assert found["ai_analysis"]["explanation"]["checks"]["control"]["outcome"] == "different"


@pytest.mark.parametrize("disabled", [False, True])
async def test_control_failure_is_not_called_verified(site_server, tmp_path, logger, disabled):
    scanner = make_scanner(server_sites(site_server), tmp_path, logger)
    scanner.config.control_check = not disabled
    real_fetch = scanner.fetch

    async def fetch(session, url, config, limiter, log):
        if "torvalds" not in url:
            raise RuntimeError("private failure detail")
        return await real_fetch(session, url, config, limiter, log)

    scanner.fetch = fetch
    result = next(r for r in await scanner.scan_all_sites("torvalds") if r["site"] == "alpha")
    assert result["status"] == "Found"
    evidence = result["ai_analysis"]["explanation"]
    assert evidence["checks"]["control"]["outcome"] == ("disabled" if disabled else "unavailable")
    assert "private failure detail" not in json.dumps(evidence)


async def test_identical_control_explanation(tmp_path, logger, found_html):
    scanner = fake_scanner(tmp_path, logger, found_html)
    scanner.config.control_check = True
    result = (await scanner.scan_all_sites("alice"))[0]
    evidence = result["ai_analysis"]["explanation"]
    assert evidence["checks"]["control"]["outcome"] == "same"
    assert "same_as_control" in evidence["reason_codes"]
    assert result["status"] == "Maybe"


async def test_control_reset_gets_fresh_observations(site_server, tmp_path, logger):
    scanner = make_scanner(server_sites(site_server), tmp_path, logger)
    calls = []
    real_fetch = scanner.fetch

    async def fetch(*args):
        calls.append(args[1])
        return await real_fetch(*args)

    scanner.fetch = fetch
    await scanner.scan_all_sites("torvalds")
    first = len(calls)
    scanner.reset_cycle()
    await scanner.scan_all_sites("torvalds")
    assert len(calls) == first * 2


def fake_scanner(tmp_path, logger, content="", status=200, error=None):
    scanner = make_scanner({"example": "https://example.test/{}"}, tmp_path, logger)
    scanner.config.control_check = False

    async def fetch(*args):
        return FetchResult(
            url="https://example.test/alice", final_url="https://example.test/alice",
            status=status, content=content, response_time=0.1, headers={},
            error=error, redirect_count=0,
        )

    scanner.fetch = fetch
    return scanner


@pytest.mark.parametrize("code,reason,expected", [
    (404, "http_gone", "Not Found"), (410, "http_gone", "Not Found"),
    (403, "http_error", "Maybe"), (500, "http_error", "Maybe"),
])
async def test_override_preserves_the_initial_verdict(tmp_path, logger, found_html, code, reason, expected):
    scanner = fake_scanner(tmp_path, logger, found_html, status=code)
    scanner.detector.predict = lambda _: DetectionResult("Found", 98, 50, "heuristic", 0.99)
    result = (await scanner.scan_all_sites("alice"))[0]
    evidence = result["ai_analysis"]["explanation"]
    assert evidence["initial_detector"]["status"] == "Found"
    assert evidence["final"]["status"] == expected
    assert evidence["final"]["override_reason"] == reason
    assert evidence["checks"]["http"]["code"] == code


@pytest.mark.parametrize("code,status", [(0, "Error"), (408, "Timeout")])
async def test_fetch_failure_is_explained_without_recording_private_details(tmp_path, logger, code, status):
    scanner = fake_scanner(tmp_path, logger, status=code, error="private request credentials")
    result = (await scanner.scan_all_sites("alice"))[0]
    evidence = result["ai_analysis"]["explanation"]
    assert evidence["final"]["status"] == status
    assert evidence["reason_codes"][0] == "fetch_error"
    assert evidence["detector"] is None
    assert "private request credentials" not in json.dumps(evidence)


async def test_extraction_failure_is_explained(tmp_path, logger):
    scanner = fake_scanner(tmp_path, logger)

    def fail(*args):
        raise ValueError("invalid markup")

    scanner.extractor.extract = fail
    result = (await scanner.scan_all_sites("alice"))[0]
    assert result["ai_analysis"]["explanation"]["reason_codes"] == ["extraction_error", "control_disabled"]
    assert result["status"] == "Error"


async def test_deadline_has_a_distinct_explanation_and_cancels_fetch(tmp_path, logger):
    scanner = fake_scanner(tmp_path, logger)
    cancelled = []

    async def fetch(*args):
        try:
            await asyncio.Future()
        finally:
            cancelled.append(True)

    scanner.fetch = fetch
    scanner._site_deadline = lambda: 0.01
    result = (await scanner.scan_all_sites("alice"))[0]
    assert result["ai_analysis"]["explanation"]["reason_codes"] == ["site_deadline"]
    assert cancelled == [True]


@pytest.mark.parametrize("outcome", ["selected", "retained_http", "unavailable"])
async def test_browser_evidence_labels_selected_source(tmp_path, logger, found_html, outcome):
    scanner = fake_scanner(tmp_path, logger, found_html)
    scanner.config.use_playwright = True
    initial = DetectionResult("Maybe", 60, 0, "heuristic", 0.5)
    second = DetectionResult("Found", 90, 10, "heuristic", 0.9) if outcome == "selected" else initial
    predictions = iter((initial, second))
    scanner.detector.predict = lambda _: next(predictions)

    async def render(url):
        if outcome == "unavailable":
            raise RuntimeError("browser failed")
        return found_html, url + "/rendered"

    scanner.browser_fallback = SimpleNamespace(fetch=render)
    result = (await scanner.scan_all_sites("alice"))[0]
    evidence = result["ai_analysis"]["explanation"]
    assert evidence["checks"]["browser"]["outcome"] == outcome
    assert evidence["initial_detector"]["source"] == "http"
    assert evidence["detector"]["source"] == ("rendered" if outcome == "selected" else "http")
    assert evidence["checks"]["http"]["source"] == "http"
    assert "code" not in evidence["checks"]["browser"]


def test_legacy_evidence_is_not_invented():
    assert explanation_lines({"ai_analysis": {"method": "ml+heuristic"}}) == ["Detailed evidence was not recorded."]


def test_explanation_config_and_cli_precedence():
    config = ScannerConfig()
    cli.apply_config(config, {"explain": False})
    cli.apply_cli_overrides(config, cli.build_parser().parse_args(["alice", "--explain"]))
    assert config.explain is True
    cli.apply_config(config, {"explain": True})
    cli.apply_cli_overrides(config, cli.build_parser().parse_args(["alice"]))
    assert config.explain is True


def test_explanation_renderers_escape_remote_text(tmp_path):
    info = {
        "site": "[red]example[/red]", "url": "https://example.test/alice",
        "status": "Found", "confidence": 90, "code": 200, "response_time": 0.1,
        "ai_analysis": {"explanation": {
            "schema_version": 1, "summary": "<script>bad()</script> [red]literal[/red]",
            "checks": {},
        }},
    }
    stream = io.StringIO()
    render_explanations(Console(file=stream, width=200), [info])
    assert "[red]literal[/red]" in stream.getvalue()
    files = ResultsExporter(tmp_path).save_results("alice", "basic", {"alice": [info]}, ["html", "md"])
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "<script>bad()" not in text
        assert "&lt;script&gt;" in text


def test_read_explain_shows_legacy_evidence_without_prompting(tmp_path, monkeypatch):
    from rich.prompt import Prompt

    def forbidden(*args, **kwargs):
        pytest.fail("--read --explain must display the evidence without an interactive prompt")

    monkeypatch.setattr(Prompt, "ask", forbidden)
    info = {
        "site": "example", "url": "https://example.test/alice",
        "status": "Found", "confidence": 90, "code": 200, "response_time": 0.1,
    }
    exporter = ResultsExporter(tmp_path, explain=True)
    path = exporter.save_results("alice", "basic", {"alice": [info]}, ["json"])[0]
    output = io.StringIO()
    exporter.console = Console(file=output, width=120)
    exporter.display_results_from_file(str(path))
    assert "Detailed evidence was not recorded" in output.getvalue()


def test_read_explain_rejects_malformed_nested_report(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"scan_summary": {}, "variations": {"alice": []}}), encoding="utf-8")
    exporter = ResultsExporter(tmp_path, explain=True)
    output = io.StringIO()
    exporter.console = Console(file=output)
    exporter.display_results_from_file(str(path))
    assert "expected nested report objects" in output.getvalue()
