"""--json-stdout and --only-found: what the scan actually writes.

Before 2.7.3 --json-stdout only silenced the banner; no scan ever wrote its JSON,
and --only-found was read from the command line and then ignored.
"""

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aliens_eye import cli


@pytest.fixture
async def fake_sites(tmp_path, found_html, not_found_html):
    """alpha knows only `torvalds`; beta is a site that answers 404 for everyone."""
    app = web.Application()

    async def alpha(request):
        if request.match_info["u"] != "torvalds":
            return web.Response(text=not_found_html, status=404, content_type="text/html")
        return web.Response(text=found_html, content_type="text/html")

    async def beta(request):
        return web.Response(text=not_found_html, status=404, content_type="text/html")

    app.router.add_get("/alpha/{u}", alpha)
    app.router.add_get("/beta/{u}", beta)
    server = TestServer(app)
    await server.start_server()
    base = f"http://{server.host}:{server.port}"
    sites = tmp_path / "sites.json"
    sites.write_text(json.dumps({"alpha": base + "/alpha/{}", "beta": base + "/beta/{}"}), encoding="utf-8")
    yield sites
    await server.close()


async def run(sites, out, *extra):
    args = cli.build_parser().parse_args([
        "-l", "basic", "--profile", "full", "--sites", str(sites), "--output", str(out),
        "--retries", "0", *extra,
    ])
    await cli.run_scan(args)


def stdout_lines(capsys):
    captured = capsys.readouterr()
    return [line for line in captured.out.splitlines() if line.strip()], captured.err


async def test_json_stdout_writes_the_report_as_one_json_line(fake_sites, tmp_path, capsys):
    await run(fake_sites, tmp_path / "out", "--json-stdout", "torvalds")
    lines, err = stdout_lines(capsys)
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert report["scan_summary"]["base_username"] == "torvalds"
    assert report["variations"]["torvalds"]["sites"]["alpha"]["status"] == "Found"
    assert report["variations"]["torvalds"]["sites"]["beta"]["status"] == "Not Found"


async def test_stdout_carries_nothing_but_the_json(fake_sites, tmp_path, capsys):
    """The banner, progress bar and summary go to stderr, so `| jq` and json.load work."""
    await run(fake_sites, tmp_path / "out", "--json-stdout", "torvalds")
    lines, err = stdout_lines(capsys)
    assert len(lines) == 1 and lines[0].startswith("{") and lines[0].endswith("}")
    assert "Scan Summary" in err and "lxask" not in lines[0]


async def test_each_username_is_its_own_line(fake_sites, tmp_path, capsys):
    await run(fake_sites, tmp_path / "out", "--json-stdout", "torvalds", "nobody_here")
    lines, _ = stdout_lines(capsys)
    reports = [json.loads(line) for line in lines]
    assert [r["scan_summary"]["base_username"] for r in reports] == ["torvalds", "nobody_here"]


async def test_the_output_is_ascii_safe(fake_sites, tmp_path, capsys):
    """A Windows console in a legacy code page must not fail on a name with accents."""
    await run(fake_sites, tmp_path / "out", "--json-stdout", "josé")
    lines, _ = stdout_lines(capsys)
    assert json.loads(lines[0])["scan_summary"]["base_username"] == "josé"
    assert lines[0].isascii()


async def test_files_are_still_written_alongside(fake_sites, tmp_path, capsys):
    await run(fake_sites, tmp_path / "out", "--json-stdout", "torvalds")
    assert len(list((tmp_path / "out").glob("*.json"))) == 1


async def test_a_normal_scan_prints_no_json(fake_sites, tmp_path, capsys):
    await run(fake_sites, tmp_path / "out", "--plain", "torvalds")
    out = capsys.readouterr().out
    assert '"scan_summary"' not in out and "Scan Summary" in out


async def test_no_username_means_no_output_not_a_prompt(fake_sites, tmp_path, capsys, monkeypatch):
    """A script asking for JSON must never be left waiting on a question."""
    def no_prompt(*args, **kwargs):
        raise AssertionError("asked for a username in --json-stdout mode")

    monkeypatch.setattr(cli.Prompt, "ask", no_prompt)
    await run(fake_sites, tmp_path / "out", "--json-stdout")
    assert stdout_lines(capsys)[0] == []


# --- --only-found ---------------------------------------------------------------------------


async def test_only_found_lists_just_found_and_maybe_sites(fake_sites, tmp_path, capsys):
    await run(fake_sites, tmp_path / "out", "--json-stdout", "--only-found", "torvalds")
    lines, _ = stdout_lines(capsys)
    report = json.loads(lines[0])
    assert set(report["variations"]["torvalds"]["sites"]) == {"alpha"}


async def test_only_found_keeps_the_true_totals(fake_sites, tmp_path, capsys):
    """Dropping Not Found rows from the list must not make it look like fewer sites were scanned."""
    await run(fake_sites, tmp_path / "out", "--json-stdout", "--only-found", "torvalds")
    report = json.loads(stdout_lines(capsys)[0][0])
    info = report["variations"]["torvalds"]["scan_info"]
    assert info["sites_scanned"] == 2 and info["not_found"] == 1 and info["found"] == 1
    assert report["scan_summary"]["total_sites_scanned"] == 2
    assert report["scan_summary"]["only_found"] is True


async def test_without_only_found_every_site_is_listed(fake_sites, tmp_path, capsys):
    await run(fake_sites, tmp_path / "out", "--json-stdout", "torvalds")
    report = json.loads(stdout_lines(capsys)[0][0])
    assert set(report["variations"]["torvalds"]["sites"]) == {"alpha", "beta"}
    assert "only_found" not in report["scan_summary"]


async def test_only_found_also_applies_to_the_saved_files(fake_sites, tmp_path, capsys):
    out = tmp_path / "out"
    await run(fake_sites, out, "--only-found", "--format", "json,csv", "torvalds")
    saved = json.loads(next(out.glob("*.json")).read_text("utf-8"))
    assert set(saved["variations"]["torvalds"]["sites"]) == {"alpha"}
    rows = next(out.glob("*.csv")).read_text("utf-8").splitlines()
    assert len(rows) == 2 and ",alpha," in rows[1]          # header + the one Found site


async def test_correlation_is_included_when_asked_for(fake_sites, tmp_path, capsys, monkeypatch):
    async def fake_correlate(report, **kwargs):
        return {"clusters": [], "profiles_considered": 1, "avatar_hashing": False}

    monkeypatch.setattr("aliens_eye.core.correlate.correlate_report", fake_correlate)
    await run(fake_sites, tmp_path / "out", "--json-stdout", "--correlate", "torvalds")
    report = json.loads(stdout_lines(capsys)[0][0])
    assert report["correlation"]["profiles_considered"] == 1


def test_only_found_keeps_maybe_results_and_drops_the_rest(tmp_path):
    from aliens_eye.core.exporter import ResultsExporter

    def entry(site, status):
        return {"site": site, "status": status, "code": 200, "url": f"https://{site}.test/u",
                "response_time": 0.1, "confidence": 60}

    results = {"someone": [entry("a", "Found"), entry("b", "Maybe"), entry("c", "Not Found"),
                           entry("d", "Error"), entry("e", "Timeout")]}
    report = ResultsExporter(tmp_path, only_found=True).report_dict("someone", "basic", results)
    assert set(report["variations"]["someone"]["sites"]) == {"a", "b"}
    assert report["variations"]["someone"]["scan_info"]["sites_scanned"] == 5
    everything = ResultsExporter(tmp_path).report_dict("someone", "basic", results)
    assert set(everything["variations"]["someone"]["sites"]) == {"a", "b", "c", "d", "e"}
