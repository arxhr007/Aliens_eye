# Contributing to Aliens Eye

Thanks for helping out. Issues and pull requests are welcome — adding sites to
`src/aliens_eye/data/sites.json`, expanding the ground-truth set in
`src/aliens_eye/data/selfcheck.json`, and improving the detector all directly
improve accuracy.

By participating, you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting set up

```bash
git clone https://github.com/arxhr007/Aliens_eye.git
cd Aliens_eye
python -m venv .venv
.venv/Scripts/activate          # Windows; source .venv/bin/activate elsewhere
pip install -e ".[dev,train,pdf]"
```

Optional extras, only if your change needs them: `browser` (Playwright),
`correlate` (avatar matching), `tui`, `serve` (MCP server).

## Checks that must pass

```bash
ruff check src tests aliens_eye.py
pytest -q
```

CI runs these on Python 3.10–3.13 across Linux and Windows, then builds the
package (`python -m build` + `twine check`). Keep changes Python 3.10 compatible
and inside the ruff rules already in `pyproject.toml` (line length 110).

Tests never hit the live network. Reuse the existing local `aiohttp` test
servers and injected `fetch` functions (`tests/conftest.py`,
`tests/test_scanner.py`, `tests/test_control.py` are the patterns to copy).
A change that needs a live platform to verify it is not ready to merge.

## Ways to contribute

### Adding a site

Add `"name": "url-template-with-{}"` to `src/aliens_eye/data/sites.json`. The
URL must locate an account by username — sites that can only be searched, or
keyed by an internal ID the username doesn't map to, can't be checked reliably
and will produce false "Found" results. NSFW sites also go in
`src/aliens_eye/data/nsfw_sites.json`. `tests/test_sites.py` validates the file.

### Improving detection

Detection changes are measured, not argued:

- Ground truth lives in `selfcheck.json` (train split) and `eval_holdout.json`
  (holdout). The split is **site-disjoint** — accounts from a site the model
  trained on do not belong in the holdout. `train collect --split holdout` is
  refused unless `--allow-leakage` is passed; don't pass it.
- Record a frozen corpus (`corpus record`), then evaluate with
  `selfcheck --corpus` and `eval ablate --corpus`. Replay makes metrics
  reproducible; live-web numbers are not.
- Retraining (`train collect` + `train fit`) needs the `train` extra. Exported
  `model.json` carries its own thresholds and blend weight —
  `tests/test_detector.py` pins them, so update the test table if you ship a
  new model.

### Reporting bugs

Open an issue with: the command you ran, what you expected, what happened, and
platform/Python version. Redact URLs or usernames you don't want public. For
scanner bugs, a saved JSON report or a small reproducing HTML page helps most —
the test suite turns those into local fixtures.

## Pull requests

- One change per PR. Describe *why* in the commit message, like the existing
  history (`fix: ...`, `feat: ...`, or a plain description).
- Don't bump `pyproject.toml`/`__init__.py` versions or touch the changelog in
  feature PRs — the maintainer does releases, and CI tags a release when the
  version changes on `main`.
- Don't commit secrets, real scan outputs containing third-party page content,
  or corpora (see `WORKING.md` — captured corpora are local artifacts).
- Keep the documented behavior honest: if a number or claim in README/WORKING.md
  changes, update the doc in the same PR.

## Questions

Open a discussion or issue on GitHub — maintainers and contributors answer
there so the next person finds it too.
