import json

from aliens_eye.core.scanner import filter_sites, load_nsfw_sites, load_sites_data
from aliens_eye.ml.collect import load_selfcheck_data

SITES = {
    "github": "https://github.com/{}",
    "gitlab": "https://gitlab.com/{}",
    "reddit": "https://www.reddit.com/user/{}",
    "pornhub": "https://example.org/{}",
}


def test_include_filter():
    result = filter_sites(SITES, include=["git"])
    assert set(result) == {"github", "gitlab"}


def test_exclude_filter():
    result = filter_sites(SITES, exclude=["git"])
    assert set(result) == {"reddit", "pornhub"}


def test_include_and_exclude():
    result = filter_sites(SITES, include=["git"], exclude=["lab"])
    assert set(result) == {"github"}


def test_case_insensitive():
    result = filter_sites(SITES, include=["GitHub"])
    assert set(result) == {"github"}


def test_no_filters_returns_all():
    assert filter_sites(SITES) == SITES


def test_packaged_sites_load_and_valid():
    sites = load_sites_data()
    assert len(sites) > 800
    for name, template in sites.items():
        assert isinstance(template, str)
        assert template.startswith("http"), f"{name} has invalid template"


def test_custom_sites_path(tmp_path):
    path = tmp_path / "sites.json"
    path.write_text(json.dumps(SITES), encoding="utf-8")
    assert load_sites_data(path) == SITES


def test_nsfw_list_subset_of_sites():
    sites = load_sites_data()
    nsfw = load_nsfw_sites()
    assert nsfw
    missing = [name for name in nsfw if name not in sites]
    assert not missing, f"NSFW entries missing from sites.json: {missing}"


def test_selfcheck_sites_exist():
    sites = load_sites_data()
    selfcheck = load_selfcheck_data("all")
    missing = [site for site in selfcheck if site not in sites]
    assert not missing, f"selfcheck entries missing from sites.json: {missing}"
    for site, usernames in selfcheck.items():
        assert usernames, f"{site} has no usernames"


def test_ground_truth_splits_are_site_disjoint():
    """The train split and the eval holdout must share no site.

    This is the guard against the train/eval leak: training reads
    data/selfcheck.json and evaluation reads data/eval_holdout.json, so any
    overlap means the detector is scored on platforms it trained on.
    """
    train = set(load_selfcheck_data("train"))
    holdout = set(load_selfcheck_data("holdout"))
    overlap = train & holdout
    assert not overlap, f"train/holdout splits overlap on: {sorted(overlap)}"
    assert train and holdout


def test_ground_truth_all_split_is_the_union():
    train = set(load_selfcheck_data("train"))
    holdout = set(load_selfcheck_data("holdout"))
    assert set(load_selfcheck_data("all")) == train | holdout


def test_unknown_split_rejected():
    import pytest

    with pytest.raises(ValueError, match="Unknown ground-truth split"):
        load_selfcheck_data("nope")
