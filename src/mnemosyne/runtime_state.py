"""Persistent runtime side-state for local CLI and MCP tools."""

from __future__ import annotations

import json
import copy
import os
import tempfile
import logging
import weakref
import threading
from contextlib import nullcontext
from collections import defaultdict, deque
from math import ceil
from pathlib import Path
from typing import Any

from mnemosyne.gate import RegressionCase
from mnemosyne.learning import LearningSystem
from mnemosyne.observability import MetricsRegistry
from mnemosyne.queue import InProcessQueue
from mnemosyne.user_model import LatentUserProfile, SupportStrategy, UserMistakeEvent, UserModel, UserModelEntry


_LOG = logging.getLogger(__name__)


class _PersistentMetricsRegistry(MetricsRegistry):
    """Track new observations even when an equal-valued sample rolls off a window."""

    def __init__(self, snapshot=None):
        super().__init__(snapshot)
        self.persistence_lock = threading.RLock()
        self.pending_samples = defaultdict(lambda: deque(maxlen=200))
        self.changed_gauges = set()

    def increment(self, name, amount=1):
        with self.persistence_lock:
            super().increment(name, amount)

    def observe(self, name, value):
        with self.persistence_lock:
            super().observe(name, value)
            self.pending_samples[name].append(float(value))

    def gauge(self, name, value):
        with self.persistence_lock:
            super().gauge(name, value)
            self.changed_gauges.add(name)

    def snapshot(self):
        with self.persistence_lock:
            return super().snapshot()


def _support_strategy_threshold(value: Any) -> int:
    try:
        return max(2, int(value))
    except (TypeError, ValueError):
        return 2

def migrate_legacy_learning(runtime, learning: LearningSystem, tenant_id: str) -> dict[str, int]:
    """Import compatibility objects into their canonical records exactly once."""
    before = runtime.writer.read(tenant_id)
    if learning.engine is runtime.engine:
        learning.persist_native([tenant_id])
    else:
        destination = LearningSystem(runtime.engine)
        destination.import_legacy({
            "trajectories": [item.to_dict() for item in learning.trajectories.values()],
            "attributions": [item.to_dict() for item in learning.attributions.values()],
            "lessons": [item.to_dict() for item in learning.lessons.values()],
            "procedures": [item.to_dict() for item in learning.procedures.values()],
        }, [tenant_id])
    after = runtime.writer.read(tenant_id)
    return {"archived": len(after["episodes"].keys() - before["episodes"].keys())}


class RuntimeState:
    """JSON-backed side-state for non-core local runtime surfaces.

    The core memory engine persists evidence, assertions, relations, and audit
    data. This side-state keeps user-profile and learning-loop objects durable
    for the local CLI/MCP process without changing the canonical schema.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.data: dict[str, Any] = {
            "user_model": {
                "entries": [],
                "latent_profiles": [],
                "mistake_events": [],
                "support_strategies": [],
                "support_strategy_threshold": 2,
            },
            "learning": {"trajectories": [], "attributions": [], "lessons": [], "procedures": []},
            "queue": {"order": [], "jobs": []},
            "metrics": {"counters": {}, "gauges": {}, "samples": {}},
        }
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

        self._baseline = copy.deepcopy(self.data)
        self._metrics_baselines = weakref.WeakKeyDictionary()
        self._metrics_save_lock = threading.RLock()

    @classmethod
    def from_store_path(cls, store_path: str | Path | None) -> "RuntimeState | None":
        if not store_path:
            return None
        path = Path(store_path).expanduser()
        return cls(path.with_suffix(path.suffix + ".runtime.json"))

    def save(self) -> dict[str, Any]:
        # Merge independent writers under a short file lock; provider work has
        # already finished. Never resurrect a concurrently erased profile row.
        from mnemosyne._file_lock import exclusive_file_lock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.path.with_suffix(self.path.suffix + ".lock"), timeout=1.0):
            # A file that lacks a section (hand-written, very old) did not delete it: read it as unchanged.
            current = {**self._baseline, **json.loads(self.path.read_text())} if self.path.exists() else self._baseline
            merged = _merge_state(self._baseline, self.data, current)
            self._publish(merged)
            if "gate_cases" in merged:  # read lazily from self.data, no live owner: keep seeing other writers' cases
                self.data["gate_cases"] = merged["gate_cases"]
            # Baseline = what THIS process wrote. The other sections are rebuilt from live objects that never
            # saw other writers' rows; adopting the merged file here would turn "never saw" into "deleted".
            self._baseline = copy.deepcopy(self.data)
        return merged

    def _publish(self, data) -> None:
        """Publish under the caller's file lock, leaving an intact prior file on failure."""
        descriptor, temporary = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load_user_model(self) -> UserModel:
        user_data = self.data.get("user_model", {})
        model = UserModel(
            support_strategy_threshold=_support_strategy_threshold(
                user_data.get("support_strategy_threshold", 2)
            )
        )
        for row in user_data.get("entries", []):
            model.add_entry(UserModelEntry.from_dict(row))
        for row in user_data.get("latent_profiles", []):
            model.set_latent_profile(LatentUserProfile.from_dict(row))
        model.mistake_events = [UserMistakeEvent.from_dict(row) for row in user_data.get("mistake_events", [])]
        model.support_strategies = {
            strategy.id: strategy
            for strategy in (
                SupportStrategy.from_dict(row) for row in user_data.get("support_strategies", [])
            )
        }
        return model

    def refresh_user_model(self, model: UserModel) -> None:
        """Fold the profile another process saved into a live model, in place: its holders keep the object."""
        # shortcut: parses the whole file on every profile call, add an mtime check if that shows up in profiles
        saved = json.loads(self.path.read_text(encoding="utf-8")).get("user_model") if self.path.exists() else None
        if saved is None or saved == self._baseline["user_model"]:
            return
        self.data["user_model"] = saved
        self._baseline["user_model"] = copy.deepcopy(saved)
        fresh = vars(self.load_user_model())
        fresh.pop("_source_custody")
        vars(model).update(fresh)

    def save_user_model(self, model: UserModel) -> None:
        self.data["user_model"] = {
            "entries": [entry.to_dict() for entry in model.entries.values()],
            "latent_profiles": [profile.to_dict() for profile in model.latent_profiles.values()],
            "mistake_events": [event.to_dict() for event in model.mistake_events],
            "support_strategies": [strategy.to_dict() for strategy in model.support_strategies.values()],
            "support_strategy_threshold": model.support_strategy_threshold,
        }
        self.save()

    def load_learning(self, learning: LearningSystem) -> LearningSystem:
        learning_data = self.data.get("learning", {})
        if "engine_tenants" in learning_data:
            checkpoint = learning_data.get("engine_path")
            if checkpoint is not None:
                from mnemosyne.engine import LocalMemoryEngine
                path = self.path.with_suffix(self.path.suffix + ".learning.json").resolve()
                if checkpoint != path.name:
                    raise ValueError("learning checkpoint must be adjacent to its runtime state")
                current = getattr(learning.engine, "store_path", None)
                if current is not None and Path(current).resolve() != path:
                    raise ValueError("learning checkpoint belongs to another engine")
                if current is None:
                    if (not isinstance(learning.engine, LocalMemoryEngine)
                            or learning.engine.evidence or getattr(learning.engine, "_learning_data", {})):
                        raise ValueError("load a learning checkpoint with an empty local engine")
                    if not path.is_file():
                        raise FileNotFoundError(path)
                    learning.engine = LocalMemoryEngine.shared_writer(path)
            learning.load_native(learning_data["engine_tenants"])
            return learning
        learning.import_legacy(learning_data)
        if learning._native_tenants:
            self.save_learning(learning)
        return learning

    def migrate_learning(self, runtime, tenant_id: str) -> dict[str, int]:
        from mnemosyne.runtime_state import migrate_legacy_learning
        legacy = self.load_learning(LearningSystem(runtime.engine))
        return migrate_legacy_learning(runtime, legacy, tenant_id)

    def save_learning(self, learning: LearningSystem) -> None:
        from mnemosyne.engine import LocalMemoryEngine
        checkpoint = self.path.with_suffix(self.path.suffix + ".learning.json").resolve()
        engine = learning.engine
        if (isinstance(engine, LocalMemoryEngine) and not getattr(engine, "store_path", None)
                and not getattr(engine, "root_dir", None)):
            # Explicitly saving an ephemeral engine gives its native records,
            # evidence and audit trail one durable home, rather than reserializing
            # a second, lossy compatibility model into runtime side-state.
            engine.attach_store(checkpoint)
        tenants = learning.persist_native()
        self.data["learning"] = {"engine_tenants": tenants}
        if getattr(engine, "store_path", None) and Path(engine.store_path).resolve() == checkpoint:
            self.data["learning"]["engine_path"] = checkpoint.name
        self.save()

    def load_queue(self) -> InProcessQueue:
        return InProcessQueue.from_dict(self.data.get("queue"))

    def save_queue(self, queue: InProcessQueue) -> None:
        self.data["queue"] = queue.to_dict()
        merged = self.save()["queue"]
        # Adopt other processes' jobs in place (workers and pipelines hold this object), and the baseline
        # with them. This run's finished jobs stay in memory only, for its own report.
        fresh = InProcessQueue.from_dict(merged)
        done = {job.id: job for job in queue.jobs.values() if job.status == "complete"}
        queue.jobs, queue._order = {**done, **fresh.jobs}, fresh._order
        self.data["queue"] = merged
        self._baseline["queue"] = copy.deepcopy(merged)

    def load_metrics(self) -> MetricsRegistry:
        metrics = _PersistentMetricsRegistry(self.data.get("metrics"))
        self._metrics_baselines[metrics] = metrics.snapshot().to_dict()
        return metrics

    def save_metrics(self, metrics: MetricsRegistry) -> None:
        """Merge advisory telemetry independently from strict profile state.

        Counters contribute each registry's unsaved delta. Observations append
        in commit order and retain the latest 200 samples. Explicit gauge writes
        use last-committing-writer semantics; derived p95 gauges use the merged
        sample window. Failed telemetry persistence cannot fail a memory write.
        """
        registry_lock = metrics.persistence_lock if isinstance(metrics, _PersistentMetricsRegistry) else nullcontext()
        with self._metrics_save_lock, registry_lock:
            self._save_metrics(metrics)

    def _save_metrics(self, metrics: MetricsRegistry) -> None:
        from mnemosyne._file_lock import exclusive_file_lock

        desired = metrics.snapshot().to_dict()
        base = self._metrics_baselines.get(metrics, {})
        pending = ({name: list(values) for name, values in metrics.pending_samples.items()}
                   if isinstance(metrics, _PersistentMetricsRegistry) else None)
        changed = metrics.changed_gauges if isinstance(metrics, _PersistentMetricsRegistry) else None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with exclusive_file_lock(self.path.with_suffix(self.path.suffix + ".lock"), timeout=1.0):
                current = json.loads(self.path.read_text()) if self.path.exists() else copy.deepcopy(self._baseline)
                merged = _merge_metrics(base, desired, current.get("metrics", {}), pending, changed)
                self._publish({**current, "metrics": merged})
            self.data["metrics"] = copy.deepcopy(merged)
            self._baseline["metrics"] = copy.deepcopy(merged)
            self._metrics_baselines[metrics] = desired
            if isinstance(metrics, _PersistentMetricsRegistry):
                metrics.pending_samples.clear()
                metrics.changed_gauges.clear()
        except (OSError, ValueError, TypeError):
            # Retain deltas/journal for a subsequent save; never log source data.
            _LOG.warning("Advisory metrics persistence deferred", exc_info=False)

    def load_gate_cases(self) -> list[RegressionCase]:
        return [RegressionCase.from_dict(row) for row in self.data.get("gate_cases", [])]

    def save_gate_cases(self, cases: list[RegressionCase]) -> None:
        self.data["gate_cases"] = [case.to_dict() for case in cases]
        self.save()


def _merge_metrics(base, desired, current, observations=None, changed_gauges=None):
    """Merge telemetry deltas, keeping strict conflict rules out of the data path."""
    result = copy.deepcopy(current)
    counters = result.setdefault("counters", {})
    for name, value in desired.get("counters", {}).items():
        delta = value - base.get("counters", {}).get(name, 0)
        counters[name] = counters.get(name, 0) + delta

    gauges = result.setdefault("gauges", {})
    for name, value in desired.get("gauges", {}).items():
        if (changed_gauges is not None and name in changed_gauges) or (
                changed_gauges is None and value != base.get("gauges", {}).get(name)):
            gauges[name] = value

    samples = result.setdefault("samples", {})
    if observations is None:
        observations = {}
        for name, values in desired.get("samples", {}).items():
            previous = base.get("samples", {}).get(name, [])
            # Plain externally supplied registries lack an observation journal.
            # Match the retained window's overlap rather than appending its past.
            overlap = next((size for size in range(min(len(previous), len(values)), 0, -1)
                            if previous[-size:] == values[:size]), 0)
            observations[name] = values[overlap:]
    for name, appended in observations.items():
        if not appended:
            continue
        samples[name] = (samples.get(name, []) + list(appended))[-200:]
        ordered = sorted(samples[name])
        gauges[name + ".p95"] = ordered[max(0, ceil(len(ordered) * 0.95) - 1)]
    return result


def _merge_state(base, desired, current):
    """Three-way merge, rejecting simultaneous changes to the same value."""
    if desired == base:
        return copy.deepcopy(current)
    if current == base or current == desired:
        return copy.deepcopy(desired)
    if all(isinstance(value, dict) for value in (base, desired, current)):
        result = {}
        missing = object()
        for key in base.keys() | desired.keys() | current.keys():
            old, new, live = base.get(key, missing), desired.get(key, missing), current.get(key, missing)
            if new is missing:
                if old is missing:
                    if live is not missing:
                        result[key] = copy.deepcopy(live)
                    continue
                if live != old and live is not missing:
                    raise ValueError("concurrent runtime state conflict")
                continue
            if (old is missing and live is not missing and live != new
                    and isinstance(new, (dict, list)) and type(live) is type(new)):
                old = type(new)()  # both writers added this key (first learning save): merge them as additions
            if old is missing:
                if live is not missing and live != new:
                    raise ValueError("concurrent runtime state conflict")
                result[key] = copy.deepcopy(new)
            elif live is missing:
                if new != old:
                    raise ValueError("concurrent runtime state conflict")
            else:
                result[key] = _merge_state(old, new, live)
        return result
    if all(isinstance(value, list) for value in (base, desired, current)):
        if all(isinstance(row, str) for rows in (base, desired, current) for row in rows):
            # Id lists (queue order, learning tenants): keep the live order, drop what this writer removed, add what it added.
            removed, known = set(base) - set(desired), set(base) | set(current)
            return [row for row in current if row not in removed] + [row for row in desired if row not in known]
        def key(row):
            if not isinstance(row, dict):
                return None
            return row.get("id") or (str(row.get("tenant_id")) + ":" + str(row["user_id"]) if row.get("user_id") else None)
        if all(key(row) is not None for rows in (base, desired, current) for row in rows):
            mappings = [{key(row): row for row in rows} for rows in (base, desired, current)]
            if all(len(mapping) == len(rows) for mapping, rows in zip(mappings, (base, desired, current))):
                return list(_merge_state(*mappings).values())
    raise ValueError("concurrent runtime state conflict")
