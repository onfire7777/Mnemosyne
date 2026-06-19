"""Dual user model: authoritative explicit entries plus advisory latent state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from mnemosyne.ids import new_id


class UserMemoryKind(str, Enum):
    IDENTITY = "identity"
    HARD_INSTRUCTION = "hard_instruction"
    EXPLICIT_PREFERENCE = "explicit_preference"
    INFERRED_PREFERENCE = "inferred_preference"
    SITUATIONAL_PREFERENCE = "situational_preference"
    TEMPORARY_STATE = "temporary_state"


AUTHORITY_ORDER = {
    UserMemoryKind.HARD_INSTRUCTION: 6,
    UserMemoryKind.IDENTITY: 5,
    UserMemoryKind.EXPLICIT_PREFERENCE: 4,
    UserMemoryKind.SITUATIONAL_PREFERENCE: 3,
    UserMemoryKind.TEMPORARY_STATE: 2,
    UserMemoryKind.INFERRED_PREFERENCE: 1,
}


@dataclass(slots=True)
class UserModelEntry:
    tenant_id: str
    user_id: str
    kind: UserMemoryKind
    statement: str
    scope: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7
    exceptions: dict[str, Any] = field(default_factory=dict)
    source_evidence_cids: list[str] = field(default_factory=list)
    valid_from: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None
    status: str = "active"
    id: str = field(default_factory=new_id)

    def authority(self) -> int:
        return AUTHORITY_ORDER[self.kind]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["valid_from"] = self.valid_from.astimezone(UTC).isoformat()
        data["valid_to"] = self.valid_to.astimezone(UTC).isoformat() if self.valid_to else None
        return data


@dataclass(slots=True)
class LatentUserProfile:
    tenant_id: str
    user_id: str
    embedding: list[float]
    summary: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "embedding": list(self.embedding),
            "summary": self.summary,
            "updated_at": self.updated_at.astimezone(UTC).isoformat(),
        }


class UserModel:
    def __init__(self) -> None:
        self.entries: dict[str, UserModelEntry] = {}
        self.latent_profiles: dict[tuple[str, str], LatentUserProfile] = {}

    def add_entry(self, entry: UserModelEntry) -> str:
        for current in self.entries.values():
            if (
                current.tenant_id == entry.tenant_id
                and current.user_id == entry.user_id
                and current.scope == entry.scope
                and current.status == "active"
                and self._conflicts(current.statement, entry.statement)
                and current.authority() < entry.authority()
            ):
                current.status = "superseded"
                current.valid_to = entry.valid_from
        self.entries[entry.id] = entry
        return entry.id

    def set_latent_profile(self, profile: LatentUserProfile) -> None:
        self.latent_profiles[(profile.tenant_id, profile.user_id)] = profile

    def context_packet(self, tenant_id: str, user_id: str, scope: dict[str, Any]) -> dict[str, Any]:
        active = [
            entry
            for entry in self.entries.values()
            if entry.tenant_id == tenant_id
            and entry.user_id == user_id
            and entry.status == "active"
            and self._scope_matches(entry.scope, scope)
            and not self._excepted(entry, scope)
        ]
        active.sort(key=lambda item: (item.authority(), item.confidence), reverse=True)
        latent = self.latent_profiles.get((tenant_id, user_id))
        return {
            "authoritative": [entry.to_dict() for entry in active if entry.kind != UserMemoryKind.INFERRED_PREFERENCE],
            "inferred": [entry.to_dict() for entry in active if entry.kind == UserMemoryKind.INFERRED_PREFERENCE],
            "latent_advisory": latent.to_dict() if latent else None,
            "rules": {
                "hard_instruction_outranks_inference": True,
                "latent_never_overrides_explicit": True,
                "scope_matching_required": True,
            },
        }

    @staticmethod
    def _scope_matches(entry_scope: dict[str, Any], request_scope: dict[str, Any]) -> bool:
        return all(request_scope.get(key) == value for key, value in entry_scope.items())

    @staticmethod
    def _excepted(entry: UserModelEntry, scope: dict[str, Any]) -> bool:
        return any(scope.get(key) == value for key, value in entry.exceptions.items())

    @staticmethod
    def _conflicts(left: str, right: str) -> bool:
        return left.strip().lower() != right.strip().lower()

