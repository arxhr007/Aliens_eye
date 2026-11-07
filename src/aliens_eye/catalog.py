from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from aliens_eye.core.sites import (
    MAX_SITES,
    CatalogError,
    SiteCatalog,
    SiteDefinition,
    canonical_template,
    read_json,
)

MIT_NOTICE = """MIT License

{copyright}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
SOURCES = {
    "maigret": ("https://github.com/soxoj/maigret", "Copyright (c) 2020-2026 Soxoj"),
    "sherlock": ("https://github.com/sherlock-project/sherlock", "Copyright (c) 2019 Sherlock Project"),
}


def merge_maigret_entry(entry: dict, engines: dict) -> dict:
    result = dict(entry)
    engine = entry.get("engine")
    if not engine:
        return result
    if engine not in engines or not isinstance(engines[engine], dict):
        raise CatalogError("unknown engine")
    for key, value in engines[engine].get("site", {}).items():
        if isinstance(value, list):
            result[key] = list(result.get(key, [])) + value
        elif isinstance(value, dict):
            result[key] = {**result.get(key, {}), **value}
        else:
            result.setdefault(key, value)
    return result


def _template(value, entry: dict) -> str:
    if not isinstance(value, str):
        raise CatalogError("missing URL template")
    for field in ("urlMain", "urlSubpath"):
        value = value.replace("{" + field + "}", str(entry.get(field, "")))
    return value.replace("{username}", "{}")


def _markers(value) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def definition_from_upstream(name: str, entry: dict, source: str) -> SiteDefinition:
    if entry.get("type", "username") != "username":
        raise CatalogError("unsupported identifier type")
    if entry.get("protocol", "") not in ("", "http", "https"):
        raise CatalogError("unsupported protocol")
    if entry.get("activation"):
        raise CatalogError("activation or authentication required")
    if entry.get("similarSearch"):
        raise CatalogError("similar-name search is not an exact profile lookup")
    method = entry.get("requestMethod") or entry.get("request_method") or "GET"
    if method.upper() != "GET" or entry.get("requestHeadOnly"):
        raise CatalogError("only read-only GET probes are supported")
    if entry.get("requestPayload") or entry.get("request_payload"):
        raise CatalogError("request payloads are not supported")
    if entry.get("getParams"):
        raise CatalogError("additional query parameters are not supported")
    check = entry.get("checkType") or entry.get("errorType") or "status_code"
    error_codes = entry.get("errorCode", [])
    if isinstance(error_codes, int):
        error_codes = [error_codes]
    tags = _markers(entry.get("tags"))
    data = {
        "url": _template(entry.get("url"), entry),
        "check_type": check,
        "presence": _markers(entry.get("presenseStrs")),
        "absence": _markers(entry.get("absenceStrs") or entry.get("errorMsg")),
        "error_markers": list((entry.get("errors") or {}).keys()),
        "error_codes": error_codes,
        "headers": entry.get("headers") or {},
        "follow_redirects": check != "response_url",
        "username_regex": entry.get("regexCheck"),
        "encoding": entry.get("encoding"),
        "tags": tags,
        "nsfw": bool(entry.get("isNSFW")) or any(t.lower() in {"porn", "nsfw", "adult", "xx nsfw xx"} for t in tags),
        "disabled": entry.get("disabled", False),
        "engine": entry.get("engine"),
        "source": source,
        "upstream_name": name,
    }
    if entry.get("urlProbe"):
        data["probe_url"] = _template(entry["urlProbe"], entry)
    if check == "message" and not (data["presence"] or data["absence"]):
        raise CatalogError("message rule has no evidence")
    return SiteDefinition.from_dict(name.casefold(), data)


def import_catalog(
    paths: dict[str, Path], *, revisions: dict[str, str] | None = None, include_examples: bool = False,
) -> SiteCatalog:
    definitions: dict[str, SiteDefinition] = {}
    sources, issues, identities = {}, [], {}
    duplicates = 0
    for source, path in sorted(paths.items()):
        if source not in SOURCES:
            raise CatalogError(f"Unsupported import source: {source}")
        path = Path(path)
        data = read_json(path)
        if not isinstance(data, dict):
            raise CatalogError(f"{source}: expected a JSON object")
        if source == "maigret" and "sites" not in data:
            raise CatalogError("maigret: expected nested sites and engines")
        entries = data.get("sites", {}) if source == "maigret" else data
        engines = data.get("engines", {}) if source == "maigret" else {}
        if not isinstance(entries, dict) or not isinstance(engines, dict) or len(entries) > MAX_SITES:
            raise CatalogError(f"{source}: invalid source structure")
        repo, copyright_text = SOURCES[source]
        sources[source] = {
            "repository": repo, "license": "MIT", "notice": MIT_NOTICE.format(copyright=copyright_text),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "revision": (revisions or {}).get(source),
            "entries": sum(isinstance(v, dict) for v in entries.values()),
        }
        if include_examples:
            sources[source]["training_examples"] = []
        for original_name, raw in sorted(entries.items()):
            if original_name.startswith("$"):
                continue
            try:
                if not isinstance(raw, dict):
                    raise CatalogError("entry is not an object")
                expanded = merge_maigret_entry(raw, engines) if source == "maigret" else raw
                site = definition_from_upstream(original_name, expanded, source)
            except (CatalogError, TypeError, ValueError, AttributeError) as exc:
                issues.append({"source": source, "site": original_name, "reason": str(exc)})
                continue
            if include_examples and not site.disabled:
                claimed = raw.get("usernameClaimed", raw.get("username_claimed", []))
                claimed = [claimed] if isinstance(claimed, str) else claimed
                for username in claimed if isinstance(claimed, list) else []:
                    if isinstance(username, str) and username and site.accepts(username):
                        sources[source]["training_examples"].append({
                            "site": original_name, "url": site.url, "username": username,
                            "label": 1, "verified": False, "label_source": source,
                        })
            identity = canonical_template(site.url)
            previous = identities.get(identity)
            if previous is not None:
                old = definitions[previous]
                winner, other = (site, old) if old.disabled and not site.disabled else (old, site)
                definitions[previous] = replace(
                    winner, name=previous,
                    aliases=tuple(sorted(set(old.aliases + site.aliases + (other.name,)) - {previous})),
                    also_in=tuple(sorted(set(old.also_in + site.also_in + (other.source,)) - {winner.source})),
                    tags=tuple(sorted(set(old.tags + site.tags))),
                    nsfw=old.nsfw or site.nsfw,
                )
                duplicates += 1
                continue
            key = site.name
            if key in definitions:
                key = f"{source}:{key}:{hashlib.sha256(identity.encode()).hexdigest()[:8]}"
                site = replace(site, name=key)
            identities[identity] = key
            definitions[key] = site
    return SiteCatalog(definitions, sources, issues, duplicates)


def merge_catalogs(*catalogs: SiteCatalog) -> SiteCatalog:
    definitions, sources, identities, issues = {}, {}, {}, []
    duplicates = 0
    for catalog in catalogs:
        for name, metadata in catalog.sources.items():
            if name in sources and sources[name].get("sha256") != metadata.get("sha256"):
                raise CatalogError(f"Cannot merge different snapshots of source {name}")
            sources[name] = {**sources.get(name, {}), **metadata}
        issues.extend(catalog.issues)
        duplicates += catalog.deduplicated
        for name, site in sorted(catalog.definitions.items()):
            identity = canonical_template(site.url)
            if identity in identities:
                key = identities[identity]
                old = definitions[key]
                use_incoming = not site.disabled and (
                    old.disabled or old.source == "aliens-eye" and old.check_type is None and site.check_type is not None
                )
                winner, other = (site, old) if use_incoming else (old, site)
                definitions[key] = replace(
                    winner, name=key,
                    aliases=tuple(sorted(set(old.aliases + site.aliases + (old.name, site.name)) - {key})),
                    also_in=tuple(sorted(set(old.also_in + site.also_in + (other.source,)) - {winner.source})),
                    tags=tuple(sorted(set(old.tags + site.tags))), nsfw=old.nsfw or site.nsfw,
                )
                duplicates += 1
                continue
            key = name if name not in definitions else f"{site.source}:{name}:{hashlib.sha256(identity.encode()).hexdigest()[:8]}"
            definitions[key] = replace(site, name=key)
            identities[identity] = key
    if len(definitions) > MAX_SITES:
        raise CatalogError("Merged catalog exceeds the site limit")
    return SiteCatalog(definitions, sources, issues, duplicates)


def write_catalog(path: Path, catalog: SiteCatalog) -> None:
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2) + "\n")


def with_standard_catalog(catalog: SiteCatalog) -> SiteCatalog:
    from importlib import resources

    from aliens_eye import __version__

    raw = (resources.files("aliens_eye.data") / "sites.json").read_text("utf-8")
    legacy = json.loads(raw)
    nsfw = set(json.loads((resources.files("aliens_eye.data") / "nsfw_sites.json").read_text("utf-8")))
    definitions, issues = dict(catalog.definitions), list(catalog.issues)
    identities = {canonical_template(site.url): name for name, site in definitions.items()}
    duplicates = catalog.deduplicated
    for name, url in sorted(legacy.items()):
        try:
            site = SiteDefinition.from_dict(name, {
                "url": url, "source": "aliens-eye", "upstream_name": name, "nsfw": name in nsfw,
            })
        except CatalogError as exc:
            issues.append({"source": "aliens-eye", "site": name, "reason": str(exc)})
            continue
        identity = canonical_template(url)
        if identity in identities:
            key = identities[identity]
            previous = definitions[key]
            definitions[key] = replace(
                previous, aliases=tuple(sorted(set(previous.aliases + (name,)) - {key})),
                also_in=tuple(sorted(set(previous.also_in + ("aliens-eye",)) - {previous.source})),
                nsfw=previous.nsfw or site.nsfw,
            )
            duplicates += 1
        else:
            key = name if name not in definitions else f"aliens-eye:{name}"
            identities[identity] = key
            definitions[key] = replace(site, name=key)
    sources = {
        **catalog.sources,
        "aliens-eye": {
            "repository": "https://github.com/arxhr007/Aliens_eye", "license": "MIT",
            "notice": MIT_NOTICE.format(copyright="Copyright (c) 2021 Aaron Thomas"),
            "sha256": hashlib.sha256(raw.encode()).hexdigest(), "version": __version__, "entries": len(legacy),
        },
    }
    return SiteCatalog(definitions, sources, issues, duplicates)


def run_catalog_command(argv: list[str]) -> None:
    from aliens_eye.core.scanner import load_sites_data

    parser = argparse.ArgumentParser(prog="aliens_eye sites")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="Inspect or convert local MIT-licensed site databases")
    for source in SOURCES:
        importer.add_argument(f"--{source}", type=Path)
        importer.add_argument(f"--{source}-revision")
    importer.add_argument("--out", type=Path, help="Write a new catalog; existing files are never overwritten")
    importer.add_argument("--with-standard", action="store_true", help="Include unique validated entries from the standard catalog")
    importer.add_argument("--include-examples", action="store_true", help="Retain upstream-asserted training usernames with their provenance")
    for command in ("stats", "list", "validate"):
        child = commands.add_parser(command)
        child.add_argument("--sites", type=Path)
        child.add_argument("--catalog", choices=("standard", "extended"), default="standard")
        child.add_argument("--tag")
        child.add_argument("--source")
        child.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "import":
        paths = {source: getattr(args, source) for source in SOURCES if getattr(args, source)}
        if not paths:
            parser.error("provide --maigret and/or --sherlock with a local JSON path")
        catalog = import_catalog(
            paths, revisions={s: getattr(args, f"{s}_revision") for s in paths},
            include_examples=args.include_examples,
        )
        if args.with_standard:
            catalog = with_standard_catalog(catalog)
        if args.out:
            write_catalog(args.out, catalog)
        print(json.dumps(catalog.stats(), ensure_ascii=False, indent=2))
        return
    sites = load_sites_data(args.sites, catalog=args.catalog)
    if isinstance(sites, SiteCatalog):
        selected = [
            name for name, site in sites.definitions.items()
            if (not args.tag or args.tag.casefold() in {t.casefold() for t in site.tags})
            and (not args.source or args.source == site.source or args.source in site.also_in)
        ]
        sites = sites.subset(selected)
    if args.command == "list":
        if args.json:
            print(json.dumps(sites, ensure_ascii=False, indent=2))
        else:
            for name, template in sorted(sites.items()):
                print(f"{name}\t{template}")
    else:
        if isinstance(sites, SiteCatalog):
            report = sites.stats()
            if args.command == "validate":
                report["issues"] = sites.issues
        else:
            groups: dict[str, list[str]] = {}
            invalid = []
            for name, url in sites.items():
                try:
                    SiteDefinition.from_dict(name, {"url": url})
                    groups.setdefault(canonical_template(url), []).append(name)
                except (CatalogError, ValueError) as exc:
                    invalid.append({"site": name, "reason": str(exc)})
            report = {
                "entries": len(sites), "valid_templates": sum(map(len, groups.values())),
                "unique_templates": len(groups), "invalid": invalid,
                "aliases": [names for names in groups.values() if len(names) > 1],
                "live_verified": False,
            }
        print(json.dumps(report, ensure_ascii=False, indent=2))
