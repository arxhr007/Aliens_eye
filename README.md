<h1 align="center">ALIENS EYE</h1>

<div align="center">
  <img src="https://raw.githubusercontent.com/arxhr007/Aliens_eye/main/photos/logo.png" 
       alt="Aliens Eye Logo" 
       width="400" 
       height="300">
</div>


<h1 align="center">AI-OSINT Username Scanner</h1>


<h3 align="center">Advanced AI-Powered Social Media Username Finder</h3>
<h4 align="center">Scan 840+ platforms with intelligent detection</h4>

<p align="center">
<a href="#"><img alt="Forks" src="https://img.shields.io/github/forks/BLINKING-IDIOT/Aliens_eye?style=for-the-badge"></a>
<a href="#"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/BLINKING-IDIOT/Aliens_eye/main?color=green&style=for-the-badge"></a>
<a href="#"><img alt="Stars" src="https://img.shields.io/github/stars/BLINKING-IDIOT/Aliens_eye?style=for-the-badge&color=red"></a>
<a href="#"><img alt="License" src="https://img.shields.io/github/license/BLINKING-IDIOT/Aliens_eye?color=orange&style=for-the-badge"></a>
<a href="https://github.com/BLINKING-IDIOT/Aliens_eye/issues"><img alt="Issues" src="https://img.shields.io/github/issues/BLINKING-IDIOT/Aliens_eye?color=purple&style=for-the-badge"></a>
</p>

## Highlights

- Async scanning across a large platform catalog from sites.json
- Feature extraction with selectolax instead of fragile regex
- Heuristic detection with confidence scoring
- JSON, CSV, and HTML reports
- Playwright fallback for hard pages

## Requirements

- Python 3.10+
- Required packages: aiohttp, selectolax, playwright
- Internet connection

## Install

### Linux

```bash
# Clone the repository
git clone https://github.com/arxhr007/Aliens_eye.git
cd Aliens_eye

# Upgrade pip
python3 -m pip install --upgrade pip

# Install dependencies
python3 -m pip install -r requirements.txt

# Install Playwright browser binaries
python3 -m playwright install --with-deps
```

### Windows (PowerShell)

```powershell
git clone https://github.com/arxhr007/Aliens_eye.git
cd Aliens_eye

# Upgrade pip
py -m pip install --upgrade pip

# Install dependencies
py -m pip install -r requirements.txt

# Install Playwright browser binaries
py -m playwright install
```
### Run

After installation, run the scanner from the project directory.

Linux / iSH:

```bash
cd Aliens_eye
python3 aliens_eye.py username
```

Windows (PowerShell):

```powershell
cd Aliens_eye
py .\aliens_eye.py username
```

## Configuration

Aliens Eye reads a JSON config file and merges it with CLI flags. CLI flags always win.

Search order when no --config is provided:
- ./config.json
- <script_dir>/config.json
- /etc/aliens_eye/config.json
- /usr/local/etc/aliens_eye/config.json
- /data/data/com.termux/files/usr/etc/aliens_eye/config.json

Example config.json:

```json
{
  "concurrent": 50,
  "timeout": 10.0,
  "max_content_bytes": 100000,
  "retries": 2,
  "backoff_base": 0.5,
  "backoff_cap": 8.0,
  "jitter": 0.2,
  "rate_limit_delay": 0.2,
  "fingerprints_path": "cache/fingerprints.json",
  "output_dir": "results",
  "output_formats": ["json", "csv", "html"],
  "use_playwright": false,
  "max_fingerprints_per_label": 50,
  "level": "basic"
}
```

## Usage

```bash
# Interactive prompts
aliens_eye

# Single username
aliens_eye username

# Multiple usernames
aliens_eye username1 username2

# Advanced scan level
aliens_eye username -l advanced

# Limit concurrency
aliens_eye username -c 30

# Enable verbose logs
aliens_eye username -v

# Use a custom config file
aliens_eye --config config.json username

# Export CSV + HTML in addition to JSON
aliens_eye username --format json,csv,html --output results

# Enable Playwright fallback for Maybe results
aliens_eye username --playwright

# View results from a previous scan
aliens_eye -r results/username_advanced_20250514_120000.json
```

If you run from source, call:

```bash
python aliens_eye.py username
```

## Outputs

Results are saved to the output directory with timestamped filenames:

- JSON: username_level_YYYYMMDD_HHMMSS.json
- CSV: username_level_YYYYMMDD_HHMMSS.csv
- HTML: username_level_YYYYMMDD_HHMMSS.html

## Architecture

Core modules live under core/ (scanner, detector, analyzer, http, exporter). Utilities are in utils/. For internals and flowcharts, see WORKING.md.

## Disclaimer

This tool is for educational purposes and legitimate OSINT research only. You are responsible for complying with laws and site terms of service.
