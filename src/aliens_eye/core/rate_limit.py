import asyncio
import time


class DomainRateLimiter:
    """Simple per-domain rate limiting with retry-after support."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_allowed: dict[str, float] = {}
        self._global_lock = asyncio.Lock()

    async def wait_for_slot(self, domain: str, min_delay: float, retry_after: float | None) -> None:
        lock = await self._get_lock(domain)
        async with lock:
            now = time.monotonic()
            next_time = self._next_allowed.get(domain, now)
            delay = max(0.0, next_time - now)
            if retry_after:
                delay = max(delay, retry_after)
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_allowed[domain] = time.monotonic() + min_delay

    async def _get_lock(self, domain: str) -> asyncio.Lock:
        async with self._global_lock:
            if domain not in self._locks:
                self._locks[domain] = asyncio.Lock()
            return self._locks[domain]
