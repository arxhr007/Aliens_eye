import json

import pytest

from aliens_eye.catalog import SOURCES, import_catalog, merge_catalogs, merge_maigret_entry, write_catalog
from aliens_eye.core.sites import (
    CatalogError,
    SiteCatalog,
    SiteDefinition,
    canonical_template,
    load_catalog,
)


def source_file(tmp_path, data, name="maigret.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def maigret_data():
    return {
        "sites": {
            "Community": {
                "urlMain": "https://community.example",
                "engine": "Forum",
                "tags": ["forum"],
                "usernameClaimed": "alice",
            },
            "Disabled": {
                "url": "https://disabled.example/{username}",
                "disabled": True,
            },
            "Numeric": {
                "url": "https://numeric.example/{username}",
                "type": "steam_id",
            },
            "Activation": {
                "url": "https://activation.example/{username}",
                "activation": {"method": "example"},
            },
            "Post": {
                "url": "https://post.example/{username}",
                "requestMethod": "POST",
            },
        },
        "engines": {
            "Forum": {
                "site": {
                    "url": "{urlMain}/u/{username}",
                    "urlProbe": "{urlMain}/u/{username}.json",
                    "checkType": "message",
                    "presenseStrs": ['"username":'],
                    "absenceStrs": ['"not_found"'],
                }
            }
        },
    }


def test_imports_nested_maigret_engines(tmp_path, maigret_data):
    path = source_file(tmp_path, maigret_data)
    catalog = import_catalog({"maigret": path}, revisions={"maigret": "test-revision"})
    assert isinstance(catalog, dict)
    assert catalog["community"] == "https://community.example/u/{}"
    site = catalog.definitions["community"]
    assert site.probe_url == "https://community.example/u/{}.json"
    assert site.presence == ('"username":',)
    assert site.engine == "Forum"
    assert site.tags == ("forum",)
    assert site.source == "maigret"
    assert catalog.sources["maigret"]["revision"] == "test-revision"
    assert len(catalog.sources["maigret"]["sha256"]) == 64
    assert catalog.sources["maigret"]["license"] == "MIT"
    assert "Copyright (c) 2020-2026 Soxoj" in catalog.sources["maigret"]["notice"]
    assert "usernameClaimed" not in json.dumps(catalog.to_dict())


def test_disabled_and_unsupported_entries_are_not_enabled(tmp_path, maigret_data):
    catalog = import_catalog({"maigret": source_file(tmp_path, maigret_data)})
    assert set(catalog) == {"community"}
    assert "disabled" in catalog.definitions
    assert len(catalog.issues) == 3
    assert {item["site"] for item in catalog.issues} == {"Numeric", "Activation", "Post"}


def test_engine_merge_preserves_explicit_scalars_and_merges_markers():
    result = merge_maigret_entry(
        {
            "engine": "Example",
            "url": "https://override.example/{username}",
            "presenseStrs": ["local"],
            "errors": {"same": "local"},
        },
        {"Example": {"site": {
            "url": "{urlMain}/u/{username}",
            "presenseStrs": ["engine"],
            "errors": {"same": "engine", "extra": "error"},
        }}},
    )
    assert result["url"] == "https://override.example/{username}"
    assert result["presenseStrs"] == ["local", "engine"]
    assert result["errors"] == {"same": "engine", "extra": "error"}


def test_import_deduplicates_templates_not_hosts(tmp_path):
    path = source_file(tmp_path, {
        "$schema": "https://example.org/schema",
        "One": {"url": "https://www.example.org/u/{}", "errorType": "status_code"},
        "Alias": {"url": "http://example.org/u/{}/", "errorType": "status_code"},
        "Other": {"url": "https://example.org/people/{}", "errorType": "status_code"},
    }, "sherlock.json")
    catalog = import_catalog({"sherlock": path})
    assert len(catalog) == 2
    assert any(site.aliases for site in catalog.definitions.values())
    assert catalog.stats()["deduplicated"] == 1


PRIMARY, SECONDARY = list(SOURCES)


def test_opt_in_examples_keep_provenance_and_stay_unverified(tmp_path, request):
    data = request.getfixturevalue(f"{PRIMARY}_data")
    catalog = import_catalog({PRIMARY: source_file(tmp_path, data)}, include_examples=True)
    samples = catalog.sources[PRIMARY]["training_examples"]
    assert samples == [{
        "site": "Community", "url": "https://community.example/u/{}", "username": "alice",
        "label": 1, "verified": False, "label_source": PRIMARY,
    }]
    assert "training_examples" not in catalog.stats()["sources"][PRIMARY]
    assert catalog.stats()["sources"][PRIMARY]["training_example_count"] == 1


def test_merging_catalogs_upgrades_native_rules_and_retains_aliases(tmp_path):
    native = SiteDefinition.from_dict("original", {"url": "https://example.org/u/{}", "source": "aliens-eye"})
    upstream = import_catalog({SECONDARY: source_file(tmp_path, {
        "Upstream Name": {"url": "https://www.example.org/u/{}/", "errorType": "message", "errorMsg": "no user"},
        "Unique": {"url": "https://unique.example/{}", "errorType": "status_code"},
    }, "upstream.json")})
    merged = merge_catalogs(SiteCatalog({"original": native}), upstream)
    assert len(merged) == 2
    assert merged.definitions["original"].source == SECONDARY
    assert merged.definitions["original"].check_type == "message"
    assert "upstream name" in merged.definitions["original"].aliases
    assert "aliens-eye" in merged.definitions["original"].also_in
    assert merged.sources[SECONDARY]["license"] == "MIT"


def test_merging_different_revisions_requires_an_explicit_source_choice():
    with pytest.raises(CatalogError, match="different snapshots"):
        merge_catalogs(SiteCatalog({}, {SECONDARY: {"sha256": "one"}}), SiteCatalog({}, {SECONDARY: {"sha256": "two"}}))


@pytest.mark.parametrize("url", [
    "file:///tmp/{}",
    "https://user:password@example.org/{}",
    "https://127.0.0.1/{}",
    "http://169.254.169.254/{}",
    "https://localhost/{}",
    "https://example.org/{account}",
    "https://example.org/{}/{}",
    "https://example.org/no-placeholder",
    "https://example.org/{}?api_key=example",
])
def test_rejects_unsafe_or_ambiguous_templates(url):
    with pytest.raises(CatalogError):
        SiteDefinition.from_dict("test", {"url": url})


@pytest.mark.parametrize("headers", [
    {"Authorization": "example"},
    {"Cookie": "example"},
    {"X-Api-Key": "example"},
    {"Host": "localhost"},
    {"Accept": "text/html\r\nX-Injected: value"},
])
def test_rejects_unsafe_headers(headers):
    with pytest.raises(CatalogError):
        SiteDefinition.from_dict("test", {"url": "https://example.org/{}", "headers": headers})


def test_username_constraints_and_encoding():
    site = SiteDefinition.from_dict("test", {
        "url": "https://example.org/{}",
        "username_regex": "^[a-z][a-z0-9_]{1,14}$",
    })
    assert site.accepts("alice_1")
    assert not site.accepts("ALICE")
    assert not site.accepts("x" * 16)
    assert not site.accepts("a/b")
    unconstrained = SiteDefinition.from_dict("other", {"url": "https://other.example/{}"})
    assert unconstrained.profile_url("a/b") == "https://other.example/a%2Fb"


def test_subdomain_templates_reject_non_dns_handles():
    site = SiteDefinition.from_dict("test", {"url": "https://{}.example.org/"})
    assert site.accepts("alice-1")
    assert not site.accepts("a.b")
    assert not site.accepts("a/b")
    assert not site.accepts("-alice")


@pytest.mark.parametrize("pattern", [
    "(a+)+$", "(a|aa)+$", "(?i)(A|aa)+$", "[broken",
    "^a+a+a+a+a+a+a+a+a+a+b$", "^(a|aa)(a|aa)(a|aa)(a|aa)b$",
    r"(?i)(\u0130|ii)+$", r"(?i)(\u0131|ii)+$",
])
def test_rejects_invalid_or_unbounded_regex_work(pattern):
    with pytest.raises(CatalogError):
        SiteDefinition.from_dict("test", {
            "url": "https://example.org/{}", "username_regex": pattern,
        })


def test_roundtrip_preserves_definitions_and_notices(tmp_path, maigret_data):
    catalog = import_catalog({"maigret": source_file(tmp_path, maigret_data)})
    output = tmp_path / "catalog.json"
    write_catalog(output, catalog)
    restored = load_catalog(output)
    assert restored == catalog
    assert restored.to_dict() == catalog.to_dict()
    with pytest.raises(FileExistsError):
        write_catalog(output, catalog)


def test_copy_and_subset_preserve_metadata(tmp_path, maigret_data):
    catalog = import_catalog({"maigret": source_file(tmp_path, maigret_data)})
    assert isinstance(catalog.copy(), SiteCatalog)
    subset = catalog.subset(["community"])
    assert subset.definitions["community"] == catalog.definitions["community"]
    assert subset.sources == catalog.sources


def test_canonical_templates_preserve_path_case_and_query():
    assert canonical_template("http://www.example.org/u/{}/") == canonical_template("https://example.org/u/{}")
    assert canonical_template("https://example.org/U/{}") != canonical_template("https://example.org/u/{}")
    assert canonical_template("https://example.org/?user={}") != canonical_template("https://example.org/?page={}")


def test_catalog_rejects_unknown_schema(tmp_path):
    with pytest.raises(CatalogError, match="version"):
        load_catalog(source_file(tmp_path, {"schema_version": 999, "sites": {}}))


def test_standard_extension_keeps_unique_templates_and_license(tmp_path, maigret_data):
    from aliens_eye.catalog import with_standard_catalog

    catalog = with_standard_catalog(import_catalog({"maigret": source_file(tmp_path, maigret_data)}))
    assert "community" in catalog
    assert "github" in catalog
    identities = [canonical_template(site.url) for site in catalog.definitions.values()]
    assert len(identities) == len(set(identities))
    assert "Copyright (c) 2021 Aaron Thomas" in catalog.sources["aliens-eye"]["notice"]


def test_alias_filters_work_after_deduplication():
    from aliens_eye.core.scanner import filter_sites

    site = SiteDefinition.from_dict("canonical", {"url": "https://example.org/{}", "aliases": ["old-name"]})
    catalog = SiteCatalog({"canonical": site})
    assert filter_sites(catalog, include=["old-name"]) == catalog
    assert not filter_sites(catalog, exclude=["old-name"])


@pytest.mark.parametrize("operation", ["assign", "update", "ior"])
def test_mutating_url_map_does_not_keep_stale_probe_rules(operation):
    site = SiteDefinition.from_dict("example", {
        "url": "https://example.org/{}", "probe_url": "https://api.example.org/{}", "check_type": "status_code",
    })
    catalog = SiteCatalog({"example": site})
    url = "https://replacement.example/{}"
    if operation == "assign":
        catalog["example"] = url
    elif operation == "update":
        catalog.update(example=url)
    else:
        catalog |= {"example": url}
    restored = catalog.copy()
    assert restored["example"] == url
    assert restored.definitions["example"].probe_url is None
    assert restored.definitions["example"].check_type is None


@pytest.mark.parametrize("operation", ["delete", "pop", "popitem", "clear"])
def test_removed_sites_do_not_reappear_when_copying(operation):
    catalog = SiteCatalog({"example": SiteDefinition.from_dict("example", {"url": "https://example.org/{}"})})
    if operation == "delete":
        del catalog["example"]
    elif operation == "pop":
        catalog.pop("example")
    elif operation == "popitem":
        catalog.popitem()
    else:
        catalog.clear()
    assert not catalog.copy()
    assert not catalog.definitions


def test_packaged_extended_catalog_has_provenance_and_unique_templates():
    from aliens_eye import api

    standard = api.load_sites()
    extended = api.load_sites(catalog="extended")
    assert len(standard) == 788
    assert len(extended) > 7500
    assert isinstance(extended, SiteCatalog)
    identities = [canonical_template(site.url) for site in extended.definitions.values()]
    assert len(identities) == len(set(identities))
    assert extended.sources["maigret"]["revision"] == "21577cf7730ddaad0f17d7797e6dbf4642411b50"
    assert extended.sources["maigret"]["license"] == "MIT"
    assert all(site.source in extended.sources for site in extended.definitions.values())


def test_catalog_commands_keep_stdout_machine_readable(tmp_path, maigret_data, capsys):
    from aliens_eye.catalog import run_catalog_command

    source = source_file(tmp_path, maigret_data)
    output = tmp_path / "converted.json"
    run_catalog_command(["import", "--maigret", str(source)])
    assert json.loads(capsys.readouterr().out)["enabled"] == 1
    assert not output.exists()
    run_catalog_command(["import", "--maigret", str(source), "--out", str(output)])
    capsys.readouterr()
    run_catalog_command(["list", "--sites", str(output), "--tag", "forum", "--json"])
    assert json.loads(capsys.readouterr().out) == {"community": "https://community.example/u/{}"}


async def test_library_scan_preserves_loaded_rule_metadata(tmp_path, monkeypatch):
    from aliens_eye import api
    from aliens_eye.core.scanner import UsernameScanner

    site = SiteDefinition.from_dict("example", {
        "url": "https://example.org/{}", "probe_url": "https://api.example.org/{}", "check_type": "status_code",
    })
    path = tmp_path / "catalog.json"
    write_catalog(path, SiteCatalog({"example": site}))
    monkeypatch.setattr(api, "_cache_root", lambda: tmp_path / "cache")

    async def scan(self, name, template, username, session, limiter):
        assert self.sites_data.definitions[name].probe_url == site.probe_url
        return {
            "site": name, "url": site.profile_url(username), "final_url": site.profile_url(username),
            "status": "Maybe", "code": 200, "confidence": 50, "response_time": 0.0, "ai_analysis": {},
        }

    monkeypatch.setattr(UsernameScanner, "_scan_site", scan)
    report = await api.scan("alice", sites=api.load_sites(path=path), use_ml=False)
    assert report["variations"]["alice"]["sites"]["example"]["status"] == "Maybe"
