"""Registry of named, versioned, fingerprinted rebuildable projections (spec §4.0).

Every derived index is disposable by construction: a fingerprint mismatch or
version bump triggers rebuild from the ledger. ANN/quantized tiers plug in
here in later phases. Stdlib only.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mnemosyne.journal import _fsync_dir


@dataclass(frozen=True)
class ProjectionSpec:
    name: str
    version: int
    fingerprint: Callable[[], str]
    rebuild: Callable[[], None]


class ProjectionRegistry:
    def __init__(self, state_dir: Path) -> None:
        self._state_path = Path(state_dir) / "projections.json"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._specs: dict[str, ProjectionSpec] = {}

    def _load(self) -> dict[str, Any]:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        return {}

    def _save(self, state: dict[str, Any]) -> None:
        """Atomic write-and-swap: write tmp, fsync, rename over original.

        Same durability idiom as ``journal.CIDJournal._rewrite``.
        """
        tmp = self._state_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(state, sort_keys=True, indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self._state_path)
        _fsync_dir(self._state_path.parent)

    def register(self, spec: ProjectionSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"projection already registered: {spec.name}")
        self._specs[spec.name] = spec

    def check(self, name: str) -> bool:
        spec = self._specs[name]
        stored = self._load().get(name)
        return bool(stored) and stored["version"] == spec.version and stored["fingerprint"] == spec.fingerprint()

    def ensure(self, name: str) -> bool:
        spec = self._specs[name]
        if self.check(name):
            return False
        spec.rebuild()
        state = self._load()
        state[name] = {"version": spec.version, "fingerprint": spec.fingerprint()}
        self._save(state)
        return True

    def status(self) -> dict[str, dict[str, Any]]:
        stored = self._load()
        return {
            name: {"version": spec.version, "fresh": self.check(name), "stored": stored.get(name)}
            for name, spec in self._specs.items()
        }
