"""Reverse URL matching, and the guarded page fetch built for following links."""

import socket

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aliens_eye import api
from aliens_eye.core import netguard
from aliens_eye.core.expand import _username_from_url
from aliens_eye.core.urlmatch import ProfileUrlMatcher

SITES = {
    "github": "https://github.com/{}",
    "github.sponsors": "https://github.com/sponsors/{}",
    "reddit": "https://www.reddit.com/user/{}",
    "medium": "https://medium.com/@{}",
    "tumblr": "https://{}.tumblr.com",
    "forum": "https://forum.example/member.php?mode=view&username={}",
    "lor": "https://www.linux.example/people/{}/profile",
    "twitter": "https://twitter.com/{}",
    "boards": "https://www.pinterest.com/{}/{}",
}


@pytest.fixture
def matcher():
    return ProfileUrlMatcher(SITES)


def first(matcher, url):
    matches = matcher.match(url)
    return tuple(matches[0]) if matches else None


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/arx", ("github", "arx")),
    ("http://www.GitHub.com/arx/", ("github", "arx")),                 # scheme, www, case, slash
    ("https://github.com/arx?tab=repositories#x", ("github", "arx")),  # query and fragment ignored
    ("https://www.reddit.com/user/spez", ("reddit", "spez")),
    ("https://old.reddit.com/user/spez", ("reddit", "spez")),          # host alias
    ("https://medium.com/@someone", ("medium", "someone")),
    ("https://arx.tumblr.com", ("tumblr", "arx")),
    ("https://arx.tumblr.com/post/1", ("tumblr", "arx")),
    ("https://forum.example/member.php?username=zed&mode=view", ("forum", "zed")),
    ("https://www.linux.example/people/maxcom/profile", ("lor", "maxcom")),
    ("https://x.com/arx", ("twitter", "arx")),                         # x.com is twitter
    ("https://twitter.com/@arx", ("twitter", "arx")),                  # leading @ dropped
])
def test_profile_urls_are_recognised(matcher, url, expected):
    assert first(matcher, url) == expected


@pytest.mark.parametrize("url", [
    "https://github.com/arx/some-repo",        # a repository, not a profile
    "https://github.com/sponsors",             # fixed segment of a sibling template
    "https://github.com/features",             # site navigation
    "https://github.com/login",
    "https://github.com/",
    "https://twitter.com/intent/tweet?text=hi",
    "https://www.tumblr.com",                  # no username subdomain
    "https://www.tumblr.com/explore",
    "https://api.tumblr.com",                  # service subdomain
    "https://forum.example/member.php?username=zed",          # fixed param missing
    "https://forum.example/other.php?mode=view&username=zed",  # wrong path
    "https://www.linux.example/people/maxcom",                 # template suffix missing
    "https://github.com/logo.png",             # a file
    "https://github.com/a",                    # too short to scan
    "https://unknown.example/arx",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "not a url",
    "",
])
def test_non_profile_urls_do_not_match(matcher, url):
    assert matcher.match(url) == []


def test_most_specific_template_wins(matcher):
    assert first(matcher, "https://github.com/sponsors/arx") == ("github.sponsors", "arx")


def test_two_placeholder_templates_are_skipped(matcher):
    assert all(m.site != "boards" for m in matcher.match("https://www.pinterest.com/arx/board"))


def test_username_case_is_preserved(matcher):
    assert first(matcher, "https://github.com/ArxHR") == ("github", "ArxHR")


def test_percent_encoded_usernames_are_decoded(matcher):
    assert first(matcher, "https://github.com/%E5%9D%A6%E9%80%94") == ("github", "坦途")


def test_api_matches_against_the_real_catalogue():
    assert tuple(api.match_profile_url("https://www.instagram.com/_arx_/")[0]) == ("instagram", "_arx_")
    assert tuple(api.match_profile_url("https://www.linkedin.com/in/some-one")[0]) == ("linkedin", "some-one")
    assert api.match_profile_url("https://github.com/arx/repo") == []


def test_profile_url_round_trips_through_the_matcher():
    url = api.profile_url("github", "arx")
    assert tuple(api.match_profile_url(url)[0]) == ("github", "arx")
    with pytest.raises(KeyError):
        api.profile_url("no-such-site", "arx")


def test_expand_understands_any_catalogue_site():
    """It used to know 19 hard-coded domains and take the first path segment."""
    assert _username_from_url("https://www.linkedin.com/in/some-one") == "some-one"
    assert _username_from_url("https://twitter.com/charlie") == "charlie"
    assert _username_from_url("https://github.com/arx/repo") is None


# --- fetch_page ----------------------------------------------------------------


@pytest.fixture
async def page_server():
    hits = {"secret": 0}
    app = web.Application()

    async def page(request):
        return web.Response(text="<html><a rel='me' href='https://github.com/arx'>gh</a></html>",
                            content_type="text/html")

    async def to_internal(request):
        raise web.HTTPFound(f"http://127.0.0.1:{request.url.port}/secret")

    async def secret(request):
        hits["secret"] += 1
        return web.Response(text="internal")

    app.router.add_get("/page", page)
    app.router.add_get("/to-internal", to_internal)
    app.router.add_get("/secret", secret)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    server.hits = hits
    yield server
    await server.close()


async def test_fetch_page_returns_html(page_server):
    result = await api.fetch_page(f"http://127.0.0.1:{page_server.port}/page", allow_private=True)
    assert result["status"] == 200
    assert result["error"] is None
    assert "rel='me'" in result["html"]


async def test_fetch_page_refuses_private_addresses_by_default(page_server):
    result = await api.fetch_page(f"http://127.0.0.1:{page_server.port}/secret")
    assert result["error"]
    assert result["html"] == ""
    assert page_server.hits["secret"] == 0


async def test_fetch_page_does_not_follow_a_redirect_inward(page_server, monkeypatch):
    async def only_localhost(host):
        return host == "localhost"

    monkeypatch.setattr(netguard, "host_is_public", only_localhost)
    # Plain IPv4 connector: the public-only resolver would (rightly) refuse the
    # test server itself. The per-hop check is what is under test here.
    monkeypatch.setattr(
        "aliens_eye.core.scanner.build_session",
        lambda config, limit, headers=None, resolver=None: aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(family=socket.AF_INET)
        ),
    )
    result = await api.fetch_page(f"http://localhost:{page_server.port}/to-internal")
    assert result["error"]
    assert page_server.hits["secret"] == 0


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "", "ftp://x/y"])
async def test_fetch_page_never_raises_on_bad_urls(url):
    result = await api.fetch_page(url)
    assert result["error"] and result["html"] == ""
