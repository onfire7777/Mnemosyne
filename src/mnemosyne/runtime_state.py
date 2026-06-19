"""Persistent runtime side-state for local CLI and MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mnemosyne.learning import FailureAttribution, LearningSystem, Lesson, Procedure, Trajectory
from mnemosyne.user_model import LatentUserProfile, UserMemoryKind, UserModel, UserModelEntry


class RuntimeState:
    """JSON-backed side-state for non-core local runtime surfaces.

    The core memory engine persists evidence, assertions, relations, and audit
    data. This side-state keeps user-profile and learning-loop objects durable
    for the local CLI/MCP process without changing the canonical schema.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.data: dict[str, Any] = {
            "user_model": {"entries": [], "latent_profiles": []},
            "learning": {"trajectories": [], "attributions": [], "lessons": [], "procedures": []},
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
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def load_user_model(self) -> UserModel:
        model = UserModel()
        user_data = self.data.get("user_model", {})
        for row in user_data.get("entries", []):
            model.add_entry(UserModelEntry.from_dict(row))
        for row in user_data.get("latent_profiles", []):
            model.set_latent_profile(LatentUserProfile.from_dict(row))
        return model

    def save_user_model(self, model: UserModel) -> None:
        self.data["user_model"] = {
            "entries": [entry.to_dict() for entry in model.entries.values()],
            "latent_profiles": [profile.to_dict() for profile in model.latent_profiles.values()],
        }
        self.save()

    def load_learning(self, learning: LearningSystem) -> LearningSystem:
        learning_data = self.data.get("learning", {})
        learning.trajectories = {
            item.id: item for item in (Trajectory.from_dict(row) for row in learning_data.get("trajectories", []))
        }
        learning.attributions = {
            item.trajectory_id: item for item in (FailureAttribution.from_dict(row) for row in learning_data.get("attributions", []))
        }
        learning.lessons = {item.id: item for item in (Lesson.from_dict(row) for row in learning_data.get("lessons", []))}
        learning.procedures = {item.id: item for item in (Procedure.from_dict(row) for row in learning_data.get("procedures", []))}
        return learning

    def save_learning(self, learning: LearningSystem) -> None:
        self.data["learning"] = {
            "trajectories": [item.to_dict() for item in learning.trajectories.values()],
            "attributions": [item.to_dict() for item in learning.attributions.values()],
            "lessons": [item.to_dict() for item in learning.lessons.values()],
            "procedures": [item.to_dict() for item in learning.procedures.values()],
        }
        self.save()
