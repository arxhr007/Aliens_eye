import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from rich.console import Console
from test_report import result

from aliens_eye import cli
from aliens_eye.core import watch
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.exporter import ResultsExporter
from aliens_eye.core.watch_state import StateError, WatchStore, scope_key


async def test_watch_resume_is_rejected_before_checkpoint_or_scan(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.jsonl"
    path.write_text("keep me", encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid watch options must fail before setup")

    monkeypatch.setattr(cli, "prepare_sites", forbidden)
    args = cli.build_parser().parse_args(["alice", "--watch", "1h", "--resume", str(path)])
    with pytest.raises(ValueError, match="resume"):
        await cli.run_scan(args)
    assert path.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize("value", ["0", "-1", "bad"])
async def test_invalid_confirmation_count_is_rejected(value):
    with pytest.raises((ValueError, SystemExit)):
        args = cli.build_parser().parse_args(["alice", "--watch", "1h", "--watch-confirmations", value])
        await cli.run_scan(args)


class FakeScanner:
    def __init__(self, sequence):
        self.sequence = sequence
        self.cycles = 0
        self.calls = []
        self.config = ScannerConfig()
        self.detector = SimpleNamespace(model=None)
        self.sites_data = {"example": "https://example.test/{}"}

    def reset_cycle(self):
        self.cycles += 1

    async def scan_with_variations(self, username, level):
        self.calls.append((username, level))
        return {username: [{"site": "example", "response_time": 0.1, **self.sequence[self.cycles - 1]}]}


async def watch_cycles(tmp_path, monkeypatch, logger, sequence, *, only_found=False, usernames=None, **kwargs):
    scanner = FakeScanner(sequence)
    notifications = []
    output = io.StringIO()

    async def sleep(_interval):
        if scanner.cycles >= len(sequence):
            raise asyncio.CancelledError

    async def notify(url, payload, log):
        notifications.append(payload)

    monkeypatch.setattr(watch.asyncio, "sleep", sleep)
    monkeypatch.setattr(watch, "_notify", notify)
    exporter = ResultsExporter(tmp_path, only_found=only_found)
    with pytest.raises(asyncio.CancelledError):
        await watch.run_watch(
            scanner, exporter, usernames or ["alice"], "basic", ["csv"], 1,
            logger, Console(file=output), tmp_path, notify_url="https://example.test/hook", **kwargs,
        )
    return scanner, notifications, output.getvalue()


async def test_watch_failures_are_not_alerts_and_state_ignores_output_filter(tmp_path, monkeypatch, logger):
    scanner, notifications, output = await watch_cycles(
        tmp_path, monkeypatch, logger,
        [result(), result("Timeout", 408), result(), result("Not Found", 404), result("Not Found", 404)],
        only_found=True,
    )
    assert scanner.cycles == len(scanner.calls) == 5
    assert len(notifications) == 1
    assert notifications[0]["gone"] == ["alice:example"]
    assert notifications[0]["new"] == []
    assert "profile_changes" not in notifications[0]
    assert notifications[0]["schema_version"] == 2
    assert "no absence inferred" in output
    assert not list(tmp_path.glob("*.json"))
    assert len(list((tmp_path / ".watch").glob("*.json"))) == 1
    key = scope_key(scanner, "alice", "basic", 2, ())
    with WatchStore(tmp_path, key) as store:
        assert store.load().entries["alice:example"]["kind"] == "absent"


async def test_watch_json_lines_and_independent_usernames(tmp_path, monkeypatch, logger, capsys):
    scanner, notifications, _ = await watch_cycles(
        tmp_path, monkeypatch, logger, [result(), result("Error", 0), result()],
        usernames=["alice", "bob"], json_stdout=True,
    )
    lines = capsys.readouterr().out.splitlines()
    reports = [json.loads(line) for line in lines]
    assert len(reports) == 6
    assert [r["scan_summary"]["base_username"] for r in reports] == ["alice", "bob"] * 3
    assert scanner.cycles == 3
    assert notifications == []
    assert len(list((tmp_path / ".watch").glob("*.json"))) == 2


async def test_watch_profile_alert_is_confirmed_and_not_replayed(tmp_path, monkeypatch, logger):
    _, notifications, _ = await watch_cycles(
        tmp_path, monkeypatch, logger,
        [result(), result(name="Alice Smith"), result(name="Alice Smith")],
        profile_fields=("name",),
    )
    assert len(notifications) == 1
    assert notifications[0]["profile_changes"][0]["after"] == "Alice Smith"
    _, notifications, _ = await watch_cycles(
        tmp_path, monkeypatch, logger, [result(name="Alice Smith")], profile_fields=("name",),
    )
    assert notifications == []


async def test_invalid_watch_state_stops_before_scanning(tmp_path, logger):
    scanner = FakeScanner([result()])
    key = scope_key(scanner, "alice", "basic", 2, ())
    with WatchStore(tmp_path, key) as store:
        store.path.write_text("broken", encoding="utf-8")
    with pytest.raises(StateError):
        await watch.run_watch(
            scanner, ResultsExporter(tmp_path), ["alice"], "basic", ["json"], 1,
            logger, Console(file=io.StringIO()), tmp_path,
        )
    assert scanner.calls == []
    with WatchStore(tmp_path, key):
        pass


@pytest.mark.parametrize("status", [204, 302, 400, 500])
async def test_webhook_checks_response_and_closes_it(monkeypatch, logger, caplog, status):
    calls = []

    class Response:
        async def __aenter__(self):
            self.status = status
            return self

        async def __aexit__(self, *args):
            calls.append("closed")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            return Response()

    monkeypatch.setattr(watch.aiohttp, "ClientSession", Session)
    await watch._notify("https://example.test/secret-token", {}, logger)
    assert calls == ["closed"]
    assert ("Webhook notify failed" in caplog.text) == (status != 204)
    assert "secret-token" not in caplog.text


async def test_webhook_failure_does_not_leak_url_or_stop_monitor(monkeypatch, logger, caplog):
    def fail():
        raise TimeoutError("https://example.test/secret-token")

    monkeypatch.setattr(watch.aiohttp, "ClientSession", fail)
    await watch._notify("https://example.test/secret-token", {}, logger)
    assert "TimeoutError" in caplog.text
    assert "secret-token" not in caplog.text


@pytest.mark.parametrize("flags", [
    ["--watch-profile", "name"], ["--watch-confirmations", "2"],
    ["--watch", "1h", "--watch-profile", "name,name"],
    ["--watch", "1h", "--watch-profile", "invalid"],
    ["--watch", "1h", "--notify", "file:///not-a-webhook"],
])
async def test_watch_options_are_validated_before_setup(flags, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("options must be validated before setup")

    monkeypatch.setattr(cli, "prepare_sites", forbidden)
    with pytest.raises(ValueError):
        await cli.run_scan(cli.build_parser().parse_args(["alice", *flags]))
