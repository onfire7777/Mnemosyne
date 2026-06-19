"""Typed records for the Mnemosyne engine contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from mnemosyne.ids import new_id

Actor = Literal["user", "assistant", "tool", "system", "external"]
AssertionStatus = Literal[
    "candidate",
    "active",
    "superseded",
    "contested",
    "quarantined",
    "retracted",
]
BeliefOperation = Literal["ADD", "UPDATE", "SUPERSEDE", "NOOP", "CONTEST"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def dt_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class Evidence:
    tenant_id: str
    user_id: str
    actor: Actor
    source_type: str
    content: str
    source_identity: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trust_tier: int = 1
    capability_tags: list[str] = field(default_factory=list)
    sensitivity: int = 0
    access_policy: dict[str, Any] = field(default_factory=dict)
    branch: str = "main"
    cid: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    erased: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = dt_to_json(self.created_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        copy = dict(data)
        copy["created_at"] = parse_dt(copy.get("created_at")) or utc_now()
        return cls(**copy)


@dataclass(slots=True)
class Assertion:
    tenant_id: str
    subject: str
    predicate: str
    object: str
    user_id: str | None = None
    branch: str = "main"
    scope: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7
    calibration: dict[str, Any] = field(default_factory=dict)
    valid_from: datetime = field(default_factory=utc_now)
    valid_to: datetime | None = None
    transaction_time: datetime = field(default_factory=utc_now)
    expired_at: datetime | None = None
    justification_id: str | None = None
    source_evidence_cids: list[str] = field(default_factory=list)
    status: AssertionStatus = "candidate"
    version: int = 1
    superseded_by: str | None = None
    trust_tier: int = 1
    sensitivity: int = 0
    access_policy: dict[str, Any] = field(default_factory=dict)
    last_accessed: datetime | None = None
    access_count: int = 0
    id: str = field(default_factory=new_id)

    def statement(self) -> str:
        return f"{self.subject} {self.predicate} {self.object}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("valid_from", "valid_to", "transaction_time", "expired_at", "last_accessed"):
            data[key] = dt_to_json(getattr(self, key))
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Assertion":
        copy = dict(data)
        for key in ("valid_from", "valid_to", "transaction_time", "expired_at", "last_accessed"):
            copy[key] = parse_dt(copy.get(key))
        if copy.get("valid_from") is None:
            copy["valid_from"] = utc_now()
        if copy.get("transaction_time") is None:
            copy["transaction_time"] = utc_now()
        return cls(**copy)


@dataclass(slots=True)
class Relation:
    tenant_id: str
    source: str
    predicate: str
    target: str
    branch: str = "main"
    confidence: float = 0.7
    valid_from: datetime = field(default_factory=utc_now)
    valid_to: datetime | None = None
    source_evidence_cids: list[str] = field(default_factory=list)
    access_policy: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["valid_from"] = dt_to_json(self.valid_from)
        data["valid_to"] = dt_to_json(self.valid_to)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relation":
        copy = dict(data)
        copy["valid_from"] = parse_dt(copy.get("valid_from")) or utc_now()
        copy["valid_to"] = parse_dt(copy.get("valid_to"))
        return cls(**copy)


@dataclass(slots=True)
class Preference:
    tenant_id: str
    user_id: str
    category: Literal["format", "tone", "workflow", "tooling", "domain", "constraint"]
    statement: str
    scope: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7
    explicit: bool = False
    exceptions: dict[str, Any] = field(default_factory=dict)
    source_evidence_cids: list[str] = field(default_factory=list)
    valid_from: datetime = field(default_factory=utc_now)
    valid_to: datetime | None = None
    status: AssertionStatus = "active"
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["valid_from"] = dt_to_json(self.valid_from)
        data["valid_to"] = dt_to_json(self.valid_to)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preference":
        copy = dict(data)
        copy["valid_from"] = parse_dt(copy.get("valid_from")) or utc_now()
        copy["valid_to"] = parse_dt(copy.get("valid_to"))
        return cls(**copy)


@dataclass(slots=True)
class Hit:
    id: str
    kind: Literal["evidence", "assertion", "relation", "preference"]
    tenant_id: str
    branch: str
    text: str
    score: float
    channel: str
    provenance: list[str] = field(default_factory=list)
    trust_tier: int = 1
    sensitivity: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResult:
    query: str
    hits: list[Hit]
    confidence: float
    abstained: bool
    uncertainty_note: str | None
    token_budget: int
    used_tokens: int
    explain: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [hit.to_dict() for hit in self.hits],
            "confidence": self.confidence,
            "abstained": self.abstained,
            "uncertainty_note": self.uncertainty_note,
            "token_budget": self.token_budget,
            "used_tokens": self.used_tokens,
            "explain": self.explain,
        }


@dataclass(slots=True)
class MergeReport:
    from_branch: str
    into_branch: str
    evidence_added: int
    assertions_added: int
    assertions_merged: int
    relations_added: int
    conflicts: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Justification:
    tenant_id: str
    assertion_id: str
    evidence_cids: list[str] = field(default_factory=list)
    rule: str | None = None
    dependency_ids: list[str] = field(default_factory=list)
    kind: Literal["support", "assumption"] = "support"
    label: dict[str, Any] = field(default_factory=dict)
    hypothesis_prob: float | None = None
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Justification":
        return cls(**dict(data))


@dataclass(slots=True)
class Contradiction:
    tenant_id: str
    a: str
    b: str
    status: Literal["open", "resolved"] = "open"
    resolution: str | None = None
    detected_at: datetime = field(default_factory=utc_now)
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["detected_at"] = dt_to_json(self.detected_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Contradiction":
        copy = dict(data)
        copy["detected_at"] = parse_dt(copy.get("detected_at")) or utc_now()
        return cls(**copy)


@dataclass(slots=True)
class BeliefRevisionReport:
    operation: BeliefOperation
    assertion_id: str
    justification_id: str | None
    affected_assertion_ids: list[str]
    contradictions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
