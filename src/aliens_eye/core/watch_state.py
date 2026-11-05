from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .report import PROFILE_FIELDS, profile_change
from .variations import generate_username_variations


class StateError(ValueError):
    pass


class MonitorState:
    def __init__(self, confirmations: int = 2, fields: tuple[str, ...] = ()) -> None:
        if type(confirmations) is not int or confirmations < 1:
            raise ValueError("watch confirmations must be an integer >= 1")
        if any(field not in PROFILE_FIELDS for field in fields) or len(set(fields)) != len(fields):
            raise ValueError("watch profile fields must be name, bio, or avatar without duplicates")
        self.confirmations = confirmations
        self.fields = tuple(fields)
        self.entries: dict[str, dict[str, Any]] = {}

    def observe(self, observations: dict[str, dict], observed_at: str) -> dict[str, list]:
        delta: dict[str, list] = {"new": [], "gone": [], "profile_changes": [], "unavailable": []}
        for key in sorted(self.entries.keys() | observations.keys()):
            current = observations.get(key, {"kind": "unavailable", "profile": {}})
            entry = self.entries.get(key)
            kind = current["kind"]
            if kind == "unavailable":
                delta["unavailable"].append(key)
                if entry:
                    entry.update(pending_absence=0, pending_profile={})
                continue
            profile = {f: dict(v) for f, v in current["profile"].items() if f in self.fields}
            if entry is None:
                self.entries[key] = {
                    "kind": kind, "profile": profile, "pending_absence": 0,
                    "pending_profile": {}, "last_observed": observed_at,
                }
                continue
            entry["last_observed"] = observed_at
            if kind == "absent":
                entry["pending_profile"] = {}
                if entry["kind"] == "found":
                    entry["pending_absence"] += 1
                    if entry["pending_absence"] >= self.confirmations:
                        entry.update(kind="absent", profile={}, pending_absence=0)
                        delta["gone"].append(key)
                continue
            entry["pending_absence"] = 0
            if entry["kind"] == "absent":
                entry.update(kind="found", profile=profile, pending_profile={})
                delta["new"].append(key)
                continue
            for field in self.fields:
                before, after = entry["profile"].get(field), profile.get(field)
                if not after:
                    entry["pending_profile"].pop(field, None)
                    continue
                if not before or before["source"] != after["source"]:
                    entry["profile"][field] = after
                    entry["pending_profile"].pop(field, None)
                    continue
                change = profile_change(key, field, before, after)
                if change is None:
                    entry["pending_profile"].pop(field, None)
                    continue
                pending = entry["pending_profile"].get(field, {})
                count = pending.get("count", 0) + 1 if pending.get("value") == after["value"] else 1
                if count >= self.confirmations:
                    entry["profile"][field] = after
                    entry["pending_profile"].pop(field, None)
                    delta["profile_changes"].append(change)
                else:
                    entry["pending_profile"][field] = {**after, "count": count}
        return delta

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1, "confirmations": self.confirmations,
            "fields": list(self.fields), "entries": self.entries,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MonitorState:
        try:
            if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
                raise ValueError("unsupported schema")
            if not isinstance(data["fields"], list):
                raise ValueError("invalid fields")
            state = cls(data["confirmations"], tuple(data["fields"]))
            entries = data["entries"]
            if not isinstance(entries, dict):
                raise ValueError("invalid entries")
            for key, entry in entries.items():
                if not isinstance(key, str) or not isinstance(entry, dict):
                    raise ValueError("invalid entry")
                if entry["kind"] not in {"found", "absent"} or not isinstance(entry["last_observed"], str):
                    raise ValueError("invalid observation")
                pending_absence = entry["pending_absence"]
                if type(pending_absence) is not int or not 0 <= pending_absence < state.confirmations:
                    raise ValueError("invalid confirmations")
                for name in ("profile", "pending_profile"):
                    values = entry[name]
                    if not isinstance(values, dict) or any(f not in state.fields for f in values):
                        raise ValueError("invalid profile")
                    for value in values.values():
                        if not isinstance(value, dict) or any(
                            not isinstance(value.get(f), str) or not value[f] for f in ("value", "source")
                        ):
                            raise ValueError("invalid profile value")
                        if name == "pending_profile" and (
                            type(value.get("count")) is not int or not 0 < value["count"] < state.confirmations
                        ):
                            raise ValueError("invalid profile confirmations")
                if entry["kind"] == "absent" and (entry["profile"] or entry["pending_profile"] or pending_absence):
                    raise ValueError("invalid absent state")
            state.entries = entries
            return state
        except (KeyError, TypeError, ValueError) as exc:
            raise StateError("Invalid or unsupported watch state; use a separate output directory or recover it explicitly.") from exc


def scope_key(scanner, username: str, level: str, confirmations: int, fields: tuple[str, ...]) -> str:
    from aliens_eye import __version__

    config = scanner.config
    model = scanner.detector.model
    model_hash = hashlib.sha256(json.dumps(asdict(model), sort_keys=True).encode()).hexdigest() if model else None
    material = {
        "version": __version__, "username": username, "level": level,
        "variations": generate_username_variations(username, level),
        "sites": sorted(scanner.sites_data.items()), "model": model_hash,
        "settings": {
            key: getattr(config, key) for key in (
                "use_ml", "use_playwright", "control_check", "max_content_bytes",
                "timeout", "retries", "backoff_base", "backoff_cap", "rate_limit_delay",
            )
        },
        "confirmations": confirmations, "fields": sorted(fields),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


class WatchStore:
    def __init__(self, output_dir: Path, scope: str) -> None:
        if not scope or any(c not in "0123456789abcdef" for c in scope):
            raise ValueError("watch scope must be a hexadecimal key")
        self.scope = scope
        self.path = Path(output_dir) / ".watch" / f"{scope}.json"
        self._lock = None

    def __enter__(self) -> WatchStore:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.with_suffix(".lock").open("a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise StateError("Cannot lock watch state; another monitor may be using this scope.") from exc
        self._lock = handle
        return self

    def __exit__(self, *_args) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def load(self, confirmations: int = 2, fields: tuple[str, ...] = ()) -> MonitorState:
        self._require_lock()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return MonitorState(confirmations, fields)
        except (OSError, ValueError) as exc:
            raise StateError("Cannot read watch state; use a separate output directory or recover it explicitly.") from exc
        state = MonitorState.from_dict(data)
        if data.get("scope") != self.scope or state.confirmations != confirmations or state.fields != fields:
            raise StateError("Watch state does not match this monitor; use a separate output directory.")
        return state

    def save(self, state: MonitorState) -> None:
        self._require_lock()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({**state.to_dict(), "scope": self.scope}, handle, ensure_ascii=True, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _require_lock(self) -> None:
        if self._lock is None:
            raise StateError("Watch state must be locked before reading or writing.")
