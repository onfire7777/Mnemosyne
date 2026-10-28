"""First-Class Evolving Observations for the Mnemosyne cognitive substrate.

Observations capture evolving, evidence-grounded beliefs and behavioral patterns
synthesized across multiple sessions. They maintain verbatim proof quotes against
un-erased source evidence, algorithmic independent source accounting, dynamic
salience and standing scaling with corroboration velocity, and live transitive
custody invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import math
from typing import Any, Iterable, Literal

from mnemosyne.ids import new_id
from mnemosyne.models import dt_to_json, parse_dt, utc_now
from mnemosyne.standing import (
    AUTHORITY_THRESHOLD,
    GROUNDED_FLOOR,
    SELF_GENERATED_CEILING,
)

ObservationStatus = Literal["active", "superseded", "retracted", "quarantined", "contested"]


class ProofQuoteValidationError(ValueError):
    """Raised when a proof quote cannot be verified against source evidence."""


ProofQuoteVerificationError = ProofQuoteValidationError


class ObservationConflict(ValueError):
    """Raised on version/concurrency conflict updating an observation."""


@dataclass
class ProofQuote:
    """Verbatim quote span grounded in source evidence."""

    cid: str = ""
    quote: str = ""
    start: int | None = None
    end: int | None = None
    sha256: str | None = None
    source_evidence_cid: str | None = None
    exact_quote: str | None = None
    byte_start: int | None = None
    byte_end: int | None = None

    def __post_init__(self) -> None:
        if not self.cid and self.source_evidence_cid:
            self.cid = self.source_evidence_cid
        elif self.cid and not self.source_evidence_cid:
            self.source_evidence_cid = self.cid

        if not self.quote and self.exact_quote:
            self.quote = self.exact_quote
        elif self.quote and not self.exact_quote:
            self.exact_quote = self.quote

        if self.start is None and self.byte_start is not None:
            self.start = self.byte_start
        elif self.start is not None and self.byte_start is None:
            self.byte_start = self.start

        if self.end is None and self.byte_end is not None:
            self.end = self.byte_end
        elif self.end is not None and self.byte_end is None:
            self.byte_end = self.end

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "cid": self.cid,
            "quote": self.quote,
            "source_evidence_cid": self.cid,
            "exact_quote": self.quote,
        }
        if self.start is not None:
            res["start"] = self.start
            res["byte_start"] = self.start
        if self.end is not None:
            res["end"] = self.end
            res["byte_end"] = self.end
        if self.sha256 is not None:
            res["sha256"] = self.sha256
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any] | ProofQuote) -> ProofQuote:
        if isinstance(data, ProofQuote):
            return data
        cid = str(data.get("cid") or data.get("source_evidence_cid") or "")
        quote = str(data.get("quote") or data.get("exact_quote") or "")
        start = data.get("start") if data.get("start") is not None else data.get("byte_start")
        end = data.get("end") if data.get("end") is not None else data.get("byte_end")
        return cls(
            cid=cid,
            quote=quote,
            start=start,
            end=end,
            sha256=data.get("sha256"),
            source_evidence_cid=cid,
            exact_quote=quote,
            byte_start=start,
            byte_end=end,
        )


@dataclass
class ContradictionSnapshot:
    """Historical record of a prior observation superseded or contradicted."""

    prior_observation_id: str = ""
    content: str = ""
    superseded_at: datetime = field(default_factory=utc_now)
    superseding_evidence_cids: list[str] = field(default_factory=list)
    rationale: str = ""
    timestamp: str | None = None
    contradicting_claim: str | None = None
    resolved: bool = False
    severity: float = 1.0

    def __post_init__(self) -> None:
        if not self.content and self.contradicting_claim:
            self.content = self.contradicting_claim
        elif self.content and not self.contradicting_claim:
            self.contradicting_claim = self.content
        if self.timestamp:
            parsed = parse_dt(self.timestamp)
            if parsed:
                self.superseded_at = parsed

    def to_dict(self) -> dict[str, Any]:
        return {
            "prior_observation_id": self.prior_observation_id,
            "content": self.content,
            "superseded_at": dt_to_json(self.superseded_at),
            "superseding_evidence_cids": list(self.superseding_evidence_cids),
            "rationale": self.rationale,
            "timestamp": dt_to_json(self.superseded_at),
            "contradicting_claim": self.content,
            "resolved": self.resolved,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | ContradictionSnapshot) -> ContradictionSnapshot:
        if isinstance(data, ContradictionSnapshot):
            return data
        content = str(data.get("content") or data.get("contradicting_claim") or "")
        return cls(
            prior_observation_id=str(data.get("prior_observation_id") or ""),
            content=content,
            superseded_at=parse_dt(data.get("superseded_at") or data.get("timestamp")) or utc_now(),
            superseding_evidence_cids=list(data.get("superseding_evidence_cids") or []),
            rationale=str(data.get("rationale") or ""),
            contradicting_claim=content,
            resolved=bool(data.get("resolved", False)),
            severity=float(data.get("severity", 1.0)),
        )


@dataclass(slots=True)
class Observation:
    """First-class evolving belief or pattern grounded in source evidence."""

    tenant_id: str
    user_id: str
    subject: str
    topic: str
    content: str
    branch: str = "main"
    observation_id: str = field(default_factory=new_id)
    proof_quotes: list[ProofQuote] = field(default_factory=list)
    source_evidence_cids: list[str] = field(default_factory=list)
    independent_source_count: int = 1
    corroboration_velocity: float = 0.0
    contradiction_history: list[ContradictionSnapshot] = field(default_factory=list)
    standing: float = 0.51
    salience: float = 0.5
    access_velocity: float = 0.0
    access_count: int = 0
    last_accessed_at: datetime | None = None
    status: ObservationStatus = "active"
    superseded_by: str | None = None
    version: int = 1
    freshness_watermark: str | None = None
    trust_tier: int = 0
    sensitivity: int = 0
    access_policy: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.proof_quotes:
            self.proof_quotes = [ProofQuote.from_dict(q) for q in self.proof_quotes]
        if self.contradiction_history:
            self.contradiction_history = [
                ContradictionSnapshot.from_dict(c) for c in self.contradiction_history
            ]

    @property
    def authority(self) -> bool:
        """Authority is true if standing is at or above the authority threshold."""
        return self.standing >= AUTHORITY_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "tenant_id": self.tenant_id,
            "branch": self.branch,
            "user_id": self.user_id,
            "subject": self.subject,
            "topic": self.topic,
            "content": self.content,
            "proof_quotes": [q.to_dict() for q in self.proof_quotes],
            "source_evidence_cids": list(self.source_evidence_cids),
            "independent_source_count": self.independent_source_count,
            "corroboration_velocity": self.corroboration_velocity,
            "contradiction_history": [c.to_dict() for c in self.contradiction_history],
            "standing": self.standing,
            "salience": self.salience,
            "access_velocity": self.access_velocity,
            "access_count": self.access_count,
            "last_accessed_at": dt_to_json(self.last_accessed_at),
            "status": self.status,
            "superseded_by": self.superseded_by,
            "version": self.version,
            "freshness_watermark": self.freshness_watermark,
            "trust_tier": self.trust_tier,
            "sensitivity": self.sensitivity,
            "access_policy": dict(self.access_policy),
            "created_at": dt_to_json(self.created_at),
            "updated_at": dt_to_json(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Observation:
        copy_data = dict(data)
        copy_data["proof_quotes"] = [
            ProofQuote.from_dict(q) for q in copy_data.get("proof_quotes", [])
        ]
        copy_data["contradiction_history"] = [
            ContradictionSnapshot.from_dict(c)
            for c in copy_data.get("contradiction_history", [])
        ]
        copy_data["created_at"] = parse_dt(copy_data.get("created_at")) or utc_now()
        copy_data["updated_at"] = parse_dt(copy_data.get("updated_at")) or utc_now()
        copy_data["last_accessed_at"] = parse_dt(copy_data.get("last_accessed_at"))
        return cls(**copy_data)


def verify_proof_quote(
    quote: ProofQuote | dict[str, Any],
    evidence_content: str,
    *,
    is_erased: bool = False,
    is_retired: bool = False,
) -> None:
    """Verify that a proof quote matches live source evidence text and sha256."""
    if isinstance(quote, dict):
        quote = ProofQuote.from_dict(quote)
    if is_erased:
        raise ProofQuoteValidationError(f"Evidence {quote.cid} has been erased")
    if is_retired:
        raise ProofQuoteValidationError(f"Evidence {quote.cid} is retired")
    if not quote.quote or not isinstance(quote.quote, str):
        raise ProofQuoteValidationError("Proof quote cannot be empty")

    if quote.start is not None and quote.end is not None:
        if not (0 <= quote.start < quote.end <= len(evidence_content)):
            raise ProofQuoteValidationError(
                f"Proof quote slice [{quote.start}:{quote.end}] out of bounds for content length {len(evidence_content)}"
            )
        actual = evidence_content[quote.start:quote.end]
        if actual != quote.quote:
            raise ProofQuoteValidationError(
                f"Proof quote text mismatch at [{quote.start}:{quote.end}]: expected {quote.quote!r}, found {actual!r}"
            )
    else:
        if quote.quote not in evidence_content:
            raise ProofQuoteValidationError(
                f"Proof quote {quote.quote!r} is not a substring of evidence {quote.cid}"
            )

    if quote.sha256 is not None:
        computed_sha256 = hashlib.sha256(quote.quote.encode("utf-8")).hexdigest()
        if computed_sha256.lower() != quote.sha256.lower():
            raise ProofQuoteValidationError(
                f"Proof quote sha256 mismatch: expected {quote.sha256}, computed {computed_sha256}"
            )


def verify_observation_proof_quotes(
    observation: Observation,
    engine: Any,
    branch: str = "main",
) -> None:
    """Verify all proof quotes on an observation against the live engine storage."""
    for quote in observation.proof_quotes:
        if callable(engine):
            ev = engine(quote.cid)
        elif hasattr(engine, "get_evidence"):
            ev = engine.get_evidence(observation.tenant_id, quote.cid, branch=branch)
        else:
            raise ValueError("Engine or getter must be provided to verify proof quotes")
        if ev is None:
            raise ProofQuoteValidationError(f"Source evidence {quote.cid} not found")
        is_erased = bool(getattr(ev, "erased", False))
        is_retired = getattr(ev, "retired_at", None) is not None
        verify_proof_quote(
            quote,
            ev.content,
            is_erased=is_erased,
            is_retired=is_retired,
        )


def compute_independent_source_count(evidence_rows: Iterable[Any]) -> int:
    """Algorithmic independent source accounting.

    Origins set is collected from user actors across distinct sessions,
    source identities, or CIDs.
    """
    origins: set[str] = set()
    for row in evidence_rows:
        if getattr(row, "actor", None) == "user":
            origin = (
                getattr(row, "source_identity", None)
                or getattr(row, "session_id", None)
                or getattr(row, "cid", None)
            )
            if origin:
                origins.add(str(origin))
    return max(1, len(origins)) if origins else 0


def compute_dynamic_standing(
    independent_source_count: int,
    corroboration_velocity: float = 0.0,
    contradiction_count: int = 0,
    access_velocity: float = 0.0,
    base_confidence: float = 0.51,
) -> float:
    """Compute dynamic standing and groundedness.

    - If independent_source_count <= 0: capped at SELF_GENERATED_CEILING (0.49).
    - If independent_source_count >= 1: starts at GROUNDED_FLOOR (0.51),
      scales with corroboration count (+0.10 per additional source up to 0.90),
      adds corroboration velocity bonus (+0.05 * tanh(corroboration_velocity)),
      adds rehearsal bonus (+0.05 * min(1.0, access_velocity)),
      subtracts contradiction pressure (-0.15 * contradiction_count).
    """
    if independent_source_count <= 0:
        return min(SELF_GENERATED_CEILING, max(0.1, base_confidence))

    score = GROUNDED_FLOOR + 0.10 * min(4, max(0, independent_source_count - 1))
    if corroboration_velocity > 0:
        score += 0.05 * math.tanh(corroboration_velocity)
    if access_velocity > 0:
        score += 0.05 * min(1.0, access_velocity)
    if contradiction_count > 0:
        score -= 0.15 * contradiction_count
        return max(0.0, min(0.99, round(score, 4)))
    return max(GROUNDED_FLOOR, min(0.99, round(score, 4)))


def compute_dynamic_salience(
    base_salience: float = 0.5,
    access_count: int = 0,
    created_at: datetime | None = None,
    last_accessed_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[float, float]:
    """Dynamically compute (salience, access_velocity) from recency and rehearsal."""
    now = now or utc_now()
    created = created_at or now
    hours_elapsed = max(0.0, (now - created).total_seconds() / 3600.0)
    v_access = access_count / (hours_elapsed + 1.0)

    last_access = last_accessed_at or created
    hours_since_access = max(0.0, (now - last_access).total_seconds() / 3600.0)
    recency_factor = math.exp(-0.05 * hours_since_access)

    salience = 0.5 * base_salience + 0.3 * min(1.0, v_access) + 0.2 * recency_factor
    clamped_salience = max(0.0, min(1.0, round(salience, 4)))
    return clamped_salience, round(v_access, 4)


def reconcile_observation(
    existing: Observation,
    incoming: Observation,
    *,
    now: datetime | None = None,
) -> tuple[Observation, bool]:
    """Reconcile an incoming observation with an existing active observation.

    Returns:
        (reconciled_observation, is_contradiction)
    """
    now = now or utc_now()
    # Check if contents are identical or harmonious
    if existing.content.strip().lower() == incoming.content.strip().lower():
        # Reinforcement / corroboration
        all_cids = list(dict.fromkeys(list(existing.source_evidence_cids) + list(incoming.source_evidence_cids)))
        existing_quotes = {q.cid: q for q in existing.proof_quotes}
        for q in incoming.proof_quotes:
            existing_quotes[q.cid] = q
        merged_quotes = list(existing_quotes.values())

        old_sources = existing.independent_source_count
        new_sources = max(old_sources, incoming.independent_source_count, len(all_cids))

        delta_sources = max(0, new_sources - old_sources)
        hours_elapsed = max(0.01, (now - existing.updated_at).total_seconds() / 3600.0)
        v_c = delta_sources / hours_elapsed

        standing = compute_dynamic_standing(
            independent_source_count=new_sources,
            corroboration_velocity=v_c,
            contradiction_count=len(existing.contradiction_history),
            access_velocity=existing.access_velocity,
        )
        salience, v_acc = compute_dynamic_salience(
            base_salience=existing.salience,
            access_count=existing.access_count + 1,
            created_at=existing.created_at,
            last_accessed_at=now,
            now=now,
        )

        reconciled = Observation(
            tenant_id=existing.tenant_id,
            user_id=existing.user_id,
            subject=existing.subject,
            topic=existing.topic,
            content=existing.content,
            branch=existing.branch,
            observation_id=existing.observation_id,
            proof_quotes=merged_quotes,
            source_evidence_cids=all_cids,
            independent_source_count=new_sources,
            corroboration_velocity=round(v_c, 4),
            contradiction_history=existing.contradiction_history,
            standing=standing,
            salience=salience,
            access_velocity=v_acc,
            access_count=existing.access_count + 1,
            last_accessed_at=now,
            status="active",
            version=existing.version + 1,
            freshness_watermark=dt_to_json(now),
            trust_tier=max(existing.trust_tier, incoming.trust_tier),
            sensitivity=max(existing.sensitivity, incoming.sensitivity),
            access_policy=dict(existing.access_policy),
            created_at=existing.created_at,
            updated_at=now,
        )
        return reconciled, False

    # Contradiction: incoming supersedes existing
    snapshot = ContradictionSnapshot(
        prior_observation_id=existing.observation_id,
        content=existing.content,
        superseded_at=now,
        superseding_evidence_cids=list(incoming.source_evidence_cids),
        rationale=f"Content updated from {existing.content!r} to {incoming.content!r}",
    )
    new_history = list(incoming.contradiction_history) + [snapshot]
    standing = compute_dynamic_standing(
        independent_source_count=incoming.independent_source_count,
        corroboration_velocity=incoming.corroboration_velocity,
        contradiction_count=len(new_history),
        access_velocity=incoming.access_velocity,
    )
    salience, v_acc = compute_dynamic_salience(
        base_salience=incoming.salience,
        access_count=incoming.access_count,
        created_at=incoming.created_at,
        last_accessed_at=now,
        now=now,
    )
    superseding = Observation(
        tenant_id=incoming.tenant_id,
        user_id=incoming.user_id,
        subject=incoming.subject,
        topic=incoming.topic,
        content=incoming.content,
        branch=incoming.branch,
        observation_id=incoming.observation_id or new_id(),
        proof_quotes=incoming.proof_quotes,
        source_evidence_cids=incoming.source_evidence_cids,
        independent_source_count=incoming.independent_source_count,
        corroboration_velocity=incoming.corroboration_velocity,
        contradiction_history=new_history,
        standing=standing,
        salience=salience,
        access_velocity=v_acc,
        access_count=incoming.access_count,
        last_accessed_at=now,
        status="active",
        version=1,
        freshness_watermark=dt_to_json(now),
        trust_tier=incoming.trust_tier,
        sensitivity=incoming.sensitivity,
        access_policy=dict(incoming.access_policy),
        created_at=now,
        updated_at=now,
    )
    return superseding, True
