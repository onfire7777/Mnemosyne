"""P15-S2 15-01-01 — deterministic fast|medium|slow cadence tiers.

Pins allowlisted tiers, due selection, tenant/branch isolation, replay
idempotence, the existing [5 steps, 24h] rail, unchanged default behavior,
receipt fields, and the rule that derived rows never count as independent
corroboration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.consolidation import (
    DEFAULT_CONSOLIDATION_PASSES,
    ConsolidationJob,
    ConsolidationWorker,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.ids import evidence_cid
from mnemosyne.models import Evidence
from mnemosyne.policy import CONSOLIDATION_CADENCE_TIERS, OperatingPolicy

TENANT = "tenant-timescales"
OTHER_TENANT = "tenant-timescales-other"
USER = "user-timescales"
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

FAST_PASSES = ["replayer", "summarizer", "embedder"]
MEDIUM_PASSES = [
    "replayer",
    "extractor",
    "resolver",
    "belief_reviser",
    "promotion_gate",
]
SLOW_PASSES = [
    "replayer",
    "lesson_distiller",
    "skill_inducer",
    "forgetter",
    "user_model_updater",
]
TIER_PASSES = {"fast": FAST_PASSES, "medium": MEDIUM_PASSES, "slow": SLOW_PASSES}


def _engine(*, tenant: str = TENANT) -> LocalMemoryEngine:
    return LocalMemoryEngine()


def _append(
    engine: LocalMemoryEngine,
    content: str,
    *,
    tenant: str = TENANT,
    branch: str = "main",
    source_type: str = "episode",
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=USER,
            actor="user",
            source_type=source_type,
            content=content,
            trust_tier=0,
            access_policy={"tenant": tenant},
        ),
        branch=branch,
    )


def _worker(
    engine: LocalMemoryEngine | None = None, **kwargs: object
) -> ConsolidationWorker:
    return ConsolidationWorker(engine or _engine(), gate_cases=[], **kwargs)


def _payload(
    cids: list[str],
    *,
    tenant: str = TENANT,
    branch: str = "main",
    cadence_tier: str | None = None,
    step: int | None = None,
    now: datetime | None = None,
    passes: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": tenant,
        "branch": branch,
        "source_evidence_cids": list(cids),
    }
    if cadence_tier is not None:
        payload["cadence_tier"] = cadence_tier
    if step is not None:
        payload["consolidation_step"] = step
    if now is not None:
        payload["now"] = now.isoformat()
    if passes is not None:
        payload["passes"] = list(passes)
    return payload


def _receipt(result: object) -> dict[str, object]:
    receipt = getattr(result, "cadence_receipt", None)
    assert isinstance(receipt, dict)
    return receipt


def _summaries(
    engine: LocalMemoryEngine, tenant: str = TENANT
) -> list[dict[str, object]]:
    return [
        row
        for row in engine.export_tenant(tenant)["evidence"]
        if row.get("source_type") == "consolidation-summary"
    ]


def _postgres_case() -> RegressionCase:
    return RegressionCase(
        id="case-postgres",
        signature="fact-sig preferred database",
        query="preferred database",
        expected_substring="Postgres",
        protected=True,
    )


def _active_assertions(engine: LocalMemoryEngine, tenant: str = TENANT) -> list[dict]:
    return [
        row
        for row in engine.export_tenant(tenant)["assertions"]
        if row.get("status") == "active"
    ]


def test_cadence_tiers_are_allowlisted_fast_medium_slow() -> None:
    assert CONSOLIDATION_CADENCE_TIERS == ("fast", "medium", "slow")
    policy = OperatingPolicy()
    assert set(policy.consolidation_cadence_tier_passes) == {"fast", "medium", "slow"}
    assert set(policy.consolidation_cadence_tier_min_steps) == {
        "fast",
        "medium",
        "slow",
    }
    for tier, passes in TIER_PASSES.items():
        assert policy.consolidation_cadence_tier_passes[tier] == passes
        assert set(passes).issubset(set(DEFAULT_CONSOLIDATION_PASSES))
    assert policy.consolidation_cadence_tier_min_steps["fast"] == 5
    assert policy.consolidation_cadence_tier_min_steps["medium"] == 15
    assert policy.consolidation_cadence_tier_min_steps["slow"] == 60


@pytest.mark.parametrize("bogus", ["sleep", "FAST", "weekly", "", "turbo"])
def test_unknown_cadence_tier_is_rejected(bogus: str) -> None:
    engine = _engine()
    cid = _append(engine, "Unknown tier must fail closed before any pass runs.")
    worker = _worker(engine)
    with pytest.raises(ValueError, match="cadence_tier"):
        worker.run_queue_payload(_payload([cid], cadence_tier=bogus, step=0, now=NOW))


@pytest.mark.parametrize("tier", ["fast", "medium", "slow"])
def test_requested_tier_selects_policy_pass_set(tier: str) -> None:
    engine = _engine()
    cid = _append(engine, f"Tier {tier} selects a frozen existing pass set.")
    result = _worker(engine).run_queue_payload(
        _payload([cid], cadence_tier=tier, step=0, now=NOW)
    )
    assert result.passes_run == TIER_PASSES[tier]
    receipt = _receipt(result)
    assert receipt["tier"] == tier
    assert receipt["due_reason"] == "first_pass"
    assert receipt["input_cids"] == [cid]


def test_default_behavior_unchanged_when_tier_not_requested() -> None:
    engine = _engine()
    cid = _append(engine, "Default consolidation must keep the unscoped pass list.")
    worker = _worker(engine)
    defaulted = worker.run_queue_payload(_payload([cid], step=0, now=NOW))
    explicit = worker.run_queue_payload(
        _payload([cid], step=5, now=NOW + timedelta(hours=1), passes=["summarizer"])
    )

    assert defaulted.passes_run == list(DEFAULT_CONSOLIDATION_PASSES)
    assert defaulted.cadence_receipt is None
    assert defaulted.source_evidence_cids == [cid]
    assert explicit.passes_run == ["summarizer"]
    assert explicit.cadence_receipt is None


def test_due_selection_is_deterministic_and_skips_unripe_cids() -> None:
    engine = _engine()
    ripe = _append(engine, "This medium item has never been consolidated.")
    held = _append(engine, "This medium item was already processed at step 0.")
    workers = [_worker(engine), _worker(engine)]
    receipts: list[dict[str, object]] = []
    for worker in workers:
        first = worker.run_queue_payload(
            _payload([held], cadence_tier="medium", step=0, now=NOW)
        )
        assert _receipt(first)["due_reason"] == "first_pass"
        assert _receipt(first)["input_cids"] == [held]
        mixed = worker.run_queue_payload(
            _payload(
                [held, ripe],
                cadence_tier="medium",
                step=5,
                now=NOW + timedelta(minutes=10),
            )
        )
        receipt = _receipt(mixed)
        assert receipt["tier"] == "medium"
        assert receipt["due_reason"] == "first_pass"
        assert receipt["input_cids"] == [ripe]
        receipts.append(
            {
                "tier": receipt["tier"],
                "due_reason": receipt["due_reason"],
                "input_cids": receipt["input_cids"],
                "policy_fingerprint": receipt["policy_fingerprint"],
            }
        )
    assert receipts[0] == receipts[1]


def test_tenant_and_branch_due_state_are_isolated() -> None:
    engine = _engine()
    engine.branch("research", frm="main", tenant_id=TENANT)
    main_cid = _append(engine, "Isolation source on main for tenant A.")
    other_branch_cid = _append(
        engine,
        "Isolation source on a research branch for tenant A.",
        branch="research",
    )
    other_tenant_cid = _append(
        engine,
        "Isolation source on main for tenant B.",
        tenant=OTHER_TENANT,
    )
    worker = _worker(engine, consolidation_min_steps=0)
    worker.run_queue_payload(_payload([main_cid], cadence_tier="fast", step=0, now=NOW))

    other_tenant = worker.run_queue_payload(
        _payload(
            [other_tenant_cid],
            tenant=OTHER_TENANT,
            cadence_tier="fast",
            step=0,
            now=NOW,
        )
    )
    other_branch = worker.run_queue_payload(
        _payload(
            [other_branch_cid],
            branch="research",
            cadence_tier="fast",
            step=0,
            now=NOW,
        )
    )
    same_scope = worker.run_queue_payload(
        _payload([main_cid], cadence_tier="fast", step=0, now=NOW)
    )

    assert _receipt(other_tenant)["due_reason"] == "first_pass"
    assert _receipt(other_tenant)["input_cids"] == [other_tenant_cid]
    assert _receipt(other_branch)["due_reason"] == "first_pass"
    assert _receipt(other_branch)["input_cids"] == [other_branch_cid]
    assert _receipt(same_scope)["due_reason"] == "not_due"
    assert _receipt(same_scope)["input_cids"] == []


def test_replay_of_due_tier_is_idempotent() -> None:
    engine = _engine()
    cid = _append(engine, "Replay must not mint a second derived summary.")
    worker = _worker(engine, consolidation_min_steps=0)

    first = worker.run_queue_payload(
        _payload([cid], cadence_tier="fast", step=0, now=NOW)
    )
    second = worker.run_queue_payload(
        _payload([cid], cadence_tier="fast", step=0, now=NOW)
    )
    summaries = _summaries(engine)

    assert _receipt(first)["due_reason"] == "first_pass"
    assert _receipt(second)["due_reason"] == "not_due"
    assert _receipt(second)["input_cids"] == []
    assert len(summaries) == 1
    assert first.source_evidence_cids == [cid]


def test_tiered_runs_still_honor_five_step_and_twenty_four_hour_rail() -> None:
    engine = _engine()
    first_cid = _append(engine, "First due fast item consumes the cadence rail.")
    second_cid = _append(engine, "A second due item still cannot outrun five steps.")
    stale_cid = _append(engine, "A stale tenant may run once the 24h bound is crossed.")
    worker = _worker(engine)

    worker.run_queue_payload(
        _payload([first_cid], cadence_tier="fast", step=0, now=NOW)
    )
    with pytest.raises(RuntimeError, match="cadence"):
        worker.run_queue_payload(
            _payload(
                [second_cid],
                cadence_tier="fast",
                step=1,
                now=NOW + timedelta(minutes=1),
            )
        )

    stale = worker.run_queue_payload(
        _payload(
            [stale_cid],
            cadence_tier="fast",
            step=1,
            now=NOW + timedelta(hours=25),
        )
    )
    assert _receipt(stale)["due_reason"] == "first_pass"
    assert (
        next(item for item in stale.pass_results if item["name"] == "summarizer")[
            "status"
        ]
        == "complete"
    )


def test_receipt_emits_tier_due_reason_cids_fingerprint_and_mutation_rail() -> None:
    engine = _engine()
    cid = _append(engine, "Receipt fields must be present on a due tiered pass.")
    policy = OperatingPolicy()
    result = _worker(engine).run_queue_payload(
        _payload([cid], cadence_tier="slow", step=0, now=NOW)
    )
    receipt = _receipt(result)
    mutation = next(
        item for item in result.pass_results if item["name"] == "mutation_rails"
    )

    assert receipt["tier"] == "slow"
    assert receipt["due_reason"] == "first_pass"
    assert receipt["input_cids"] == [cid]
    assert receipt["policy_fingerprint"] == policy.cadence_policy_fingerprint()
    assert len(receipt["policy_fingerprint"]) == 64
    assert receipt["mutation_rail"] == mutation["details"]
    assert receipt["mutation_rail"]["tenant_id"] == TENANT
    assert receipt["mutation_rail"]["branch"] == "main"
    assert "supersessions_allowed" in receipt["mutation_rail"]
    assert "prunes_allowed" in receipt["mutation_rail"]


def test_policy_fingerprint_is_stable_and_sensitive_to_tier_routing() -> None:
    left = OperatingPolicy()
    right = OperatingPolicy()
    assert left.cadence_policy_fingerprint() == right.cadence_policy_fingerprint()

    mutated = OperatingPolicy()
    mutated.consolidation_cadence_tier_passes["slow"] = list(FAST_PASSES)
    assert mutated.cadence_policy_fingerprint() != left.cadence_policy_fingerprint()


def test_slow_may_consume_derived_rows_but_they_are_not_independent_corroboration() -> (
    None
):
    engine = _engine()
    grounded = _append(engine, "The preferred database is Postgres.")
    worker = ConsolidationWorker(
        engine,
        gate_cases=[
            RegressionCase(
                id="case-postgres",
                signature="fact-sig preferred database",
                query="preferred database",
                expected_substring="Postgres",
                protected=True,
            )
        ],
        consolidation_min_steps=0,
    )
    fast = worker.run_queue_payload(
        _payload([grounded], cadence_tier="fast", step=0, now=NOW)
    )
    derived = next(
        item["details"]["summary_cid"]
        for item in fast.pass_results
        if item["name"] == "summarizer" and item["details"].get("summary_cid")
    )

    slow = worker.run_queue_payload(
        _payload(
            [grounded, derived],
            cadence_tier="slow",
            step=5,
            now=NOW + timedelta(hours=1),
        )
    )
    receipt = _receipt(slow)
    assert derived in receipt["input_cids"]
    assert grounded in receipt["input_cids"]
    assert engine.get_evidence(TENANT, derived, "main") is not None

    signals = worker._fact_unit_signals_for_job(
        ConsolidationJob(
            tenant_id=TENANT,
            signature="fact-sig",
            query="preferred database",
            candidate_subject="preferred database",
            candidate_predicate="is",
            candidate_object="Postgres",
            source_evidence_cids=[grounded, derived],
        )
    )
    assert signals["independent_corroboration_count"] == 1
    result = worker.run_job(
        ConsolidationJob(
            tenant_id=TENANT,
            signature="derived-must-not-corroborate",
            query="preferred database",
            candidate_subject="preferred database",
            candidate_predicate="is",
            candidate_object="Postgres",
            source_evidence_cids=[grounded, derived],
        )
    )
    assert result.promoted is False
    assert any("fact_external_corroboration" in item for item in result.failed_cases)


def test_fast_tier_does_not_extract_or_promote_facts() -> None:
    engine = _engine()
    cid_a = _append(engine, "The preferred database is Postgres.")
    cid_b = _append(
        engine,
        "Independent note: preferred database remains Postgres.",
        source_type="chat",
    )
    worker = ConsolidationWorker(engine, [_postgres_case()], consolidation_min_steps=0)

    fast = worker.run_queue_payload(
        _payload([cid_a, cid_b], cadence_tier="fast", step=0, now=NOW)
    )
    names = {item["name"] for item in fast.pass_results}

    assert fast.passes_run == FAST_PASSES
    assert fast.candidate_results == []
    assert "extractor" not in names
    assert "belief_reviser" not in names
    assert _active_assertions(engine) == []


def test_held_cids_are_not_unioned_into_due_candidate_provenance() -> None:
    engine = _engine()
    held = _append(engine, "Completely unrelated astronomy fact about nebulae and quasars.")
    ripe = _append(
        engine,
        "Independent confirmation: preferred database remains Postgres.",
        source_type="chat",
    )
    worker = ConsolidationWorker(engine, [_postgres_case()], consolidation_min_steps=0)
    worker.run_queue_payload(_payload([held], cadence_tier="medium", step=0, now=NOW))

    mixed = worker.run_queue_payload(
        _payload([held, ripe], cadence_tier="medium", step=5, now=NOW + timedelta(minutes=10))
    )
    receipt = _receipt(mixed)

    assert receipt["input_cids"] == [ripe]
    assert mixed.candidate_results
    assert all(item.get("promoted") is False for item in mixed.candidate_results)
    assert _active_assertions(engine) == []


def test_implicit_invocations_advance_due_steps_across_not_due_polls() -> None:
    engine = _engine()
    cid = _append(engine, "Implicit steps must advance even when a poll is not due.")
    worker = _worker(engine, consolidation_min_steps=0)

    first = worker.run_queue_payload(_payload([cid], cadence_tier="fast", now=NOW))
    assert _receipt(first)["due_reason"] == "first_pass"

    for _ in range(4):
        poll = worker.run_queue_payload(_payload([cid], cadence_tier="fast", now=NOW))
        assert _receipt(poll)["due_reason"] == "not_due"

    due_again = worker.run_queue_payload(_payload([cid], cadence_tier="fast", now=NOW))
    assert _receipt(due_again)["due_reason"] == "min_steps_elapsed"
    assert _receipt(due_again)["input_cids"] == [cid]


def test_missing_due_cids_remain_retryable_after_they_arrive() -> None:
    engine = _engine()
    content = "Late-arriving evidence must still be due for the requested tier."
    cid = evidence_cid(
        content,
        tenant_id=TENANT,
        user_id=USER,
        source_type="episode",
        content_pointer=None,
        modality="text",
        sensitivity=0,
    )
    worker = _worker(engine, consolidation_min_steps=0)

    missing = worker.run_queue_payload(_payload([cid], cadence_tier="fast", step=0, now=NOW))
    assert missing.evidence_seen == 0
    assert cid in missing.skipped

    written = _append(engine, content)
    assert written == cid
    retry = worker.run_queue_payload(_payload([cid], cadence_tier="fast", step=0, now=NOW))
    assert _receipt(retry)["due_reason"] == "first_pass"
    assert _receipt(retry)["input_cids"] == [cid]
    assert retry.evidence_seen == 1


def test_requested_tier_ignores_caller_pass_override() -> None:
    engine = _engine()
    cid = _append(engine, "A slow receipt must not run only a caller summarizer override.")
    result = _worker(engine, consolidation_min_steps=0).run_queue_payload(
        _payload([cid], cadence_tier="slow", step=0, now=NOW, passes=["summarizer"])
    )
    assert result.passes_run == SLOW_PASSES
    assert _receipt(result)["tier"] == "slow"
