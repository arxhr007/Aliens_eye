import pytest

from aliens_eye.utils.logger import setup_logger


@pytest.fixture
def logger():
    return setup_logger(verbose=False)


@pytest.fixture
def found_html():
    return """
    <html><head>
    <title>torvalds (Linus Torvalds) - Profile</title>
    <meta name="description" content="torvalds profile picture, followers and posts">
    </head><body class="user-profile">
    <div class="profile-header"><img src="a.png"><img src="b.png"><img src="c.png">
    <img src="d.png"><img src="e.png"><img src="f.png"></div>
    <p>Follow torvalds. 1000 followers. Joined 2011. Posts and activity timeline.</p>
    </body></html>
    """


@pytest.fixture
def not_found_html():
    return """
    <html><head><title>Page not found - 404</title></head>
    <body class="error not-found">
    <h1>404 Not Found</h1><p>Sorry, this page doesn't exist. User not found.</p>
    <form action="/search"><input name="q"><input name="x"><input name="y"></form>
    </body></html>
    """
