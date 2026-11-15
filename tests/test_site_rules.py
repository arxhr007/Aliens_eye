import json

import pytest
from test_scanner import make_scanner

from aliens_eye.core.http import FetchResult
from aliens_eye.core.site_rules import rule_evidence
from aliens_eye.core.sites import SiteCatalog, SiteDefinition


def definition(**changes):
    return SiteDefinition.from_dict("example", {
        "url": "https://profiles.example/{}",
        "probe_url": "https://api.example/users/{}",
        "check_type": "message",
        "presence": ['"login":'],
        "absence": ['"missing"'],
        "source": "maigret",
        **changes,
    })


def fetched(url, body, status=200, error=None, content_type="application/json"):
    return FetchResult(
        url, url, status, body, 0.1, {"Content-Type": content_type}, error, 0,
    )


def test_rule_requires_positive_evidence_when_declared():
    site = definition()
    assert rule_evidence(site, fetched("https://api.example/users/alice", "{}"))["verdict"] is None
    assert rule_evidence(site, fetched("https://api.example/users/alice", '{"login":"alice"}'))["verdict"] == "Found"


def test_conflicting_rule_markers_are_inconclusive():
    evidence = rule_evidence(definition(), fetched("https://api.example/users/alice", '"login": "missing"'))
    assert evidence["verdict"] is None
    assert evidence["reason"] == "conflicting_markers"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_error_pages_cannot_be_rule_hits(status):
    evidence = rule_evidence(definition(), fetched("https://api.example/users/alice", '{"login":"alice"}', status))
    assert evidence["verdict"] is None
    assert evidence["reason"] == "http_unavailable"


async def test_json_probe_keeps_public_url_and_requires_matching_user(tmp_path, logger):
    site = definition()
    scanner = make_scanner(SiteCatalog({site.name: site}), tmp_path, logger)
    seen = []

    async def fetch(session, url, config, limiter, log):
        seen.append((url, config.request))
        body = json.dumps({"login": "alice", "name": "Alice", "bio": "Public biography"})
        return fetched(url, body) if url.endswith("/alice") else fetched(url, '{"missing":true}', 404)

    scanner.fetch = fetch
    result = await scanner._scan_site(site.name, site.url, "alice", None, None)
    assert result["status"] == "Found"
    assert result["url"] == "https://profiles.example/alice"
    assert result["ai_analysis"]["request"]["url"] == "https://api.example/users/alice"
    assert result["ai_analysis"]["signals"]["profile"]["name"] == "Alice"
    assert result["ai_analysis"]["model_applicable"] is False
    assert result["ai_analysis"]["explanation"]["checks"]["control"]["outcome"] == "different"
    assert len(seen) == 2
    assert all(options is not None for _, options in seen)


async def test_json_for_another_username_is_not_found(tmp_path, logger):
    site = definition()
    scanner = make_scanner(SiteCatalog({site.name: site}), tmp_path, logger)

    async def fetch(session, url, config, limiter, log):
        return fetched(url, '{"login":"someone_else"}')

    scanner.fetch = fetch
    result = await scanner._scan_site(site.name, site.url, "alice", None, None)
    assert result["status"] == "Maybe"
    assert "username_not_confirmed" in result["ai_analysis"]["explanation"]["reason_codes"]


async def test_unavailable_control_never_confirms_imported_hit(tmp_path, logger):
    site = definition()
    scanner = make_scanner(SiteCatalog({site.name: site}), tmp_path, logger)

    async def fetch(session, url, config, limiter, log):
        return fetched(url, '{"login":"alice"}') if url.endswith("/alice") else fetched(url, "", 408, "timeout")

    scanner.fetch = fetch
    result = await scanner._scan_site(site.name, site.url, "alice", None, None)
    assert result["status"] == "Maybe"
    assert result["ai_analysis"]["explanation"]["checks"]["control"]["outcome"] == "unavailable"


async def test_invalid_site_username_is_skipped_without_network(tmp_path, logger):
    site = definition(username_regex="^[a-z]{2,5}$")
    scanner = make_scanner(SiteCatalog({site.name: site}), tmp_path, logger)

    async def forbidden(*args):
        pytest.fail("invalid username reached the network")

    scanner.fetch = forbidden
    result = await scanner._scan_site(site.name, site.url, "name_too_long", None, None)
    assert result["status"] == "Skipped"


async def test_positive_control_cannot_confirm_a_hit(tmp_path, logger):
    site = definition()
    scanner = make_scanner(SiteCatalog({site.name: site}), tmp_path, logger)

    async def fetch(session, url, config, limiter, log):
        return fetched(url, json.dumps({"login": url.rsplit("/", 1)[-1]}))

    scanner.fetch = fetch
    result = await scanner._scan_site(site.name, site.url, "alice", None, None)
    assert result["status"] == "Maybe"
    assert result["ai_analysis"]["explanation"]["checks"]["control"]["outcome"] == "same"


def test_filtering_and_plain_override_preserve_correct_metadata():
    from aliens_eye.core.scanner import filter_sites, merge_site_maps

    catalog = SiteCatalog({"example": definition(tags=["coding"], nsfw=True)})
    assert isinstance(filter_sites(catalog, tags=["coding"]), SiteCatalog)
    assert not filter_sites(catalog, exclude_nsfw=True)
    merged = merge_site_maps(catalog, {"example": "https://override.example/{}"})
    assert merged.definitions["example"].probe_url is None
    assert merged.definitions["example"].check_type is None


async def test_selfcheck_uses_the_same_probe_pipeline(tmp_path, logger):
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.detector import Detector
    from aliens_eye.selfcheck import run_selfcheck

    site = definition()
    calls = []

    async def fetch(session, url, config, limiter, log):
        calls.append(url)
        return fetched(url, '{"login":"alice"}') if url.endswith("/alice") else fetched(url, '{"missing":true}', 404)

    result = await run_selfcheck(
        SiteCatalog({"example": site}), Detector(), ScannerConfig(), logger,
        fetch=fetch, jobs=[("example", site.profile_url("alice"), "alice", 1)], report_format="json",
    )
    assert result["overall"]["tp"] == 1
    assert len(calls) == 2
    assert all(url.startswith("https://api.example/") for url in calls)


def test_corpus_jobs_use_probe_urls_and_valid_negative_usernames():
    import random

    from aliens_eye.corpus.record import build_jobs

    site = definition(username_regex="^[a-z]{2,5}$")
    catalog = SiteCatalog({"example": site})
    jobs = build_jobs(catalog, {"example": ["alice"]}, 4, random.Random(123))
    assert len(jobs) == 5
    assert all(site.accepts(job[2]) for job in jobs)
    assert all(job[1] == site.request(job[2]).url for job in jobs)
    assert jobs == build_jobs(catalog, {"example": ["alice"]}, 4, random.Random(123))


def test_replay_rejects_unrecorded_request_policy(tmp_path, monkeypatch):
    import asyncio

    from test_corpus import make_corpus

    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.sites import SiteRequest
    from aliens_eye.corpus.replay import ReplayFetcher
    from aliens_eye.corpus.store import CorpusError

    url = "https://api.example/users/alice"
    root, _ = make_corpus(tmp_path, monkeypatch, {url: (200, '{"login":"alice"}')}, [
        ("example", url, "alice", 1),
    ])
    replay = ReplayFetcher(root)
    with pytest.raises(CorpusError, match="policy"):
        asyncio.run(replay(None, url, ScannerConfig(request=SiteRequest(url, follow_redirects=False)), None, None))


async def test_structured_fetch_applies_request_policy_and_retries(monkeypatch, logger):
    from aliens_eye.core import netguard
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.http import fetch_url
    from aliens_eye.core.rate_limit import DomainRateLimiter
    from aliens_eye.core.sites import SiteRequest

    calls = []
    url = "https://api.example/users/alice"

    async def guarded(session, target, **options):
        calls.append(options)
        status = 503 if len(calls) == 1 else 200
        return netguard.GuardedResponse(target, target, status, {}, b'{"login":"alice"}', "utf-8", 0)

    monkeypatch.setattr(netguard, "guarded_get", guarded)
    config = ScannerConfig(
        request=SiteRequest(url, {"Accept": "application/json"}, False),
        retries=1, rate_limit_delay=0, backoff_base=0, jitter=0,
    )
    response = await fetch_url(None, url, config, DomainRateLimiter(), logger)
    assert response.status == 200
    assert response.error is None
    assert len(calls) == 2
    assert all(call["follow_redirects"] is False for call in calls)
    assert all(call["headers"] == {"Accept": "application/json"} for call in calls)


async def test_structured_fetch_does_not_bypass_a_guard_refusal(monkeypatch, logger):
    from aliens_eye.core import netguard
    from aliens_eye.core.config import ScannerConfig
    from aliens_eye.core.http import fetch_url
    from aliens_eye.core.rate_limit import DomainRateLimiter
    from aliens_eye.core.sites import SiteRequest

    async def guarded(*args, **kwargs):
        raise netguard.GuardError("refused destination")

    monkeypatch.setattr(netguard, "guarded_get", guarded)
    url = "https://api.example/users/alice"
    result = await fetch_url(None, url, ScannerConfig(request=SiteRequest(url), retries=0), DomainRateLimiter(), logger)
    assert result.error
    assert "refused destination" in result.error


# --- verdicts the site's own evidence should settle ------------------------------

def scanner_for(site, tmp_path, logger, pages):
    """A scanner whose network is ``pages(url) -> FetchResult``."""
    scanner = make_scanner(SiteCatalog({site.name: site}), tmp_path, logger)

    async def fetch(session, url, config, limiter, log):
        return pages(url)

    scanner.fetch = fetch
    return scanner


async def verdict(site, tmp_path, logger, pages, username="alice"):
    result = await scanner_for(site, tmp_path, logger, pages)._scan_site(site.name, site.url, username, None, None)
    return result, result["ai_analysis"]["explanation"]


WIKI = {"presence": ['"userid":'], "absence": ['"missing":', '"invalid":']}


async def test_wiki_style_json_confirms_the_user_by_name(tmp_path, logger):
    site = definition(**WIKI)

    def pages(url):
        if url.endswith("/alice"):
            return fetched(url, json.dumps({"query": {"users": [{"userid": 7, "name": "Alice", "editcount": 12}]}}))
        return fetched(url, json.dumps({"query": {"users": [{"name": url.rsplit("/", 1)[-1], "missing": ""}]}}))

    result, explanation = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Found" and result["confidence"] == 75
    assert explanation["checks"]["control"]["outcome"] == "different"
    assert "username_not_confirmed" not in explanation["reason_codes"]


async def test_wiki_style_json_for_a_missing_user_is_not_found(tmp_path, logger):
    site = definition(**WIKI)

    def pages(url):
        return fetched(url, json.dumps({"query": {"users": [{"name": url.rsplit("/", 1)[-1], "missing": ""}]}}))

    result, _ = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Not Found"


async def test_an_explicit_marker_is_enough_when_the_json_carries_no_handle(tmp_path, logger):
    site = definition(**WIKI)

    def pages(url):
        if url.endswith("/alice"):
            return fetched(url, '{"userid": 7, "editcount": 12, "registered": "2019"}')
        return fetched(url, '{"missing": ""}')

    result, _ = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Found"


async def test_json_naming_a_different_handle_stays_unconfirmed(tmp_path, logger):
    """A lookup that answers with the closest account is not a hit for the one asked about."""
    site = definition(**WIKI)

    def pages(url):
        if url.endswith("/alice"):
            return fetched(url, '{"userid": 7, "username": "alice_2009"}')
        return fetched(url, '{"missing": ""}')

    result, explanation = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Maybe"
    assert "username_not_confirmed" in explanation["reason_codes"]


STATUS_RULE = {"check_type": "status_code", "presence": [], "absence": []}


async def test_status_only_json_needs_the_control_to_be_refused(tmp_path, logger):
    site = definition(**STATUS_RULE)

    def refused(url):
        return fetched(url, '{"id": 1, "posts": 3}') if url.endswith("/alice") else fetched(url, '{"error":"no"}', 404)

    result, explanation = await verdict(site, tmp_path, logger, refused)
    assert result["status"] == "Found" and result["confidence"] == 65
    assert explanation["checks"]["control"]["outcome"] == "different"

    def answers_everyone(url):
        return fetched(url, '{"id": 1, "posts": 3}' if url.endswith("/alice") else '{"id": 2, "posts": 9, "extra": [1, 2, 3]}')

    result, _ = await verdict(site, tmp_path / "second", logger, answers_everyone)
    assert result["status"] == "Maybe"


async def test_status_only_json_is_not_found_without_a_control(tmp_path, logger):
    site = definition(**STATUS_RULE)
    scanner = scanner_for(site, tmp_path, logger, lambda url: fetched(url, '{"id": 1}'))
    scanner.config.control_check = False
    result = await scanner._scan_site(site.name, site.url, "alice", None, None)
    assert result["status"] == "Maybe"


def html(body, title="Community"):
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


PROFILE = html(
    '<div class="profile-card"><h1>alice</h1><p>Member since 2019. 240 posts, 12 followers.</p>'
    "<p>Photography, long walks and bread.</p></div>",
    "alice - profile",
)
SIGN_IN = html("<form><h1>Sign in</h1><p>You need to sign in or sign up before continuing.</p></form>", "Sign in")
HTML_RULE = {"probe_url": None, "presence": ["profile-card"], "absence": ["no-such-member"]}


async def test_a_marker_less_control_page_is_compared_by_what_it_shows(tmp_path, logger):
    """Self-hosted software answers an unknown name with its sign-in page: no marker either way."""
    site = definition(**HTML_RULE)

    def pages(url):
        return fetched(url, PROFILE if url.endswith("/alice") else SIGN_IN, content_type="text/html")

    result, explanation = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Found"
    assert explanation["checks"]["control"]["outcome"] == "different"
    assert len(explanation["reason_codes"]) == len(set(explanation["reason_codes"]))


async def test_a_site_showing_everyone_the_same_marked_page_is_not_a_hit(tmp_path, logger):
    site = definition(**HTML_RULE)

    def pages(url):
        return fetched(url, PROFILE.replace("alice", url.rsplit("/", 1)[-1]), content_type="text/html")

    result, _ = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Maybe"


async def test_a_challenge_page_as_control_verifies_nothing(tmp_path, logger):
    site = definition(**HTML_RULE)
    wall = html("<p>Checking your browser before accessing the site.</p>", "Just a moment...")

    def pages(url):
        return fetched(url, PROFILE if url.endswith("/alice") else wall, content_type="text/html")

    result, explanation = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Maybe"
    assert explanation["checks"]["control"]["outcome"] == "unavailable"
    assert explanation["reason_codes"].count("control_unavailable") == 1


RICH_PROFILE = (
    '<html><head><title>alice (@alice)</title><meta property="og:type" content="profile">'
    '<meta property="og:title" content="alice"><meta name="description" content="alice on Community">'
    '<link rel="canonical" href="https://profiles.example/alice"></head>'
    '<body><main class="user-page"><h1>alice</h1><p>Joined 2019. 240 posts and 12 followers.</p></main></body></html>'
)
STALE_RULE = {"probe_url": None, "presence": ["old-profile-marker"], "absence": ["no-such-member"]}


async def test_a_stale_marker_defers_to_the_page_when_the_site_refuses_the_control(tmp_path, logger):
    site = definition(**STALE_RULE)

    def pages(url):
        if url.endswith("/alice"):
            return fetched(url, RICH_PROFILE, content_type="text/html")
        return fetched(url, html("<p>Nothing here.</p>", "Not found"), 404, content_type="text/html")

    result, explanation = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Found" and result["confidence"] <= 65
    assert explanation["checks"]["control"]["outcome"] == "different"


async def test_a_stale_marker_is_not_a_hit_when_the_control_is_only_different(tmp_path, logger):
    site = definition(**STALE_RULE)

    def pages(url):
        return fetched(url, RICH_PROFILE if url.endswith("/alice") else SIGN_IN, content_type="text/html")

    result, _ = await verdict(site, tmp_path, logger, pages)
    assert result["status"] == "Maybe"


async def test_a_made_up_name_is_never_found(tmp_path, logger):
    """Every site shape above, asked about a name it does not have."""
    name = "zq0f3a9c1d7e5b2a"
    cases = [
        (WIKI, lambda url: fetched(url, '{"query": {"users": [{"name": "X", "missing": ""}]}}')),
        (STATUS_RULE, lambda url: fetched(url, '{"error":"no"}', 404)),
        (HTML_RULE, lambda url: fetched(url, SIGN_IN, content_type="text/html")),
        (STALE_RULE, lambda url: fetched(url, SIGN_IN, content_type="text/html")),
    ]
    for index, (rule, pages) in enumerate(cases):
        site = definition(**rule)
        for control_check in (True, False):
            scanner = scanner_for(site, tmp_path / f"{index}{control_check}", logger, pages)
            scanner.config.control_check = control_check
            result = await scanner._scan_site(site.name, site.url, name, None, None)
            assert result["status"] != "Found", (rule, control_check)
