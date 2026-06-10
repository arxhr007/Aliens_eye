import aiohttp
import pytest
from aioresponses import aioresponses

from aliens_eye.core.analyzer import FeatureExtractor
from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.fingerprints import FingerprintStore
from aliens_eye.core.scanner import UsernameScanner, build_connector

SITES = {
    "alpha": "https://alpha.example/{}",
    "beta": "https://beta.example/users/{}",
}


@pytest.fixture
def scanner(tmp_path, logger):
    config = ScannerConfig(
        retries=0,
        rate_limit_delay=0.0,
        output_dir=tmp_path / "results",
        fingerprints_path=tmp_path / "fp.json",
        plain_output=True,
    )
    return UsernameScanner(
        sites_data=dict(SITES),
        config=config,
        extractor=FeatureExtractor(),
        detector=Detector(),
        fingerprints=FingerprintStore(config.fingerprints_path),
        logger=logger,
    )


async def test_scan_all_sites_mocked(scanner, found_html, not_found_html):
    with aioresponses() as mocked:
        mocked.get("https://alpha.example/torvalds", status=200, body=found_html)
        mocked.get("https://beta.example/users/torvalds", status=404, body=not_found_html)
        results = await scanner.scan_all_sites("torvalds")

    assert len(results) == 2
    by_site = {r["site"]: r for r in results}
    assert by_site["alpha"]["status"] == "Found"
    assert by_site["alpha"]["code"] == 200
    assert by_site["beta"]["status"] == "Not Found"
    assert by_site["beta"]["code"] == 404
    for r in results:
        assert set(r) >= {"site", "url", "status", "code", "confidence", "ai_analysis"}


async def test_scan_handles_connection_error(scanner):
    with aioresponses() as mocked:
        mocked.get(
            "https://alpha.example/ghost",
            exception=aiohttp.ClientConnectionError("refused"),
        )
        mocked.get("https://beta.example/users/ghost", status=200, body="<html></html>")
        results = await scanner.scan_all_sites("ghost")

    by_site = {r["site"]: r for r in results}
    assert by_site["alpha"]["status"] == "Error"


async def test_scan_with_variations_basic(scanner, found_html):
    with aioresponses() as mocked:
        mocked.get("https://alpha.example/torvalds", status=200, body=found_html)
        mocked.get("https://beta.example/users/torvalds", status=200, body=found_html)
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
