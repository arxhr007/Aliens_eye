"""The Playwright fallback must not leak browsers or pages (#26).

A scan that reported 40+ GB of memory on a laptop had the fallback switched on.
Chromium is the likely holder: every "Maybe" result opens a page, and a scan has
hundreds. These tests use a fake Playwright, so they need no browser.
"""

import asyncio
import sys
import types

import pytest

from aliens_eye.core.browser import BrowserFallback


class FakePage:
    def __init__(self, world, fail=None, hang=False):
        self.world, self.fail, self.hang = world, fail, hang
        self.url = "https://example.test/final"
        self.closed = False

    async def goto(self, url, **kwargs):
        self.world.open_pages.add(self)
        self.world.peak_open = max(self.world.peak_open, len(self.world.open_pages))
        if self.hang:
            await asyncio.sleep(3600)
        if self.fail:
            raise self.fail
        await asyncio.sleep(0.01)

    async def content(self):
        return "<html>ok</html>"

    async def close(self):
        self.closed = True
        self.world.open_pages.discard(self)


class FakeContext:
    def __init__(self, world):
        self.world, self.closed = world, False

    async def new_page(self):
        self.world.pages_created += 1
        mode = self.world.next_page_mode()
        page = FakePage(self.world, **mode)
        self.world.all_pages.append(page)
        return page

    async def close(self):
        self.closed = True
        # Closing a context closes its pages.
        for page in list(self.world.open_pages):
            page.closed = True
            self.world.open_pages.discard(page)


class FakeBrowser:
    def __init__(self, world):
        self.world, self.closed = world, False

    async def new_context(self, **kwargs):
        context = FakeContext(self.world)
        self.world.contexts.append(context)
        return context

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, world):
        self.world = world

    async def launch(self, **kwargs):
        await asyncio.sleep(0.05)       # starting a real browser takes a while
        browser = FakeBrowser(self.world)
        self.world.browsers.append(browser)
        return browser


class FakePlaywright:
    def __init__(self, world):
        self.chromium = FakeChromium(world)

    async def stop(self):
        pass


class World:
    def __init__(self):
        self.browsers, self.contexts, self.all_pages = [], [], []
        self.open_pages, self.peak_open, self.pages_created = set(), 0, 0
        self.modes = []

    def next_page_mode(self):
        return self.modes.pop(0) if self.modes else {}


@pytest.fixture
def world(monkeypatch):
    world = World()

    class Starter:
        async def start(self):
            await asyncio.sleep(0.05)
            return FakePlaywright(world)

    module = types.ModuleType("playwright.async_api")
    module.async_playwright = lambda: Starter()
    package = types.ModuleType("playwright")
    package.async_api = module
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    return world


async def test_concurrent_first_fetches_start_one_browser(world):
    """Regression: 50 workers hitting a Maybe together each launched a Chromium."""
    fallback = BrowserFallback(timeout=5, user_agent="test")
    await asyncio.gather(*(fallback.fetch(f"https://example.test/{i}") for i in range(30)))
    assert len(world.browsers) == 1
    assert len(world.contexts) == 1
    await fallback.close()
    assert world.browsers[0].closed


async def test_a_page_that_fails_to_load_is_still_closed(world):
    world.modes = [{"fail": RuntimeError("net::ERR_TIMED_OUT")}]
    fallback = BrowserFallback(timeout=5, user_agent="test")
    with pytest.raises(RuntimeError):
        await fallback.fetch("https://example.test/a")
    assert world.all_pages[0].closed
    assert world.open_pages == set()


async def test_a_cancelled_fetch_closes_its_page(world):
    """The scan gives each site a deadline and cancels it; the page must not outlive that."""
    world.modes = [{"hang": True}]
    fallback = BrowserFallback(timeout=5, user_agent="test")
    task = asyncio.create_task(fallback.fetch("https://example.test/slow"))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.all_pages[0].closed
    assert world.open_pages == set()


async def test_one_page_is_open_at_a_time(world):
    fallback = BrowserFallback(timeout=5, user_agent="test")
    await asyncio.gather(*(fallback.fetch(f"https://example.test/{i}") for i in range(20)))
    assert world.peak_open == 1


async def test_the_context_is_recycled_so_browser_memory_stays_bounded(world, monkeypatch):
    monkeypatch.setattr("aliens_eye.core.browser.RECYCLE_AFTER_PAGES", 5)
    fallback = BrowserFallback(timeout=5, user_agent="test")
    for i in range(12):
        await fallback.fetch(f"https://example.test/{i}")
    assert len(world.browsers) == 1                  # the browser is reused
    assert len(world.contexts) == 3                  # 12 pages at 5 per context
    assert [c.closed for c in world.contexts] == [True, True, False]
    await fallback.close()
    assert all(c.closed for c in world.contexts)


async def test_a_failed_close_does_not_hide_the_result(world, monkeypatch):
    fallback = BrowserFallback(timeout=5, user_agent="test")

    async def broken_close(self):
        raise RuntimeError("target closed")

    monkeypatch.setattr(FakePage, "close", broken_close)
    content, final_url = await fallback.fetch("https://example.test/a")
    assert content == "<html>ok</html>" and final_url == "https://example.test/final"


async def test_close_is_safe_when_never_started(world):
    await BrowserFallback(timeout=5, user_agent="test").close()


async def test_fetch_after_close_starts_fresh(world):
    fallback = BrowserFallback(timeout=5, user_agent="test")
    await fallback.fetch("https://example.test/a")
    await fallback.close()
    await fallback.fetch("https://example.test/b")
    assert len(world.browsers) == 2


async def test_a_browser_that_fails_halfway_through_starting_is_shut_down(world, monkeypatch):
    """The browser launched, the context did not: the browser must not be left running."""
    async def broken_context(self, **kwargs):
        raise RuntimeError("could not create a context")

    monkeypatch.setattr(FakeBrowser, "new_context", broken_context)
    fallback = BrowserFallback(timeout=5, user_agent="test")
    with pytest.raises(RuntimeError):
        await fallback.fetch("https://example.test/a")
    assert len(world.browsers) == 1 and world.browsers[0].closed
