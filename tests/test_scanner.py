import socket

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.fingerprints import FingerprintStore
from aliens_eye.core.scanner import UsernameScanner, build_connector, format_site_url


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def site_server(found_html, not_found_html):
    app = web.Application()

    async def alpha(request):
        # A site that knows its users: anyone else gets its "no such user" page.
        if request.match_info["username"] not in {"torvalds", "ghost"}:
            return web.Response(text=not_found_html, status=404, content_type="text/html")
        return web.Response(text=found_html, content_type="text/html")

    async def beta(request):
        return web.Response(text=not_found_html, status=404, content_type="text/html")

    app.router.add_get("/alpha/{username}", alpha)
    app.router.add_get("/beta/users/{username}", beta)
    server = TestServer(app)
    await server.start_server()
    yield server
    await server.close()


def make_scanner(sites, tmp_path, logger):
    config = ScannerConfig(
        retries=0,
        rate_limit_delay=0.0,
        output_dir=tmp_path / "results",
        fingerprints_path=tmp_path / "fp.json",
        plain_output=True,
    )
    return UsernameScanner(
        sites_data=sites,
        config=config,
        extractor=FeatureExtractor(),
        detector=Detector(),
        fingerprints=FingerprintStore(config.fingerprints_path),
        logger=logger,
    )


def server_sites(server):
    base = f"http://{server.host}:{server.port}"
    return {
        "alpha": base + "/alpha/{}",
        "beta": base + "/beta/users/{}",
    }


async def test_scan_all_sites_end_to_end(site_server, tmp_path, logger):
    scanner = make_scanner(server_sites(site_server), tmp_path, logger)
    results = await scanner.scan_all_sites("torvalds")

    assert len(results) == 2
    by_site = {r["site"]: r for r in results}
    assert by_site["alpha"]["status"] == "Found"
    assert by_site["alpha"]["code"] == 200
    assert by_site["beta"]["status"] == "Not Found"
    assert by_site["beta"]["code"] == 404
    for r in results:
        assert set(r) >= {"site", "url", "status", "code", "confidence", "ai_analysis"}


async def test_scan_handles_connection_error(site_server, tmp_path, logger):
    sites = server_sites(site_server)
    sites["dead"] = f"http://127.0.0.1:{free_port()}/{{}}"
    scanner = make_scanner(sites, tmp_path, logger)
    results = await scanner.scan_all_sites("ghost")

    by_site = {r["site"]: r for r in results}
    assert by_site["dead"]["status"] in {"Error", "Timeout"}
    assert by_site["alpha"]["status"] == "Found"


async def test_scan_with_variations_basic(site_server, tmp_path, logger):
    scanner = make_scanner(server_sites(site_server), tmp_path, logger)
    all_results = await scanner.scan_with_variations("torvalds", "basic")

    assert list(all_results) == ["torvalds"]
    assert len(all_results["torvalds"]) == 2


def test_format_url_fallbacks():
    assert (
        UsernameScanner._format_url("x", "https://x.com/{}", "bob") == "https://x.com/bob"
    )
    assert (
        UsernameScanner._format_url("x", "https://x.com/{user}", "bob")
        == "https://x.com/bob"
    )


def test_format_site_url_percent_encodes_non_ascii():
    url = format_site_url("weibo", "https://weibo.com/{}", "坦途")
    assert url == "https://weibo.com/%E5%9D%A6%E9%80%94"
    assert "坦途" not in url


def test_format_site_url_leaves_ascii_handles_unchanged():
    assert format_site_url("x", "https://x.com/{}", "bob_dev-99") == "https://x.com/bob_dev-99"


def test_format_site_url_encodes_special_characters():
    url = format_site_url("x", "https://x.com/{}", "a b@c")
    assert url == "https://x.com/a%20b%40c"


async def test_build_connector_tcp():
    config = ScannerConfig()
    connector = build_connector(config, 5)
    assert isinstance(connector, aiohttp.TCPConnector)
    await connector.close()


async def test_build_connector_socks():
    from aiohttp_socks import ProxyConnector

    config = ScannerConfig(proxy="socks5://127.0.0.1:9050")
    connector = build_connector(config, 5)
    assert isinstance(connector, ProxyConnector)
    await connector.close()


async def test_build_connector_http_proxy_uses_tcp():
    config = ScannerConfig(proxy="http://127.0.0.1:8080")
    connector = build_connector(config, 5)
    assert isinstance(connector, aiohttp.TCPConnector)
    await connector.close()


# --- bot-wall cap ---------------------------------------------------------

from aliens_eye.core.scanner import _looks_like_bot_wall  # noqa: E402


@pytest.mark.parametrize("title", [
    "Just a moment...",
    "Checking your browser",
    "Attention Required! | Cloudflare",
    "Access Denied",
    "500 Internal Server Error",
    "Verify you are human",
])
def test_challenge_and_error_titles_are_bot_walls(title):
    assert _looks_like_bot_wall({"title": title, "meta_samples": []})


def test_challenge_text_in_meta_tags_counts():
    assert _looks_like_bot_wall({"title": "example.com", "meta_samples": ["Please complete the CAPTCHA"]})


@pytest.mark.parametrize("signals", [
    {"title": "torvalds (Linus Torvalds) - Profile", "meta_samples": ["followers and posts"]},
    {"title": "", "meta_samples": []},
    {"title": None},
    {},
])
def test_ordinary_pages_are_not_bot_walls(signals):
    assert not _looks_like_bot_wall(signals)


async def test_a_challenge_page_is_capped_at_maybe(found_html, tmp_path, logger):
    """A 200 page with profile wording but a challenge title must not be Found.

    Seen live: pcgamer served "Checking your browser" for every username, real
    or made up, and each one was reported as a found account.
    """
    app = web.Application()
    challenge = found_html.replace(
        "<title>torvalds (Linus Torvalds) - Profile</title>",
        "<title>Checking your browser</title>",
    )
    assert challenge != found_html

    async def page(request):
        return web.Response(text=challenge, content_type="text/html")

    app.router.add_get("/u/{username}", page)
    server = TestServer(app)
    await server.start_server()
    try:
        sites = {"walled": f"http://{server.host}:{server.port}/u/{{}}"}
        [result] = await make_scanner(sites, tmp_path, logger).scan_all_sites("torvalds")
    finally:
        await server.close()

    assert result["status"] == "Maybe"
    assert result["confidence"] <= 55
    # The suffix is only added when the uncapped verdict was Found, so this also
    # proves the cap is what changed the result.
    assert result["ai_analysis"]["method"].endswith("-botwall-capped")


async def test_a_cancelled_scan_leaves_no_workers_behind(tmp_path, logger):
    """Regression: cancelling a scan (a caller's timeout) left its workers pending forever."""
    import asyncio

    app = web.Application()

    async def stall(request):
        await asyncio.sleep(30)
        return web.Response(text="late")

    app.router.add_get("/slow/{username}", stall)
    server = TestServer(app)
    await server.start_server()
    try:
        base = f"http://{server.host}:{server.port}"
        scanner = make_scanner({f"s{i}": base + "/slow/{}" for i in range(4)}, tmp_path, logger)
        before = asyncio.all_tasks()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(scanner.scan_all_sites("torvalds"), 0.3)
        await asyncio.sleep(0.05)
        left = [t for t in asyncio.all_tasks() - before if "_worker" in repr(t.get_coro())]
        assert left == []
    finally:
        await server.close()


async def test_one_site_that_never_answers_cannot_hold_up_the_scan(site_server, tmp_path, logger):
    """A real scan sat on its last request for half an hour. Whatever the cause
    inside one site's check, the scan moves on after a bounded wait."""
    import asyncio

    from aliens_eye.core.http import fetch_url

    scanner = make_scanner(server_sites(site_server), tmp_path, logger)
    scanner.config.timeout = 0.2
    scanner.config.backoff_cap = 0.0

    async def fetch(session, url, config, rate_limiter, log):
        if "/beta/" in url:
            await asyncio.sleep(3600)      # ignores every timeout the HTTP layer has
        return await fetch_url(session, url, config, rate_limiter, log)

    scanner.fetch = fetch
    results = await asyncio.wait_for(scanner.scan_all_sites("torvalds"), 10)
    by_site = {r["site"]: r for r in results}
    assert by_site["alpha"]["status"] == "Found"
    assert by_site["beta"]["status"] == "Timeout" and by_site["beta"]["code"] == 408
