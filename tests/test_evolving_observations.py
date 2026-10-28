"""Comprehensive test suite for Evolving Observations (Milestone 2).

Verifies:
- First-Class Observation model and lifecycle
- Verbatim ProofQuote verification with SHA-256 byte-level exact slices
- Algorithmic independent source accounting (user actors vs assistant)
- Dynamic continuous standing scaling with corroboration velocity and contradiction history
- Dynamic salience computation with recency decay and access velocity
- Transitive custody invalidation (erasing evidence retracts observation)
- Cross-engine parity across LocalMemoryEngine and SqliteEngine
- Zero-DELETE invariant enforcement
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ids import evidence_cid
from mnemosyne.models import Evidence, dt_to_json
from mnemosyne.observations import (
    Observation,
    ProofQuote,
    ProofQuoteVerificationError,
    compute_dynamic_salience,
    compute_dynamic_standing,
    compute_independent_source_count,
    verify_proof_quote,
)
from mnemosyne.sqlite_engine import SqliteEngine


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(params=["local", "sqlite"])
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    if request.param == "local":
        return LocalMemoryEngine(store_path=tmp_path / "local-store.json")
    return SqliteEngine(tmp_path / "sqlite-store")


def _seed_evidence(
    engine: Any,
    tenant_id: str,
    content: str,
    *,
    user_id: str = "alice",
    actor: str = "user",
    branch: str = "main",
    session_id: str | None = None,
) -> Evidence:
    cid = evidence_cid(
        content,
        tenant_id=tenant_id,
        user_id=user_id,
        source_type="chat",
        content_pointer=None,
        modality="text",
        sensitivity=0,
    )
    ev = Evidence(
        tenant_id=tenant_id,
        user_id=user_id,
        actor=actor,
        source_type="chat",
        content=content,
        branch=branch,
        cid=cid,
        created_at=datetime.now(UTC),
        session_id=session_id,
    )
    engine.append_evidence(ev, branch=branch)
    return ev


# ---------------------------------------------------------------------------
# Unit tests: ProofQuote verification
# ---------------------------------------------------------------------------


def test_proof_quote_exact_verification():
    content = "The quick brown fox jumps over the lazy dog."
    quote_text = "quick brown fox"
    start = content.index(quote_text)
    end = start + len(quote_text)
    sha = hashlib.sha256(quote_text.encode("utf-8")).hexdigest()

    pq = ProofQuote(
        cid="cid1",
        quote=quote_text,
        start=start,
        end=end,
        sha256=sha,
    )

    # Valid quote must verify without exception
    verify_proof_quote(pq, content)


def test_proof_quote_corrupted_text_fails():
    content = "The quick brown fox jumps over the lazy dog."
    quote_text = "quick brown fox"
    start = content.index(quote_text)
    end = start + len(quote_text)
    sha = hashlib.sha256(quote_text.encode("utf-8")).hexdigest()

    pq = ProofQuote(
        cid="cid1",
        quote="quick brown cat",  # Mismatch text
        start=start,
        end=end,
        sha256=sha,
    )

    with pytest.raises(ProofQuoteVerificationError, match="mismatch"):
        verify_proof_quote(pq, content)


def test_proof_quote_hash_tamper_fails():
    content = "The quick brown fox jumps over the lazy dog."
    quote_text = "quick brown fox"
    start = content.index(quote_text)
    end = start + len(quote_text)

    pq = ProofQuote(
        cid="cid1",
        quote=quote_text,
        start=start,
        end=end,
        sha256="0000000000000000000000000000000000000000000000000000000000000000",
    )

    with pytest.raises(ProofQuoteVerificationError, match="sha256 mismatch"):
        verify_proof_quote(pq, content)


def test_proof_quote_bounds_error_fails():
    content = "Short text"
    pq = ProofQuote(
        cid="cid1",
        quote="Short text",
        start=0,
        end=100,  # Out of bounds
        sha256=hashlib.sha256(b"Short text").hexdigest(),
    )

    with pytest.raises(ProofQuoteVerificationError, match="out of bounds"):
        verify_proof_quote(pq, content)


# ---------------------------------------------------------------------------
# Unit tests: Independent source accounting
# ---------------------------------------------------------------------------


def test_independent_source_accounting():
    ev1 = Evidence(tenant_id="t1", user_id="u1", actor="user", source_type="chat", content="c1", cid="cid1")
    ev2 = Evidence(tenant_id="t1", user_id="u2", actor="user", source_type="chat", content="c2", cid="cid2")
    count_1 = compute_independent_source_count([ev1, ev2])
    assert count_1 == 2

    # Duplicate cid/identity counts once
    count_2 = compute_independent_source_count([ev1, ev1])
    assert count_2 == 1

    # Assistant actors do NOT count as independent sources
    ev_asst = Evidence(tenant_id="t1", user_id="bot", actor="assistant", source_type="chat", content="c3", cid="cid3")
    count_3 = compute_independent_source_count([ev_asst])
    assert count_3 == 0

    # Mixed: user + assistant -> only user is counted
    count_4 = compute_independent_source_count([ev1, ev_asst])
    assert count_4 == 1


# ---------------------------------------------------------------------------
# Unit tests: Dynamic standing & salience scaling
# ---------------------------------------------------------------------------


def test_standing_grounded_vs_ungrounded():
    # Grounded single source: >= 0.51
    standing_grounded = compute_dynamic_standing(
        independent_source_count=1,
        corroboration_velocity=0.0,
        contradiction_count=0,
    )
    assert standing_grounded >= 0.51

    # Ungrounded / self-generated (0 independent sources): capped <= 0.49
    standing_ungrounded = compute_dynamic_standing(
        independent_source_count=0,
        corroboration_velocity=0.0,
        contradiction_count=0,
    )
    assert standing_ungrounded <= 0.49

    # Corroboration velocity boosts standing
    standing_boosted = compute_dynamic_standing(
        independent_source_count=3,
        corroboration_velocity=0.5,
        contradiction_count=0,
    )
    assert standing_boosted > standing_grounded

    # Contradiction count drops standing
    standing_penalized = compute_dynamic_standing(
        independent_source_count=1,
        corroboration_velocity=0.0,
        contradiction_count=1,
    )
    assert standing_penalized < standing_grounded


def test_dynamic_salience():
    now = datetime.now(UTC)
    past = now - timedelta(days=5)

    # Fresh access has high salience
    salience_fresh, v_fresh = compute_dynamic_salience(
        base_salience=0.6,
        access_count=10,
        created_at=past,
        last_accessed_at=now,
        now=now,
    )
    assert 0.0 <= salience_fresh <= 1.0

    # Stale access has decayed salience
    salience_decayed, v_decayed = compute_dynamic_salience(
        base_salience=0.6,
        access_count=10,
        created_at=past,
        last_accessed_at=past,
        now=now,
    )
    assert salience_decayed < salience_fresh


# ---------------------------------------------------------------------------
# Engine tests: Lifecycle & Parity
# ---------------------------------------------------------------------------


def test_observation_lifecycle(engine: Any):
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    content = "Project Mnemosyne uses strict acyclic custody for knowledge pages."
    ev = _seed_evidence(engine, tenant_id, content, user_id="alice")

    quote_text = "acyclic custody"
    start = content.index(quote_text)
    end = start + len(quote_text)
    sha = hashlib.sha256(quote_text.encode("utf-8")).hexdigest()

    pq = ProofQuote(
        cid=ev.cid,
        quote=quote_text,
        start=start,
        end=end,
        sha256=sha,
    )

    obs = Observation(
        tenant_id=tenant_id,
        observation_id="obs-custody-1",
        user_id="alice",
        subject="Mnemosyne",
        topic="Architecture",
        content="Mnemosyne architecture requires acyclic custody.",
        proof_quotes=[pq],
        source_evidence_cids=[ev.cid],
    )

    # 1. Upsert
    saved = engine.observation_upsert(obs)
    assert saved is not None
    # Check retrieval
    retrieved = engine.observation_get(tenant_id, "obs-custody-1")
    assert retrieved is not None
    assert retrieved.observation_id == "obs-custody-1"
    assert retrieved.standing >= 0.51
    assert retrieved.version == 1
    assert retrieved.status == "active"
    assert retrieved.subject == "Mnemosyne"

    # 2. List
    listed = engine.observation_list(tenant_id, subject="Mnemosyne")
    assert len(listed) >= 1
    assert any(o.observation_id == "obs-custody-1" for o in listed)

    # 3. Reconcile with incoming contradiction (different content)
    contradicting_obs = Observation(
        tenant_id=tenant_id,
        observation_id="obs-custody-2",
        user_id="bob",
        subject="Mnemosyne",
        topic="Architecture",
        content="Mnemosyne allows cyclic references.",
        proof_quotes=[pq],
        source_evidence_cids=[ev.cid],
    )
    reconciled, is_contradiction = engine.observation_reconcile(
        tenant_id,
        branch="main",
        observation=contradicting_obs,
    )
    assert is_contradiction is True
    assert len(reconciled.contradiction_history) >= 1
    assert reconciled.standing < retrieved.standing

    # 4. Retract (Zero-DELETE soft update)
    retracted_result = engine.observation_retract(tenant_id, "obs-custody-1", reason="superseded by v2")
    assert bool(retracted_result) is True

    # Confirm status is retracted in storage
    retracted_obs = engine.observation_get(tenant_id, "obs-custody-1", validate_custody=False)
    assert retracted_obs is not None
    assert retracted_obs.status in ("retracted", "superseded")

    # 5. Verify export contains the record (never deleted)
    exported = engine.export_tenant(tenant_id)
    assert "observations" in exported
    exported_obs = [o for o in exported["observations"] if o["observation_id"] == "obs-custody-1"]
    assert len(exported_obs) == 1
    assert exported_obs[0]["status"] in ("retracted", "superseded")


def test_observation_proof_quote_verification_failure(engine: Any):
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    content = "The database is PostgreSQL 16."
    ev = _seed_evidence(engine, tenant_id, content)

    # Tampered quote text that does not match slice
    pq_bad = ProofQuote(
        cid=ev.cid,
        quote="PostgreSQL 17",
        start=content.index("PostgreSQL 16"),
        end=content.index("PostgreSQL 16") + len("PostgreSQL 16"),
        sha256=hashlib.sha256(b"PostgreSQL 17").hexdigest(),
    )

    obs = Observation(
        tenant_id=tenant_id,
        observation_id="obs-bad-proof",
        user_id="alice",
        subject="Database",
        topic="Version",
        content="Database is version 17.",
        proof_quotes=[pq_bad],
        source_evidence_cids=[ev.cid],
    )

    with pytest.raises(ProofQuoteVerificationError):
        engine.observation_upsert(obs)


def test_transitive_custody_invalidation(engine: Any):
    """Erasing backing evidence must cause observation_get to invalidate and retract the observation."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    content = "Temporary confidential note regarding system migration."
    ev = _seed_evidence(engine, tenant_id, content)

    quote_text = "system migration"
    start = content.index(quote_text)
    end = start + len(quote_text)
    sha = hashlib.sha256(quote_text.encode("utf-8")).hexdigest()

    pq = ProofQuote(
        cid=ev.cid,
        quote=quote_text,
        start=start,
        end=end,
        sha256=sha,
    )

    obs = Observation(
        tenant_id=tenant_id,
        observation_id="obs-transitive-1",
        user_id="alice",
        subject="Migration",
        topic="Confidential",
        content="System migration is confidential.",
        proof_quotes=[pq],
        source_evidence_cids=[ev.cid],
    )
    engine.observation_upsert(obs)

    active_obs = engine.observation_get(tenant_id, "obs-transitive-1")
    assert active_obs is not None
    assert active_obs.status == "active"
    assert active_obs.standing >= 0.51

    # Now erase the backing evidence
    engine.forget(tenant_id, ev.cid)

    # Next observation_get must detect erased evidence and retract the observation
    invalidated_obs = engine.observation_get(tenant_id, "obs-transitive-1")
    assert invalidated_obs is not None
    assert invalidated_obs.status == "retracted"
    assert invalidated_obs.standing <= 0.49


def test_observation_reconcile_tampered_proof_quote_rejected(engine: Any):
    """Reconciling with tampered proof quotes must be rejected with ProofQuoteVerificationError across all backends."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    content = "The database cluster runs version 16.4."
    ev = _seed_evidence(engine, tenant_id, content)

    valid_pq = ProofQuote(
        cid=ev.cid,
        quote="version 16.4",
        start=content.index("version 16.4"),
        end=content.index("version 16.4") + len("version 16.4"),
        sha256=hashlib.sha256(b"version 16.4").hexdigest(),
    )
    obs1 = Observation(
        tenant_id=tenant_id,
        observation_id="obs-initial",
        user_id="alice",
        subject="Cluster",
        topic="Version",
        content="The database cluster runs version 16.4.",
        proof_quotes=[valid_pq],
        source_evidence_cids=[ev.cid],
    )
    engine.observation_upsert(obs1)

    # Tampered quote text: forged content not in evidence
    tampered_pq = ProofQuote(
        cid=ev.cid,
        quote="version 99.0-fake",
        sha256=hashlib.sha256(b"version 99.0-fake").hexdigest(),
    )
    incoming = Observation(
        tenant_id=tenant_id,
        observation_id="obs-incoming-tampered",
        user_id="alice",
        subject="Cluster",
        topic="Version",
        content="The database cluster runs version 16.4.",
        proof_quotes=[tampered_pq],
        source_evidence_cids=[ev.cid],
    )

    with pytest.raises(ProofQuoteVerificationError):
        engine.observation_reconcile(tenant_id, observation=incoming)


def test_observation_reconcile_sybil_resistance_same_session(engine: Any):
    """Multiple evidence CIDs from the same user session must not inflate independent_source_count beyond 1."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    session_id = "session-alice-1"
    ev1 = _seed_evidence(engine, tenant_id, "User prefers dark mode by default.", user_id="alice", session_id=session_id)
    ev2 = _seed_evidence(engine, tenant_id, "User reaffirmed dark mode in settings.", user_id="alice", session_id=session_id)
    ev3 = _seed_evidence(engine, tenant_id, "User clicked dark mode switch again.", user_id="alice", session_id=session_id)

    obs1 = Observation(
        tenant_id=tenant_id,
        observation_id="obs-sybil-base",
        user_id="alice",
        subject="UI",
        topic="Theme",
        content="User prefers dark mode.",
        proof_quotes=[
            ProofQuote(
                cid=ev1.cid,
                quote="dark mode",
                sha256=hashlib.sha256(b"dark mode").hexdigest(),
            )
        ],
        source_evidence_cids=[ev1.cid],
    )
    engine.observation_upsert(obs1)

    # Incoming observation from same user with multiple corroborating CIDs
    incoming = Observation(
        tenant_id=tenant_id,
        observation_id="obs-sybil-incoming",
        user_id="alice",
        subject="UI",
        topic="Theme",
        content="User prefers dark mode.",
        proof_quotes=[
            ProofQuote(
                cid=ev2.cid,
                quote="dark mode",
                sha256=hashlib.sha256(b"dark mode").hexdigest(),
            ),
            ProofQuote(
                cid=ev3.cid,
                quote="dark mode",
                sha256=hashlib.sha256(b"dark mode").hexdigest(),
            ),
        ],
        source_evidence_cids=[ev2.cid, ev3.cid],
    )

    reconciled, is_contradiction = engine.observation_reconcile(tenant_id, observation=incoming)
    assert is_contradiction is False
    assert reconciled.independent_source_count == 1

    stored = engine.observation_get(tenant_id, reconciled.observation_id)
    assert stored is not None
    assert stored.independent_source_count == 1


def test_transitive_custody_invalidation_on_retired_evidence(engine: Any):
    """Evidence with retired_at set must trigger transitive observation retraction in observation_get."""
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    content = "Deprecating legacy token endpoint on Friday."
    ev = _seed_evidence(engine, tenant_id, content)

    pq = ProofQuote(
        cid=ev.cid,
        quote="legacy token endpoint",
        sha256=hashlib.sha256(b"legacy token endpoint").hexdigest(),
    )
    obs = Observation(
        tenant_id=tenant_id,
        observation_id="obs-retired-test",
        user_id="alice",
        subject="Auth",
        topic="Tokens",
        content="Legacy token endpoint is being deprecated.",
        proof_quotes=[pq],
        source_evidence_cids=[ev.cid],
    )
    engine.observation_upsert(obs)

    active = engine.observation_get(tenant_id, "obs-retired-test")
    assert active is not None
    assert active.status == "active"

    # Retire the evidence
    now_dt = datetime.now(UTC)
    if isinstance(engine, LocalMemoryEngine):
        key = engine._evidence_key(tenant_id, "main", ev.cid)
        engine.evidence[key].retired_at = now_dt
        engine._persist()
    elif isinstance(engine, SqliteEngine):
        with engine._lock:
            conn = engine._connect(tenant_id)
            conn.execute(
                "UPDATE evidence SET retired_at = ? WHERE tenant_id = ? AND branch = ? AND cid = ?",
                (dt_to_json(now_dt), tenant_id, "main", ev.cid),
            )
            conn.commit()

    # Accessing observation must detect retired evidence and retract
    retracted = engine.observation_get(tenant_id, "obs-retired-test")
    assert retracted is not None
    assert retracted.status == "retracted"
    assert retracted.standing <= 0.20
