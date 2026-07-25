"""Lease #14 — must_keep + pointer-to-original properties (I7 / FR-13 / §25).

Property suite for graduated forgetting:
* must_keep memories never demote under cold/low utility
* demotion always binds a non-null verbatim_pointer (explicit or item_id)
* sole-support abstention when only confabulation-risky gist/trace remains
* consolidation forgetter wire honors must_keep and persists pointer across reloads
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.lifecycle import (
    FidelityTier,
    LifecycleState,
    demotion_decision,
    sole_support_requires_abstention,
)
from mnemosyne.models import Evidence

TENANT = "tenant-must-keep"
USER = "user-must-keep"


def _cold(
    item_id: str,
    tier: FidelityTier = FidelityTier.VERBATIM,
    *,
    must_keep: bool = False,
    protected: bool = False,
    verbatim_pointer: str | None = None,
    next_rehearsal_at: datetime | None = None,
) -> LifecycleState:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    return LifecycleState(
        item_id=item_id,
        tier=tier,
        salience=0.01,
        importance=0.0,
        access_count=0,
        last_accessed=now - timedelta(days=400),
        must_keep=must_keep,
        protected=protected,
        verbatim_pointer=verbatim_pointer,
        next_rehearsal_at=next_rehearsal_at,
    )


def test_must_keep_never_demotes_under_cold_utility() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    for tier in (
        FidelityTier.VERBATIM,
        FidelityTier.EXTRACTIVE_SUMMARY,
        FidelityTier.ABSTRACTIVE_GIST,
    ):
        state = _cold(
            f"keep-{tier.value}",
            tier,
            must_keep=True,
            next_rehearsal_at=now + timedelta(days=90),
        )
        updated, demoted = demotion_decision(state, now, utility_threshold=0.99)
        assert demoted is False, tier
        assert updated.tier == tier
        assert updated.must_keep is True


def test_demotion_always_sets_non_null_verbatim_pointer() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    unset = _cold("orig-unset", FidelityTier.VERBATIM, verbatim_pointer=None)
    demoted, changed = demotion_decision(unset, now, utility_threshold=0.2)
    assert changed is True
    assert demoted.verbatim_pointer == "orig-unset"

    explicit = _cold("gist-a", FidelityTier.EXTRACTIVE_SUMMARY, verbatim_pointer="cid-raw-9")
    demoted2, changed2 = demotion_decision(explicit, now, utility_threshold=0.2)
    assert changed2 is True
    assert demoted2.verbatim_pointer == "cid-raw-9"


def test_must_keep_preserves_existing_verbatim_pointer_without_demotion() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    state = _cold(
        "keep-ptr",
        FidelityTier.EXTRACTIVE_SUMMARY,
        must_keep=True,
        verbatim_pointer="cid-original",
        next_rehearsal_at=now + timedelta(days=60),
    )
    updated, demoted = demotion_decision(state, now, utility_threshold=0.99)
    assert demoted is False
    assert updated.verbatim_pointer == "cid-original"


def test_sole_support_abstention_on_confabulation_risky_gist() -> None:
    risky = LifecycleState(
        "gist-only",
        FidelityTier.ABSTRACTIVE_GIST,
        0.3,
        0.2,
        0,
        None,
        confabulation_risk=True,
    )
    clean = LifecycleState(
        "gist-clean",
        FidelityTier.ABSTRACTIVE_GIST,
        0.3,
        0.2,
        0,
        None,
        confabulation_risk=False,
    )
    trace = LifecycleState(
        "trace-only",
        FidelityTier.STATISTICAL_TRACE,
        0.2,
        0.1,
        0,
        None,
        confabulation_risk=True,
    )
    verbatim = LifecycleState("v", FidelityTier.VERBATIM, 0.9, 0.5, 0, None)
    assert sole_support_requires_abstention([risky]) is True
    assert sole_support_requires_abstention([trace]) is True
    assert sole_support_requires_abstention([clean]) is False
    assert sole_support_requires_abstention([verbatim]) is False
    assert sole_support_requires_abstention([risky, verbatim]) is False
    assert sole_support_requires_abstention([]) is False


def test_forgetter_never_demotes_must_keep_cold_evidence() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    engine = LocalMemoryEngine()
    state = _cold(
        "will-be-cid",
        FidelityTier.VERBATIM,
        must_keep=True,
        next_rehearsal_at=now + timedelta(days=120),
    )
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="Durable must-keep memory that is cold.",
            metadata={"lifecycle": {**state.to_dict(), "item_id": "pending"}},
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    # Bind item_id to the real CID after append (forgetter uses cid as item_id).
    lifecycle = engine.get_evidence(TENANT, cid).metadata["lifecycle"]  # type: ignore[union-attr]
    lifecycle["item_id"] = cid
    engine.update_evidence_metadata(
        TENANT,
        cid,
        {"lifecycle": lifecycle},
        branch="main",
        actor="test",
        source="setup",
    )

    worker = ConsolidationWorker(engine, [], consolidation_min_steps=0)
    result = worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid],
            "passes": ["forgetter"],
            "now": now.isoformat(),
            "utility_threshold": 0.99,
        }
    )
    forgetter = next(p for p in result.pass_results if p.get("name") == "forgetter")
    assert forgetter["status"] == "complete"
    assert forgetter["details"]["demoted"] == 0
    assert cid not in forgetter["details"].get("demoted_cids", [])

    after = engine.get_evidence(TENANT, cid)
    assert after is not None
    lc = after.metadata["lifecycle"]
    assert lc["must_keep"] is True
    assert lc["demoted"] is False
    assert lc["tier"] == FidelityTier.VERBATIM.value


def test_forgetter_persists_explicit_verbatim_pointer_across_reload_demotion() -> None:
    """Regression: _lifecycle_state must load verbatim_pointer so a second demotion
    cannot replace an explicit pointer-to-original with item_id."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    engine = LocalMemoryEngine()
    state = _cold(
        "pending",
        FidelityTier.VERBATIM,
        must_keep=False,
        verbatim_pointer="cid-verbatim-original",
    )
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="Summary backed by a distinct verbatim original.",
            metadata={"lifecycle": {**state.to_dict(), "item_id": "pending"}},
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    lifecycle = engine.get_evidence(TENANT, cid).metadata["lifecycle"]  # type: ignore[union-attr]
    lifecycle["item_id"] = cid
    engine.update_evidence_metadata(
        TENANT,
        cid,
        {"lifecycle": lifecycle},
        branch="main",
        actor="test",
        source="setup",
    )

    worker = ConsolidationWorker(engine, [], consolidation_min_steps=0)
    worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid],
            "passes": ["forgetter"],
            "now": now.isoformat(),
            "utility_threshold": 0.2,
        }
    )
    mid = engine.get_evidence(TENANT, cid)
    assert mid is not None
    assert mid.metadata["lifecycle"]["demoted"] is True
    assert mid.metadata["lifecycle"]["verbatim_pointer"] == "cid-verbatim-original"
    assert mid.metadata["lifecycle"]["tier"] == FidelityTier.EXTRACTIVE_SUMMARY.value

    # Second forgetter pass: cold again, should demote once more but keep pointer.
    mid.metadata["lifecycle"]["last_accessed"] = (now - timedelta(days=400)).isoformat()
    mid.metadata["lifecycle"]["salience"] = 0.01
    mid.metadata["lifecycle"]["importance"] = 0.0
    engine.update_evidence_metadata(
        TENANT,
        cid,
        {"lifecycle": mid.metadata["lifecycle"]},
        branch="main",
        actor="test",
        source="re-cold",
    )
    worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid],
            "passes": ["forgetter"],
            "now": (now + timedelta(days=1)).isoformat(),
            "utility_threshold": 0.2,
        }
    )
    final = engine.get_evidence(TENANT, cid)
    assert final is not None
    assert final.metadata["lifecycle"]["verbatim_pointer"] == "cid-verbatim-original"
    assert final.metadata["lifecycle"]["tier"] == FidelityTier.ABSTRACTIVE_GIST.value


def test_forgetter_honors_top_level_must_keep_metadata() -> None:
    """When must_keep is only on evidence.metadata (not nested lifecycle), still honor it."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="Top-level must_keep flag.",
            metadata={
                "must_keep": True,
                "lifecycle": {
                    "tier": FidelityTier.VERBATIM.value,
                    "salience": 0.01,
                    "importance": 0.0,
                    "access_count": 0,
                    "last_accessed": (now - timedelta(days=400)).isoformat(),
                    "next_rehearsal_at": (now + timedelta(days=90)).isoformat(),
                },
            },
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    worker = ConsolidationWorker(engine, [], consolidation_min_steps=0)
    worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid],
            "passes": ["forgetter"],
            "now": now.isoformat(),
            "utility_threshold": 0.99,
        }
    )
    after = engine.get_evidence(TENANT, cid)
    assert after is not None
    assert after.metadata["lifecycle"]["demoted"] is False
    assert after.metadata["lifecycle"]["tier"] == FidelityTier.VERBATIM.value
    assert after.metadata["lifecycle"]["must_keep"] is True
