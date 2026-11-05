import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_report import result

from aliens_eye.core.config import ScannerConfig
from aliens_eye.core.report import observation
from aliens_eye.core.watch_state import MonitorState, StateError, WatchStore, scope_key

KEY = "alice:example"


def observe(state, status="Found", code=200, name="Alice"):
    return state.observe({KEY: observation(result(status, code, name))}, "2026-11-04T00:00:00+00:00")


def test_failure_then_recovery_is_not_a_disappearance():
    state = MonitorState()
    assert observe(state)["new"] == []
    assert observe(state, "Timeout", 408)["gone"] == []
    assert observe(state)["new"] == []


def test_absence_requires_consecutive_evidence_and_emits_once():
    state = MonitorState()
    observe(state)
    assert observe(state, "Not Found", 404)["gone"] == []
    observe(state, "Error", 0)
    assert observe(state, "Not Found", 404)["gone"] == []
    assert observe(state, "Not Found", 410)["gone"] == [KEY]
    assert observe(state, "Not Found", 404)["gone"] == []
    assert observe(state)["new"] == [KEY]
    assert observe(state)["new"] == []


def test_omitted_site_resets_confirmation_without_erasing_baseline():
    state = MonitorState()
    observe(state)
    observe(state, "Not Found", 404)
    state.observe({}, "now")
    assert observe(state, "Not Found", 404)["gone"] == []
    assert observe(state)["new"] == []


def test_first_conclusive_observation_establishes_baseline():
    state = MonitorState(confirmations=1)
    observe(state, "Error", 0)
    assert observe(state)["new"] == []
    assert observe(state, "Not Found", 404)["gone"] == [KEY]


def test_profile_change_is_opt_in_and_confirmed():
    state = MonitorState(fields=("name",))
    observe(state)
    assert observe(state, name="Alice Smith")["profile_changes"] == []
    changes = observe(state, name="Alice Smith")["profile_changes"]
    assert changes == [{
        "key": KEY, "field": "name", "before": "Alice", "after": "Alice Smith",
        "source": "opengraph", "type": "name_changed",
    }]
    assert observe(state, name="Alice Smith")["profile_changes"] == []
    default = MonitorState()
    observe(default)
    observe(default, name="Alice Smith")
    assert observe(default, name="Alice Smith")["profile_changes"] == []


def test_restart_preserves_pending_confirmations(tmp_path):
    state = MonitorState()
    observe(state)
    observe(state, "Not Found", 404)
    with WatchStore(tmp_path, "abc") as store:
        store.save(state)
    with WatchStore(tmp_path, "abc") as store:
        loaded = store.load()
        assert observe(loaded, "Not Found", 404)["gone"] == [KEY]


def test_invalid_state_is_not_overwritten(tmp_path):
    with WatchStore(tmp_path, "abc") as store:
        store.path.write_text('{"broken": true}', encoding="utf-8")
        with pytest.raises(StateError):
            store.load()
        assert json.loads(store.path.read_text(encoding="utf-8")) == {"broken": True}


def test_scope_has_only_one_writer_and_releases_lock(tmp_path):
    with WatchStore(tmp_path, "abc"):
        with pytest.raises(StateError), WatchStore(tmp_path, "abc"):
            pass
        with WatchStore(tmp_path, "def"):
            pass
    with WatchStore(tmp_path, "abc"):
        pass


def test_atomic_write_failure_preserves_previous_state(tmp_path, monkeypatch):
    from aliens_eye.core import watch_state

    state = MonitorState()
    observe(state)
    with WatchStore(tmp_path, "abc") as store:
        store.save(state)
        before = store.path.read_bytes()
        observe(state, "Not Found", 404)

        def fail(*args):
            raise OSError("replace failed")

        monkeypatch.setattr(watch_state.os, "replace", fail)
        with pytest.raises(OSError):
            store.save(state)
        assert store.path.read_bytes() == before
        assert {p.suffix for p in store.path.parent.iterdir()} == {".json", ".lock"}


@pytest.mark.parametrize("change", [
    lambda state: state.update(schema_version=999),
    lambda state: state.update(entries=[]),
    lambda state: state.update(confirmations=True),
    lambda state: state["entries"][KEY].update(pending_absence=5),
    lambda state: state["entries"][KEY].update(profile={"name": {"value": [], "source": "opengraph"}}),
    lambda state: state["entries"][KEY].update(pending_profile={"name": {"value": "Bob", "source": "opengraph", "count": 0}}),
])
def test_invalid_state_schema_is_rejected(change):
    state = MonitorState(fields=("name",))
    observe(state)
    data = deepcopy(state.to_dict())
    change(data)
    with pytest.raises(StateError):
        MonitorState.from_dict(data)


def test_scope_changes_with_templates_and_policy_without_storing_credentials():
    scanner = SimpleNamespace(
        config=ScannerConfig(), detector=SimpleNamespace(model=None),
        sites_data={"example": "https://example.test/{}"},
    )
    key = scope_key(scanner, "alice", "basic", 2, ())
    assert key != scope_key(scanner, "bob", "basic", 2, ())
    assert key != scope_key(scanner, "alice", "basic", 1, ())
    assert key != scope_key(scanner, "alice", "basic", 2, ("name",))
    scanner.sites_data["other"] = "https://other.test/{}"
    assert key != scope_key(scanner, "alice", "basic", 2, ())
    scanner.sites_data.pop("other")
    scanner.config = replace(scanner.config, control_check=False)
    assert key != scope_key(scanner, "alice", "basic", 2, ())


def test_profile_failure_resets_confirmation_and_retains_last_stable_value():
    state = MonitorState(fields=("name",))
    observe(state)
    observe(state, name="Alice Smith")
    observe(state, "Timeout", 408)
    assert observe(state, name="Alice Smith")["profile_changes"] == []
    assert observe(state, name="Alice Smith")["profile_changes"][0]["before"] == "Alice"


def test_profile_baseline_resets_after_absence():
    state = MonitorState(confirmations=1, fields=("name",))
    observe(state)
    observe(state, "Not Found", 404)
    assert observe(state, name="Alice Smith")["profile_changes"] == []
    assert observe(state, name="Alice Smith")["profile_changes"] == []
