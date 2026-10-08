"""A Found has to survive a second opinion: issue #22.

A username that does not exist was reported Found on 11 of 19 sites tried,
because the page each site returns for *anyone* looks like a profile.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from test_scanner import make_scanner

from aliens_eye.core import control
from aliens_eye.core.control import http_overrule, page_shape, same_page, text_similarity

# --- the comparison ---------------------------------------------------------------


def profile(username, name="", bio="", extra=""):
    return f"""<html><head><title>{username} {name} - Profile</title>
    <meta property="og:title" content="{name or username}">
    <meta name="description" content="{username} profile picture, followers and posts">
    <style>.x{{color:red}}</style><script>var boot = "{username}-{extra}";</script>
    </head><body class="user-profile"><div class="profile-header">
    <img src="a.png"><img src="b.png"><img src="c.png"><img src="d.png"><img src="e.png"><img src="f.png"></div>
    <p>Follow {username}. Posts and activity timeline. {bio}</p></body></html>"""


def shape(username, **kw):
    return page_shape(profile(username, **kw), f"https://site.example/u/{username}", username)


def test_the_same_shell_for_two_usernames_is_the_same_page():
    """Only the username differs, and that is masked out."""
    assert text_similarity(shape("kristoferweston"), shape("zq1b2c3d4e5f6a")) == 1.0
    assert same_page(shape("kristoferweston"), shape("zq1b2c3d4e5f6a"))


def test_a_real_profile_is_not_the_missing_user_page():
    real = shape("torvalds", name="Linus Torvalds", bio="Creator of Linux and Git. 250k followers. " * 3)
    assert not same_page(real, shape("zq1b2c3d4e5f6a"))


def test_scripts_and_styles_are_not_compared():
    """A nonce or build id in a script must not make two shells look different."""
    assert text_similarity(shape("a_user", extra="nonce-1"), shape("zq1b2c3d4e5f6a", extra="nonce-2")) == 1.0


def test_meta_tags_count_even_when_the_body_is_empty():
    """A JavaScript app whose server fills in the real name is still told apart."""
    def app(username, title):
        html = f'<html><head><meta property="og:title" content="{title}"></head><body><div id="root"></div></body></html>'
        return page_shape(html, f"https://app.example/{username}", username)

    assert not same_page(app("torvalds", "Linus Torvalds is on App with 12 posts"), app("zq1b2c3d4e5f6a", "App"))
    assert same_page(app("torvalds", "App"), app("zq1b2c3d4e5f6a", "App"))


def test_username_matching_ignores_case():
    a = page_shape("<html><body>Profile of TORVALDS</body></html>", "https://x.example/Torvalds", "Torvalds")
    b = page_shape("<html><body>Profile of zq1b2c3d4e5f6a</body></html>", "https://x.example/zq1b2c3d4e5f6a", "zq1b2c3d4e5f6a")
    assert text_similarity(a, b) == 1.0 and a.final_path == b.final_path


def test_two_empty_pages_are_the_same_page():
    assert same_page(page_shape("", "", "a"), page_shape("", "", "b"))


def test_a_much_larger_page_is_not_the_same_page_even_with_the_same_words():
    small = page_shape("<html><body>hello</body></html>", "", "a")
    big = page_shape("<html><body>hello</body><script>" + "x" * 5000 + "</script></html>", "", "b")
    assert text_similarity(small, big) == 1.0 and not same_page(small, big)


def test_control_usernames_are_random_and_ordinary_looking():
    names = {control.control_username() for _ in range(50)}
    assert len(names) == 50
    assert all(name.isalnum() and name.islower() and len(name) == 16 for name in names)


@pytest.mark.parametrize("code,expected", [
    (200, None), (301, None), (404, ("Not Found", "http-gone")), (410, ("Not Found", "http-gone")),
    (400, ("Maybe", "http-error")), (403, ("Maybe", "http-error")), (429, ("Maybe", "http-error")),
    (500, ("Maybe", "http-error")), (503, ("Maybe", "http-error")), (999, ("Maybe", "http-error")),
])
def test_http_errors_overrule_a_found(code, expected):
    assert http_overrule(code) == expected


# --- in a scan ------------------------------------------------------------------------


@pytest.fixture
async def sites(found_html, not_found_html):
    """Four sites that all return a profile-looking page, for different reasons."""
    app = web.Application()
    hits: list[str] = []

    def page_for(username):
        return found_html.replace("torvalds", username)

    async def shell(request):                     # the same page for anyone: a JS shell
        hits.append(request.path)
        return web.Response(text=page_for(request.match_info["u"]), content_type="text/html")

    async def honest(request):                    # a real page for one user, a different one otherwise
        hits.append(request.path)
        if request.match_info["u"] == "torvalds":
            return web.Response(text=found_html, content_type="text/html")
        return web.Response(text=not_found_html, content_type="text/html")   # a "soft" 404: status 200

    def with_status(status):
        async def handler(request):               # a profile-looking page under an error code
            hits.append(request.path)
            return web.Response(text=page_for(request.match_info["u"]), status=status, content_type="text/html")
        return handler

    app.router.add_get("/shell/{u}", shell)
    app.router.add_get("/honest/{u}", honest)
    for status in (404, 410, 403, 500):
        app.router.add_get(f"/s{status}/{{u}}", with_status(status))
    server = TestServer(app)
    await server.start_server()
    server.hits = hits
    server.base = f"http://{server.host}:{server.port}"
    yield server
    await server.close()


async def scan(server, tmp_path, logger, names, username="torvalds", **config):
    scanner = make_scanner({n: f"{server.base}/{n}/{{}}" for n in names}, tmp_path, logger)
    for key, value in config.items():
        setattr(scanner.config, key, value)
    results = {r["site"]: r for r in await scanner.scan_all_sites(username)}
    return scanner, results


async def test_a_site_that_shows_everyone_the_same_page_is_only_a_maybe(sites, tmp_path, logger):
    _, results = await scan(sites, tmp_path, logger, ["shell"])
    assert results["shell"]["status"] == "Maybe"
    assert results["shell"]["confidence"] <= 55
    assert results["shell"]["ai_analysis"]["method"].endswith("-same-as-missing-user")


async def test_a_site_that_tells_users_apart_keeps_its_found(sites, tmp_path, logger):
    _, results = await scan(sites, tmp_path, logger, ["honest"])
    assert results["honest"]["status"] == "Found"
    assert "same-as-missing-user" not in results["honest"]["ai_analysis"]["method"]
    assert len(sites.hits) == 2                       # the profile, and one made-up username


async def test_without_the_check_the_shell_is_reported_found_as_before(sites, tmp_path, logger):
    _, results = await scan(sites, tmp_path, logger, ["shell"], control_check=False)
    assert results["shell"]["status"] == "Found"
    assert len(sites.hits) == 1


async def test_the_made_up_username_is_asked_for_once_per_site(sites, tmp_path, logger):
    scanner, _ = await scan(sites, tmp_path, logger, ["shell"])
    await scanner.scan_all_sites("someoneelse")
    await scanner.scan_all_sites("athirdperson")
    assert len(sites.hits) == 4                       # three usernames + one control


async def test_only_a_found_costs_a_second_request(sites, tmp_path, logger):
    _, results = await scan(sites, tmp_path, logger, ["honest"], username="nobodyhere")
    assert results["honest"]["status"] != "Found"
    assert len(sites.hits) == 1


@pytest.mark.parametrize("name,status", [("s404", "Not Found"), ("s410", "Not Found"),
                                         ("s403", "Maybe"), ("s500", "Maybe")])
async def test_a_profile_looking_error_page_is_never_found(sites, tmp_path, logger, name, status):
    """Regression (#22): chatujme.cz answered 404 and was reported Found at 84%."""
    _, off = await scan(sites, tmp_path, logger, [name], control_check=False, retries=0)
    assert off[name]["status"] == status
    assert len(sites.hits) == 1                       # settled by the status code alone


async def test_a_control_that_cannot_be_fetched_changes_nothing(sites, tmp_path, logger):
    scanner = make_scanner({"honest": f"{sites.base}/honest/{{}}"}, tmp_path, logger)
    real_fetch = scanner.fetch

    async def fetch(session, url, config, rate_limiter, log):
        if "torvalds" not in url:
            raise RuntimeError("network fell over")
        return await real_fetch(session, url, config, rate_limiter, log)

    scanner.fetch = fetch
    results = await scanner.scan_all_sites("torvalds")
    assert results[0]["status"] == "Found"
