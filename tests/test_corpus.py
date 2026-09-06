"""Frozen-corpus record/replay: round-trip, determinism, and the guards that
keep a replayed evaluation from silently drifting."""

import asyncio
import json

import pytest

from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.detector import Detector
from aliens_eye.core.fingerprints import FingerprintStore, build_fingerprint
from aliens_eye.core.http import FetchResult
from aliens_eye.corpus.record import (
    RecordingFetcher,
    build_jobs,
    plausible_negative,
    random_negative,
)
from aliens_eye.corpus.replay import MISSING_ERROR, ReplayFetcher
from aliens_eye.corpus.store import CorpusError, CorpusStore, body_digest

SITES = {
    "github": "https://github.com/{}",
    "reddit": "https://www.reddit.com/user/{}",
}


class FakeNetwork:
    """Stands in for fetch_url so tests never touch the network."""

    def __init__(self, responses: dict[str, tuple[int, str]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def __call__(self, session, url, config, rate_limiter, logger):
        self.calls.append(url)
        status, body = self.responses.get(url, (404, "<html>no such user</html>"))
        return FetchResult(
            url=url, final_url=url, status=status, content=body,
            response_time=0.125, headers={"Server": "test"}, error=None,
            redirect_count=0,
        )


def make_corpus(tmp_path, monkeypatch, responses, jobs):
    """Record `jobs` against a fake network and return the corpus root."""
    from aliens_eye.corpus import record as record_mod

    network = FakeNetwork(responses)
    monkeypatch.setattr(record_mod, "fetch_url", network)

    root = tmp_path / "corpus"
    store = CorpusStore(root)
    store.init()
    recorder = RecordingFetcher(store, tool_version="test")
    for site, url, username, label in jobs:
        recorder.register(url, site, username, label)

    async def drive():
        for _, url, _, _ in jobs:
            await recorder(None, url, ScannerConfig(), None, _NullLogger())

    asyncio.run(drive())
    written = recorder.flush()
    store.write_manifest({"tool_version": "test", "records": written})
    return root, network


class _NullLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


# --- round trip -----------------------------------------------------------


def test_record_then_replay_round_trips(tmp_path, monkeypatch, found_html):
    url = "https://github.com/torvalds"
    root, _ = make_corpus(
        tmp_path, monkeypatch, {url: (200, found_html)},
        [("github", url, "torvalds", 1)],
    )

    replay = ReplayFetcher(root)
    result = asyncio.run(replay(None, url, ScannerConfig(), None, _NullLogger()))
    assert result.status == 200
    assert result.content == found_html
    assert result.response_time == 0.125
    assert result.headers["Server"] == "test"
    assert result.error is None


def test_replay_makes_no_network_calls(tmp_path, monkeypatch, found_html):
    url = "https://github.com/torvalds"
    root, network = make_corpus(
        tmp_path, monkeypatch, {url: (200, found_html)},
        [("github", url, "torvalds", 1)],
    )
    before = len(network.calls)
    replay = ReplayFetcher(root)
    asyncio.run(replay(None, url, ScannerConfig(), None, _NullLogger()))
    assert len(network.calls) == before


# --- determinism ----------------------------------------------------------


def test_replay_is_deterministic_across_runs_and_orders(
    tmp_path, monkeypatch, found_html, not_found_html
):
    """Same corpus -> identical detections, regardless of visit order.

    This is the property the whole corpus exists for: a metric change must be
    attributable to the detector, never to which worker finished first.
    """
    urls = {
        "https://github.com/torvalds": (200, found_html),
        "https://github.com/nosuchuser99": (404, not_found_html),
        "https://www.reddit.com/user/spez": (200, found_html),
    }
    jobs = [
        ("github", "https://github.com/torvalds", "torvalds", 1),
        ("github", "https://github.com/nosuchuser99", "nosuchuser99", 0),
        ("reddit", "https://www.reddit.com/user/spez", "spez", 1),
    ]
    root, _ = make_corpus(tmp_path, monkeypatch, urls, jobs)

    def score(order):
        from aliens_eye.core.analyzer import FeatureExtractor

        replay = ReplayFetcher(root)
        extractor = FeatureExtractor()
        detector = Detector()
        # Read-only, empty store: no cross-response accumulation, so scoring
        # cannot depend on completion order.
        fingerprints = FingerprintStore(tmp_path / "fp.json", read_only=True)
        out = {}
        for site, url, username, _ in order:
            fetch = asyncio.run(replay(None, url, ScannerConfig(), None, _NullLogger()))
            bundle = extractor.extract(
                fetch.content, fetch.final_url, username, site,
                fetch.status, fetch.response_time, fetch.headers, fetch.redirect_count,
            )
            fp = build_fingerprint(bundle.fingerprint)
            scored = fingerprints.score(site, fp)
            bundle.features["fingerprint_match_found"] = float(scored["match_found"])
            bundle.features["fingerprint_match_not_found"] = float(scored["match_not_found"])
            fingerprints.add(site, "found", fp)
            detection = detector.predict(bundle.features)
            out[url] = (detection.status, detection.confidence, detection.probability)
        return out

    first = score(jobs)
    assert first == score(jobs), "same order must reproduce"
    assert first == score(list(reversed(jobs))), "reversed order must reproduce"


def test_readonly_fingerprint_store_does_not_accumulate(tmp_path, found_html):
    store = FingerprintStore(tmp_path / "fp.json", read_only=True)
    fp = {"title_hash": "a", "meta_hash": "b", "dom_signature": "c", "server": "d"}
    store.add("github", "found", fp)
    assert store.score("github", fp)["match_found"] == 0
    store.save()
    assert not (tmp_path / "fp.json").exists()


def test_writable_fingerprint_store_still_accumulates(tmp_path):
    store = FingerprintStore(tmp_path / "fp.json")
    fp = {"title_hash": "a", "meta_hash": "b", "dom_signature": "c", "server": "d"}
    store.add("github", "found", fp)
    assert store.score("github", fp)["match_found"] > 0


# --- storage --------------------------------------------------------------


def test_identical_bodies_are_stored_once(tmp_path, monkeypatch, not_found_html):
    """Error pages repeat across every negative; the corpus must not duplicate them."""
    urls = {
        f"https://github.com/ghost{i}": (404, not_found_html) for i in range(5)
    }
    jobs = [("github", url, f"ghost{i}", 0) for i, url in enumerate(urls)]
    root, _ = make_corpus(tmp_path, monkeypatch, urls, jobs)

    bodies = list((root / "bodies").rglob("*.gz"))
    assert len(bodies) == 1
    assert ReplayFetcher(root).stats()["records"] == 5


def test_body_digest_is_content_addressed():
    assert body_digest("abc") == body_digest("abc")
    assert body_digest("abc") != body_digest("abd")
    assert body_digest("") == ""


def test_records_are_written_in_stable_order(tmp_path, monkeypatch, found_html):
    urls = {f"https://github.com/u{i}": (200, found_html + str(i)) for i in range(4)}
    jobs = [("github", f"https://github.com/u{i}", f"u{i}", i % 2) for i in range(4)]
    root, _ = make_corpus(tmp_path, monkeypatch, urls, jobs)
    lines = (root / "records.jsonl").read_text("utf-8").strip().splitlines()
    keys = [(json.loads(x)["site"], json.loads(x)["label"], json.loads(x)["username"]) for x in lines]
    assert keys == sorted(keys)


# --- guards ---------------------------------------------------------------


def test_strict_replay_raises_on_missing_url(tmp_path, monkeypatch, found_html):
    url = "https://github.com/torvalds"
    root, _ = make_corpus(
        tmp_path, monkeypatch, {url: (200, found_html)},
        [("github", url, "torvalds", 1)],
    )
    replay = ReplayFetcher(root, strict=True)
    with pytest.raises(CorpusError, match="not in the corpus"):
        asyncio.run(replay(None, "https://github.com/absent", ScannerConfig(), None, _NullLogger()))


def test_lenient_replay_reports_miss_as_fetch_error(tmp_path, monkeypatch, found_html):
    url = "https://github.com/torvalds"
    root, _ = make_corpus(
        tmp_path, monkeypatch, {url: (200, found_html)},
        [("github", url, "torvalds", 1)],
    )
    replay = ReplayFetcher(root, strict=False)
    result = asyncio.run(
        replay(None, "https://github.com/absent", ScannerConfig(), None, _NullLogger())
    )
    assert result.error == MISSING_ERROR
    assert replay.misses == ["https://github.com/absent"]


def test_missing_corpus_raises(tmp_path):
    with pytest.raises(CorpusError, match="No corpus manifest"):
        ReplayFetcher(tmp_path / "nope")


def test_version_mismatch_raises(tmp_path, monkeypatch, found_html):
    url = "https://github.com/torvalds"
    root, _ = make_corpus(
        tmp_path, monkeypatch, {url: (200, found_html)},
        [("github", url, "torvalds", 1)],
    )
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    manifest["corpus_version"] = 999
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CorpusError, match="re-record"):
        ReplayFetcher(root)


# --- job construction -----------------------------------------------------


def test_build_jobs_covers_positives_and_negatives():
    import random

    ground_truth = {"github": ["torvalds", "mojombo"], "reddit": ["spez"]}
    jobs = build_jobs(SITES, ground_truth, negatives_per_site=4, rng=random.Random(1))
    positives = [j for j in jobs if j[3] == 1]
    negatives = [j for j in jobs if j[3] == 0]
    assert len(positives) == 3
    assert len(negatives) == 8
    assert {j[0] for j in jobs} == {"github", "reddit"}


def test_build_jobs_skips_sites_absent_from_sites_json():
    import random

    jobs = build_jobs(SITES, {"nowhere": ["someone"]}, 2, random.Random(1))
    assert jobs == []


def test_build_jobs_is_seed_reproducible():
    import random

    gt = {"github": ["torvalds"]}
    a = build_jobs(SITES, gt, 4, random.Random(7))
    b = build_jobs(SITES, gt, 4, random.Random(7))
    assert a == b


def test_negative_pools_have_different_morphology():
    """Random negatives are separable on shape alone; plausible ones are not.

    A negative class of 16-char random strings is an artificially easy problem
    and inflates every metric, which is why the corpus mixes in handles built
    from ordinary word morphology.
    """
    import random

    rng = random.Random(3)
    randoms = [random_negative(rng) for _ in range(50)]
    plausibles = [plausible_negative(rng) for _ in range(50)]
    assert all(len(u) >= 14 for u in randoms)
    assert min(len(u) for u in plausibles) < 14
    # Random strings are ~uniform over the alphabet; word-built handles are not.
    assert sum(c.isdigit() for u in randoms for c in u) > sum(
        c.isdigit() for u in plausibles for c in u
    )


def test_plausible_negatives_vary():
    import random

    rng = random.Random(11)
    assert len({plausible_negative(rng) for _ in range(40)}) > 20


# --- corpus as the evaluation set -----------------------------------------


def test_eval_jobs_returns_labelled_rows(tmp_path, monkeypatch, found_html, not_found_html):
    urls = {
        "https://github.com/torvalds": (200, found_html),
        "https://github.com/ghost1": (404, not_found_html),
        "https://www.reddit.com/user/spez": (200, found_html),
    }
    jobs_in = [
        ("github", "https://github.com/torvalds", "torvalds", 1),
        ("github", "https://github.com/ghost1", "ghost1", 0),
        ("reddit", "https://www.reddit.com/user/spez", "spez", 1),
    ]
    root, _ = make_corpus(tmp_path, monkeypatch, urls, jobs_in)

    jobs = ReplayFetcher(root).eval_jobs()
    assert sorted(jobs) == sorted(jobs_in)
    assert jobs == sorted(jobs, key=lambda j: (j[0], j[3], j[2])), "must be stably ordered"


def test_eval_jobs_filters_by_site(tmp_path, monkeypatch, found_html):
    urls = {
        "https://github.com/torvalds": (200, found_html),
        "https://www.reddit.com/user/spez": (200, found_html),
    }
    jobs_in = [
        ("github", "https://github.com/torvalds", "torvalds", 1),
        ("reddit", "https://www.reddit.com/user/spez", "spez", 1),
    ]
    root, _ = make_corpus(tmp_path, monkeypatch, urls, jobs_in)

    jobs = ReplayFetcher(root).eval_jobs({"github"})
    assert [j[0] for j in jobs] == ["github"]


def test_eval_jobs_hit_the_corpus_exactly(tmp_path, monkeypatch, found_html, not_found_html):
    """Regression: the eval set must come from the corpus, not be regenerated.

    Regenerating negatives at eval time yields URLs the corpus never captured,
    so every negative misses and the negative class is empty -- which silently
    reports a false-positive rate computed over nothing.
    """
    urls = {
        "https://github.com/torvalds": (200, found_html),
        "https://github.com/ghost1": (404, not_found_html),
        "https://github.com/ghost2": (404, not_found_html),
    }
    jobs_in = [
        ("github", "https://github.com/torvalds", "torvalds", 1),
        ("github", "https://github.com/ghost1", "ghost1", 0),
        ("github", "https://github.com/ghost2", "ghost2", 0),
    ]
    root, _ = make_corpus(tmp_path, monkeypatch, urls, jobs_in)

    replay = ReplayFetcher(root, strict=True)
    jobs = replay.eval_jobs()

    async def drive():
        for _, url, _, _ in jobs:
            await replay(None, url, ScannerConfig(), None, _NullLogger())

    asyncio.run(drive())
    assert replay.misses == []
    assert replay.hits == len(jobs)
    # The negative class is non-empty, so FPR is computed over something.
    assert sum(1 for j in jobs if j[3] == 0) == 2


def test_eval_jobs_skips_unlabelled_records(tmp_path, monkeypatch, found_html):
    url = "https://github.com/torvalds"
    root, _ = make_corpus(
        tmp_path, monkeypatch, {url: (200, found_html)},
        [("github", url, "torvalds", None)],
    )
    assert ReplayFetcher(root).eval_jobs() == []
