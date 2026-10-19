import asyncio

# A browser holds on to memory for every page it has ever rendered, closed or not.
# Replacing its context now and then hands that memory back to the system.
RECYCLE_AFTER_PAGES = 40
CLOSE_TIMEOUT = 5.0


class BrowserFallback:
    """Playwright-based fallback for hard pages.

    Starts one browser, on first use, and shows it one page at a time.
    """

    def __init__(self, timeout: float, user_agent: str) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages_in_context = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed") from exc

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context(user_agent=self.user_agent)
        except BaseException:
            await self.close()      # never leave a half-started browser running
            raise
        self._pages_in_context = 0

    async def close(self) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        self._context = self._browser = self._playwright = None
        self._pages_in_context = 0
        for closer in (context and context.close, browser and browser.close,
                       playwright and playwright.stop):
            if closer is None:
                continue
            try:
                await asyncio.wait_for(closer(), CLOSE_TIMEOUT)
            except Exception:  # noqa: BLE001 - shutting down; there is nothing left to save
                pass

    async def _fresh_context(self):
        """The context to open the next page in, replaced every so many pages."""
        if self._context is None:
            await self.start()
        elif self._pages_in_context >= RECYCLE_AFTER_PAGES:
            old = self._context
            self._context = await self._browser.new_context(user_agent=self.user_agent)
            self._pages_in_context = 0
            try:
                await asyncio.wait_for(old.close(), CLOSE_TIMEOUT)
            except Exception:  # noqa: BLE001
                pass
        return self._context

    async def fetch(self, url: str) -> tuple[str, str]:
        # Starting the browser is inside the lock: with 50 scan workers asking at
        # once, checking first and starting outside it launched one Chromium each.
        async with self._lock:
            context = await self._fresh_context()
            page = await context.new_page()
            self._pages_in_context += 1
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
                content = await page.content()
                final_url = page.url
            finally:
                # Also on a timeout, an error, or a cancelled scan: an open page
                # stays in the browser, and a scan has hundreds of these to load.
                try:
                    await asyncio.wait_for(page.close(), CLOSE_TIMEOUT)
                except Exception:  # noqa: BLE001
                    pass
            return content, final_url
