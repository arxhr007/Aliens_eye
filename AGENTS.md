# Local workflow

- Ask the user before any GitHub-related action, including pushing or opening a pull request. Do not commit unless requested.
- On this Windows checkout, use `.venv/Scripts/python.exe` for local verification.
- Lint: `.venv/Scripts/python.exe -m ruff check src tests aliens_eye.py`.
- Tests: `.venv/Scripts/python.exe -m pytest -q`. Scanner and monitoring tests use fake fetchers or local aiohttp servers; live platform scans and real webhook delivery are not needed.
- Offline package verification is available with `uv build --offline --out-dir <temporary-directory>` followed by `.venv/Scripts/python.exe -m twine check <temporary-directory>/*`. The cached isolated build backend is available even though Hatchling is not installed in the project virtual environment.
- Put validation build artifacts in a fresh temporary directory, not over existing release artifacts in `dist/`.
