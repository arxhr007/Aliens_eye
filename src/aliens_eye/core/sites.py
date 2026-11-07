from __future__ import annotations

import importlib
import ipaddress
import json
import re
import string
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

SCHEMA_VERSION = 1
MAX_CATALOG_BYTES = 32_000_000
MAX_SITES = 30_000
SAFE_HEADERS = {"accept", "accept-language", "user-agent", "referer"}
CHECK_TYPES = {"status_code", "message", "response_url"}


class CatalogError(ValueError):
    pass


def canonical_template(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    port = parsed.port
    if port and port not in (80, 443):
        host = f"{host}:{port}"
    return urlunsplit(("", host, parsed.path.rstrip("/"), parsed.query, ""))


def training_group(site: str, template: str | None = None) -> str:
    if template:
        host = (urlsplit(template).hostname or "").lower().removeprefix("www.")
        if host:
            return host.removeprefix("{}.")
    return f"site:{site.casefold()}"


def validate_template(value: str, *, probe: bool = False) -> None:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise CatalogError("URL template must be a nonempty string of at most 4096 characters")
    tokens = value.count("{}")
    if not (1 <= tokens <= 4 if probe else tokens == 1):
        raise CatalogError("URL template must identify one username")
    if any(ch in value.replace("{}", "") for ch in "{}\r\n\t\\"):
        raise CatalogError("URL template contains unresolved fields or invalid characters")
    try:
        parsed = urlsplit(value.replace("{}", "aliens-eye-probe"))
        host = parsed.hostname
        _port = parsed.port
    except ValueError as exc:
        raise CatalogError("Invalid URL template") from exc
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise CatalogError("Only public http(s) URLs without credentials are supported")
    if parsed.fragment or any(ch.isspace() for ch in value):
        raise CatalogError("URL templates cannot contain fragments or whitespace")
    if any(key.lower() in {"access_token", "authorization", "auth", "api_key", "apikey", "password", "secret", "token"}
           for key, _ in parse_qsl(parsed.query)):
        raise CatalogError("Credential-bearing query parameters are not supported")
    if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
        raise CatalogError("Private hosts are not supported")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise CatalogError("A public hostname is required") from None
    else:
        if not address.is_global:
            raise CatalogError("Private addresses are not supported")


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item or len(item) > 4096 for item in value
    ):
        raise CatalogError(f"{field_name} must be a list of nonempty strings")
    return tuple(dict.fromkeys(value))


@lru_cache(maxsize=512)
def username_pattern(pattern: str) -> re.Pattern:
    if not isinstance(pattern, str) or not pattern or len(pattern) > 512:
        raise CatalogError("Invalid username regex")
    parser = importlib.import_module("re._parser" if sys.version_info >= (3, 11) else "sre_parse")
    try:
        tree = parser.parse(pattern, 0)
    except (re.error, OverflowError, RecursionError) as exc:
        raise CatalogError("Invalid username regex") from exc

    def first_chars(nodes):
        if not nodes:
            return None
        op, arg = nodes[0]
        if str(op) == "LITERAL":
            return {arg}
        if str(op) == "SUBPATTERN":
            return first_chars(arg[-1])
        if str(op) == "IN":
            result = set()
            for kind, val in arg:
                if str(kind) == "LITERAL":
                    result.add(val)
                elif str(kind) == "RANGE" and val[1] - val[0] <= 256:
                    result.update(range(val[0], val[1] + 1))
                elif str(kind) == "CATEGORY" and str(val) in {"CATEGORY_DIGIT", "CATEGORY_WORD", "CATEGORY_SPACE"}:
                    chars = {
                        "CATEGORY_DIGIT": string.digits,
                        "CATEGORY_WORD": string.ascii_letters + string.digits + "_",
                        "CATEGORY_SPACE": string.whitespace,
                    }[str(val)]
                    result.update(map(ord, chars))
                else:
                    return None
            return result
        return None

    repetitions = 0

    def check(nodes, repeated=False, depth=0):
        nonlocal repetitions
        if depth > 12:
            raise CatalogError("Username regex is too complex")
        for op, arg in nodes:
            name = str(op)
            if name in {"MAX_REPEAT", "MIN_REPEAT"}:
                repetitions += 1
                if repeated:
                    raise CatalogError("Nested username regex repetition is not supported")
                if repetitions > 1:
                    raise CatalogError("Multiple username regex repetitions require manual review")
                check(arg[2], True, depth + 1)
            elif name == "SUBPATTERN":
                check(arg[-1], repeated, depth + 1)
            elif name in {"ASSERT", "ASSERT_NOT"}:
                check(arg[1], repeated, depth + 1)
            elif name == "BRANCH":
                seen = set()
                for branch in arg[1]:
                    chars = first_chars(branch)
                    chars = {chr(c).lower() for c in chars} if chars and all(c < 128 for c in chars) else None
                    if not chars or seen & chars:
                        raise CatalogError("Ambiguous username regex alternatives require manual review")
                    seen.update(chars)
                    check(branch, repeated, depth + 1)
            elif name not in {"LITERAL", "NOT_LITERAL", "IN", "AT", "ANY", "CATEGORY"}:
                raise CatalogError(f"Unsupported username regex operation: {name}")

    check(tree)
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise CatalogError("Invalid username regex") from exc


@dataclass(frozen=True)
class SiteRequest:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    follow_redirects: bool = True
    encoding: str | None = None

    @property
    def identity(self) -> str:
        return sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class SiteDefinition:
    name: str
    url: str
    probe_url: str | None = None
    check_type: str | None = None
    presence: tuple[str, ...] = ()
    absence: tuple[str, ...] = ()
    error_markers: tuple[str, ...] = ()
    error_codes: tuple[int, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    follow_redirects: bool = True
    encoding: str | None = None
    username_regex: str | None = None
    tags: tuple[str, ...] = ()
    nsfw: bool = False
    disabled: bool = False
    engine: str | None = None
    source: str = "custom"
    upstream_name: str = ""
    aliases: tuple[str, ...] = ()
    also_in: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> SiteDefinition:
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise CatalogError("Invalid site name")
        if not isinstance(data, dict):
            raise CatalogError(f"{name}: expected a site object")
        unknown = set(data) - (set(cls.__dataclass_fields__) - {"name"})
        if unknown:
            raise CatalogError(f"{name}: unknown fields: {', '.join(sorted(unknown))}")
        validate_template(data.get("url"))
        if data.get("probe_url") is not None:
            validate_template(data["probe_url"], probe=True)
        if data.get("check_type") is not None and data["check_type"] not in CHECK_TYPES:
            raise CatalogError(f"{name}: unsupported check type")
        values = dict(data)
        values["username_regex"] = values.get("username_regex") or None
        values["encoding"] = values.get("encoding") or None
        for key in ("presence", "absence", "error_markers", "tags", "aliases", "also_in"):
            values[key] = _strings(values.get(key, ()), key)
        codes = values.get("error_codes", ())
        if not isinstance(codes, (list, tuple)) or any(type(c) is not int or not 100 <= c < 600 for c in codes):
            raise CatalogError(f"{name}: invalid HTTP status codes")
        values["error_codes"] = tuple(codes)
        for key in ("follow_redirects", "nsfw", "disabled"):
            if key in values and type(values[key]) is not bool:
                raise CatalogError(f"{name}: {key} must be boolean")
        for key in ("encoding", "username_regex", "engine", "source", "upstream_name"):
            if values.get(key) is not None and not isinstance(values[key], str):
                raise CatalogError(f"{name}: {key} must be a string")
        headers = values.get("headers", {})
        if not isinstance(headers, dict) or any(
            not isinstance(k, str) or k.lower() not in SAFE_HEADERS
            or not isinstance(v, str) or len(v) > 1024 or "\r" in v or "\n" in v
            for k, v in headers.items()
        ):
            raise CatalogError(f"{name}: unsupported or unsafe request headers")
        if values.get("username_regex"):
            username_pattern(values["username_regex"])
        if values.get("encoding"):
            try:
                "".encode(values["encoding"])
            except LookupError as exc:
                raise CatalogError(f"{name}: unknown response encoding") from exc
        return cls(name=name, **values)

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()

    def accepts(self, username: str) -> bool:
        if not isinstance(username, str) or not 1 <= len(username) <= 128:
            return False
        for template in (self.url, self.probe_url or self.url):
            if "{}" in urlsplit(template).netloc and not re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", username
            ):
                return False
        return self.username_regex is None or username_pattern(self.username_regex).search(username) is not None

    def profile_url(self, username: str) -> str:
        return self.url.replace("{}", quote(username, safe=""))

    def request(self, username: str) -> SiteRequest:
        return SiteRequest(
            (self.probe_url or self.url).replace("{}", quote(username, safe="")),
            dict(self.headers), self.follow_redirects, self.encoding,
        )

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values.pop("name")
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in values.items()
            if value not in (None, "", (), {}, False) or key == "follow_redirects"
        }


class SiteCatalog(dict[str, str]):
    def __init__(
        self,
        definitions: dict[str, SiteDefinition],
        sources: dict[str, dict] | None = None,
        issues: list[dict[str, str]] | None = None,
        deduplicated: int = 0,
    ) -> None:
        self.definitions = dict(definitions)
        self.sources = dict(sources or {})
        self.issues = list(issues or [])
        self.deduplicated = deduplicated
        if any(name != site.name for name, site in definitions.items()):
            raise CatalogError("Site keys must match their definition names")
        super().__init__((name, site.url) for name, site in definitions.items() if not site.disabled)

    def __setitem__(self, name: str, url: str) -> None:
        old = self.definitions.get(name)
        if old is None or old.url != url or old.disabled:
            self.definitions[name] = SiteDefinition.from_dict(name, {"url": url})
        super().__setitem__(name, url)

    def __delitem__(self, name: str) -> None:
        super().__delitem__(name)
        self.definitions.pop(name, None)

    def update(self, *args, **kwargs) -> None:
        for name, url in dict(*args, **kwargs).items():
            self[name] = url

    def pop(self, name, *default):
        if name not in self:
            return super().pop(name, *default)
        value = self[name]
        del self[name]
        return value

    def popitem(self):
        name, value = super().popitem()
        self.definitions.pop(name, None)
        return name, value

    def clear(self) -> None:
        super().clear()
        self.definitions.clear()

    def setdefault(self, name, default=None):
        if name not in self:
            self[name] = default
        return self[name]

    def __ior__(self, other):
        self.update(other)
        return self

    def copy(self) -> SiteCatalog:
        return self.subset(self.definitions)

    def subset(self, names) -> SiteCatalog:
        names = set(names)
        return SiteCatalog(
            {k: v for k, v in self.definitions.items() if k in names},
            self.sources, self.issues, self.deduplicated,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "sources": self.sources,
            "sites": {name: site.to_dict() for name, site in sorted(self.definitions.items())},
            "issues": self.issues,
            "deduplicated": self.deduplicated,
        }

    def stats(self) -> dict[str, Any]:
        return {
            "entries": len(self.definitions),
            "enabled": len(self),
            "disabled": sum(s.disabled for s in self.definitions.values()),
            "excluded": len(self.issues),
            "deduplicated": self.deduplicated,
            "live_verified": False,
            "sources": self.sources,
            "tags": dict(sorted(Counter(t for s in self.definitions.values() for t in s.tags).items())),
        }


def read_json(path: Path) -> Any:
    path = Path(path)
    if path.stat().st_size > MAX_CATALOG_BYTES:
        raise CatalogError("Catalog exceeds the size limit")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Invalid catalog JSON: {path.name}") from exc


def catalog_from_dict(data: dict[str, Any]) -> SiteCatalog:
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise CatalogError("Unsupported catalog schema version")
    sites = data.get("sites")
    if not isinstance(sites, dict) or len(sites) > MAX_SITES:
        raise CatalogError("Invalid catalog site collection")
    sources, issues = data.get("sources", {}), data.get("issues", [])
    if not isinstance(sources, dict) or not isinstance(issues, list):
        raise CatalogError("Invalid catalog provenance")
    return SiteCatalog(
        {name: SiteDefinition.from_dict(name, value) for name, value in sites.items()},
        sources, issues, int(data.get("deduplicated", 0)),
    )


def load_catalog(path: Path) -> SiteCatalog:
    return catalog_from_dict(read_json(path))
