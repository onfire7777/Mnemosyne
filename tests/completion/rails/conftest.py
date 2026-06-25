"""Shared fixtures/helpers for the §31 invariant-rail breach tests.

These tests are *adversarial*: each one constructs an input that deliberately
tries to breach one of the seven immutable §31 rails and asserts the system
refuses or clamps. Earlier completion branches used strict xfail markers as
forcing functions while Tier A enforcement was still landing; current tests in
this directory should run as live regressions unless a new, evidence-backed
strict-audit gap is intentionally added.

No ``src/mnemosyne`` module is imported with side effects beyond construction;
nothing here mutates the production tree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Iterable

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
from mnemosyne.security import TrustTier

TENANT = "tenant-rails"
USER = "user-rails"


def fresh_engine() -> LocalMemoryEngine:
    """A purely in-memory engine (no store_path => no disk persistence)."""

    return LocalMemoryEngine()


def add_evidence(
    engine: LocalMemoryEngine,
    *,
    content: str,
    trust_tier: int = int(TrustTier.DIRECT_USER),
    actor: str = "user",
    source_type: str = "seed",
    source_identity: str | None = None,
    branch: str = "main",
) -> str:
    """Append one Evidence row and return its content CID.

    Matches the canonical construction used throughout ``tests/`` (e.g.
    ``tests/test_self_optimization.py::seeded_engine``).
    """

    return engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor=actor,  # type: ignore[arg-type]
            source_type=source_type,
            content=content,
            source_identity=source_identity,
            trust_tier=trust_tier,
            access_policy={"tenant": TENANT},
        ),
        branch=branch,
    )


def make_assertion(
    *,
    subject: str,
    predicate: str,
    obj: str,
    trust_tier: int,
    source_cids: Iterable[str],
    confidence: float = 0.8,
    valid_from: datetime | None = None,
    status: str = "candidate",
) -> Assertion:
    """Build an Assertion with explicit trust tier and validity window.

    ``valid_from`` is exposed because the live supersession path in
    ``engine.upsert_assertion`` keys recency tie-breaks off it.
    """

    kwargs = dict(
        tenant_id=TENANT,
        user_id=USER,
        subject=subject,
        predicate=predicate,
        object=obj,
        confidence=confidence,
        trust_tier=trust_tier,
        source_evidence_cids=list(source_cids),
        status=status,  # type: ignore[arg-type]
    )
    if valid_from is not None:
        kwargs["valid_from"] = valid_from
    return Assertion(**kwargs)  # type: ignore[arg-type]


def active_assertions(engine: LocalMemoryEngine, branch: str = "main") -> list[Assertion]:
    return [
        item
        for item in engine.assertions.values()
        if item.tenant_id == TENANT and item.branch == branch and item.status in {"active", "contested"}
    ]


def utcnow() -> datetime:
    return datetime.now(UTC)


def minutes_ago(minutes: float) -> datetime:
    return utcnow() - timedelta(minutes=minutes)
