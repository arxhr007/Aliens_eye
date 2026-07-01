#!/usr/bin/python3
"""Backward-compatible launcher. Prefer `pip install aliens-eye` and the
`aliens_eye` command; this shim keeps `python aliens_eye.py` working from a
source checkout."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    src_dir = Path(__file__).resolve().parent / "src"
    if src_dir.exists():
        sys.path.insert(0, str(src_dir))
    # Drop this shim from sys.modules so the real package can be imported.
    sys.modules.pop("aliens_eye", None)

    from aliens_eye.cli import main

    main()
