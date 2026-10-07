"""Reverse lookup: which site and username does a profile URL belong to?

The catalogue maps ``site -> url template``. Scanning fills a username into every
template; this goes the other way, so a link found on a page ("instagram.com/_arx_")
can be turned back into ``("instagram", "_arx_")``.

Templates come in three shapes, all handled:

* path       ``https://github.com/{}``, ``https://lor.example/people/{}/profile``
* subdomain  ``https://{}.tumblr.com``
* query      ``https://forum.example/member.php?username={}``

A match must fit the whole template. ``github.com/arx/some-repo`` is not the
profile ``github.com/{}``, and ``github.com/features`` is site navigation, not a
user called "features": words that are page names, and the fixed first segment of
any sibling template on the same host (``sponsors`` in ``github.com/sponsors/{}``),
are never accepted as usernames.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import NamedTuple
from urllib.parse import parse_qsl, unquote, urlparse

PLACEHOLDER = "{}"
_TOKEN = "\x00user\x00"

#: Hosts that serve the same profiles as a catalogue host.
HOST_ALIASES = {
    "x.com": "twitter.com",
    "mobile.twitter.com": "twitter.com",
    "mobile.x.com": "twitter.com",
    "telegram.me": "t.me",
    "m.facebook.com": "facebook.com",
    "fb.com": "facebook.com",
    "old.reddit.com": "reddit.com",
    "new.reddit.com": "reddit.com",
    "m.youtube.com": "youtube.com",
    "threads.com": "threads.net",
}

#: Path segments and subdomains that are pages or services, never usernames.
RESERVED = frozenset({
    "about", "account", "accounts", "admin", "api", "app", "apps", "blog", "careers",
    "categories", "collections", "contact", "docs", "download", "events", "explore",
    "features", "feed", "hashtag", "help", "home", "i", "in", "intent", "jobs", "join",
    "legal", "login", "logout", "m", "marketplace", "messages", "mobile", "new", "news",
    "notifications", "orgs", "p", "policies", "policy", "press", "pricing", "privacy",
    "profile", "register", "results", "search", "security", "settings", "share",
    "sharer", "shop", "signin", "sign-in", "signup", "sign-up", "status", "store",
    "support", "tag", "tags", "terms", "topics", "tos", "trending", "u", "c", "user",
    "users", "channel", "watch", "www", "static", "cdn", "assets", "images", "img",
})

_FILE_SUFFIXES = (
    ".html", ".htm", ".php", ".asp", ".aspx", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".webp", ".ico", ".pdf", ".xml", ".json", ".js", ".css", ".txt", ".zip", ".rss",
)


class ProfileMatch(NamedTuple):
    site: str
    username: str


def _norm_host(host: str) -> str:
    host = (host or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return HOST_ALIASES.get(host, host)


def _valid_username(raw: str, reserved: frozenset[str] | set[str]) -> str | None:
    username = unquote(raw or "").strip().lstrip("@")
    if not 2 <= len(username) <= 64 or any(ch.isspace() for ch in username):
        return None
    lowered = username.lower()
    if lowered in RESERVED or lowered in reserved or lowered.endswith(_FILE_SUFFIXES):
        return None
    return username


class _Rule(NamedTuple):
    site: str
    weight: int                       # literal characters matched; higher is more specific
    path_re: re.Pattern | None        # captures the username (path shape)
    host_re: re.Pattern | None        # captures the username (subdomain shape)
    path: str | None                  # exact path (query shape; subdomain shape with a path)
    query_key: str | None             # query parameter holding the username
    query_fixed: tuple[tuple[str, str], ...]


class ProfileUrlMatcher:
    """Compiled reverse index over a site catalogue."""

    def __init__(self, sites: dict[str, str]) -> None:
        self._by_host: dict[str, list[_Rule]] = {}
        self._by_suffix: dict[str, list[_Rule]] = {}
        self._reserved: dict[str, set[str]] = {}
        for site, template in sorted(sites.items()):
            self._add(site, template)
        for rules in (*self._by_host.values(), *self._by_suffix.values()):
            rules.sort(key=lambda r: (-r.weight, r.site))

    def _add(self, site: str, template: str) -> None:
        if not isinstance(template, str) or template.count(PLACEHOLDER) != 1:
            return  # two-placeholder templates (pinterest boards) name no single user
        try:
            parsed = urlparse(template.replace(PLACEHOLDER, _TOKEN))
        except ValueError:
            return
        host = (parsed.hostname or "").lower()
        if not host:
            return
        path = parsed.path.rstrip("/")

        if _TOKEN in host:
            prefix, _, suffix = host.partition(_TOKEN)
            suffix = _norm_host(suffix.lstrip("."))
            if prefix or not suffix or _TOKEN in path:
                return
            self._by_suffix.setdefault(suffix, []).append(_Rule(
                site, len(suffix) + len(path),
                None, re.compile(r"^(?P<u>[^.]+)\." + re.escape(suffix) + "$"),
                path or None, None, (),
            ))
            return

        host = _norm_host(host)
        if _TOKEN in path:
            literal = path.replace(_TOKEN, "")
            pattern = re.escape(path).replace(re.escape(_TOKEN), r"(?P<u>[^/?#]+)")
            self._by_host.setdefault(host, []).append(_Rule(
                site, len(literal), re.compile("^" + pattern + "$", re.IGNORECASE),
                None, None, None, (),
            ))
            first = path.strip("/").split("/", 1)[0]
            if first and _TOKEN not in first:
                self._reserved.setdefault(host, set()).add(first.lstrip("@").lower())
            return

        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        keys = [k for k, v in pairs if v == _TOKEN]
        if len(keys) != 1:
            return
        fixed = tuple((k, v) for k, v in pairs if v != _TOKEN)
        self._by_host.setdefault(host, []).append(_Rule(
            site, len(path) + len(keys[0]), None, None, path.lower(), keys[0], fixed,
        ))

    def match(self, url: str) -> list[ProfileMatch]:
        """Every catalogue profile this URL could be, most specific first."""
        try:
            parsed = urlparse((url or "").strip())
        except ValueError:
            return []
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return []
        host = _norm_host(parsed.hostname)
        path = parsed.path.rstrip("/")
        reserved = self._reserved.get(host, set())
        found: list[tuple[int, ProfileMatch]] = []

        for rule in self._by_host.get(host, ()):
            raw = None
            if rule.path_re is not None:
                hit = rule.path_re.match(path)
                raw = hit.group("u") if hit else None
            elif rule.query_key is not None and path.lower() == rule.path:
                query = dict(parse_qsl(parsed.query, keep_blank_values=True))
                if all(query.get(k) == v for k, v in rule.query_fixed):
                    raw = query.get(rule.query_key)
            username = _valid_username(raw, reserved) if raw else None
            if username:
                found.append((rule.weight, ProfileMatch(rule.site, username)))

        labels = host.split(".")
        for i in range(1, len(labels) - 1):
            suffix = ".".join(labels[i:])
            for rule in self._by_suffix.get(suffix, ()):
                hit = rule.host_re.match(host)
                if not hit or (rule.path is not None and path.lower() != rule.path.lower()):
                    continue
                username = _valid_username(hit.group("u"), frozenset())
                if username:
                    found.append((rule.weight, ProfileMatch(rule.site, username)))

        found.sort(key=lambda item: (-item[0], item[1].site))
        seen: set[ProfileMatch] = set()
        ordered = []
        for _, match in found:
            if match not in seen:
                seen.add(match)
                ordered.append(match)
        return ordered


@lru_cache(maxsize=4)
def _cached(items: tuple[tuple[str, str], ...]) -> ProfileUrlMatcher:
    return ProfileUrlMatcher(dict(items))


def matcher_for(sites: dict[str, str]) -> ProfileUrlMatcher:
    """A matcher for this catalogue, compiled once and reused."""
    return _cached(tuple(sorted(sites.items())))
