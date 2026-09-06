# Phase A baseline — "before" measurements

Archived starting point for the paper. These are the numbers the study improves on,
and the ones the limitations section must quote honestly.

## Provenance

- Tool version: 2.2.2, shipped `data/model.json` (`version 2.0.0`, `cv_f1 0.5622`)
- Command: `aliens_eye selfcheck --split {train,holdout} --negatives 2 --report json`
- Ground truth: site-disjoint split introduced in Phase A
  (`data/selfcheck.json` = 30 sites / 45 positives, `data/eval_holdout.json` = 13 sites / 15 positives)
- Captured: 2026-09-06, single residential connection, no proxy
- Seed: 1234 (default), so negative usernames are reproducible; the **responses are not**

## Results

| Split | Samples | Network errors | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|
| train (fit) | 51 | 39 | 0.455 | 0.882 | **0.600** | 0.529 |
| holdout (generalization) | 27 | 12 | 0.500 | 0.556 | **0.526** | 0.278 |

## Reading these numbers

**The train/holdout gap is the point.** F1 drops 0.600 → 0.526 on platforms the model
never trained on. Before Phase A the two sets were the same accounts, so no such gap
was observable — every previously reported figure was a fit measure presented as an
accuracy measure.

**They are not yet publishable as-is.** Three problems, all of which Phases B–D exist
to fix:

1. **Attrition.** 51 of 90 train requests and 12 of 39 holdout requests failed outright;
   only 9 of 13 holdout sites returned any usable row. Metrics computed over survivors
   are conditioned on a site being reachable and unblocked from one machine on one day.
2. **Sample size.** 27 usable holdout observations. The confidence interval on F1 = 0.526
   spans most of the unit interval; the gap above is directionally right but not
   statistically supported.
3. **Non-reproducibility.** Live web. Re-running this tomorrow gives different numbers
   and there is no way to tell a model change from a platform change. This is precisely
   what the Phase B frozen corpus removes.

## Failure classes already visible

Per-site holdout breakdown surfaces the systematic errors worth naming in the paper:

- **Catch-all / soft-404 pages** — `archive.org` and `duolingo` both scored FPR 1.00:
  every random non-existent username was called Found. These platforms serve a
  200-with-profile-chrome response for absent users, which defeats status and
  structure signals alike.
- **Under-detection on JS-rendered profiles** — `vimeo`, `unsplash`, `linktree`, and
  `hackernews` missed their known-good positive (recall 0.00), consistent with content
  arriving after page load. Quantifying how much of this the Playwright fallback
  recovers is ablation D2.
- **Clean cases** — `dribbble` and `last.fm` scored F1 1.00, confirming the pipeline
  works where markup is server-rendered and structured data is present.

## Files

- `before_train.json` — full metrics, train split
- `before_holdout.json` — full metrics, holdout split

Regenerate with the command above. Do not overwrite these files; add new dated ones,
since the value here is the frozen "before".

---

# Phase B — frozen corpus results

## Reproducible holdout evaluation

Corpus `paper/corpus/v1` (232 records, 43 sites, 4 negatives/site), replayed:

| Split | Samples | Errors | Precision | Recall | F1 | FPR | tp/fp/fn/tn |
|---|---|---|---|---|---|---|---|
| holdout, replayed | 52 | 15 | 0.444 | 0.667 | **0.533** | 0.250 | 8/10/4/30 |

Archived as `corpus_holdout_v1.json`. Three consecutive runs produced
byte-identical output (sha256 `be8ba0e6…`), so this number is now a fixed point:
any future change to it is attributable to the detector.

Compare with the Phase A live holdout run (F1 0.526, FPR 0.278) — close, but the
live figure was computed over a negative class that partly failed to fetch,
whereas the replayed figure scores all 40 recorded negatives.

### A defect this surfaced

The first replay attempt reported **precision 1.000, FPR 0.000, tn 0**. The
evaluator was regenerating random negatives at scoring time rather than reading
them from the corpus, so every negative URL missed the corpus and was dropped as
a fetch error. The negative class was empty and FPR was a division over nothing.

Fixed: with `--corpus`, the corpus supplies the evaluation set
(`ReplayFetcher.eval_jobs`). `tests/test_corpus.py::test_eval_jobs_hit_the_corpus_exactly`
guards it. **Any live-web OSINT benchmark that generates negatives independently
of what it managed to fetch has this bug**, and it inflates precision silently.

## Page drift: why the corpus is necessary

`replay_equivalence.json`. 24 corpus URLs re-fetched live and compared feature
vector by feature vector against their stored bodies (`response_time` excluded).

| | |
|---|---|
| Sampled | 24 |
| Live fetch failed (excluded) | 2 |
| Compared | 22 |
| **Identical feature vectors** | **12 (54.5%)** |
| **Changed feature vectors** | **10 (45.5%)** |
| Harness mismatches | **0** |

Two findings:

1. **Replay is faithful.** Zero cases of identical bytes yielding different
   features, so the replay path and the live path are equivalent and a replayed
   evaluation measures the detector, not the harness.
2. **Live-web evaluation is not stable enough to measure a detector.** Within
   *hours* of capture, 45.5% of comparable pages produced a different feature
   vector — `scratch` moved 10 of 30 features, `medium`, `patreon`, `vimeo` and
   `codewars` 7 each. Drift was not confined to noisy scalars like
   `content_length`: `error_keyword_count`, `profile_section_count` and
   `error_section_count` all moved, and those directly drive detection.

That second result stands on its own as a methodological argument: a same-day
re-run of any live username-enumeration benchmark can shift the inputs to nearly
half its evaluation set. Reported accuracy differences smaller than that drift
are not interpretable.

Caveat: 22 comparisons on one connection. Directionally strong, not a precise
drift rate — measuring that properly needs repeated captures on a schedule.

---

# Phase D — baselines and ablations

`ablations_all_v1.json`, `ablations_holdout_v1.json`, `pairwise_v1.json`.
Every configuration scored over the **same** corpus rows, with features extracted
once and shared, so differences are attributable to the configuration alone.

```bash
aliens_eye eval ablate --corpus paper/corpus/v1 --split all --out paper/baselines/ablations_all_v1.json
```

## Results (corpus v1, all 43 sites, 151 usable rows: 39 pos / 112 neg)

| Configuration | P | R | F1 | F1 95% CI | FPR | Maybe | vs shipped |
|---|---|---|---|---|---|---|---|
| status_only | 0.400 | 0.821 | 0.538 | 0.42–0.64 | 0.429 | 0.000 | −0.031 ns |
| status_not_404 | 0.352 | 0.949 | 0.514 | 0.41–0.61 | 0.607 | 0.000 | −0.055 ns |
| heuristic_only | 0.349 | 0.974 | 0.513 | 0.41–0.61 | 0.634 | 0.093 | −0.056 ns |
| **ml_only** | **0.758** | 0.641 | **0.694** | 0.55–0.81 | **0.071** | 0.503 | **+0.126** |
| blended_shipped *(as released)* | 0.429 | 0.846 | 0.569 | 0.45–0.67 | 0.393 | 0.285 | reference |
| no_dom | 0.415 | 0.872 | 0.562 | 0.44–0.67 | 0.429 | 0.265 | −0.007 ns |
| no_keywords | 0.418 | 0.846 | 0.559 | 0.44–0.66 | 0.411 | 0.238 | −0.010 ns |
| no_size | 0.440 | 0.846 | 0.579 | 0.46–0.68 | 0.375 | 0.298 | +0.010 ns |
| no_status | 0.394 | 0.718 | 0.509 | 0.39–0.62 | 0.384 | 0.530 | −0.060 ns |
| no_structured_data | 0.421 | 0.821 | 0.556 | 0.43–0.66 | 0.393 | 0.291 | −0.012 ns |
| no_timing | 0.440 | 0.846 | 0.579 | 0.46–0.68 | 0.375 | 0.298 | +0.010 ns |
| no_url_shape | 0.444 | 0.718 | 0.549 | 0.42–0.66 | 0.312 | 0.338 | −0.020 ns |

`ns` = the 95% paired-bootstrap CI on the F1 difference spans zero, i.e. this
corpus cannot distinguish that configuration from the shipped blend. CIs are
percentile bootstrap, 2000 resamples; comparisons are **paired** because every
configuration scores the same rows.

## Pairwise comparisons (4000 resamples)

| Baseline → Candidate | ΔF1 | 95% CI | Verdict |
|---|---|---|---|
| status_only → **ml_only** | **+0.157** | [+0.033, +0.275] | **separable** |
| status_only → blended_shipped | +0.031 | [−0.019, +0.084] | not separable |
| status_only → heuristic_only | −0.024 | [−0.087, +0.045] | not separable |
| heuristic_only → **ml_only** | **+0.181** | [+0.042, +0.309] | **separable** |
| blended_shipped → **ml_only** | **+0.126** | [+0.006, +0.238] | **separable** |
| status_not_404 → **ml_only** | **+0.181** | [+0.035, +0.313] | **separable** |

## What this establishes

**1. The thesis survives — but only for the model, not for the shipped system.**
`ml_only` beats the naive status check by +0.157 F1 with a CI clear of zero. So
"structural-feature classification outperforms status-code heuristics" is a
supportable claim. **The system as released does not support it**:
`blended_shipped` vs `status_only` is +0.031, CI spanning zero. Shipping a blend
that cannot be distinguished from `if status == 200` is the single most
important thing this evaluation found.

**2. The heuristic engine is dead weight, and worse.** `heuristic_only` scores
F1 0.513 at **FPR 0.634** with recall 0.974 — it calls almost everything Found.
It is not distinguishable from a status check (−0.024, ns). Because the shipped
blend gives it 40% of the vote, it drags the model down: removing it entirely
(`blended_shipped → ml_only`) is a **significant +0.126 F1 improvement** and cuts
FPR from 0.393 to 0.071. The blend weight is not a tuning detail; it is actively
costing accuracy.

**3. No feature group is individually significant.** Every `no_*` row is `ns`.
Notably `no_size` and `no_timing` both score *above* the full blend (+0.010, ns) —
`content_length`, `text_length` and `response_time` look like noise features
rather than signal, which is what one expects from 30 features fit on 368 samples
at `C=0.01`. Not yet conclusive; it is a hypothesis for Phase E to test on the
expanded corpus.

**4. Abstention is doing real work, and must be reported.** `ml_only` reaches
precision 0.758 partly by returning Maybe on **50.3%** of rows. That is a defensible
design for an investigative tool — abstaining beats guessing — but a precision
figure quoted without the Maybe rate beside it would be misleading. This is why
the harness reports both.

## Threats to validity

- **151 rows, 39 positives.** CIs are wide (`ml_only` F1 spans 0.55–0.81). The
  separable results are directional, not precise.
- **81 of 232 rows excluded** as capture errors — metrics are conditioned on a
  site being reachable from one machine on one day.
- **Site-disjoint holdout is smaller still** (52 rows), and on it *nothing* is
  separable, including `ml_only`. The significant results above come from the
  full 43-site corpus, which includes the sites the model trained on. **The
  headline comparisons are therefore not yet clean generalization claims** —
  they need the Phase C expansion before they can be reported as such.
- Plausible negatives are unverified (see `paper/corpus/README.md`).

## Still outstanding: external tool baselines (D1)

`status_only` and `status_not_404` are faithful implementations of the naive
strategy, **not** of Sherlock, Maigret, WhatsMyName or Blackbird. Those tools
carry per-site detection rules in their own data files, so comparing against them
over the frozen corpus means vendoring their rule sets and applying them offline —
which is the right method (it isolates detection logic from HTTP client
behaviour) but pulls in third-party data and licence questions not yet resolved.
Until that is done, **this evaluation has no external baseline** and should not
claim one.

## Recommendation

Change the shipped blend to drop the heuristic vote, or retune it. The evidence
for `ml_weight = 1.0` over the current `0.6` is the strongest signal in this
evaluation (+0.126 F1, FPR 0.393 → 0.071). This has **not** been applied: it
changes runtime behaviour for every user of the tool, and rests on 151 rows from
a 43-site corpus with 35% capture attrition. It should be re-confirmed on the
Phase C corpus before shipping.

---

# Phase D1 — external tool baselines

`external_v1.json`. Sherlock's and WhatsMyName's **actual per-site rules**, applied
to the **same stored responses** our detector sees. This isolates detection logic
from HTTP client behaviour, retry policy, and which sites happened to be reachable.

```bash
# Rule data is not vendored — fetch it yourself and mind its licence.
curl -o sherlock.json https://raw.githubusercontent.com/sherlock-project/sherlock/master/sherlock_project/resources/data.json
curl -o wmn.json      https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json

aliens_eye eval external --corpus paper/corpus/v1 --split all \
    --sherlock sherlock.json --whatsmyname wmn.json --out paper/baselines/external_v1.json
```

Sherlock: MIT. WhatsMyName: CC BY-SA 4.0, © Micah Hoffman et al. Neither is
redistributed here. The result bundle records each file's sha256.

## Sherlock (475 rules; covers 42 of our 43 sites; decides 151/151 rows)

| Detector | P | R | F1 | FPR | ΔF1 vs Sherlock | 95% CI |
|---|---|---|---|---|---|---|
| **Sherlock** | 0.453 | 0.872 | **0.597** | 0.366 | reference | |
| ours: status_only | | | 0.538 | | −0.059 | [−0.119, −0.005] **separable** |
| ours: heuristic_only | | | 0.513 | | −0.083 | [−0.146, −0.017] **separable** |
| ours: blended_shipped | | | 0.569 | | −0.028 | [−0.107, +0.048] ns |
| ours: ml_only | | | 0.694 | | +0.098 | [−0.040, +0.226] ns |

Rule types exercised on our rows: 140 `status_code`, 70 `message`, 17 `response_url`.

## WhatsMyName (688 rules; covers 32 of our 43 sites; decides only 24/151 rows)

| Detector | P | R | F1 | FPR | ΔF1 vs WMN | 95% CI |
|---|---|---|---|---|---|---|
| **WhatsMyName** | 0.889 | 1.000 | **0.941** | 0.062 | reference | |
| ours: status_only | | | 0.727 | | −0.214 | [−0.434, −0.062] **separable** |
| ours: heuristic_only | | | 0.696 | | −0.245 | [−0.474, −0.082] **separable** |
| ours: blended_shipped | | | 0.800 | | −0.141 | [−0.333, +0.000] ns |
| ours: ml_only | | | 0.824 | | −0.118 | [−0.333, +0.000] ns |

WMN scores 0.941 but **abstains on 84% of the corpus** — 29 rows have no rule and
98 more match neither the `e_string`/`e_code` nor `m_string`/`m_code` side. Its
number is computed on a self-selected subset of rows where its markers matched
cleanly. That subset is genuinely easier (our `ml_only` gets 0.824 there versus
0.694 overall), but it is not entirely a selection effect: WMN still leads on the
same rows.

## The finding that matters

**This tool does not beat curated per-site rules, and the paper cannot claim it
does.** `ml_only` is nominally ahead of Sherlock (+0.098) but the CI spans zero.
`blended_shipped` — the system as actually released — is nominally *behind*
Sherlock (−0.028, ns). Against WhatsMyName, every configuration we have is behind
on WMN's covered rows.

That kills the framing "ML-blended detection beats existing OSINT tooling". What
survives is narrower and, arguably, more interesting:

> A generic structural classifier with **no per-site rules** performs
> indistinguishably from Sherlock's 475 hand-curated ones on the sites where
> those rules exist — and unlike them, it is defined on all 840 sites in the
> catalogue, and does not decay when a platform changes its markup.

That claim is supported by two results already in hand: the statistical tie with
Sherlock above, and the Phase B measurement that **45.5% of pages changed their
feature vector within hours**, which is exactly the maintenance burden curated
rules carry and a rule-free classifier does not.

It is also *testable*, and not yet tested. The decisive experiment is the
complement of this one: score both approaches on sites where Sherlock has **no**
rule. Sherlock covers 42 of our 43 ground-truth sites because those sites are
popular; across the full 840-site catalogue its coverage will be far lower. That
experiment needs the Phase C expansion.

## Caveats

- **Reimplemented semantics, not upstream code.** The engines implement the
  documented `errorType` / `e_code` rule vocabularies; where upstream behaviour is
  ambiguous the charitable reading was taken (the one favouring the external
  tool). `tests/test_external.py` pins each interpretation.
- **Rules were fetched 2026-09-06** against a corpus captured the same day, so
  they are well matched in time. A rule set and a corpus from different dates
  would understate the external tool.
- Only Sherlock and WhatsMyName were run. Maigret is supported (same rule
  vocabulary) but was not fetched.
- 151 rows, 39 positives. Same power limits as the rest of Phase D.

---

# Phase C — 428-site corpus, and what it overturns

Corpus v2: 428 sites, 2284 records (572 positive / 1712 negative), 974 distinct
bodies, 978 capture errors (43%). Ground truth cross-sourced with provenance, so
neither external tool is scored on its own tuning set.

**The Phase D findings did not replicate.** They were measured on a 43-site
corpus that included sites the model trained on. On a site-disjoint 142-site
holdout they disappear.

## Ablations — v1 (43 sites) vs v2 holdout (142 sites)

| Configuration | v1 F1 | v1 vs shipped | v2 F1 | v2 95% CI | v2 vs shipped |
|---|---|---|---|---|---|
| status_only | 0.538 | −0.031 ns | 0.538 | 0.46–0.61 | +0.007 ns |
| heuristic_only | 0.513 | −0.056 ns | 0.500 | 0.43–0.57 | −0.031 ns |
| **ml_only** | 0.694 | **+0.126 separable** | 0.546 | 0.45–0.63 | **+0.015 ns** |
| blended_shipped | 0.569 | reference | 0.531 | 0.45–0.60 | reference |

`ml_only`'s significant +0.126 advantage over the shipped blend **vanishes**
(+0.015, ns) once the model is evaluated only on platforms it never trained on.
Its F1 falls 0.694 → 0.546 and its precision 0.758 → 0.595. The Phase D
conclusion — "drop the heuristic, ship ml_weight 1.0" — **is not supported by
this evaluation** and should not be acted on.

More bluntly: on the v2 holdout **no configuration is distinguishable from
`if status == 200`.** Every comparison against the shipped blend is ns except
`no_timing` (+0.023), and with 12 comparisons at 95% confidence roughly one
false positive is expected by chance, so that row is not evidence either.

## External baselines, cross-sourced and non-circular

Sherlock scored only on sites whose accounts came from WhatsMyName or our own
curation (225 self-sourced rows excluded); WhatsMyName likewise (98 excluded).

**Sherlock** — 120 rows, 32% of the holdout:

| Detector | F1 | ΔF1 vs Sherlock | 95% CI |
|---|---|---|---|
| Sherlock | 0.562 | reference | |
| ours: ml_only | 0.613 | +0.051 | [−0.093, +0.194] ns |
| ours: status_only | 0.588 | +0.026 | [−0.054, +0.107] ns |
| ours: blended_shipped | 0.571 | +0.010 | [−0.084, +0.108] ns |
| ours: heuristic_only | 0.522 | −0.039 | [−0.111, +0.037] ns |

**WhatsMyName** — 37 rows, 10% of the holdout (141 no rule, 99 undecided):

| Detector | F1 | ΔF1 vs WMN | 95% CI |
|---|---|---|---|
| WhatsMyName | 0.933 | reference | |
| ours: ml_only | 0.933 | +0.000 | [+0.000, +0.000] ns |
| ours: blended_shipped | 0.667 | −0.267 | [−0.504, −0.089] **separable** |
| ours: status_only | 0.636 | −0.297 | [−0.538, −0.111] **separable** |

`ml_only` produces **identical predictions to WhatsMyName on all 37 rows** — a
zero-width CI, not a near miss. On the narrow subset WMN is willing to decide,
the rule-free classifier and 688 curated rules agree completely.

## Where this leaves the paper

Supportable now:

1. **A rule-free classifier matches curated per-site rules on held-out
   platforms.** Statistically tied with Sherlock on 120 non-circular rows;
   identical to WhatsMyName on the 37 rows it decides. Neither better nor worse —
   but achieved with zero per-site maintenance, and defined on all 840 catalogue
   sites rather than 475 or 688.
2. **Current username-enumeration benchmarks cannot resolve the differences the
   field claims.** On 375 holdout rows, nothing — not ML, not heuristics, not
   curated rules — separates from an HTTP-status baseline.
3. **Live-web evaluation is unstable**: 45.5% of pages changed feature vector
   within hours (Phase B).

Not supportable, and previously overstated here:

- That this tool beats a naive status check. It does not, on held-out sites.
- That dropping the heuristic significantly helps. It does not replicate.
- Any claim resting on the v1 corpus, which was not a generalization test.

## What actually limits this evaluation

Not the detector — the measurement.

- **Capture attrition 43%** (978/2284; 376/751 on the holdout). Half the
  evaluation is thrown away before scoring, and what survives is conditioned on
  being reachable and unblocked from one residential connection on one day.
- **Label noise ≈ 7.6%.** Of 131 independently checkable positives, 10 are
  contradicted by every rule set other than their own source — `fanpop/test`,
  `notabug.org/red`, `mstdn.io/greg` (HTTP 410 Gone). Imported accounts are
  asserted, not verified.
- **Rule coverage is thin on ordinary sites.** Sherlock has rules for only 32% of
  holdout rows, WhatsMyName decides 10%. The comparison rests on a fraction of
  the corpus.

Fixing attrition — multiple vantage points, retries across days, honouring
Retry-After more patiently — is now worth more than any change to the detector.
