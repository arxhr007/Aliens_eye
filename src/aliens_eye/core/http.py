import asyncio
import random
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from .config import ScannerConfig
from .rate_limit import DomainRateLimiter


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content: str
    response_time: float
    headers: dict[str, str]
    error: str | None
    redirect_count: int


def _should_retry(status: int) -> bool:
    return status in {408, 429, 500, 502, 503, 504}


def _parse_retry_after(headers: dict[str, str]) -> float | None:
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def fetch_url(
    session: aiohttp.ClientSession,
    url: str,
    config: ScannerConfig,
    rate_limiter: DomainRateLimiter,
    logger,
) -> FetchResult:
    error_message = None
    last_status = 0
    last_headers: dict[str, str] = {}
    final_url = url
    redirect_count = 0

    retry_after = None
    for attempt in range(config.retries + 1):
        try:
            parsed = urlparse(url)
            await rate_limiter.wait_for_slot(
                parsed.netloc, config.rate_limit_delay, retry_after
            )

            # SOCKS proxies are handled by the session connector; only plain
            # HTTP(S) proxies go through aiohttp's per-request proxy support.
            http_proxy = None
            if config.proxy and config.proxy.lower().startswith(("http://", "https://")):
                http_proxy = config.proxy

            start_time = time.monotonic()
            async with session.get(
                url, timeout=config.timeout, allow_redirects=True, proxy=http_proxy
            ) as response:
                raw = await response.content.read(config.max_content_bytes)
                encoding = response.charset or "utf-8"
                content = raw.decode(encoding, errors="ignore")
                response_time = time.monotonic() - start_time
                last_status = response.status
                last_headers = dict(response.headers)
                final_url = str(response.url)
                redirect_count = len(response.history)

                if _should_retry(response.status) and attempt < config.retries:
                    retry_after = _parse_retry_after(last_headers)
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message="retryable status",
                    )

                return FetchResult(
                    url=url,
                    final_url=final_url,
                    status=last_status,
                    content=content,
                    response_time=response_time,
                    headers=last_headers,
                    error=None,
                    redirect_count=redirect_count,
                )
        except asyncio.TimeoutError:
            error_message = "timeout"
            last_status = 408
        except aiohttp.ClientResponseError as exc:
            error_message = str(exc)
            last_status = exc.status or last_status
            retry_after = _parse_retry_after(last_headers)
        except aiohttp.ClientError as exc:
            error_message = str(exc)
        except Exception as exc:
            error_message = str(exc)

        if attempt < config.retries:
            backoff = min(config.backoff_base * (2 ** attempt), config.backoff_cap)
            backoff += random.uniform(0.0, config.jitter)
            if retry_after:
                backoff = max(backoff, retry_after)
            await asyncio.sleep(backoff)

    logger.debug("Fetch failed for %s: %s", url, error_message)
    return FetchResult(
        url=url,
        final_url=final_url,
        status=last_status,
        content="",
        response_time=0.0,
        headers=last_headers,
        error=error_message,
        redirect_count=redirect_count,
    )
