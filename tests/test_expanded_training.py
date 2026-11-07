"""Expanded-catalog training: ground-truth eligibility and the offline pipeline."""

import importlib.util
import json
from pathlib import Path

import pytest

from aliens_eye.core.http import FetchResult
from aliens_eye.core.sites import CatalogError, SiteCatalog, SiteDefinition
from aliens_eye.ml.expanded import build_ground_truth, upstream_examples

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train_expanded.py"


def site(name, url, **extra):
    return SiteDefinition.from_dict(name, {"url": url, "source": "upstream", **extra})


def example(url, username, source="upstream"):
    return {"site": "upstream", "url": url, "username": username, "label": 1,
            "verified": False, "label_source": source}


def test_only_profile_page_sites_outside_the_holdout_receive_usernames():
    catalog = SiteCatalog({
        "good": site("good", "https://good.example/u/{}"),
        "off": site("off", "https://off.example/u/{}", disabled=True),
        "api": site("api", "https://api.example/u/{}", probe_url="https://api.example/v1/{}"),
        "adult": site("adult", "https://adult.example/u/{}", nsfw=True),
        "held": site("held", "https://held.example/u/{}"),
        "strict": site("strict", "https://strict.example/u/{}", username_regex="^[a-z]+$"),
    })
    examples = [
        example("https://www.good.example/u/{}/", "alice"),  # same identity, different spelling
        example("https://good.example/u/{}", "alice", "community"),
        example("https://good.example/u/{}", "bob"),
        example("https://good.example/u/{}", "carol"),
        example("https://off.example/u/{}", "alice"),
        example("https://api.example/u/{}", "alice"),
        example("https://adult.example/u/{}", "alice"),
        example("https://held.example/u/{}", "alice"),
        example("https://strict.example/u/{}", "Alice9"),
        example("https://unknown.example/{}", "alice"),
    ]
    truth, subset, skipped = build_ground_truth(catalog, examples, excluded_groups={"held.example"})
    assert truth == {"good": {"usernames": ["alice", "bob"], "source": "upstream+community"}}
    assert list(subset.definitions) == ["good"]
    assert skipped == {
        "over per-site limit": 1, "disabled site": 1, "API probe, not a profile page": 1, "nsfw": 1,
        "overlaps holdout": 1, "username rejected by site rule": 1, "not in catalog": 1,
    }


def test_nsfw_sites_are_opt_in():
    catalog = SiteCatalog({"adult": site("adult", "https://adult.example/u/{}", nsfw=True)})
    truth, _, _ = build_ground_truth(
        catalog, [example("https://adult.example/u/{}", "alice")], include_nsfw=True, excluded_groups=set(),
    )
    assert truth == {"adult": {"usernames": ["alice"], "source": "upstream"}}


def test_default_exclusion_is_the_bundled_holdout():
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.ml.collect import load_selfcheck_data

    standard = load_sites_data()
    held = next(name for name in sorted(load_selfcheck_data("holdout")) if name in standard)
    catalog = SiteCatalog({held: SiteDefinition.from_dict(held, {"url": standard[held]})})
    truth, _, skipped = build_ground_truth(catalog, [example(standard[held], "someone")])
    assert truth == {}
    assert skipped == {"overlaps holdout": 1}


def test_upstream_usernames_must_come_from_the_catalog_snapshot(tmp_path):
    from aliens_eye.catalog import SOURCES

    primary = next(iter(SOURCES))
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"sites": {"Community": {
        "url": "https://community.example/u/{username}", "checkType": "status_code", "usernameClaimed": "alice",
    }}}), encoding="utf-8")
    matching = SiteCatalog({}, {primary: {"sha256": __import__("hashlib").sha256(data.read_bytes()).hexdigest()}})
    names = {(e["url"], e["username"]) for e in upstream_examples(matching, data)}
    assert ("https://community.example/u/{}", "alice") in names
    with pytest.raises(CatalogError, match="does not match the catalog snapshot"):
        upstream_examples(SiteCatalog({}, {primary: {"sha256": "0" * 64}}), data)


def found(username):
    return (
        f"<html><head><title>{username} - Profile</title>"
        f'<meta property="og:title" content="{username}"><link rel="canonical" href="https://x/{username}"></head>'
        f'<body><div class="profile"><h1>{username}</h1><p>Joined 2019. Followers 120. Posts 48.</p>'
        f'<img class="avatar" src="/a/{username}.png"><a href="/{username}/followers">followers</a>'
        + "".join(f'<a href="/p/{i}">post {i}</a>' for i in range(12)) + "</div></body></html>"
    )


NOT_FOUND = '<html><head><title>Page not found</title></head><body class="error">Sorry, this user does not exist. 404</body></html>'


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("train_expanded", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pipeline_records_collects_fits_and_compares_without_replacing_the_shipped_model(
    tmp_path, monkeypatch, script,
):
    from aliens_eye.catalog import write_catalog
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.corpus import record as record_mod
    from aliens_eye.ml.collect import load_selfcheck_data
    from aliens_eye.ml.expanded import write_ground_truth

    positives = {}

    async def network(session, url, config, rate_limiter, logger):
        status, body = (200, found(positives[url])) if url in positives else (404, NOT_FOUND)
        return FetchResult(url, url, status, body, 0.1, {"Content-Type": "text/html"}, None, 0)

    monkeypatch.setattr(record_mod, "fetch_url", network)
    work = tmp_path / "run"
    work.mkdir()
    sites = {f"s{i}": site(f"s{i}", f"https://s{i}.example/u/{{}}") for i in range(10)}
    truth = {name: {"usernames": [f"user{name}a", f"user{name}b"], "source": "upstream"} for name in sites}
    for name, entry in truth.items():
        for username in entry["usernames"]:
            positives[f"https://{name}.example/u/{username}"] = username
    write_catalog(work / script.SITES, SiteCatalog(sites))
    write_ground_truth(work / script.GROUND_TRUTH, truth)

    standard = load_sites_data()
    holdout = {k: v for k, v in sorted(load_selfcheck_data("holdout").items()) if k in standard}
    holdout = dict(list(holdout.items())[:6])
    for name, usernames in holdout.items():
        for username in usernames:
            positives[standard[name].replace("{}", username)] = username
    import asyncio

    asyncio.run(record_mod.record_corpus(
        {k: standard[k] for k in holdout}, holdout, tmp_path / "holdout", _Log(), negatives_per_site=2,
    ))

    shipped = (Path(__import__("aliens_eye").__file__).parent / "data" / "model.json").read_bytes()
    script.main(["record", "--work", str(work), "--negatives", "3", "--concurrency", "4"])
    for stage in ("collect", "fit"):
        script.main([stage, "--work", str(work)])
    script.main(["compare", "--work", str(work), "--holdout-corpus", str(tmp_path / "holdout"), "--bootstrap", "50"])

    dataset = (work / script.DATASET).read_text("utf-8").splitlines()
    assert dataset[0].endswith("label,site,site_group,label_source,split")
    assert {row.split(",")[-3] for row in dataset[1:]} == {f"s{i}.example" for i in range(10)}
    model = json.loads((work / script.MODEL).read_text("utf-8"))
    assert model["training"]["validation"] == "site-grouped"
    assert model["training"]["site_groups"] == 10
    comparison = json.loads((work / script.COMPARISON).read_text("utf-8"))
    assert set(comparison) == {"shipped", "candidate", "verdict"}
    assert comparison["shipped"]["positives"] > 0
    assert (Path(__import__("aliens_eye").__file__).parent / "data" / "model.json").read_bytes() == shipped
    with pytest.raises(SystemExit, match="already exists"):
        script.main(["fit", "--work", str(work)])


class _Log:
    def debug(self, *a, **k):
        pass

    info = warning = debug
