"""Recursive expansion: mine linked usernames out of found profiles.

Given scan results, pull candidate usernames from each Found/Maybe profile's bio
(``@handle`` mentions) and external links that follow a known ``domain/<user>``
shape (github.com/<user>, twitter.com/<user>, ...). These feed another scan hop.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.]{2,30})")
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)

# Domains where the first path segment is the username.
_USER_PATH_DOMAINS = {
    "github.com", "gitlab.com", "twitter.com", "x.com", "instagram.com",
    "t.me", "telegram.me", "medium.com", "dev.to", "reddit.com",
    "tiktok.com", "youtube.com", "twitch.tv", "keybase.io", "about.me",
    "codepen.io", "replit.com", "soundcloud.com", "pinterest.com",
}

# Path segments that are never usernames.
_PATH_STOPWORDS = {
    "in", "u", "user", "users", "profile", "channel", "c", "watch", "p",
    "about", "home", "login", "signup", "help", "settings", "explore",
}


def _username_from_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _USER_PATH_DOMAINS:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None
    candidate = segments[0].lstrip("@")
    if candidate.lower() in _PATH_STOPWORDS:
        candidate = segments[1] if len(segments) > 1 else ""
    candidate = candidate.strip()
    if len(candidate) < 2 or "." in candidate and not candidate.replace(".", "").isalnum():
        return None
    return candidate if candidate else None


def candidate_usernames_from_results(
    all_results: dict[str, list[dict[str, Any]]],
    exclude: set[str] | None = None,
    limit: int = 25,
) -> list[str]:
    """Collect deduped candidate usernames linked from Found/Maybe profiles."""
    exclude = {e.lower() for e in (exclude or set())}
    found: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        name = name.strip()
        low = name.lower()
        if len(name) < 2 or low in exclude or low in seen:
            return
        seen.add(low)
        found.append(name)

    for results in all_results.values():
        for item in results:
            if item.get("status") not in {"Found", "Maybe"}:
                continue
            profile = item.get("ai_analysis", {}).get("signals", {}).get("profile", {}) or {}
            bio = profile.get("bio", "") or ""
            for handle in _HANDLE_RE.findall(bio):
                _add(handle)
            for url in _URL_RE.findall(bio):
                uname = _username_from_url(url)
                if uname:
                    _add(uname)

    return found[:limit]
