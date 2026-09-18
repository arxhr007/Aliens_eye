"""Body reading: the whole page, not whatever happened to arrive first."""

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.http import fetch_url
from aliens_eye.core.rate_limit import DomainRateLimiter

HEAD = "<html><head><title>t</title>" + "<!-- padding -->" * 3000  # ~48 KB of head
TAIL = '<meta property="og:image" content="https://cdn.example/me.png"></head><body>ok</body></html>'


@pytest.fixture
async def dribble_server():
    """Sends the body in several chunks with pauses between them.

    That is the condition real servers produce, and the one where a single
    StreamReader.read(n) returns only the first chunk.
    """
    app = web.Application()

    async def dribble(request):
        response = web.StreamResponse(headers={"Content-Type": "text/html; charset=utf-8"})
        await response.prepare(request)
        body = (HEAD + TAIL).encode()
        for start in range(0, len(body), 8192):
            await response.write(body[start:start + 8192])
            await asyncio.sleep(0.01)
        await response.write_eof()
        return response

    app.router.add_get("/page", dribble)
    server = TestServer(app)
    await server.start_server()
    yield server
    await server.close()


async def test_fetch_reads_past_the_first_chunk(dribble_server, logger):
    """Regression: og: tags beyond the first network chunk were silently lost."""
    config = ScannerConfig(retries=0, rate_limit_delay=0.0)
    async with aiohttp.ClientSession() as session:
        result = await fetch_url(
            session, f"http://{dribble_server.host}:{dribble_server.port}/page",
            config, DomainRateLimiter(), logger,
        )
    assert result.error is None
    assert len(result.content) == len(HEAD + TAIL)
    assert 'og:image' in result.content


async def test_fetch_is_deterministic_across_runs(dribble_server, logger):
    config = ScannerConfig(retries=0, rate_limit_delay=0.0)
    url = f"http://{dribble_server.host}:{dribble_server.port}/page"
    lengths = set()
    async with aiohttp.ClientSession() as session:
        for _ in range(3):
            result = await fetch_url(session, url, config, DomainRateLimiter(), logger)
            lengths.add(len(result.content))
    assert lengths == {len(HEAD + TAIL)}


async def test_fetch_still_honours_the_size_cap(dribble_server, logger):
    config = ScannerConfig(retries=0, rate_limit_delay=0.0, max_content_bytes=10_000)
    async with aiohttp.ClientSession() as session:
        result = await fetch_url(
            session, f"http://{dribble_server.host}:{dribble_server.port}/page",
            config, DomainRateLimiter(), logger,
        )
    assert len(result.content.encode()) == 10_000
