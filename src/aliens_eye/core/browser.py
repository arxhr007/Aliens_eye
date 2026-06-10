import asyncio


class BrowserFallback:
    """Playwright-based fallback for hard pages."""

    def __init__(self, timeout: float, user_agent: str) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None
        self._context = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed") from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(user_agent=self.user_agent)

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(self, url: str) -> tuple[str, str]:
        if not self._context:
            await self.start()

        async with self._lock:
            page = await self._context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
            content = await page.content()
            final_url = page.url
            await page.close()
            return content, final_url
