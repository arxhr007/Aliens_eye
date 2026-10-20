"""macOS starts a program with 256 file descriptors; one scan can pass that.

The follow-up report on #26 ended in Errno 24 from every socket and subprocess
spawn afterwards. The limit is raised at startup where the OS allows it, and
asking must never itself be a way to fail.
"""

from aliens_eye.utils.fdlimit import raise_fd_limit


def test_the_limit_is_raised_or_reported():
    limit = raise_fd_limit()
    assert limit is None or limit >= 256


def test_asking_twice_leaves_the_same_limit():
    assert raise_fd_limit() == raise_fd_limit()
