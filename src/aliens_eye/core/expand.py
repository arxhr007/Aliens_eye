"""Recursive expansion: mine linked usernames out of found profiles.

Given scan results, pull candidate usernames from each Found/Maybe profile's bio
(``@handle`` mentions) and external links that are profile URLs on any site in
the catalogue. These feed another scan hop.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.]{2,30})")
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)

@lru_cache(maxsize=1)
def _catalogue() -> tuple[tuple[str, str], ...]:
    from .scanner import load_sites_data

    return tuple(sorted(load_sites_data().items()))


def _username_from_url(url: str) -> str | None:
    """The username a profile link points at, for any site in the catalogue.

    This used to recognise 19 hard-coded domains by taking the first path
    segment. It now reverse-matches the link against every catalogue template
    (see ``core.urlmatch``), so ``linkedin.com/in/<user>`` or
    ``<user>.tumblr.com`` are understood and ``github.com/<user>/<repo>`` is
    correctly not taken for a profile.
    """
    from .urlmatch import matcher_for

    matches = matcher_for(dict(_catalogue())).match(url)
    return matches[0].username if matches else None


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
