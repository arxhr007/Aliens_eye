"""Fetching attacker-chosen URLs: every hop and the connected address are checked."""

import socket
import urllib.error
import urllib.request

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aliens_eye.core import netguard


@pytest.fixture
async def redirector():
    """One loopback server. Reached as ``localhost`` it plays the public site;
    reached as ``127.0.0.1`` it plays the internal service a redirect aims at."""
    hits = {"secret": 0}
    app = web.Application()

    async def to_internal(request):
        raise web.HTTPFound(f"http://127.0.0.1:{request.url.port}/secret")

    async def to_public(request):
        raise web.HTTPFound("/ok")

    async def loop(request):
        raise web.HTTPFound("/loop")

    async def secret(request):
        hits["secret"] += 1
        return web.Response(text="internal data")

    async def ok(request):
        return web.Response(text="fine")

    app.router.add_get("/to-internal", to_internal)
    app.router.add_get("/to-public", to_public)
    app.router.add_get("/loop", loop)
    app.router.add_get("/secret", secret)
    app.router.add_get("/ok", ok)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    server.hits = hits
    yield server
    await server.close()


@pytest.fixture
def only_localhost_is_public(monkeypatch):
    async def fake(host):
        return host == "localhost"

    monkeypatch.setattr(netguard, "host_is_public", fake)


def ipv4_session():
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET))


async def test_redirect_to_an_internal_address_is_not_followed(redirector, only_localhost_is_public):
    """Regression: the guard checked the first URL, then the client followed 302s."""
    async with ipv4_session() as session:
        with pytest.raises(netguard.GuardError):
            await netguard.guarded_get(session, f"http://localhost:{redirector.port}/to-internal")
    assert redirector.hits["secret"] == 0


async def test_redirect_to_a_public_address_is_followed(redirector, only_localhost_is_public):
    async with ipv4_session() as session:
        response = await netguard.guarded_get(session, f"http://localhost:{redirector.port}/to-public")
    assert response.body == b"fine"
    assert response.redirects == 1
    assert response.final_url.endswith("/ok")


async def test_redirect_loops_are_cut_off(redirector, only_localhost_is_public):
    async with ipv4_session() as session:
        with pytest.raises(netguard.GuardError, match="too many redirects"):
            await netguard.guarded_get(session, f"http://localhost:{redirector.port}/loop")


async def test_first_hop_is_checked_too(redirector, only_localhost_is_public):
    async with ipv4_session() as session:
        with pytest.raises(netguard.GuardError):
            await netguard.guarded_get(session, f"http://127.0.0.1:{redirector.port}/secret")
    assert redirector.hits["secret"] == 0


async def test_allow_private_lifts_the_check(redirector):
    async with ipv4_session() as session:
        response = await netguard.guarded_get(
            session, f"http://127.0.0.1:{redirector.port}/secret", allow_private=True
        )
    assert response.body == b"internal data"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x/", "", "http://"])
async def test_non_http_urls_are_never_fetchable(url):
    assert await netguard.is_public_url(url) is False
    assert await netguard.is_public_url(url, allow_private=True) is False
    assert netguard.is_public_url_sync(url, allow_private=True) is False


@pytest.mark.parametrize("address,public", [
    ("8.8.8.8", True),
    ("127.0.0.1", False),
    ("10.1.2.3", False),
    ("192.168.0.1", False),
    ("169.254.169.254", False),
    ("::1", False),
    ("fe80::1", False),
    ("not-an-ip", False),
])
def test_is_public_ip(address, public):
    assert netguard.is_public_ip(address) is public


class FakeResolver:
    def __init__(self, hosts):
        self.hosts = hosts

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [{"hostname": host, "host": h, "port": port, "family": family, "proto": 0, "flags": 0}
                for h in self.hosts]

    async def close(self):
        pass


async def test_resolver_passes_public_answers():
    resolver = netguard.PublicOnlyResolver(FakeResolver(["8.8.8.8", "1.1.1.1"]))
    assert [r["host"] for r in await resolver.resolve("example.com")] == ["8.8.8.8", "1.1.1.1"]


@pytest.mark.parametrize("answers", [["127.0.0.1"], ["8.8.8.8", "10.0.0.1"], []])
async def test_resolver_refuses_any_private_answer(answers):
    """One private answer among public ones is how DNS rebinding gets in."""
    resolver = netguard.PublicOnlyResolver(FakeResolver(answers))
    with pytest.raises(OSError):
        await resolver.resolve("evil.example")


def test_sync_opener_refuses_private_redirects():
    handler = netguard._GuardedRedirects(allow_private=False)
    request = urllib.request.Request("https://8.8.8.8/a.png")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/secret")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(request, None, 302, "Found", {}, "file:///etc/passwd")


def test_sync_fetch_refuses_before_opening(monkeypatch):
    opened = []
    monkeypatch.setattr(urllib.request.OpenerDirector, "open",
                        lambda self, req, *a, **k: opened.append(req))
    for url in ("file:///etc/passwd", "http://127.0.0.1/x", "http://169.254.169.254/"):
        assert netguard.guarded_urlopen_bytes(url) is None
    assert opened == []


@pytest.mark.parametrize("url,reason", [
    ("http://127.0.0.1/x", "non-public"),
    ("http://no-such-host.invalid/", "does not resolve"),
    ("file:///etc/passwd", "not an http(s) address"),
])
async def test_refusals_say_why(url, reason):
    """A dead domain and a blocked private address need different responses."""
    assert reason in await netguard.refusal_reason(url)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(netguard.GuardError, match=reason.replace("(", r"\(").replace(")", r"\)")):
            await netguard.guarded_get(session, url)
