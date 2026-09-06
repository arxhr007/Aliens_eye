"""External-tool baselines, evaluated over the frozen corpus.

Sherlock, Maigret and WhatsMyName do not differ from this tool by algorithm so
much as by *curated per-site rules*. A fair comparison therefore has to run their
rules, not a paraphrase of their approach -- and it has to run them over the same
stored responses, so the comparison isolates detection logic from HTTP client
behaviour, retry policy, and which sites happened to be reachable that day.

**These are reimplementations of the documented rule semantics, not the upstream
code.** Each engine below states its interpretation explicitly so a reviewer can
check it. Where upstream behaviour is ambiguous the interpretation is the
charitable one -- the reading most likely to make the external tool look good.

Rule data is **not vendored**. It is fetched by the user and passed by path:

* Sherlock -- ``sherlock_project/resources/data.json`` (MIT)
* WhatsMyName -- ``wmn-data.json`` (CC BY-SA 4.0, (C) Micah Hoffman et al.)
* Maigret -- ``maigret/resources/data.json`` (MIT), read with the Sherlock engine
  since it uses the same ``checkType``/``errorType`` vocabulary.

Keeping the data out of the tree avoids relicensing questions and keeps the
comparison honest about its provenance: the version fetched is recorded in the
result bundle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

#: Verdicts an external rule can return. ``None`` means the tool has no rule for
#: that site and the row must be excluded from its score rather than counted
#: against it.
FOUND = "Found"
NOT_FOUND = "Not Found"
UNKNOWN = None


def _netloc(url: str) -> str:
    """Host key for matching rules to corpus rows, ignoring a leading ``www.``."""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in value if v]


@dataclass
class ExternalRule:
    site_name: str
    netloc: str
    raw: dict[str, Any]


class RuleEngine:
    """Base: maps corpus rows to a verdict using an external tool's rules."""

    name = "external"

    def __init__(self, rules: dict[str, ExternalRule], source: dict[str, Any]) -> None:
        self.rules = rules
        self.source = source

    @property
    def covered_netlocs(self) -> set[str]:
        return set(self.rules)

    def rule_for(self, url: str) -> ExternalRule | None:
        return self.rules.get(_netloc(url))

    def decide(self, url: str, final_url: str, status: int, body: str) -> str | None:
        raise NotImplementedError


class SherlockEngine(RuleEngine):
    """Sherlock / Maigret ``errorType`` semantics.

    * ``status_code`` -- the account exists iff the response is 2xx. (Sherlock
      also honours an explicit ``errorCode``; when present, that code means
      absent.)
    * ``message`` -- the account exists iff none of the error messages appear in
      the body. Multiple messages are OR-ed, matching upstream.
    * ``response_url`` -- the account exists iff the request was not redirected
      away from the profile URL. Sites using this rule bounce unknown users to a
      home or error page.

    Maigret's ``checkType`` uses the same vocabulary and is accepted here.
    """

    name = "sherlock"

    @classmethod
    def load(cls, path: Path) -> SherlockEngine:
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        rules: dict[str, ExternalRule] = {}
        for site_name, entry in data.items():
            if not isinstance(entry, dict) or "url" not in entry:
                continue
            host = _netloc(str(entry["url"]))
            if host and host not in rules:
                rules[host] = ExternalRule(site_name, host, entry)
        return cls(
            rules,
            {
                "engine": "sherlock",
                "path": str(path),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "entries": len(data),
                "usable_rules": len(rules),
            },
        )

    def decide(self, url: str, final_url: str, status: int, body: str) -> str | None:
        rule = self.rule_for(url)
        if rule is None:
            return UNKNOWN
        entry = rule.raw
        check = entry.get("errorType") or entry.get("checkType") or "status_code"

        if check == "message":
            messages = _as_list(entry.get("errorMsg") or entry.get("absenceStrs"))
            if not messages:
                return UNKNOWN
            return NOT_FOUND if any(m in body for m in messages) else FOUND

        if check == "response_url":
            # Redirected away from the requested profile URL -> absent.
            return NOT_FOUND if _strip(final_url) != _strip(url) else FOUND

        # status_code
        error_code = entry.get("errorCode")
        if error_code is not None:
            codes = {int(c) for c in _as_list(error_code)} if not isinstance(
                error_code, int
            ) else {int(error_code)}
            if status in codes:
                return NOT_FOUND
        return FOUND if 200 <= status < 300 else NOT_FOUND


class WhatsMyNameEngine(RuleEngine):
    """WhatsMyName ``e_code``/``e_string`` vs ``m_code``/``m_string`` semantics.

    An account exists iff the status matches ``e_code`` **and** ``e_string``
    appears in the body. It is absent iff the status matches ``m_code`` and, when
    an ``m_string`` is given, that string appears. Anything else is UNKNOWN --
    the format is explicitly two-sided and does not force a decision, so scoring
    an unmatched row either way would misrepresent the tool.
    """

    name = "whatsmyname"

    @classmethod
    def load(cls, path: Path) -> WhatsMyNameEngine:
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        entries = data.get("sites", data if isinstance(data, list) else [])
        rules: dict[str, ExternalRule] = {}
        for entry in entries:
            if not isinstance(entry, dict) or "uri_check" not in entry:
                continue
            host = _netloc(str(entry["uri_check"]))
            if host and host not in rules:
                rules[host] = ExternalRule(str(entry.get("name", host)), host, entry)
        return cls(
            rules,
            {
                "engine": "whatsmyname",
                "path": str(path),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "entries": len(entries),
                "usable_rules": len(rules),
                "license": data.get("license") if isinstance(data, dict) else None,
            },
        )

    def decide(self, url: str, final_url: str, status: int, body: str) -> str | None:
        rule = self.rule_for(url)
        if rule is None:
            return UNKNOWN
        entry = rule.raw
        e_code, e_string = entry.get("e_code"), entry.get("e_string") or ""
        m_code, m_string = entry.get("m_code"), entry.get("m_string") or ""

        if e_code is not None and status == int(e_code) and (not e_string or e_string in body):
            return FOUND
        if m_code is not None and status == int(m_code) and (not m_string or m_string in body):
            return NOT_FOUND
        return UNKNOWN


ENGINES = {
    "sherlock": SherlockEngine,
    "maigret": SherlockEngine,
    "whatsmyname": WhatsMyNameEngine,
}


def _strip(url: str) -> str:
    return url.rstrip("/").lower()


def score_engine(engine: RuleEngine, observations) -> dict[str, Any]:
    """Score one external engine over pre-collected corpus observations.

    Rows the engine has no rule for, or returns UNKNOWN on, are **excluded** and
    reported as coverage rather than counted as errors. Charging a tool for sites
    it never claimed to support would understate it.
    """
    from aliens_eye.selfcheck import _metrics

    tp = fp = fn = tn = 0
    covered = unknown = no_rule = 0
    predictions: list[tuple[int, int]] = []
    covered_urls: list[str] = []
    per_site: dict[str, dict[str, int]] = {}

    for obs in observations:
        if obs.error:
            continue
        if engine.rule_for(obs.url) is None:
            no_rule += 1
            continue
        verdict = engine.decide(obs.url, obs.final_url or obs.url, obs.status_code, obs.body or "")
        if verdict is UNKNOWN:
            unknown += 1
            continue
        covered += 1
        covered_urls.append(obs.url)
        predicted = 1 if verdict == FOUND else 0
        predictions.append((obs.label, predicted))

        cell = per_site.setdefault(obs.site, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        if obs.label == 1 and predicted == 1:
            key = "tp"
        elif obs.label == 1:
            key = "fn"
        elif predicted == 1:
            key = "fp"
        else:
            key = "tn"
        cell[key] += 1
        tp += key == "tp"
        fp += key == "fp"
        fn += key == "fn"
        tn += key == "tn"

    overall = _metrics(tp, fp, fn, tn)
    overall["maybe_rate"] = 0.0
    return {
        "name": engine.name,
        "source": engine.source,
        "samples": covered,
        "rows_without_rule": no_rule,
        "rows_rule_undecided": unknown,
        "overall": overall,
        "per_site": {
            s: _metrics(c["tp"], c["fp"], c["fn"], c["tn"]) for s, c in per_site.items()
        },
        "predictions": predictions,
        "covered_urls": covered_urls,
    }


async def compare_external(
    corpus: Path,
    detector,
    logger,
    rule_paths: dict[str, Path],
    sites: set[str] | None = None,
    bootstrap_iterations: int = 4000,
) -> dict[str, Any]:
    """Score external engines and our own configurations on the same rows.

    Each external tool covers a different subset of the corpus, so a single
    shared row set would shrink to whatever the least-covering tool supports.
    Instead every external engine is compared against our configurations
    **restricted to that engine's covered rows** -- a like-for-like comparison
    per tool, with the covered row count reported alongside so the reader knows
    how much corpus each number rests on.
    """
    from aliens_eye.eval.ablate import (
        build_ablations,
        collect_observations,
        paired_delta_f1,
        score_ablation,
    )

    observations = await collect_observations(corpus, sites, logger)
    ablations = {a.name: a for a in build_ablations(getattr(detector.model, "ml_weight", None))}
    ours = {
        name: score_ablation(ablations[name], observations, detector)
        for name in ("status_only", "heuristic_only", "ml_only", "blended_shipped")
    }
    # score_ablation walks observations in order and skips error rows, so the
    # prediction lists align positionally with the usable rows.
    usable = [o for o in observations if not o.error]
    index_of = {o.url: i for i, o in enumerate(usable)}

    comparisons = []
    for engine_name, path in sorted(rule_paths.items()):
        engine_cls = ENGINES[engine_name]
        engine = engine_cls.load(Path(path))
        engine.name = engine_name
        scored = score_engine(engine, observations)
        idx = [index_of[u] for u in scored["covered_urls"] if u in index_of]

        against = {}
        for our_name, our_result in ours.items():
            subset = [our_result["predictions"][i] for i in idx]
            delta = paired_delta_f1(
                scored["predictions"], subset, iterations=bootstrap_iterations
            )
            from aliens_eye.eval.ablate import _f1_from_pairs

            against[our_name] = {
                "our_f1_on_covered_rows": round(_f1_from_pairs(subset), 4),
                **delta,
            }
        scored.pop("predictions", None)
        scored.pop("covered_urls", None)
        scored["vs_ours"] = against
        scored["site_coverage"] = round(
            scored["samples"] / max(1, len(usable)), 4
        )
        comparisons.append(scored)

    for result in ours.values():
        result.pop("predictions", None)

    return {
        "corpus": str(corpus),
        "usable_rows": len(usable),
        "ours": ours,
        "external": comparisons,
        "bootstrap_iterations": bootstrap_iterations,
    }
