<h1 align="center">ALIENS EYE</h1>

<div align="center">
  <img src="https://raw.githubusercontent.com/arxhr007/Aliens_eye/main/photos/logo.png"
       alt="Aliens Eye Logo"
       width="400"
       height="300">
</div>

<h1 align="center">AI-OSINT Username Scanner</h1>

<h3 align="center">Advanced AI-Powered Social Media Username Finder</h3>
<h4 align="center">Scan 840+ platforms with ML-blended detection</h4>

<p align="center">
<a href="https://pypi.org/project/aliens-eye/"><img alt="PyPI" src="https://img.shields.io/pypi/v/aliens-eye?style=for-the-badge&color=blue"></a>
<a href="https://github.com/arxhr007/Aliens_eye/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/arxhr007/Aliens_eye/ci.yml?style=for-the-badge"></a>
<a href="#"><img alt="Python" src="https://img.shields.io/pypi/pyversions/aliens-eye?style=for-the-badge"></a>
<a href="#"><img alt="Stars" src="https://img.shields.io/github/stars/arxhr007/Aliens_eye?style=for-the-badge&color=red"></a>
<a href="#"><img alt="License" src="https://img.shields.io/github/license/arxhr007/Aliens_eye?color=orange&style=for-the-badge"></a>
</p>

<!-- TODO: record a demo GIF (e.g. with vhs or asciinema) and drop it at docs/demo.gif -->
<!-- <p align="center"><img src="docs/demo.gif" width="700"></p> -->

## Highlights

- **840+ platforms** scanned asynchronously in seconds
- **ML + heuristic detection** — a trained model blended with 25 structural signals (HTTP status, DOM shape, keywords, fingerprints) instead of naive status-code checks
- **Modern terminal UI** — live progress, sorted result tables, summary panels (powered by [rich](https://github.com/Textualize/rich))
- **Proxy & Tor support** — `--proxy socks5://...` or just `--tor`
- **Site filtering** — `--site github,reddit`, `--exclude-site`, `--no-nsfw`
- **Self-check** — `aliens_eye selfcheck` validates detection accuracy against accounts known to exist
- **Retrainable** — collect your own labeled dataset and retrain the model with `aliens_eye train`
- **Reports** in JSON, CSV, HTML, and Markdown
- **Playwright fallback** for JavaScript-heavy pages (optional extra)

## Install

```bash
pip install aliens-eye
```

Optional extras:

```bash
pip install "aliens-eye[browser]"   # Playwright fallback for hard pages
python -m playwright install chromium

pip install "aliens-eye[train]"     # scikit-learn, for retraining the ML model
```

Or with Docker:

```bash
docker build -t aliens-eye .
docker run --rm -it aliens-eye username
```

From source:

```bash
git clone https://github.com/arxhr007/Aliens_eye.git
cd Aliens_eye
pip install -e .
```

## Usage

```bash
# Interactive prompts
aliens_eye

# Single username
aliens_eye username

# Multiple usernames
aliens_eye username1 username2

# Advanced scan level (prefix/suffix variations)
aliens_eye username -l advanced

# Only scan specific sites
aliens_eye username --site github,reddit,gitlab

# Skip NSFW sites
aliens_eye username --no-nsfw

# Route through Tor (needs a local Tor daemon)
aliens_eye username --tor

# Any HTTP or SOCKS proxy
aliens_eye username --proxy socks5://127.0.0.1:1080

# Export everything
aliens_eye username --format all --output results

# Heuristics only, no ML
aliens_eye username --no-ml

# Non-interactive preset: quick / full / aggressive
aliens_eye username --profile quick

# Plain output for scripts and CI (no colors/progress)
aliens_eye username --plain

# View results from a previous scan
aliens_eye -r results/username_advanced_20260611_120000.json

# Validate detection accuracy against known accounts
aliens_eye selfcheck
```

## How detection works

Every response is converted into a 25-dimensional feature vector: HTTP status buckets, username placement (path/title/meta), error and profile keywords, DOM structure (images, forms, profile/error CSS classes), response timing, redirect counts, and per-site fingerprint matches learned from previous scans.

Two judges then vote:

1. **Heuristic engine** — weighted scoring over the features
2. **ML model** — logistic regression trained on labeled scans of real (and deliberately fake) accounts, shipped with the package and running in pure Python (no sklearn needed at runtime)

The blended probability maps to **Found / Maybe / Not Found** with a confidence percentage. If a model file is missing or invalid, the scanner silently falls back to heuristics.

### Retraining the model

```bash
pip install "aliens-eye[train]"

# 1. Scan ground-truth accounts + random non-existent usernames to build a dataset
aliens_eye train collect --out dataset.csv --negatives 4

# 2. Fit and export the model
aliens_eye train fit --data dataset.csv --out model.json

# 3. Use it
aliens_eye username --model model.json
```

## Configuration

Aliens Eye merges a JSON config file with CLI flags (CLI wins). Search order without `--config`: `./config.json`, then the platform config dir (e.g. `~/.config/aliens_eye/config.json` on Linux, `%LOCALAPPDATA%\aliens_eye` on Windows).

```json
{
  "concurrent": 50,
  "timeout": 10.0,
  "retries": 2,
  "rate_limit_delay": 0.2,
  "output_dir": "results",
  "output_formats": ["json", "csv", "html", "md"],
  "use_playwright": false,
  "proxy": null,
  "use_ml": true,
  "exclude_nsfw": false,
  "level": "basic"
}
```

## Outputs

Results are saved with timestamped filenames:

- `username_level_YYYYMMDD_HHMMSS.json` — full detail including per-site feature analysis
- `.csv` — flat rows for spreadsheets
- `.html` — styled standalone report
- `.md` — Markdown summary of Found/Maybe hits

## Architecture

The package lives under `src/aliens_eye/`: `core/` (scanner, detector, analyzer, http, exporter, fingerprints), `ml/` (inference, training, dataset collection), `utils/` (rich console layer), and `data/` (sites.json, trained model, ground-truth sets). For internals and flowcharts, see [WORKING.md](WORKING.md).

## Contributing

Issues and PRs welcome — adding sites to `src/aliens_eye/data/sites.json`, expanding the ground-truth set in `selfcheck.json`, or improving the model all directly improve detection. Run `pytest` and `ruff check src tests` before submitting.

## Disclaimer

This tool is for educational purposes and legitimate OSINT research only. You are responsible for complying with laws and site terms of service.
