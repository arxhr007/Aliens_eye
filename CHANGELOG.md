# Changelog

## 2.3.0 (2026-09-06)

Evaluation and reproducibility release. No change to detection behaviour: the shipped
model, blend weights and thresholds are untouched.

### Added
- **Frozen response corpus** (`aliens_eye corpus record` / `corpus stats`). Captures raw
  responses once and replays them through the same fetch path a scan uses, so detector
  evaluation is reproducible — the same corpus yields byte-identical results regardless
  of what platforms do afterwards. Bodies are content-addressed and deduplicated.
- **Ablation harness** (`aliens_eye eval ablate`). Scores naive status baselines, each
  judge in isolation, the shipped blend, and per-feature-group ablations over the same
  corpus rows. Reports precision/recall/F1/FPR plus the **Maybe rate**, with
  percentile-bootstrap confidence intervals and paired-bootstrap deltas.
- **External tool baselines** (`aliens_eye eval external`). Runs Sherlock's, Maigret's and
  WhatsMyName's own per-site rules against the same stored responses. Rule data is not
  vendored; pass it by path and mind the upstream licence.
- **Ground-truth builder** (`aliens_eye eval groundtruth`). Expands the ground-truth set
  from those projects' account lists, recording per-site provenance so no tool is ever
  scored on the accounts its own rules were tuned against.
- `selfcheck --split train|holdout|all`, `--corpus`, and `--ground-truth`.
- `FingerprintStore(read_only=True)`, required for deterministic replay.

### Changed
- **Ground truth expanded from 43 to 428 sites** (572 accounts), split site-disjoint into
  train (286 sites) and holdout (142).
- Corpus captures flush incrementally and support resume, so a long run cannot lose
  everything on failure.

### Fixed
- **Train/eval leakage.** Training data and evaluation both derived from
  `data/selfcheck.json`, so reported accuracy was a fit measure presented as a
  generalization measure. Splits are now site-disjoint — by site rather than by account,
  because the detector learns per-site page structure — and `train collect` refuses a
  non-train split without `--allow-leakage`.
- **Documented blend weights did not match the shipped model.** `WORKING.md` stated
  `0.4*ml + 0.6*heuristic` with thresholds 0.6/0.35, while the shipped `model.json`
  carries `ml_weight` 0.6 and thresholds 0.5559/0.3224 and overrides the module constants
  at runtime. Docs corrected and a test now pins them together.

## 2.2.3 (2026-09-06)

### Fixed
- **Scans failed outright on many platforms due to a Brotli decoding error.** The default
  request headers advertised `Accept-Encoding: gzip, deflate, br`, but Brotli was not an
  install dependency, so any server that honoured `br` returned a response the HTTP client
  could not decode (`can not decode content-encoding: brotli (br)`). Affected sites were
  reported as fetch errors rather than checked — a silent, total failure rather than a
  degraded result.

  Measured across a 428-site run, this accounted for 852 of 978 errors, with 173 sites
  failing on every request, including **artstation, bitbucket, anilist, about.me,
  archiveofourown, allmylinks, behance and bandcamp**. All return normal results now.

  Brotli is now a required dependency, and `Accept-Encoding` is built from the codecs that
  are actually importable, so an environment predating this release degrades to
  `gzip, deflate` instead of failing.

## 2.0.0 (2026-06-11)

### Added
- **PyPI package**: `pip install aliens-eye` with `aliens_eye` console command
- **Real ML detection**: logistic-regression model trained on labeled scans, blended with the heuristic engine; pure-python inference with zero ML runtime dependencies
- `aliens_eye train collect` / `aliens_eye train fit` for building datasets and retraining the model
- `aliens_eye selfcheck`: validates detection accuracy against accounts known to exist
- **Rich terminal UI**: live progress bar, sorted result tables, summary panels; `--plain` for scripts
- **Proxy support**: `--proxy` (HTTP/SOCKS4/SOCKS5) and `--tor`
- **Site filtering**: `--site`, `--exclude-site`, `--no-nsfw`
- Markdown report export (`--format md`)
- `--profile quick|full|aggressive` for non-interactive preset selection
- `--version`, `--sites` (custom site list), `--model` (custom model), `--no-ml`
- Dockerfile
- Test suite (pytest) and GitHub Actions CI (lint + tests on Linux/Windows, Python 3.10–3.13)
- Automated PyPI release workflow via trusted publishing

### Changed
- Restructured to a `src/aliens_eye/` package; `sites.json` and the model ship as package data
- Playwright is now an optional extra: `pip install aliens-eye[browser]`
- Fingerprint cache and config moved to platform-standard directories (via `platformdirs`)
- Confidence is now derived from a calibrated probability instead of fixed score bands

### Removed
- Hardcoded `/etc`, `/usr/local`, and Termux path probing
- Dead `mumble://` site entry

### Compatibility
- `python aliens_eye.py` from a source checkout still works
