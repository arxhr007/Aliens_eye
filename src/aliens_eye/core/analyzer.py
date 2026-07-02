import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from .config import (
    AUTH_PATTERNS,
    ERROR_CLASS_HINTS,
    ERROR_KEYWORDS,
    META_KEYWORDS,
    POSITIVE_KEYWORDS,
    PROFILE_CLASS_HINTS,
)

_JSON_LD_PERSON_RE = re.compile(r'"@type"\s*:\s*"Person"', re.IGNORECASE)
_JSON_LD_STR_FIELD_RE = {
    "name": re.compile(r'"name"\s*:\s*"([^"]+)"'),
    "image": re.compile(r'"image"\s*:\s*"([^"]+)"'),
}

_site_profiles_cache: dict[str, Any] | None = None


def _load_site_profiles() -> dict[str, Any]:
    """Optional per-site CSS-selector overrides for profile fields.

    Maps a site name to ``{"name": sel, "bio": sel, "avatar": sel}``. Missing or
    invalid file yields an empty map (generic extraction is used instead).
    """
    global _site_profiles_cache
    if _site_profiles_cache is None:
        try:
            text = (resources.files("aliens_eye.data") / "site_profiles.json").read_text("utf-8")
            data = json.loads(text)
            _site_profiles_cache = data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            _site_profiles_cache = {}
    return _site_profiles_cache


@dataclass
class FeatureBundle:
    features: dict[str, float]
    signals: dict[str, Any]
    fingerprint: dict[str, Any]


class FeatureExtractor:
    """Extract structured signals from HTML content."""

    def __init__(
        self,
        error_keywords: list[str] | None = None,
        positive_keywords: list[str] | None = None,
        meta_keywords: list[str] | None = None,
        auth_patterns: list[str] | None = None,
    ) -> None:
        self.error_keywords = error_keywords or ERROR_KEYWORDS
        self.positive_keywords = positive_keywords or POSITIVE_KEYWORDS
        self.meta_keywords = meta_keywords or META_KEYWORDS
        self.auth_patterns = auth_patterns or AUTH_PATTERNS

    def extract(
        self,
        content: str,
        url: str,
        username: str,
        site_name: str,
        http_code: int,
        response_time: float,
        headers: dict[str, str] | None,
        redirect_count: int,
    ) -> FeatureBundle:
        content = content or ""
        content_lower = content.lower()

        error_keyword_count = sum(
            1 for keyword in self.error_keywords if keyword in content_lower
        )
        positive_keyword_count = sum(
            1 for keyword in self.positive_keywords if keyword in content_lower
        )

        parsed_url = urlparse(url)
        path = parsed_url.path or ""
        has_username_in_path = username.lower() in path.lower()
        has_auth_pattern = any(auth in path.lower() for auth in self.auth_patterns)
        is_homepage = path in ("", "/")

        tree = HTMLParser(content)
        title_node = tree.css_first("title")
        title_text = title_node.text().strip() if title_node else ""

        meta_contents: list[str] = []
        for node in tree.css("meta"):
            content_value = node.attributes.get("content")
            if content_value:
                meta_contents.append(content_value)

        meta_text = " ".join(meta_contents).lower()
        meta_error_keyword_count = sum(
            1 for keyword in self.error_keywords if keyword in meta_text
        )
        meta_positive_keyword_count = sum(
            1 for keyword in (self.positive_keywords + self.meta_keywords)
            if keyword in meta_text
        )

        class_nodes = tree.css("[class]")
        profile_section_count = 0
        error_section_count = 0
        for node in class_nodes:
            class_attr = node.attributes.get("class", "")
            class_value = str(class_attr).lower() if class_attr is not None else ""
            if not class_value:
                continue
            if any(hint in class_value for hint in PROFILE_CLASS_HINTS):
                profile_section_count += 1
            if any(hint in class_value for hint in ERROR_CLASS_HINTS):
                error_section_count += 1

        img_count = len(tree.css("img"))
        input_count = len(tree.css("input"))
        form_count = len(tree.css("form"))
        link_count = len(tree.css("a[href]"))

        # og:type = "profile" is a strong indicator of a real profile page
        og_type_profile = 0.0
        for node in tree.css('meta[property="og:type"]'):
            if (node.attributes.get("content") or "").lower() == "profile":
                og_type_profile = 1.0
                break

        # JSON-LD Person schema appears on profile pages
        has_json_ld_person = 0.0
        for node in tree.css('script[type="application/ld+json"]'):
            script_text = node.text()
            if script_text and _JSON_LD_PERSON_RE.search(script_text):
                has_json_ld_person = 1.0
                break

        # Canonical URL containing the username is a reliable profile signal
        username_in_canonical = 0.0
        canonical_node = tree.css_first('link[rel="canonical"]')
        if canonical_node:
            canonical_href = (canonical_node.attributes.get("href") or "").lower()
            if username.lower() in canonical_href:
                username_in_canonical = 1.0

        body_node = tree.css_first("body")
        text_length = float(len(body_node.text(deep=True))) if body_node else 0.0

        profile = self._extract_profile(tree, url, site_name, title_text)

        features = {
            "http_200": 1.0 if http_code == 200 else 0.0,
            "http_3xx": 1.0 if 300 <= http_code < 400 else 0.0,
            "http_404": 1.0 if http_code == 404 else 0.0,
            "http_4xx": 1.0 if 400 <= http_code < 500 else 0.0,
            "http_5xx": 1.0 if http_code >= 500 else 0.0,
            "has_username_in_path": 1.0 if has_username_in_path else 0.0,
            "is_homepage": 1.0 if is_homepage else 0.0,
            "has_auth_pattern": 1.0 if has_auth_pattern else 0.0,
            "error_keyword_count": float(error_keyword_count),
            "positive_keyword_count": float(positive_keyword_count),
            "meta_error_keyword_count": float(meta_error_keyword_count),
            "meta_positive_keyword_count": float(meta_positive_keyword_count),
            "profile_section_count": float(profile_section_count),
            "error_section_count": float(error_section_count),
            "img_count": float(img_count),
            "input_count": float(input_count),
            "form_count": float(form_count),
            "title_has_username": 1.0
            if username.lower() in title_text.lower()
            else 0.0,
            "meta_has_username": 1.0
            if username.lower() in meta_text
            else 0.0,
            "response_time": float(response_time),
            "content_length": float(len(content)),
            "redirect_count": float(redirect_count),
            "og_type_profile": og_type_profile,
            "has_json_ld_person": has_json_ld_person,
            "username_in_canonical": username_in_canonical,
            "link_count": float(link_count),
            "text_length": text_length,
        }

        signals = {
            "site": site_name,
            "title": title_text,
            "profile": profile,
            "meta_samples": meta_contents[:5],
            "url_analysis": {
                "domain": parsed_url.netloc,
                "path": path,
                "has_username_in_path": has_username_in_path,
                "has_auth_pattern": has_auth_pattern,
                "is_homepage": is_homepage,
            },
            "dom": {
                "img_count": img_count,
                "input_count": input_count,
                "form_count": form_count,
                "profile_section_count": profile_section_count,
                "error_section_count": error_section_count,
            },
            "headers": {
                "server": (headers or {}).get("Server", ""),
                "content_type": (headers or {}).get("Content-Type", ""),
            },
        }

        fingerprint = {
            "title": title_text,
            "meta_text": meta_text,
            "dom_signature": f"img:{img_count}|form:{form_count}|profile:{profile_section_count}|error:{error_section_count}",
            "server": (headers or {}).get("Server", ""),
        }

        return FeatureBundle(features=features, signals=signals, fingerprint=fingerprint)

    def _extract_profile(
        self, tree: HTMLParser, url: str, site_name: str, title_text: str
    ) -> dict[str, str]:
        """Best-effort display name / bio / avatar for a profile page.

        Generic and provider-agnostic: OpenGraph tags, then JSON-LD Person,
        then plain <title>/<meta>. Per-site CSS overrides in
        data/site_profiles.json take precedence when present.
        """
        name = self._meta_content(tree, 'meta[property="og:title"]')
        bio = self._meta_content(tree, 'meta[property="og:description"]')
        avatar = self._meta_content(tree, 'meta[property="og:image"]')

        if not (name and avatar):
            ld_name, ld_image = self._json_ld_person_fields(tree)
            name = name or ld_name
            avatar = avatar or ld_image

        if not bio:
            bio = self._meta_content(tree, 'meta[name="description"]')
        if not name:
            name = title_text
        if not avatar:
            icon = tree.css_first('link[rel="apple-touch-icon"]')
            if icon:
                avatar = icon.attributes.get("href") or ""

        overrides = _load_site_profiles().get(site_name)
        if isinstance(overrides, dict):
            name = self._select_text(tree, overrides.get("name")) or name
            bio = self._select_text(tree, overrides.get("bio")) or bio
            avatar = self._select_attr(tree, overrides.get("avatar")) or avatar

        if avatar:
            avatar = urljoin(url, avatar)

        return {
            "name": (name or "").strip()[:200],
            "bio": (bio or "").strip()[:500],
            "avatar": (avatar or "").strip(),
        }

    @staticmethod
    def _meta_content(tree: HTMLParser, selector: str) -> str:
        node = tree.css_first(selector)
        if node:
            return (node.attributes.get("content") or "").strip()
        return ""

    @staticmethod
    def _json_ld_person_fields(tree: HTMLParser) -> tuple[str, str]:
        for node in tree.css('script[type="application/ld+json"]'):
            script_text = node.text() or ""
            if not _JSON_LD_PERSON_RE.search(script_text):
                continue
            name_match = _JSON_LD_STR_FIELD_RE["name"].search(script_text)
            image_match = _JSON_LD_STR_FIELD_RE["image"].search(script_text)
            return (
                name_match.group(1) if name_match else "",
                image_match.group(1) if image_match else "",
            )
        return "", ""

    @staticmethod
    def _select_text(tree: HTMLParser, selector: str | None) -> str:
        if not selector:
            return ""
        node = tree.css_first(selector)
        return node.text().strip() if node else ""

    @staticmethod
    def _select_attr(tree: HTMLParser, selector: str | None) -> str:
        if not selector:
            return ""
        node = tree.css_first(selector)
        if not node:
            return ""
        for attr in ("src", "href", "content", "data-src"):
            value = node.attributes.get(attr)
            if value:
                return value
        return ""
