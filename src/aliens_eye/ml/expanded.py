"""Training data for the expanded community catalog.

The HTML detection model learns from profile pages. Expanded-catalog sites only
help it once they contribute labeled pages, so this module turns the catalog
into a ground-truth file the existing corpus/collect/fit pipeline can consume:

* positives are usernames the upstream site databases assert exist (their
  ``usernameClaimed`` / ``username_claimed`` fields) plus the curated train
  split for native sites. Upstream assertions are unverified: they are marked
  with their source, and the collector already drops positives that now 404;
* negatives are generated later, at recording time;
* every site whose training group overlaps the bundled holdout split is
  excluded, so the holdout keeps measuring performance on unseen sites;
* only sites whose profile page *is* the request qualify: API probes return
  JSON the HTML model never sees, and disabled sites are known to be broken.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from aliens_eye.core.sites import SiteCatalog, canonical_template, training_group


def holdout_groups() -> set[str]:
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.ml.collect import load_selfcheck_data

    templates = load_sites_data()
    return {training_group(site, templates.get(site)) for site in load_selfcheck_data("holdout")}


def upstream_examples(catalog: SiteCatalog, upstream_path: Path | None = None) -> list[dict[str, Any]]:
    """Every asserted-existing username available for the catalog's sources.

    Examples recorded at import time ship inside the catalog. The primary
    upstream database's are read from the same local data.json snapshot the
    catalog was built from; a different snapshot is refused, because its
    usernames would describe different site rules.
    """
    examples = [
        example for metadata in catalog.sources.values()
        for example in metadata.get("training_examples", [])
    ]
    if upstream_path is not None:
        from aliens_eye.catalog import SOURCES, import_catalog
        from aliens_eye.core.sites import CatalogError

        primary = next(iter(SOURCES))
        upstream = import_catalog({primary: Path(upstream_path)}, include_examples=True)
        expected = catalog.sources.get(primary, {}).get("sha256")
        actual = upstream.sources[primary]["sha256"]
        if expected and expected != actual:
            raise CatalogError(
                f"Upstream data.json sha256 {actual[:12]} does not match the catalog snapshot {expected[:12]}"
            )
        examples.extend(upstream.sources[primary]["training_examples"])
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.ml.collect import load_ground_truth_sources, load_selfcheck_data

    standard = load_sites_data()
    sources = load_ground_truth_sources("train")
    for site, usernames in load_selfcheck_data("train").items():
        if site in standard:
            examples.extend(
                {"site": site, "url": standard[site], "username": name, "label": 1,
                 "verified": False, "label_source": sources.get(site, "curated")}
                for name in usernames
            )
    return examples


def build_ground_truth(
    catalog: SiteCatalog,
    examples: list[dict[str, Any]],
    *,
    max_per_site: int = 2,
    include_nsfw: bool = False,
    excluded_groups: set[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], SiteCatalog, dict[str, int]]:
    """Map asserted usernames onto trainable catalog sites.

    Returns ``(ground_truth, training_catalog, skipped)``. ``ground_truth`` uses
    the provenance-carrying shape ``{"usernames": [...], "source": ...}``;
    ``training_catalog`` holds only the sites that received a username, so a
    recorder fed with it never requests anything else.
    """
    if max_per_site < 1:
        raise ValueError("max_per_site must be at least one")
    excluded = holdout_groups() if excluded_groups is None else excluded_groups
    by_identity = {canonical_template(site.url): name for name, site in catalog.definitions.items()}
    skipped: Counter[str] = Counter()
    truth: dict[str, dict[str, Any]] = {}
    for example in examples:
        name = by_identity.get(canonical_template(example["url"]))
        site = catalog.definitions.get(name) if name else None
        if site is None:
            skipped["not in catalog"] += 1
        elif site.disabled:
            skipped["disabled site"] += 1
        elif site.probe_url:
            skipped["API probe, not a profile page"] += 1
        elif site.nsfw and not include_nsfw:
            skipped["nsfw"] += 1
        elif training_group(name, site.url) in excluded:
            skipped["overlaps holdout"] += 1
        elif not site.accepts(example["username"]):
            skipped["username rejected by site rule"] += 1
        else:
            entry = truth.setdefault(name, {"usernames": [], "source": example["label_source"]})
            if example["username"] in entry["usernames"]:
                # A second project asserting the same account corroborates it.
                if example["label_source"] not in entry["source"].split("+"):
                    entry["source"] += "+" + example["label_source"]
                continue
            if len(entry["usernames"]) >= max_per_site:
                skipped["over per-site limit"] += 1
                continue
            entry["usernames"].append(example["username"])
            if example["label_source"] not in entry["source"].split("+"):
                entry["source"] += "+" + example["label_source"]
    subset = SiteCatalog(
        {name: catalog.definitions[name] for name in sorted(truth)},
        {key: {k: v for k, v in value.items() if k != "training_examples"} for key, value in catalog.sources.items()},
    )
    return dict(sorted(truth.items())), subset, dict(skipped)


def write_ground_truth(path: Path, truth: dict[str, dict[str, Any]]) -> None:
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(truth, ensure_ascii=False, indent=2) + "\n")


def write_training_catalog(path: Path, catalog: SiteCatalog) -> None:
    from aliens_eye.catalog import write_catalog

    write_catalog(Path(path), catalog)
