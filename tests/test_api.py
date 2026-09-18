"""The public programmatic API: shape, progress hook, isolation and delegation."""

import pytest
from test_scanner import server_sites, site_server  # noqa: F401 - fixture re-export

from aliens_eye import api


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Keep every test out of the real user cache."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(api, "_cache_root", lambda: cache)
    return cache


async def test_scan_returns_a_report_shaped_dict(site_server):  # noqa: F811
    report = await api.scan("torvalds", sites=server_sites(site_server))

    assert report["scan_summary"]["base_username"] == "torvalds"
    assert report["scan_summary"]["scan_level"] == "basic"
    sites = report["variations"]["torvalds"]["sites"]
    assert sites["alpha"]["status"] == "Found"
    assert sites["beta"]["status"] == "Not Found"


async def test_on_result_is_called_once_per_site(site_server):  # noqa: F811
    seen = []
    await api.scan(
        "torvalds",
        sites=server_sites(site_server),
        on_result=lambda username, result: seen.append((username, result["site"])),
    )
    assert sorted(seen) == [("torvalds", "alpha"), ("torvalds", "beta")]


async def test_async_on_result_is_awaited(site_server):  # noqa: F811
    seen = []

    async def hook(username, result):
        seen.append(result["site"])

    await api.scan("torvalds", sites=server_sites(site_server), on_result=hook)
    assert sorted(seen) == ["alpha", "beta"]


async def test_a_failing_hook_does_not_kill_the_scan(site_server):  # noqa: F811
    def hook(username, result):
        raise RuntimeError("UI went away")

    report = await api.scan("torvalds", sites=server_sites(site_server), on_result=hook)
    assert report["variations"]["torvalds"]["sites"]["alpha"]["status"] == "Found"


async def test_scan_does_not_write_into_the_callers_cwd(site_server, tmp_path, monkeypatch):  # noqa: F811
    """A library call must not litter ./results wherever the caller happens to be."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    await api.scan("torvalds", sites=server_sites(site_server))
    assert not (work / "results").exists()


async def test_quiet_scan_prints_nothing(site_server, capsys):  # noqa: F811
    await api.scan("torvalds", sites=server_sites(site_server))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("username", ["", " ", "a", None])
async def test_scan_rejects_bad_usernames(username):
    with pytest.raises(ValueError, match="username"):
        await api.scan(username, sites={})


async def test_scan_rejects_unknown_levels():
    with pytest.raises(ValueError, match="level"):
        await api.scan("torvalds", "extreme", sites={})


async def test_correlate_passes_the_private_avatar_flag_through(monkeypatch):
    captured = {}

    async def fake_correlate_report(report, **kwargs):
        captured.update(kwargs)
        return {"clusters": []}

    import aliens_eye.core.correlate as correlate_mod

    monkeypatch.setattr(correlate_mod, "correlate_report", fake_correlate_report)
    await api.correlate({"variations": {}})
    assert captured["allow_private_avatars"] is False
    await api.correlate({"variations": {}}, allow_private_avatars=True)
    assert captured["allow_private_avatars"] is True


def test_load_sites_can_exclude_nsfw():
    from aliens_eye.core.scanner import load_nsfw_sites

    everything = api.load_sites()
    safe = api.load_sites(exclude_nsfw=True)
    nsfw = set(load_nsfw_sites())
    assert len(safe) < len(everything)
    assert not (set(safe) & nsfw)


async def test_mcp_scan_delegates_to_the_api(monkeypatch):
    """The MCP server and the API must not drift apart: one implementation."""
    from aliens_eye import mcp_server

    calls = {}

    async def fake_scan(username, level, **kwargs):
        calls.update(username=username, level=level, **kwargs)
        return {"ok": True}

    monkeypatch.setattr(api, "scan", fake_scan)
    result = await mcp_server._run_scan("torvalds", "basic", None, no_ml=True)
    assert result == {"ok": True}
    assert calls["username"] == "torvalds"
    assert calls["use_ml"] is False
    assert calls["quiet"] is True


async def test_quiet_scan_does_not_silence_the_global_console(site_server):  # noqa: F811
    """Regression: an early version flipped the process-wide console to quiet,
    so one library call silenced every later Aliens Eye print in the process."""
    from aliens_eye.utils.console import get_console

    before = get_console()
    await api.scan("torvalds", sites=server_sites(site_server))
    after = get_console()
    assert after is before
    assert not after.quiet
