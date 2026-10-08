"""Is this the page a site shows for a user who does not exist?

Many sites answer every profile address with HTTP 200: a JavaScript shell that
fills itself in later, a "no such user" page, a redirect to search. Such a page
names the username and carries profile-shaped markup, so scored on its own it
can look like a hit.

The scanner therefore asks the site a second question: what do you show for a
username that certainly does not exist? If the page for the searched username is
essentially that same page, the site has not told the two apart, and neither
can the scanner. This module is the comparison; the scanner decides what to do
with the answer.
"""

from __future__ import annotations

import re
import secrets
from collections import Counter
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from selectolax.lexbor import LexborHTMLParser

# A page counts as "the same page" at or above these. On the 286 training sites
# the pages wrongly reported as Found sit almost entirely at a similarity of
# 1.0 (45 of 52), so any threshold from 0.85 to 0.995 removes the same ones;
# 0.95 leaves room for a timestamp or a rotating recommendation. The length
# test is a guard for pages whose text matches while one carries far more data.
SAME_TEXT = 0.95
SAME_LENGTH = 0.85

# The server saying outright that there is no such page.
GONE_CODES = (404, 410)

_PLACEHOLDER = "\x00user\x00"
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_META_NAMES = ("description", "og:title", "og:description", "og:image", "og:url",
               "twitter:title", "twitter:description", "twitter:image", "profile:username")
_MAX_TOKENS = 6000


def control_username() -> str:
    """A handle that will not exist anywhere: 16 random lowercase characters."""
    return "zq" + secrets.token_hex(7)


@dataclass(frozen=True)
class PageShape:
    """What is compared between two pages of one site."""

    tokens: Counter
    length: int
    final_path: str     # where the request ended up, with the username masked


def _mask(text: str, username: str) -> str:
    """``text`` lowercased, with the username replaced by a fixed marker."""
    text = text.lower()
    name = username.lower()
    return text.replace(name, _PLACEHOLDER) if name else text


def page_shape(html: str, final_url: str, username: str) -> PageShape:
    """Reduce a page to what should differ between a real and a missing user."""
    parts: list[str] = []
    if html:
        tree = LexborHTMLParser(html)
        title = tree.css_first("title")
        if title is not None:
            parts.append(title.text() or "")
        for node in tree.css("meta[content]"):
            name = (node.attributes.get("property") or node.attributes.get("name") or "").lower()
            if name in _META_NAMES:
                parts.append(node.attributes.get("content") or "")
        for tag in ("script", "style", "noscript", "template", "svg"):
            for node in tree.css(tag):
                node.decompose()
        body = tree.body
        if body is not None:
            parts.append(body.text(separator=" "))
    tokens = _TOKEN_RE.findall(_mask(" ".join(parts), username))[:_MAX_TOKENS]
    try:
        parsed = urlparse(final_url)
        final_path = _mask(unquote(f"{parsed.netloc}{parsed.path}").rstrip("/"), username)
    except ValueError:
        final_path = ""
    return PageShape(Counter(tokens), len(html or ""), final_path)


def text_similarity(a: PageShape, b: PageShape) -> float:
    """Share of words the two pages have in common, 0 to 1. Two empty pages are equal."""
    total = sum(a.tokens.values()) + sum(b.tokens.values())
    if total == 0:
        return 1.0
    return 2 * sum((a.tokens & b.tokens).values()) / total


def length_ratio(a: PageShape, b: PageShape) -> float:
    longest = max(a.length, b.length)
    return 1.0 if longest == 0 else min(a.length, b.length) / longest


def http_overrule(status_code: int) -> tuple[str, str] | None:
    """What an HTTP error code makes of a page scored as Found: ``(status, reason)``.

    A 404 or 410 is the site's own answer and settles it. Any other error (a
    403 block page, a 500) is not a profile either, but says nothing about
    whether the account exists.
    """
    if status_code in GONE_CODES:
        return "Not Found", "http-gone"
    if status_code >= 400:
        return "Maybe", "http-error"
    return None


def same_page(page: PageShape, control: PageShape) -> bool:
    """True when ``page`` is, in effect, the page shown for a user who doesn't exist."""
    return text_similarity(page, control) >= SAME_TEXT and length_ratio(page, control) >= SAME_LENGTH
