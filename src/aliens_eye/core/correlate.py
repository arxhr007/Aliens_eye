"""Cross-site correlation: cluster Found/Maybe profiles that look like the same person.

Signals used per profile: avatar perceptual hash (dhash, requires Pillow via the
``[correlate]`` extra), normalized display name, tokenized bio, and external links
found in the bio. Profiles are linked by a union-find over pairwise similarity and
grouped into clusters ("likely the same person").

Avatar hashing is best-effort: if Pillow is missing or an image fails to download,
correlation still runs on name/bio/link signals alone.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .config import DEFAULT_HEADERS, ScannerConfig
from .scanner import build_connector

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.]{2,30})")
_WORD_RE = re.compile(r"[a-z0-9]+")

# Similarity thresholds.
AVATAR_MAX_HAMMING = 8      # <= this many differing bits => same image
BIO_MIN_JACCARD = 0.5       # token overlap ratio to link on bio alone
LINK_MATCH_WEIGHT = True    # a shared external link links two profiles


@dataclass
class Profile:
    variation: str
    site: str
    name: str
    bio: str
    avatar: str
    url: str
    status: str
    avatar_hash: int | None = None
    links: set[str] = field(default_factory=set)
    handles: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        # Derive links/handles from the bio when not supplied explicitly.
        if not self.links:
            self.links = set(_URL_RE.findall(self.bio or ""))
        if not self.handles:
            self.handles = {h.lower() for h in _HANDLE_RE.findall(self.bio or "")}

    @property
    def key(self) -> str:
        return f"{self.variation}:{self.site}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "variation": self.variation,
            "site": self.site,
            "name": self.name,
            "bio": self.bio,
            "avatar": self.avatar,
            "url": self.url,
            "status": self.status,
            "avatar_hash": format(self.avatar_hash, "016x") if self.avatar_hash is not None else None,
        }


def _norm_name(name: str) -> str:
    return " ".join(_WORD_RE.findall((name or "").lower()))


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def profiles_from_report(
    report: dict[str, Any], statuses: frozenset[str] = frozenset({"Found"}),
) -> list[Profile]:
    """Extract profiles (with profile signals) from a report dict.

    Defaults to Found-only: the Maybe band is dominated by 403/404 bot-walls whose
    boilerplate would pollute correlation. Only a *structured* display name (see
    ``name_from_profile``) is used as an identity signal — a bare ``<title>``
    fallback is dropped so page chrome cannot cluster unrelated sites.
    """
    profiles: list[Profile] = []
    for variation, block in report.get("variations", {}).items():
        for site, info in (block.get("sites", {}) or {}).items():
            if info.get("status") not in statuses:
                continue
            prof = info.get("ai_analysis", {}).get("signals", {}).get("profile", {}) or {}
            bio = prof.get("bio", "") or ""
            identity_name = (prof.get("name", "") or "") if prof.get("name_from_profile") else ""
            p = Profile(
                variation=variation,
                site=site,
                name=identity_name,
                bio=bio,
                avatar=prof.get("avatar", "") or "",
                url=info.get("url", "") or "",
                status=info.get("status", ""),
                links=set(_URL_RE.findall(bio)),
                handles={h.lower() for h in _HANDLE_RE.findall(bio)},
            )
            profiles.append(p)
    return profiles


# --- avatar hashing -------------------------------------------------------

def _dhash(image_bytes: bytes) -> int | None:
    """8x8 difference hash of an image -> 64-bit int. None if Pillow/decoding fails."""
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((9, 8))
    except Exception:
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            left = img.getpixel((col, row))
            right = img.getpixel((col + 1, row))
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401

        return True
    except ImportError:
        return False


async def _download_and_hash(
    session: aiohttp.ClientSession, profile: Profile, timeout: float
) -> None:
    if not profile.avatar:
        return
    try:
        async with session.get(profile.avatar, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                return
            data = await resp.content.read(2_000_000)  # cap at 2 MB
    except Exception:
        return
    profile.avatar_hash = _dhash(data)


async def hash_avatars(profiles: list[Profile], proxy: str | None = None, timeout: float = 10.0) -> None:
    """Download and dhash every profile avatar in place. No-op without Pillow."""
    if not pillow_available():
        return
    targets = [p for p in profiles if p.avatar]
    if not targets:
        return

    limit = min(20, len(targets))
    connector = build_connector(ScannerConfig(proxy=proxy), limit)
    sem = asyncio.Semaphore(limit)
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, connector=connector) as session:

        async def worker(p: Profile) -> None:
            async with sem:
                await _download_and_hash(session, p, timeout)

        await asyncio.gather(*(worker(p) for p in targets))


# --- clustering -----------------------------------------------------------

class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _pair_reason(
    a: Profile, b: Profile, common_names: frozenset[str] = frozenset()
) -> str | None:
    """Return the reason two profiles are the same person, or None.

    ``common_names`` holds normalized names that are too frequent across the scan
    to be identifying (boilerplate / generic brand titles); a name in that set
    never links a pair.
    """
    if (
        a.avatar_hash is not None
        and b.avatar_hash is not None
        and _hamming(a.avatar_hash, b.avatar_hash) <= AVATAR_MAX_HAMMING
    ):
        return "avatar"
    if a.links & b.links:
        return "shared-link"
    if a.handles & b.handles or (a.variation and a.variation in b.handles) or (b.variation and b.variation in a.handles):
        return "handle"
    na, nb = _norm_name(a.name), _norm_name(b.name)
    if na and na == nb and len(na) > 3 and na not in common_names:
        return "name"
    if _jaccard(_tokens(a.bio), _tokens(b.bio)) >= BIO_MIN_JACCARD:
        return "bio"
    return None


def _common_names(profiles: list[Profile]) -> frozenset[str]:
    """Normalized names shared by too many profiles to be identifying."""
    from collections import Counter

    counts: Counter[str] = Counter(
        na for p in profiles if (na := _norm_name(p.name))
    )
    threshold = max(4, int(0.02 * len(profiles)))
    return frozenset(name for name, count in counts.items() if count > threshold)


def cluster_profiles(profiles: list[Profile]) -> list[dict[str, Any]]:
    """Union-find clustering. Returns clusters as dicts (only multi-site clusters)."""
    n = len(profiles)
    uf = _UnionFind(n)
    common_names = _common_names(profiles)
    reasons: dict[tuple[int, int], str] = {}
    for i in range(n):
        for j in range(i + 1, n):
            reason = _pair_reason(profiles[i], profiles[j], common_names)
            if reason:
                uf.union(i, j)
                reasons[(i, j)] = reason

    groups: dict[int, list[int]] = {}
    for idx in range(n):
        groups.setdefault(uf.find(idx), []).append(idx)

    clusters: list[dict[str, Any]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        member_reasons = sorted(
            {reasons[(i, j)] for i in members for j in members if (i, j) in reasons}
        )
        clusters.append(
            {
                "size": len(members),
                "reasons": member_reasons,
                "members": [profiles[i].to_dict() for i in members],
            }
        )
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


async def correlate_report(
    report: dict[str, Any], proxy: str | None = None, timeout: float = 10.0
) -> dict[str, Any]:
    """Full correlation pass over a report dict. Returns a ``correlation`` block."""
    profiles = profiles_from_report(report)
    await hash_avatars(profiles, proxy=proxy, timeout=timeout)
    clusters = cluster_profiles(profiles)
    return {
        "avatar_hashing": pillow_available(),
        "profiles_considered": len(profiles),
        "clusters": clusters,
    }
