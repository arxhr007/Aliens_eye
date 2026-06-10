import socket

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.fingerprints import FingerprintStore
from aliens_eye.core.scanner import UsernameScanner, build_connector


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def site_server(found_html, not_found_html):
    app = web.Application()

    async def alpha(request):
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
