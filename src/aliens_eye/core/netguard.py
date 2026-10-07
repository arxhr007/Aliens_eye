"""Fetching URLs that someone else chose, without being steered somewhere private.

Avatar URLs, and the links a profile page points at, come from the scanned page,
so whoever controls that page chooses them. Fetched unchecked they turn a scan
into a request generator aimed wherever the target likes: a cloud metadata
endpoint, an intranet host, a service on the analyst's own loopback.

Three things are needed, and checking the first host alone gives none of them:

* **Scheme**: http and https only. urllib also opens ``file://``.
* **Every redirect hop**: a public URL can answer ``302 Location: http://127.0.0.1/``.
  The 2.4 and 2.5 guards validated only the URL they were handed and then let the
  HTTP client follow redirects on its own. Redirects are followed manually here,
  and each hop is validated before it is requested.
* **The address actually connected to**: resolving a name to check it, then
  letting the client resolve it again to connect, leaves a gap a hostile DNS
  server can use (answer public first, private second). :class:`PublicOnlyResolver`
  does the filtering inside the connector, so the checked address is the one used.

None of this applies through a proxy: the proxy resolves and connects, not us.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class GuardError(Exception):
    """A URL, or a hop it redirected to, is not one this process may fetch."""


def fetchable_host(url: str) -> str | None:
    """The host of an http(s) URL, or None if the URL may not be fetched at all."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return None
    return parsed.hostname or None


def is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global and not ip.is_private and not ip.is_loopback


def all_public(infos) -> bool:
    """True only if getaddrinfo returned something and every answer is public."""
    return bool(infos) and all(is_public_ip(info[4][0]) for info in infos)


async def host_is_public(host: str) -> bool:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    return all_public(infos)


def host_is_public_sync(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    return all_public(infos)


async def is_public_url(url: str, allow_private: bool = False) -> bool:
    host = fetchable_host(url)
    if host is None:
        return False
    return True if allow_private else await host_is_public(host)


def is_public_url_sync(url: str, allow_private: bool = False) -> bool:
    host = fetchable_host(url)
    if host is None:
        return False
    return True if allow_private else host_is_public_sync(host)


async def refusal_reason(url: str) -> str:
    """Why :func:`is_public_url` said no, for an error a person can act on.

    "Does not resolve" and "resolves somewhere private" call for different
    responses: the first is usually a dead domain or a blocked lookup, the
    second is the guard doing its job.
    """
    host = fetchable_host(url)
    if host is None:
        return "not an http(s) address"
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return "host does not resolve"
    return "host resolves to a non-public address" if not all_public(infos) else "refused"


class PublicOnlyResolver(AbstractResolver):
    """A resolver that refuses names with any non-public address.

    Installed on the connector, so the addresses it approves are the ones the
    connection is made to; there is no second lookup to race.
    """

    def __init__(self, inner: AbstractResolver | None = None) -> None:
        self._inner = inner or DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        results = await self._inner.resolve(host, port, family)
        if not results or not all(is_public_ip(r["host"]) for r in results):
            raise OSError(f"{host} does not resolve to a public address")
        return results

    async def close(self) -> None:
        await self._inner.close()


@dataclass
class GuardedResponse:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    charset: str | None
    redirects: int


async def guarded_get(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout: float = 15.0,
    max_bytes: int = 2_000_000,
    allow_private: bool = False,
    proxy: str | None = None,
) -> GuardedResponse:
    """GET ``url``, validating it and every redirect hop. Raises :class:`GuardError`."""
    from .http import read_capped

    current = url
    for hop in range(MAX_REDIRECTS + 1):
        if not await is_public_url(current, allow_private):
            raise GuardError(f"{await refusal_reason(current)}: {current}")
        async with session.get(
            current,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=False,
            proxy=proxy,
        ) as response:
            if response.status in _REDIRECT_STATUSES:
                location = response.headers.get("Location")
                if not location:
                    raise GuardError(f"redirect without a Location from {current!r}")
                current = urljoin(current, location)
                continue
            body = await read_capped(response, max_bytes)
            return GuardedResponse(
                url=url,
                final_url=current,
                status=response.status,
                headers=dict(response.headers),
                body=body,
                charset=response.charset,
                redirects=hop,
            )
    raise GuardError(f"too many redirects from {url!r}")


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def __init__(self, allow_private: bool) -> None:
        self._allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public_url_sync(newurl, self._allow_private):
            raise urllib.error.URLError(f"refusing redirect to {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def guarded_urlopen_bytes(
    url: str,
    *,
    timeout: float = 6.0,
    max_bytes: int = 2_000_000,
    allow_private: bool = False,
    user_agent: str = "Mozilla/5.0 aliens-eye",
) -> bytes | None:
    """Blocking fetch for synchronous callers; None on any refusal or failure.

    The opener is built with http and https handlers only, so no redirect can
    reach ``file://`` or ``ftp://`` even in principle. It validates each hop but,
    unlike :func:`guarded_get` behind a :class:`PublicOnlyResolver`, it resolves
    names twice, so a DNS-rebinding race is not closed on this path.
    """
    if not is_public_url_sync(url, allow_private):
        return None
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        _GuardedRedirects(allow_private),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return response.read(max_bytes)
    except Exception:  # noqa: BLE001 - a best-effort image fetch never fails a report
        return None
