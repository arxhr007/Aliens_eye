# Changelog

## 2.5.0 (2026-09-18)

### Fixed
- **`--correlate` merged almost everything into one "same person" cluster.** Correlation
  linked two profiles when one bio @-mentioned the handle the other was found under. In a
  scan of a single handle, every profile was found under that handle, and many sites echo it
  in page chrome (Twitter: *"The latest posts from @handle"*). One such page therefore linked
  itself to every other profile: a live scan produced a 228-profile cluster, 227 of whose
  links ran through Twitter alone. Mentions of a searched handle no longer count. Two bios
  mentioning the same *other* handle still link, as does a mention across two different
  searched handles.
- Display names that are just the site's brand (og:title "Flickr" on `flickr.albums`) no
  longer link sibling pages of the same service.

### Added
- `aliens_eye.api.correlate()` also returns `profiles`: every profile considered, with its
  avatar hash, so callers can apply their own linkage rules on top of the clusters.

## 2.4.0 (2026-09-18)

### Security
- **`--correlate` fetched attacker-chosen URLs (SSRF).** Avatar URLs are scraped from the
  target's own page (`og:image`, JSON-LD, favicon, per-site selectors), so whoever controls
  that page chooses them, and they were requested with no validation. A hostile profile could
  point its avatar at a cloud metadata endpoint, an intranet host, or a service on the
  analyst's own loopback. Avatar URLs are now limited to `http`/`https` and must resolve to
  public addresses. Upgrade if you use `--correlate`.

### Added
- **`aliens_eye.api`**, a stable programmatic API (`scan`, `correlate`, `load_sites`) for
  building other tools on Aliens Eye. It returns plain dicts shaped like the JSON report,
  prints nothing by default, and never writes into the caller's working directory.
- `UsernameScanner` accepts an `on_result(username, result)` progress hook (sync or async)
  and an injectable `console`.

### Fixed
- Sites whose response headers exceed 8190 bytes (e.g. trakt.tv) failed on every request
  with `Got more than 8190 bytes when reading`. The limit is now 64 KB.
- `--watch nan` and `--watch inf` were accepted: NaN slips past a `<= 0` check because every
  comparison with it is false. Durations must now be positive and finite.

### Changed
- The MCP server now uses `aliens_eye.api`, and routes console output to stderr for the
  whole process, not just during scans.

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
