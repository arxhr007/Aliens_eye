# Local workflow

- Ask the user before any GitHub-related action, including pushing or opening a pull request. Do not commit unless requested.
- On this Windows checkout, use `.venv/Scripts/python.exe` for local verification.
- Lint: `.venv/Scripts/python.exe -m ruff check src tests aliens_eye.py`.
- Tests: `.venv/Scripts/python.exe -m pytest -q`. Scanner and monitoring tests use fake fetchers or local aiohttp servers; live platform scans and real webhook delivery are not needed.
- Offline package verification is available with `uv build --offline --out-dir <temporary-directory>` followed by `.venv/Scripts/python.exe -m twine check <temporary-directory>/*`. The cached isolated build backend is available even though Hatchling is not installed in the project virtual environment.
- Put validation build artifacts in a fresh temporary directory, not over existing release artifacts in `dist/`.
- Catalog inspection is offline: `.venv/Scripts/python.exe aliens_eye.py sites stats --catalog extended` and `sites validate --catalog extended`. Source imports require local JSON paths, default to inspection, and refuse to overwrite an existing `--out` file.
- For offline training validation, use `train collect --corpus <existing-corpus-directory> --out <new-temporary-csv>` followed by `train fit --data <new-temporary-csv> --out <new-temporary-model>`. New rows carry site groups; legacy CSV validation is not evidence of unseen-site performance. Do not promote a candidate solely on training/CV scores.
