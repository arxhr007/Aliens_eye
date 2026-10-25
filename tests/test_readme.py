"""The README's images and links: a broken image looks bad on the front page of the project."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text("utf-8")
RAW = re.compile(r"https://raw\.githubusercontent\.com/arxhr007/Aliens_eye/(?:refs/heads/)?main/([^\s\"')]+)")


def test_every_image_the_readme_loads_from_this_repo_exists():
    paths = {match.group(1).replace("%20", " ") for match in RAW.finditer(README)}
    assert paths, "the README is expected to reference some images"
    missing = sorted(p for p in paths if not (ROOT / p).is_file())
    assert missing == []


def test_the_lxask_banner_is_a_clickable_image_that_opens_the_repository():
    match = re.search(
        r'<a href="(https://github\.com/arxhr007/lxask)">\s*<img[^>]*src="[^"]*lxask-banner\.png"[^>]*>\s*</a>',
        README,
    )
    assert match, "expected the banner image wrapped in a link to lxask"
    assert 'alt="' in match.group(0) and 'alt=""' not in match.group(0)       # readable without the image


def test_the_banner_sits_in_the_lxask_section():
    section = README.split("New from the author: lxask", 1)[1].split("\n---", 1)[0]
    assert "lxask-banner.png" in section and "https://github.com/arxhr007/lxask" in section


def test_the_banner_file_is_a_png_of_a_sensible_size():
    data = (ROOT / "photos" / "lxask-banner.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) < 500_000                                   # it ships in every checkout
