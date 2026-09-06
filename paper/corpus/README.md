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
