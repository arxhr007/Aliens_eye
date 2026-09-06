import json
import re
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


def test_accept_encoding_only_advertises_decodable_encodings():
    """Advertising br without a decoder is a hard failure, not a degradation.

    Regression: DEFAULT_HEADERS hardcoded "gzip, deflate, br" while Brotli was
    not a dependency, so every server that honoured br returned a body aiohttp
    raised on. That was 852 of 978 capture errors across a 428-site run, with
    173 sites failing completely.
    """
    from aliens_eye.core.config import DEFAULT_HEADERS

    encodings = {e.strip() for e in DEFAULT_HEADERS["Accept-Encoding"].split(",")}
    assert "gzip" in encodings and "deflate" in encodings

    try:
        import brotli  # noqa: F401
        decoder = True
    except ImportError:
        try:
            import brotlicffi  # noqa: F401
            decoder = True
        except ImportError:
            decoder = False

    assert ("br" in encodings) == decoder, (
        "Accept-Encoding advertises br without an importable Brotli decoder"
        if not decoder else
        "Brotli is installed but br is not advertised"
    )


def _pyproject_text() -> str:
    return (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def _declared_dependencies() -> list[str]:
    """Requirement strings from [project].dependencies.

    Parsed with a regex rather than tomllib: tomllib is 3.11+, and this project
    supports 3.10. Only the quoted requirements are returned, so a comment
    mentioning a package name inside the array does not count as declaring it.
    """
    block = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", _pyproject_text(), re.M | re.S)
    assert block, "could not locate [project].dependencies in pyproject.toml"
    return [match.lower() for match in re.findall(r'"([^"]+)"', block.group(1))]


def _declared_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', _pyproject_text(), re.M)
    assert match, "could not locate [project].version in pyproject.toml"
    return match.group(1)


def test_brotli_is_a_declared_dependency():
    """It is required, not an extra: the default headers depend on it."""
    assert any(dep.startswith("brotli") for dep in _declared_dependencies())


def test_package_version_matches_pyproject():
    """__version__ and pyproject must agree.

    Regression: 2.2.3 was built with pyproject bumped but
    src/aliens_eye/__init__.py left at 2.2.2, so the installed package reported
    the previous version. __version__ is what `--version` prints and what the
    corpus manifest records as tool_version, so a stale value silently
    mislabels captured research data.
    """
    from aliens_eye import __version__

    assert __version__ == _declared_version()
