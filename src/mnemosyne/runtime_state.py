"""Persistent runtime side-state for local CLI and MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mnemosyne.gate import RegressionCase
from mnemosyne.learning import FailureAttribution, LearningSystem, Lesson, Procedure, Trajectory
from mnemosyne.observability import MetricsRegistry
from mnemosyne.queue import InProcessQueue
from mnemosyne.user_model import LatentUserProfile, SupportStrategy, UserMistakeEvent, UserModel, UserModelEntry


def _support_strategy_threshold(value: Any) -> int:
    try:
        return max(2, int(value))
    except (TypeError, ValueError):
        return 2

def migrate_legacy_learning(runtime, learning: LearningSystem, tenant_id: str) -> dict[str, int]:
    """Archive legacy trajectories once without inventing receipts or outcomes.

    Existing lessons and procedures remain available through the compatibility
    reader. They cannot enter the active runtime without contemporary evidence.
    """
    from mnemosyne.experience.receipts import digest
    candidates = [row for row in learning.trajectories.values() if row.tenant_id == tenant_id]
    if not candidates:
        return {"archived": 0}

    def migrate(state):
        count = 0
        for row in candidates:
            key = 'legacy-' + digest([tenant_id, row.id])
            if key in state['episodes']:
                continue
            state['episodes'][key] = {
                'id': key, 'tenant_id': tenant_id, 'user_id': row.user_id,
                'session_id': row.session_id, 'task_class': 'legacy',
                'receipt_ids': [], 'source_cids': [], 'signals': [], 'tool_events': [],
                'used_skills': [], 'used_lessons': [], 'user_text': row.task,
                'status': 'legacy', 'created_at': row.created_at.isoformat(),
                'expires_at': row.created_at.isoformat(), 'prediction': None,
                'reward': None, 'rpe': None, 'turn_index': 0,
                'legacy_trajectory': row.to_dict(),
            }
            count += 1
        return {"archived": count}
    return runtime.writer.apply(tenant_id, 'legacy_migration', migrate)



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

    @classmethod
    def from_store_path(cls, store_path: str | Path | None) -> "RuntimeState | None":
        if not store_path:
            return None
        path = Path(store_path).expanduser()
        return cls(path.with_suffix(path.suffix + ".runtime.json"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
        tmp.replace(self.path)

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
            learning.load_native(learning_data["engine_tenants"])
            return learning
        learning.trajectories = {
            item.id: item for item in (Trajectory.from_dict(row) for row in learning_data.get("trajectories", []))
        }
        learning.attributions = {
            item.trajectory_id: item for item in (FailureAttribution.from_dict(row) for row in learning_data.get("attributions", []))
        }
        learning.lessons = {item.id: item for item in (Lesson.from_dict(row) for row in learning_data.get("lessons", []))}
        learning.procedures = {item.id: item for item in (Procedure.from_dict(row) for row in learning_data.get("procedures", []))}
        return learning

    def migrate_learning(self, runtime, tenant_id: str) -> dict[str, int]:
        from mnemosyne.runtime_state import migrate_legacy_learning
        legacy = self.load_learning(LearningSystem(runtime.engine))
        return migrate_legacy_learning(runtime, legacy, tenant_id)

    def save_learning(self, learning: LearningSystem) -> None:
        tenants = learning.persist_native()
        if getattr(learning.engine, "store_path", None) or getattr(learning.engine, "root_dir", None):
            self.data["learning"] = {"engine_tenants": tenants}
            self.save()
            return
        self.data["learning"] = {
            "trajectories": [item.to_dict() for item in learning.trajectories.values()],
            "attributions": [item.to_dict() for item in learning.attributions.values()],
            "lessons": [item.to_dict() for item in learning.lessons.values()],
            "procedures": [item.to_dict() for item in learning.procedures.values()],
        }
        self.save()

    def load_queue(self) -> InProcessQueue:
        return InProcessQueue.from_dict(self.data.get("queue"))

    def save_queue(self, queue: InProcessQueue) -> None:
        self.data["queue"] = queue.to_dict()
        self.save()

    def load_metrics(self) -> MetricsRegistry:
        return MetricsRegistry(self.data.get("metrics"))

    def save_metrics(self, metrics: MetricsRegistry) -> None:
        self.data["metrics"] = metrics.snapshot().to_dict()
        self.save()

    def load_gate_cases(self) -> list[RegressionCase]:
        return [RegressionCase.from_dict(row) for row in self.data.get("gate_cases", [])]

    def save_gate_cases(self, cases: list[RegressionCase]) -> None:
        self.data["gate_cases"] = [case.to_dict() for case in cases]
        self.save()
