# Frozen response corpus

Captured HTTP responses for the ground-truth accounts, so detector evaluation is
reproducible: the same corpus yields byte-identical metrics today and in a year,
whatever the platforms have since done to their markup.

Without this, an accuracy change cannot be attributed to the detector rather than
to the web — which is the single thing that made every earlier number in this
repo unusable as evidence.

## Layout

```
v1/
  manifest.json              capture metadata: tool version, seed, counts, skipped sites
  records.jsonl              one JSON object per request (labels, status, headers, body digest)
  bodies/<aa>/<sha256>.gz    gzipped response bodies, content-addressed
```

Bodies are content-addressed because error pages repeat: a platform serves one
"no such user" page for every non-existent username. `v1` stores 232 records in
121 distinct bodies.

## `v1`

| | |
|---|---|
| Captured | 2026-09-06 |
| Tool version | 2.2.2 |
| Command | `aliens_eye corpus record --out paper/corpus/v1 --split all --negatives 4 --seed 1234` |
| Sites | 43 (train 30 + holdout 13) |
| Records | 232 — 60 positive, 172 negative |
| Distinct bodies | 121 |
| Capture errors | 81 (35%) |
| On disk | 1.3 MB |

## Distribution

`manifest.json` and `records.jsonl` are versioned in git. **`bodies/` is
gitignored**: it holds third-party page content, including profile pages of real
people. The publication artifact is derived feature vectors plus labels; raw
bodies are available on request. See the ethics section (Phase G).

## Negatives

Negatives come in two kinds, tagged per record in `notes.negative_kind`:

- `random` — 14–20 random alphanumeric characters. Almost certainly absent, but
  an artificially easy negative class: separable on length and character
  distribution alone, which inflates every metric.
- `plausible` — built from ordinary word morphology (`quietfalcon84`,
  `amber_harbor`). Realistic shape, so a detector cannot shortcut on form.

`--plausible-ratio` sets the mix (default 0.5). **Plausible negatives are not
verified absent by construction** — on a large platform one may collide with a
real account. Phase C labelling must check them; until then they carry label 0 on
assumption, and that assumption is a known threat to validity.

## Usage

```bash
# Record
aliens_eye corpus record --out paper/corpus/v1 --split all --negatives 4 --seed 1234

# Inspect
aliens_eye corpus stats paper/corpus/v1

# Evaluate against it — no network, reproducible
aliens_eye selfcheck --split holdout --corpus paper/corpus/v1 --report json
```

The corpus supplies the evaluation set when `--corpus` is given: rows come from
the recorded labels, not from freshly generated usernames. Regenerating them
would produce URLs the corpus never captured, so every negative would miss and
the run would report a false-positive rate computed over an empty negative class.
An earlier version of this work did exactly that and reported a meaningless
`FPR 0.000`.

## Known limitations

1. **Capture attrition.** 81 of 232 requests (35%) failed at capture time —
   timeouts, bot walls, and blocks from a single residential connection. Those
   rows are stored with their error and excluded from scoring, so metrics are
   conditioned on a site being reachable from one machine on one day. Re-capturing
   from multiple vantage points is the fix, and is not yet done.
2. **Scale.** 43 sites of 840, 60 positives. Phase C expands to 200+ sites.
3. **Selection bias.** Positives are high-profile accounts (`torvalds`, `spez`,
   `magnuscarlsen`) whose pages are unusually rich. Real investigative targets
   are ordinary users with sparse pages.
4. **Single snapshot.** One capture, one day. No measurement of how fast platform
   markup drifts, which is itself worth reporting.

---

# Ground truth v2 — cross-sourced expansion

43 sites → **428 sites, 572 accounts**, built from the account lists Sherlock and
WhatsMyName already ship.

```bash
aliens_eye eval groundtruth --sherlock sherlock.json --whatsmyname wmn.json
```

| Split | Sites | Accounts | curated | sherlock | whatsmyname |
|---|---|---|---|---|---|
| train | 286 | 389 | 30 | 171 | 85 |
| holdout | 142 | 183 | 13 | 90 | 39 |

## Why provenance is recorded

Each project's accounts are **its own tuning set**. Sherlock's rules are
maintained so `username_claimed` returns Found; WhatsMyName's `e_string` markers
are chosen against its `known` accounts. Scoring a tool on the accounts its rules
were tuned against measures memorisation, not detection — and would have made
both external baselines look far better than they are.

So every site records its source, sites covered by both projects are alternated
between them, and `eval external` drops a site when scoring the project that
supplied it. Both tools stay measurable: the holdout has 90 Sherlock-sourced
sites (used to score WhatsMyName) and 39 WhatsMyName-sourced ones (used to score
Sherlock). The 43 originally curated sites are scoreable against either.

## Label quality — the main open risk

Imported accounts are **asserted by their source project, not verified here**.
220 of Sherlock's 481 handles are generic placeholders (`blue`, `red`, `user`).
Some certainly do not exist, and a false positive in ground truth is worse than a
missing site: it teaches the model that an absent-user page is a profile.

Mitigations in place:

- Every imported entry carries `verified: false` and flags placeholder handles.
- `verify_positives()` cross-checks each imported positive against every rule set
  **other than its own source** and reports positives that all independent rules
  call absent. These are candidates for review, not automatic deletions — a rule
  can be stale, and deleting on one signal would silently bias the set.

What this does **not** give is a human-rated sample or a Cohen's κ, which a
forensics venue will expect. The honest position: this is a machine-corroborated
set, and the paper must describe it that way rather than as verified ground
truth. A hand-labelled subsample is still required.

## Licensing of the derived set

The ground truth mixes MIT (Sherlock) and CC BY-SA 4.0 (WhatsMyName) material.
The WhatsMyName-derived portion carries attribution and share-alike; provenance
is recorded per site precisely so the obligations can be honoured per entry
rather than assumed across the whole file. Neither upstream data file is
redistributed here.
