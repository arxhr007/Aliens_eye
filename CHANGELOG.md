# Changelog

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
