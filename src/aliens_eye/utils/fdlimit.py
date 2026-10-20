"""The per-process file-descriptor limit.

macOS starts a program with 256, and a single scan can pass that: one pooled
socket per site plus the browser fallback's driver pipes, after which every
socket and subprocess spawn fails with Errno 24. Linux usually starts far
higher, which is why the failure looked machine-specific (#26).
"""

import sys


def raise_fd_limit(target: int = 4096) -> int | None:
    """Raise the soft file-descriptor limit to ``target``, as far as allowed.

    Returns the limit in force, or None where the platform cannot ask (Windows)
    or the hard limit is lower. Never raises: a program that cannot raise its
    limit should still run, and the error it eventually gets names the fix.
    """
    if sys.platform == "win32":
        return None
    try:
        import resource
    except ImportError:  # pragma: no cover - POSIX without the resource module
        return None
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard != resource.RLIM_INFINITY:
            target = min(target, hard)
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            soft = target
        return soft
    except (OSError, ValueError):  # a platform that refuses; run as we were given
        return None
