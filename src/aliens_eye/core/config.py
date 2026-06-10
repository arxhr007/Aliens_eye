from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_cache_dir

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/115.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

ERROR_KEYWORDS = [
    "not found",
    "doesn't exist",
    "didn't find",
    "does not exist",
    "something went wrong",
    "no such user",
    "user not found",
    "cannot find",
    "can't find",
    "not exist",
    "profile not found",
    "account does not exist",
    "username not found",
    "no user found",
    "no results found",
    "no such username",
    "isn't available",
    "that content is unavailable",
    "page not found",
    "404",
    "404 error",
    "404 not found",
    "error",
    "sorry",
    "oops",
    "unavailable",
    "account suspended",
    "invalid username",
    "account not found",
    "account terminated",
    "account disabled",
    "user doesn't have an account",
    "this account doesn't exist",
    "page was not found",
]

POSITIVE_KEYWORDS = [
    "follow",
    "subscribe",
    "like",
    "share",
    "following",
    "followers",
    "profile",
    "user",
    "posts",
    "photos",
    "bio",
    "status",
    "tweets",
    "joined",
    "member since",
    "online",
    "verified",
    "active",
    "comments",
    "uploads",
    "reviews",
    "friends",
    "connections",
    "activity",
    "timeline",
]

META_KEYWORDS = [
    "profile picture",
    "profile image",
    "avatar",
    "user page",
    "username",
    "user profile",
    "account info",
    "account information",
    "user information",
]

AUTH_PATTERNS = [
    "/login",
    "/signin",
    "/register",
    "/join",
    "auth",
    "oauth",
    "authenticate",
    "account/login",
    "session/new",
    "user/login",
    "members/login",
]

PROFILE_CLASS_HINTS = ["profile", "user", "account"]
ERROR_CLASS_HINTS = ["error", "not-found", "missing", "unavailable"]


def default_fingerprints_path() -> Path:
    return Path(user_cache_dir("aliens_eye")) / "fingerprints.json"


@dataclass
class ScannerConfig:
    concurrent: int = 50
    timeout: float = 10.0
    max_content_bytes: int = 100_000
    retries: int = 2
    backoff_base: float = 0.5
    backoff_cap: float = 8.0
    jitter: float = 0.2
    rate_limit_delay: float = 0.2
    fingerprints_path: Path = field(default_factory=default_fingerprints_path)
    output_dir: Path = Path("results")
    use_playwright: bool = False
    max_fingerprints_per_label: int = 50
    proxy: str | None = None
    include_sites: list[str] | None = None
    exclude_sites: list[str] | None = None
    exclude_nsfw: bool = False
    sites_path: Path | None = None
    model_path: Path | None = None
    use_ml: bool = True
    plain_output: bool = False
