import json
from pathlib import Path

from aliens_eye.cli import (
    TOR_PROXY,
    apply_cli_overrides,
    apply_config,
    apply_scan_profile,
    build_parser,
    load_config,
    parse_formats,
    parse_formats_value,
    parse_site_list,
)
from aliens_eye.core.config import ScannerConfig


def parse(argv):
    return build_parser().parse_args(argv)


def test_parse_formats():
    assert parse_formats("json,csv") == ["json", "csv"]
    assert parse_formats("ALL,json") == ["all"]
    assert parse_formats("") == ["json"]
    assert parse_formats_value(None) == ["json"]
    assert parse_formats_value(["json", "md"]) == ["json", "md"]


def test_parse_site_list():
    assert parse_site_list("github, reddit") == ["github", "reddit"]
    assert parse_site_list(None) is None
    assert parse_site_list(" , ") is None


def test_apply_config_overrides_fields():
    config = ScannerConfig()
    defaults = apply_config(
        config,
        {
            "concurrent": 10,
            "timeout": 3.5,
            "output_dir": "out",
            "level": "advanced",
            "output_formats": ["csv"],
            "proxy": "http://localhost:8080",
        },
    )
    assert config.concurrent == 10
    assert config.timeout == 3.5
    assert config.output_dir == Path("out")
    assert config.proxy == "http://localhost:8080"
    assert defaults["level"] == "advanced"
    assert defaults["output_formats"] == ["csv"]


def test_cli_overrides_beat_config():
    config = ScannerConfig()
    apply_config(config, {"concurrent": 10})
    args = parse(["user", "-c", "99", "--tor", "--no-ml", "--no-nsfw", "--site", "github"])
    apply_cli_overrides(config, args)
    assert config.concurrent == 99
    assert config.proxy == TOR_PROXY
    assert config.use_ml is False
    assert config.exclude_nsfw is True
    assert config.include_sites == ["github"]


def test_proxy_flag():
    config = ScannerConfig()
    args = parse(["user", "--proxy", "socks5://127.0.0.1:1080"])
    apply_cli_overrides(config, args)
    assert config.proxy == "socks5://127.0.0.1:1080"


def test_scan_profile_quick():
    config = ScannerConfig()
    args = parse(["user"])
    apply_scan_profile(config, "quick", args)
    assert config.concurrent == 25
    assert config.use_playwright is False


def test_scan_profile_respects_cli_args():
    config = ScannerConfig()
    args = parse(["user", "-c", "5"])
    apply_cli_overrides(config, args)
    apply_scan_profile(config, "aggressive", args)
    assert config.concurrent == 5
    assert config.use_playwright is True


def test_load_config_explicit_path(tmp_path, logger):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"concurrent": 7}), encoding="utf-8")
    assert load_config(str(path), logger) == {"concurrent": 7}


def test_load_config_missing_returns_empty(tmp_path, logger):
    assert load_config(str(tmp_path / "nope.json"), logger) == {}
