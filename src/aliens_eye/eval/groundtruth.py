"""Build an expanded ground-truth set from external projects, cross-sourced.

Sherlock and WhatsMyName each ship accounts asserted to exist -- Sherlock's
``username_claimed`` (one per site, MIT) and WhatsMyName's ``known`` (several per
site, CC BY-SA 4.0). Together they cover several hundred of this catalogue's
sites, which is the difference between a 43-site evaluation and a 400-site one.

**Those accounts are each project's own tuning set.** Sherlock's rules are
maintained so that ``username_claimed`` comes back Found; WhatsMyName's
``e_string`` markers are chosen against its ``known`` accounts. Scoring a tool on
the accounts its rules were tuned against measures memorisation, not detection.

So provenance is recorded per site and the comparison honours it: a site sourced
from Sherlock is excluded when scoring Sherlock, and likewise for WhatsMyName.
To keep both tools measurable, sites covered by both are alternated between the
two sources rather than all taken from one.

Accounts are **asserted, not verified**. Sherlock in particular uses generic
placeholder handles (``blue``, ``red``) on many sites. Every imported positive
carries ``verified: false`` until a capture pass confirms it resolves to a
profile; see ``verify_positives``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aliens_eye.eval.external import _netloc

CURATED = "curated"
SHERLOCK = "sherlock"
WHATSMYNAME = "whatsmyname"

#: Handles used as generic placeholders rather than real accounts. Present in a
#: source's data as test fixtures; they need verification before use as positives.
PLACEHOLDER_HANDLES = {
    "blue", "red", "green", "black", "white", "user", "username", "test",
    "admin", "adam", "john", "jsmith", "example", "demo", "none", "null",
}


@dataclass
class GroundTruthEntry:
    site: str
    usernames: list[str]
    source: str
    verified: bool = False
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"usernames": list(self.usernames), "source": self.source}
        if self.verified:
            payload["verified"] = True
        if self.notes:
            payload["notes"] = self.notes
        return payload


def _index_catalogue(sites_data: dict[str, str]) -> dict[str, str]:
    """Map host -> our site name, so external entries can be matched to ours."""
    index: dict[str, str] = {}
    for name, template in sites_data.items():
        host = _netloc(template)
        if host and host not in index:
            index[host] = name
    return index


def read_sherlock_accounts(path: Path, catalogue: dict[str, str]) -> dict[str, list[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        url, claimed = entry.get("url"), entry.get("username_claimed")
        if not url or not claimed:
            continue
        site = catalogue.get(_netloc(str(url)))
        if site and site not in out:
            out[site] = [str(claimed)]
    return out


def read_whatsmyname_accounts(path: Path, catalogue: dict[str, str]) -> dict[str, list[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("sites", data if isinstance(data, list) else [])
    out: dict[str, list[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        uri, known = entry.get("uri_check"), entry.get("known")
        if not uri or not known:
            continue
        site = catalogue.get(_netloc(str(uri)))
        if site and site not in out:
            out[site] = [str(k) for k in known if k]
    return out


def cross_source(
    existing: dict[str, list[str]],
    sherlock: dict[str, list[str]],
    whatsmyname: dict[str, list[str]],
) -> dict[str, GroundTruthEntry]:
    """Assign each new site to exactly one source, alternating on overlap.

    Sites already curated here keep their own provenance and are never
    reassigned: they predate both imports and are usable for scoring either tool.
    """
    entries: dict[str, GroundTruthEntry] = {
        site: GroundTruthEntry(site, list(usernames), CURATED, verified=True)
        for site, usernames in existing.items()
    }

    both = sorted((set(sherlock) & set(whatsmyname)) - set(entries))
    only_sherlock = sorted(set(sherlock) - set(whatsmyname) - set(entries))
    only_wmn = sorted(set(whatsmyname) - set(sherlock) - set(entries))

    # Alternate the overlap so each tool has a comparable number of sites it can
    # be scored on. Deterministic: sorted order, fixed parity.
    for position, site in enumerate(both):
        source = WHATSMYNAME if position % 2 == 0 else SHERLOCK
        usernames = whatsmyname[site] if source == WHATSMYNAME else sherlock[site]
        entries[site] = GroundTruthEntry(site, list(usernames), source)

    for site in only_sherlock:
        entries[site] = GroundTruthEntry(site, list(sherlock[site]), SHERLOCK)
    for site in only_wmn:
        entries[site] = GroundTruthEntry(site, list(whatsmyname[site]), WHATSMYNAME)

    for entry in entries.values():
        placeholders = [u for u in entry.usernames if u.lower() in PLACEHOLDER_HANDLES]
        if placeholders:
            entry.notes["placeholder_handles"] = placeholders
    return entries


def assign_splits(
    entries: dict[str, GroundTruthEntry],
    existing_train: set[str],
    existing_holdout: set[str],
    holdout_fraction: float = 0.3,
) -> dict[str, str]:
    """Site-disjoint train/holdout assignment, preserving existing placements.

    New sites are interleaved by sorted position rather than shuffled, so the
    assignment is reproducible and the holdout is spread across sources instead
    of concentrating in whichever source sorts last.
    """
    splits: dict[str, str] = {}
    for site in entries:
        if site in existing_holdout:
            splits[site] = "holdout"
        elif site in existing_train:
            splits[site] = "train"

    step = max(2, round(1 / holdout_fraction)) if holdout_fraction > 0 else 0
    unassigned = sorted(set(entries) - set(splits))
    for position, site in enumerate(unassigned):
        splits[site] = "holdout" if step and position % step == 0 else "train"
    return splits


def write_splits(
    entries: dict[str, GroundTruthEntry],
    splits: dict[str, str],
    train_path: Path,
    holdout_path: Path,
) -> dict[str, Any]:
    """Write both split files in the provenance-carrying dict form."""
    buckets: dict[str, dict[str, Any]] = {"train": {}, "holdout": {}}
    for site, entry in sorted(entries.items()):
        buckets[splits[site]][site] = entry.to_dict()

    for name, path in (("train", train_path), ("holdout", holdout_path)):
        Path(path).write_text(
            json.dumps(buckets[name], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def summarise(bucket: dict[str, Any]) -> dict[str, Any]:
        sources: dict[str, int] = {}
        for payload in bucket.values():
            sources[payload["source"]] = sources.get(payload["source"], 0) + 1
        return {
            "sites": len(bucket),
            "accounts": sum(len(p["usernames"]) for p in bucket.values()),
            "by_source": dict(sorted(sources.items())),
            "unverified_sites": sum(1 for p in bucket.values() if not p.get("verified")),
        }

    return {
        "train": summarise(buckets["train"]),
        "holdout": summarise(buckets["holdout"]),
        "total_sites": len(entries),
    }


def verify_positives(
    observations,
    engines: dict[str, Any],
    provenance: dict[str, str],
) -> dict[str, Any]:
    """Flag imported positives that both external rule sets call absent.

    Imported accounts are asserted by their source project, not verified here,
    and Sherlock in particular uses placeholder handles on many sites. A label
    error on a positive is worse than a missing site: it teaches the model that
    an absent-user page is a profile.

    The check is a consensus of signals *independent of the account's own
    source*: a positive is suspect when every other project's rules, applied to
    the captured response, say the account is absent. That is evidence of a bad
    label, not proof -- a rule can be stale -- so suspects are reported for
    review rather than deleted.

    Rows whose only ruling engine is the account's own source are skipped: that
    engine agreeing with its own tuning set proves nothing.
    """
    suspects: list[dict[str, Any]] = []
    confirmed = skipped = unrulable = 0

    for obs in observations:
        if obs.error or obs.label != 1:
            continue
        source = provenance.get(obs.site, CURATED)
        verdicts: dict[str, str] = {}
        for name, engine in engines.items():
            if name == source:
                continue  # circular: this engine was tuned on this account
            verdict = engine.decide(obs.url, obs.final_url or obs.url, obs.status_code, obs.body or "")
            if verdict is not None:
                verdicts[name] = verdict
        if not verdicts:
            unrulable += 1
            continue
        if all(v == "Not Found" for v in verdicts.values()):
            suspects.append({
                "site": obs.site,
                "username": obs.username,
                "url": obs.url,
                "status": obs.status_code,
                "source": source,
                "verdicts": verdicts,
                "placeholder": obs.username.lower() in PLACEHOLDER_HANDLES,
            })
        else:
            confirmed += 1
        skipped += 0

    by_source: dict[str, int] = {}
    for entry in suspects:
        by_source[entry["source"]] = by_source.get(entry["source"], 0) + 1
    return {
        "checked": confirmed + len(suspects),
        "corroborated": confirmed,
        "suspect": len(suspects),
        "no_independent_rule": unrulable,
        "suspect_by_source": dict(sorted(by_source.items())),
        "suspect_placeholder_handles": sum(1 for s in suspects if s["placeholder"]),
        "suspects": sorted(suspects, key=lambda s: (s["source"], s["site"])),
    }
