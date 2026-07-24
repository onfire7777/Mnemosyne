"""Dual user model: authoritative explicit entries plus advisory latent state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from mnemosyne.ids import new_id
from mnemosyne.models import parse_dt
from mnemosyne.text import hashing_embedding


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserModelEntry":
        copy = dict(data)
        copy["kind"] = UserMemoryKind(copy["kind"])
        copy["valid_from"] = parse_dt(copy.get("valid_from")) or datetime.now(UTC)
        copy["valid_to"] = parse_dt(copy.get("valid_to"))
        return cls(**copy)


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LatentUserProfile":
        copy = dict(data)
        copy["updated_at"] = parse_dt(copy.get("updated_at")) or datetime.now(UTC)
        return cls(**copy)


def build_advisory_latent_profile(
    tenant_id: str,
    user_id: str,
    summary: str,
    *,
    dims: int = 64,
) -> LatentUserProfile:
    """Build an advisory latent profile from free-text summary (FR-16 residual #26).

    Uses the deterministic hashing embedding as a local stand-in so the dual-user
    model can carry a fixed-width advisory vector without ML deps in Python core.
    Explicit/hard preferences still outrank this advisory signal.
    """

    text = (summary or "").strip() or "empty"
    return LatentUserProfile(
        tenant_id=tenant_id,
        user_id=user_id,
        embedding=hashing_embedding(text, dims=dims),
        summary=text,
    )


@dataclass(slots=True)
class UserMistakeEvent:
    """A neutral episodic record of a user slip (blueprint §24).

    Stored as an event, never a judgment. The ``pattern`` is the similarity key
    used to group repeated occurrences; ``description`` narrates the event
    factually without characterizing the user.
    """

    tenant_id: str
    user_id: str
    pattern: str
    description: str
    scope: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["occurred_at"] = self.occurred_at.astimezone(UTC).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserMistakeEvent":
        copy = dict(data)
        copy["occurred_at"] = parse_dt(copy.get("occurred_at")) or datetime.now(UTC)
        return cls(**copy)


@dataclass(slots=True)
class SupportStrategy:
    """A scoped, reversible assistance offer derived from repeated user slips.

    Per blueprint §24 a single slip never yields a strategy and never a durable
    judgment; only repeated similar events promote one, framed as assistance
    (e.g. "Offer to double-check date math before deploys.") and retractable.
    """

    tenant_id: str
    user_id: str
    pattern: str
    suggestion: str
    scope: dict[str, Any] = field(default_factory=dict)
    supporting_event_ids: list[str] = field(default_factory=list)
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.astimezone(UTC).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SupportStrategy":
        copy = dict(data)
        copy["created_at"] = parse_dt(copy.get("created_at")) or datetime.now(UTC)
        return cls(**copy)


def _default_support_suggestion(pattern: str) -> str:
    readable = pattern.replace("_", " ").replace("-", " ").strip()
    return f"Offer to double-check {readable} proactively."


class UserModel:
    def __init__(self, support_strategy_threshold: int = 2) -> None:
        self.entries: dict[str, UserModelEntry] = {}
        self.latent_profiles: dict[tuple[str, str], LatentUserProfile] = {}
        self.mistake_events: list[UserMistakeEvent] = []
        self.support_strategies: dict[str, SupportStrategy] = {}
        # Repeated-similar threshold (>=2): a single user slip never promotes a
        # strategy and never a durable judgment (blueprint §24).
        self.support_strategy_threshold = max(2, support_strategy_threshold)

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

    def record_user_mistake(
        self,
        event: UserMistakeEvent,
        *,
        suggestion: str | None = None,
    ) -> dict[str, Any]:
        """Record an episodic user-mistake event and promote a support strategy
        only once similar events repeat (blueprint §24).

        The event is stored verbatim as a neutral episode. When the count of
        similar events (same tenant/user/pattern/scope) reaches the configured
        threshold, a single scoped, reversible :class:`SupportStrategy` is
        emitted (or its supporting evidence refreshed). A lone slip promotes
        nothing. Returns a summary with the event id, the strategy id (if any),
        whether a strategy was newly promoted, and the similar-event count.
        """
        self.mistake_events.append(event)
        similar = [
            existing
            for existing in self.mistake_events
            if existing.tenant_id == event.tenant_id
            and existing.user_id == event.user_id
            and existing.pattern == event.pattern
            and existing.scope == event.scope
        ]
        result: dict[str, Any] = {
            "event_id": event.id,
            "strategy_id": None,
            "promoted": False,
            "similar_count": len(similar),
        }
        if len(similar) < self.support_strategy_threshold:
            return result
        existing_strategy = self._active_strategy(
            event.tenant_id, event.user_id, event.pattern, event.scope
        )
        supporting_ids = [item.id for item in similar]
        if existing_strategy is None:
            strategy = SupportStrategy(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                pattern=event.pattern,
                suggestion=suggestion or _default_support_suggestion(event.pattern),
                scope=dict(event.scope),
                supporting_event_ids=supporting_ids,
            )
            self.support_strategies[strategy.id] = strategy
            result["strategy_id"] = strategy.id
            result["promoted"] = True
        else:
            existing_strategy.supporting_event_ids = supporting_ids
            result["strategy_id"] = existing_strategy.id
        return result

    def active_support_strategies(
        self, tenant_id: str, user_id: str, scope: dict[str, Any]
    ) -> list[SupportStrategy]:
        return [
            strategy
            for strategy in self.support_strategies.values()
            if strategy.tenant_id == tenant_id
            and strategy.user_id == user_id
            and strategy.status == "active"
            and self._scope_matches(strategy.scope, scope)
        ]

    def retire_support_strategy(self, strategy_id: str) -> bool:
        """Reversibly retire a support strategy; returns False if already gone."""
        strategy = self.support_strategies.get(strategy_id)
        if strategy is None or strategy.status != "active":
            return False
        strategy.status = "retired"
        return True

    def _active_strategy(
        self, tenant_id: str, user_id: str, pattern: str, scope: dict[str, Any]
    ) -> SupportStrategy | None:
        for strategy in self.support_strategies.values():
            if (
                strategy.tenant_id == tenant_id
                and strategy.user_id == user_id
                and strategy.pattern == pattern
                and strategy.scope == scope
                and strategy.status == "active"
            ):
                return strategy
        return None

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
        strategies = self.active_support_strategies(tenant_id, user_id, scope)
        return {
            "authoritative": [entry.to_dict() for entry in active if entry.kind != UserMemoryKind.INFERRED_PREFERENCE],
            "inferred": [entry.to_dict() for entry in active if entry.kind == UserMemoryKind.INFERRED_PREFERENCE],
            "latent_advisory": latent.to_dict() if latent else None,
            "support_strategies": [strategy.to_dict() for strategy in strategies],
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
