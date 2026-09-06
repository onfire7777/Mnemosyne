"""P15-S2 15-01-01/15-01-02 — cadence tiers plus async sleep freshness.

Pins allowlisted tiers, due selection, tenant/branch isolation, replay
idempotence, the existing [5 steps, 24h] rail, unchanged default behavior,
receipt fields, and the rule that derived rows never count as independent
corroboration.

15-01-02 adds queue-backed sleep work: explicit RuntimeJobHandlers
registration, bounded selection, stale-job rejection, fingerprint
idempotence, half-open valid_to / access-policy expiry, and fail-closed
clock rollback, erasure, supersession, and audit/persist faults.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.consolidation import (
    CONSOLIDATE_SLEEP_JOB,
    DEFAULT_CONSOLIDATION_PASSES,
    ConsolidationJob,
    ConsolidationWorker,
    build_sleep_payload,
    sleep_job_fingerprint,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.ids import evidence_cid
from mnemosyne.jobs import RuntimeJobHandlers
from mnemosyne.models import Assertion, Evidence
from mnemosyne.policy import CONSOLIDATION_CADENCE_TIERS, OperatingPolicy
from mnemosyne.queue import InProcessQueue, QueueWorker

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
    access_policy: dict[str, object] | None = None,
    sensitivity: int = 0,
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=USER,
            actor="user",
            source_type=source_type,
            content=content,
            trust_tier=0,
            sensitivity=sensitivity,
            access_policy=access_policy or {"tenant": tenant},
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


SLEEP_ENQUEUED = NOW
SLEEP_NOT_AFTER = NOW + timedelta(hours=6)
SLEEP_ITEM_LIMIT = 8
SLEEP_PASS_LIMIT = 4
SLEEP_RUNTIME_LIMIT = 30.0


def _sleep_payload(
    cids: list[str],
    *,
    tenant: str = TENANT,
    branch: str = "main",
    requested_tier: str = "fast",
    enqueued_at: datetime = SLEEP_ENQUEUED,
    not_after: datetime = SLEEP_NOT_AFTER,
    item_limit: int = SLEEP_ITEM_LIMIT,
    pass_limit: int = SLEEP_PASS_LIMIT,
    runtime_limit_seconds: float = SLEEP_RUNTIME_LIMIT,
    now: datetime | None = NOW,
) -> dict[str, object]:
    return build_sleep_payload(
        tenant_id=tenant,
        branch=branch,
        source_evidence_cids=cids,
        requested_tier=requested_tier,
        enqueued_at=enqueued_at,
        not_after=not_after,
        item_limit=item_limit,
        pass_limit=pass_limit,
        runtime_limit_seconds=runtime_limit_seconds,
        now=now,
    )


def _sleep_receipt(result: object) -> dict[str, object]:
    receipt = getattr(result, "sleep_receipt", None)
    assert isinstance(receipt, dict)
    return receipt


def _active_assertions_for(
    engine: LocalMemoryEngine, tenant: str = TENANT
) -> list[dict[str, object]]:
    return [
        row
        for row in engine.export_tenant(tenant)["assertions"]
        if row.get("status") == "active"
    ]


def test_sleep_job_is_registered_on_runtime_handlers() -> None:
    engine = _engine()
    cid = _append(engine, "Sleep work is an explicit queue job, not a hidden daemon.")
    queue = InProcessQueue()
    handlers = RuntimeJobHandlers(engine, queue, gate_cases=[])
    handler_map = handlers.handlers()

    assert CONSOLIDATE_SLEEP_JOB in handler_map
    assert CONSOLIDATE_SLEEP_JOB != "consolidate_evidence"
    payload = _sleep_payload([cid], now=NOW)
    queued = queue.enqueue(CONSOLIDATE_SLEEP_JOB, payload)
    job = QueueWorker(queue, handler_map).run_once(CONSOLIDATE_SLEEP_JOB)

    assert queued.kind == CONSOLIDATE_SLEEP_JOB
    assert job is not None
    assert job.status == "complete"
    assert job.result is not None
    receipt = job.result["sleep_receipt"]
    assert receipt["requested_tier"] == "fast"
    assert receipt["input_cids"] == [cid]
    assert receipt["idempotency_fingerprint"] == payload["idempotency_fingerprint"]


def test_sleep_payload_binds_required_fields_and_deterministic_fingerprint() -> None:
    cids = ["cid-b", "cid-a"]
    left = _sleep_payload(cids, requested_tier="slow")
    right = _sleep_payload(list(reversed(cids)), requested_tier="slow")

    required = {
        "tenant_id",
        "branch",
        "source_evidence_cids",
        "requested_tier",
        "enqueued_at",
        "not_after",
        "item_limit",
        "pass_limit",
        "runtime_limit_seconds",
        "idempotency_fingerprint",
    }
    assert required <= set(left)
    assert left["tenant_id"] == TENANT
    assert left["branch"] == "main"
    assert left["source_evidence_cids"] == ["cid-a", "cid-b"]
    assert right["source_evidence_cids"] == ["cid-a", "cid-b"]
    assert left["requested_tier"] == "slow"
    assert left["enqueued_at"] == SLEEP_ENQUEUED.isoformat()
    assert left["not_after"] == SLEEP_NOT_AFTER.isoformat()
    assert left["item_limit"] == SLEEP_ITEM_LIMIT
    assert left["pass_limit"] == SLEEP_PASS_LIMIT
    assert left["runtime_limit_seconds"] == SLEEP_RUNTIME_LIMIT
    assert left["idempotency_fingerprint"] == right["idempotency_fingerprint"]
    assert left["idempotency_fingerprint"] == sleep_job_fingerprint(left)
    assert len(left["idempotency_fingerprint"]) == 64
    assert "fresh_until" not in left
    assert "freshness" not in left

    mutated = _sleep_payload(cids, requested_tier="medium")
    assert mutated["idempotency_fingerprint"] != left["idempotency_fingerprint"]


def test_sleep_selection_honors_item_pass_and_runtime_limits() -> None:
    engine = _engine()
    cids = [
        _append(engine, f"Sleep item {index} is eligible for bounded selection.")
        for index in range(4)
    ]
    worker = _worker(engine, consolidation_min_steps=0)
    limited_items = worker.run_sleep_payload(
        _sleep_payload(cids, item_limit=2, pass_limit=8, now=NOW)
    )
    limited_passes = worker.run_sleep_payload(
        _sleep_payload(
            [cids[2]],
            item_limit=8,
            pass_limit=1,
            requested_tier="fast",
            now=NOW,
        )
    )

    ticks = {"n": 0}

    def advancing_clock() -> datetime:
        ticks["n"] += 1
        if ticks["n"] == 1:
            return NOW
        return NOW + timedelta(seconds=5)

    runtime_capped = ConsolidationWorker(
        engine, gate_cases=[], consolidation_min_steps=0, clock=advancing_clock
    ).run_sleep_payload(
        _sleep_payload(
            [cids[3]],
            item_limit=8,
            pass_limit=8,
            runtime_limit_seconds=1.0,
            now=NOW,
        )
    )

    item_receipt = _sleep_receipt(limited_items)
    assert item_receipt["input_cids"] == sorted(cids)[:2]
    assert item_receipt["item_limit"] == 2
    assert len(_summaries(engine)) == 1

    assert limited_passes.passes_run == FAST_PASSES[:1]
    assert _sleep_receipt(limited_passes)["pass_limit"] == 1
    assert all(item["name"] != "summarizer" for item in limited_passes.pass_results)

    assert _sleep_receipt(runtime_capped)["skipped_reasons"]
    assert "runtime_limit" in _sleep_receipt(runtime_capped)["skipped_reasons"]
    assert runtime_capped.evidence_seen == 0
    assert engine.get_evidence(TENANT, cids[3], "main") is not None


def test_stale_sleep_job_is_rejected_at_not_after_boundary() -> None:
    engine = _engine()
    cid = _append(engine, "A job that has passed not_after must fail closed.")
    worker = _worker(engine, consolidation_min_steps=0)
    payload = _sleep_payload([cid], not_after=NOW, now=NOW)

    with pytest.raises(RuntimeError, match="stale"):
        worker.run_sleep_payload(payload)
    assert _summaries(engine) == []

    live = worker.run_sleep_payload(
        _sleep_payload([cid], not_after=NOW + timedelta(microseconds=1), now=NOW)
    )
    assert _sleep_receipt(live)["input_cids"] == [cid]


def test_sleep_retry_is_idempotent_for_the_same_fingerprint() -> None:
    engine = _engine()
    cid = _append(engine, "Sleep retries must reuse the same fingerprint and writes.")
    worker = _worker(engine, consolidation_min_steps=0)
    payload = _sleep_payload([cid], now=NOW)

    first = worker.run_sleep_payload(payload)
    second = worker.run_sleep_payload(payload)
    summaries = _summaries(engine)
    first_receipt = _sleep_receipt(first)
    second_receipt = _sleep_receipt(second)

    assert first_receipt["idempotency_fingerprint"] == payload["idempotency_fingerprint"]
    assert second_receipt["idempotency_fingerprint"] == first_receipt["idempotency_fingerprint"]
    assert second_receipt["memo_hit"] is True
    assert first_receipt["memo_hit"] is False
    assert len(summaries) == 1
    assert first.source_evidence_cids == [cid]


def test_sleep_expiry_uses_valid_to_and_access_policy_at_exact_boundary() -> None:
    engine = _engine()
    expires = NOW
    live_policy = {
        "tenant": TENANT,
        "expires_at": (expires + timedelta(microseconds=1)).isoformat(),
    }
    expired_policy = {"tenant": TENANT, "expires_at": expires.isoformat()}
    live_cid = _append(
        engine,
        "Live evidence is still inside the half-open access-policy window.",
        access_policy=live_policy,
    )
    expired_cid = _append(
        engine,
        "Expired evidence is excluded at the exact access-policy deadline.",
        access_policy=expired_policy,
    )
    assertion_cid = _append(
        engine,
        "Assertion validity is half-open on valid_to, not a second freshness field.",
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="preferred database",
            predicate="is",
            object="Postgres",
            valid_from=NOW - timedelta(hours=1),
            valid_to=expires,
            status="active",
            source_evidence_cids=[assertion_cid],
            access_policy={"tenant": TENANT},
        )
    )
    worker = _worker(engine, consolidation_min_steps=0)

    result = worker.run_sleep_payload(
        _sleep_payload(
            [live_cid, expired_cid, assertion_cid],
            requested_tier="medium",
            now=expires,
        )
    )
    receipt = _sleep_receipt(result)
    snapshot = engine.export_tenant(TENANT)
    assertions = snapshot["assertions"]
    expired_assertion = next(
        row
        for row in assertions
        if row["source_evidence_cids"] == [assertion_cid]
        or assertion_cid in row.get("source_evidence_cids", [])
    )

    assert receipt["input_cids"] == [live_cid]
    assert expired_cid in receipt["excluded_cids"]
    assert receipt["exclusions"][expired_cid] == "access_policy_expired"
    assert receipt["exclusions"][assertion_cid] == "valid_to_expired"
    assert "fresh_until" not in receipt
    assert expired_assertion["valid_to"] == expires.isoformat().replace("+00:00", "Z") or (
        expired_assertion["valid_to"] is not None
    )
    assert expired_assertion.get("status") != "active" or expired_assertion["valid_to"] is not None
    assert engine.get_evidence(TENANT, expired_cid, "main") is not None


def test_sleep_clock_rollback_erasure_supersession_and_audit_fail_closed() -> None:
    engine = _engine()
    cid = _append(engine, "Fail-closed faults must not emit derived sleep work.")
    worker = _worker(engine, consolidation_min_steps=0)

    with pytest.raises(RuntimeError, match="clock"):
        worker.run_sleep_payload(
            _sleep_payload([cid], enqueued_at=NOW, now=NOW - timedelta(seconds=1))
        )
    assert _summaries(engine) == []

    worker.run_sleep_payload(_sleep_payload([cid], now=NOW + timedelta(minutes=1)))
    with pytest.raises(RuntimeError, match="clock"):
        worker.run_sleep_payload(
            _sleep_payload(
                [cid],
                enqueued_at=NOW,
                now=NOW,
            )
        )

    erased_cid = _append(engine, "Erased source material cannot be sleep-distilled.")
    engine.forget(TENANT, erased_cid, branch="main")
    with pytest.raises(RuntimeError, match="eras"):
        worker.run_sleep_payload(_sleep_payload([erased_cid], now=NOW + timedelta(minutes=2)))
    assert engine.evidence_is_erased(TENANT, erased_cid, "main") is True
    assert engine.get_evidence(TENANT, erased_cid, "main") is None

    superseded_source = _append(engine, "The preferred database is MySQL.")
    replacement = _append(engine, "The preferred database is Postgres.")
    first_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="preferred database",
            predicate="is",
            object="MySQL",
            valid_from=NOW - timedelta(hours=2),
            status="active",
            source_evidence_cids=[superseded_source],
            access_policy={"tenant": TENANT},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="preferred database",
            predicate="is",
            object="Postgres",
            valid_from=NOW - timedelta(hours=1),
            status="active",
            source_evidence_cids=[replacement],
            access_policy={"tenant": TENANT},
        )
    )
    superseded = next(
        row
        for row in engine.export_tenant(TENANT)["assertions"]
        if row["id"] == first_id
    )
    assert superseded["status"] == "superseded"
    with pytest.raises(RuntimeError, match="supersed"):
        worker.run_sleep_payload(
            _sleep_payload(
                [superseded_source],
                requested_tier="medium",
                now=NOW + timedelta(minutes=3),
            )
        )
    after = next(
        row
        for row in engine.export_tenant(TENANT)["assertions"]
        if row["id"] == first_id
    )
    assert after["status"] == "superseded"
    assert after.get("superseded_by")

    persist_cid = _append(engine, "Persist failure must not leave a sleep write.")
    before_persist = {row["cid"] for row in engine.export_tenant(TENANT)["evidence"]}
    real_append = engine.append_evidence

    def _fail_persist(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("persist backend unavailable")

    engine.append_evidence = _fail_persist  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="persist"):
        worker.run_sleep_payload(
            _sleep_payload([persist_cid], now=NOW + timedelta(minutes=3, seconds=30))
        )
    engine.append_evidence = real_append  # type: ignore[method-assign]
    assert {row["cid"] for row in engine.export_tenant(TENANT)["evidence"]} == before_persist

    audit_cid = _append(engine, "Audit failure must stop sleep before any write.")
    before_audit = {row["cid"] for row in engine.export_tenant(TENANT)["evidence"]}

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit backend unavailable")

    engine._audit = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="audit"):
        worker.run_sleep_payload(
            _sleep_payload([audit_cid], now=NOW + timedelta(minutes=4))
        )
    after_audit = {row["cid"] for row in engine.export_tenant(TENANT)["evidence"]}
    assert after_audit == before_audit


def test_sleep_cannot_revive_erased_superseded_unauthorized_or_stale_data() -> None:
    engine = _engine()
    live = _append(engine, "Only currently authorized live material may be distilled.")
    erased = _append(engine, "Forgotten episode must stay forgotten after sleep replay.")
    restricted = _append(
        engine,
        "Restricted evidence is unauthorized for sleep distillation.",
        access_policy={"tenant": TENANT, "restricted": True},
    )
    expired = _append(
        engine,
        "Expired access-policy evidence cannot be revived by replay.",
        access_policy={"tenant": TENANT, "expires_at": NOW.isoformat()},
    )
    worker = _worker(engine, consolidation_min_steps=0)
    first = worker.run_sleep_payload(_sleep_payload([live], now=NOW))
    live_summary = next(
        item["details"]["summary_cid"]
        for item in first.pass_results
        if item["name"] == "summarizer" and item["details"].get("summary_cid")
    )
    engine.forget(TENANT, live, branch="main")
    engine.forget(TENANT, erased, branch="main")

    with pytest.raises(RuntimeError):
        worker.run_sleep_payload(_sleep_payload([live, live_summary], now=NOW))
    with pytest.raises(RuntimeError):
        worker.run_sleep_payload(_sleep_payload([erased], now=NOW))
    with pytest.raises(RuntimeError, match="unauthor"):
        worker.run_sleep_payload(_sleep_payload([restricted], now=NOW))
    with pytest.raises(RuntimeError, match="stale|expir"):
        worker.run_sleep_payload(_sleep_payload([expired], now=NOW))

    assert engine.get_evidence(TENANT, live, "main") is None
    assert engine.get_evidence(TENANT, live_summary, "main") is None
    assert engine.evidence_is_erased(TENANT, live, "main") is True
    assert all(
        engine.get_evidence(TENANT, str(row.get("cid") or ""), "main") is None
        for row in _summaries(engine)
        if row.get("cid")
    )
    assert _active_assertions_for(engine) == []


def test_sleep_preserves_explicit_zero_sensitivity_ceiling() -> None:
    engine = _engine()
    engine.policy.max_sensitivity = 0
    cid = _append(
        engine,
        "S1 secret must stay above an explicit zero ceiling.",
        sensitivity=1,
    )
    worker = _worker(engine, consolidation_min_steps=0)
    with pytest.raises(RuntimeError, match="unauthor"):
        worker.run_sleep_payload(_sleep_payload([cid], now=NOW))
    assert _summaries(engine) == []


def test_sleep_rejects_redaction_only_access_decisions() -> None:
    engine = _engine()
    secret = "ssn=123-45-6789 must not reach raw sleep distillation."
    cid = _append(
        engine,
        secret,
        access_policy={
            "tenant": TENANT,
            "min_role_for_raw": "operator",
            "redact_fields": ["content"],
        },
    )
    worker = _worker(engine, consolidation_min_steps=0)
    with pytest.raises(RuntimeError, match="unauthor|redact"):
        worker.run_sleep_payload(_sleep_payload([cid], now=NOW))
    summaries = _summaries(engine)
    assert summaries == []
    assert all(
        secret not in str(row.get("content") or "") or str(row.get("cid") or "") == cid
        for row in engine.export_tenant(TENANT)["evidence"]
    )


def test_sleep_pass_limit_blocks_core_mutations_outside_requested_prefix() -> None:
    engine = _engine()
    cid = _append(engine, "The preferred database is Postgres.")
    worker = ConsolidationWorker(engine, [_postgres_case()], consolidation_min_steps=0)

    replay_only = worker.run_sleep_payload(
        _sleep_payload([cid], requested_tier="medium", pass_limit=1, now=NOW)
    )
    empty_bound = worker.run_sleep_payload(
        _sleep_payload(
            [cid],
            requested_tier="medium",
            pass_limit=0,
            now=NOW + timedelta(minutes=1),
        )
    )

    assert replay_only.passes_run == ["replayer"]
    assert {item["name"] for item in replay_only.pass_results} <= {
        "replayer",
        "mutation_rails",
        "prediction_error_gate",
    }
    assert empty_bound.passes_run == []
    assert empty_bound.candidate_results == []
    assert _active_assertions_for(engine) == []


def test_sleep_runtime_deadline_stops_work_during_consolidation() -> None:
    engine = _engine()
    cid = _append(engine, "A slow later pass must stop once the sleep deadline is crossed.")
    ticks = {"n": 0}

    def late_during_run() -> datetime:
        ticks["n"] += 1
        if ticks["n"] <= 2:
            return NOW
        return NOW + timedelta(seconds=30)

    worker = ConsolidationWorker(
        engine, gate_cases=[], consolidation_min_steps=0, clock=late_during_run
    )
    result = worker.run_sleep_payload(
        _sleep_payload([cid], pass_limit=8, runtime_limit_seconds=5.0, now=NOW)
    )
    names = {item["name"] for item in result.pass_results}
    assert "runtime_limit" in _sleep_receipt(result)["skipped_reasons"]
    assert "summarizer" not in names or next(
        item for item in result.pass_results if item["name"] == "summarizer"
    )["status"] != "complete"
    assert _summaries(engine) == []


def test_sleep_fingerprint_aliases_canonicalize_item_limit_selection() -> None:
    engine = _engine()
    first = _append(engine, "Canonical first eligible sleep item.")
    second = _append(engine, "Canonical second eligible sleep item.")
    worker = _worker(engine, consolidation_min_steps=0)
    left = _sleep_payload([second, first], item_limit=1, now=NOW)
    right = _sleep_payload([first, second], item_limit=1, now=NOW)

    assert left["source_evidence_cids"] == sorted([first, second])
    assert left["idempotency_fingerprint"] == right["idempotency_fingerprint"]
    first_run = worker.run_sleep_payload(left)
    second_run = worker.run_sleep_payload(right)
    expected = [sorted([first, second])[0]]
    assert _sleep_receipt(first_run)["input_cids"] == expected
    assert _sleep_receipt(second_run)["memo_hit"] is True
    assert _sleep_receipt(second_run)["input_cids"] == expected


def test_sleep_clock_watermark_is_tenant_scoped() -> None:
    engine = _engine()
    other = OTHER_TENANT
    future_cid = _append(engine, "Future-dated tenant A job must not poison tenant B.")
    other_cid = _append(
        engine,
        "Tenant B remains eligible after tenant A sees a future clock.",
        tenant=other,
    )
    worker = _worker(engine, consolidation_min_steps=0)
    worker.run_sleep_payload(
        _sleep_payload([future_cid], now=NOW + timedelta(hours=2))
    )
    other_run = worker.run_sleep_payload(
        _sleep_payload([other_cid], tenant=other, now=NOW)
    )
    assert _sleep_receipt(other_run)["input_cids"] == [other_cid]


def test_sleep_keeps_cid_when_another_assertion_still_supports_it() -> None:
    engine = _engine()
    cid = _append(engine, "Shared source still has an active supporting assertion.")
    other = _append(engine, "Replacement object uses the same source CID.")
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="preferred database",
            predicate="is",
            object="MySQL",
            valid_from=NOW - timedelta(hours=2),
            valid_to=NOW - timedelta(hours=1),
            status="active",
            source_evidence_cids=[cid],
            access_policy={"tenant": TENANT},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="preferred database",
            predicate="is",
            object="Postgres",
            valid_from=NOW - timedelta(minutes=30),
            status="active",
            source_evidence_cids=[cid, other],
            access_policy={"tenant": TENANT},
        )
    )
    worker = _worker(engine, consolidation_min_steps=0)
    result = worker.run_sleep_payload(_sleep_payload([cid], now=NOW))
    assert _sleep_receipt(result)["input_cids"] == [cid]
    assert cid not in _sleep_receipt(result).get("excluded_cids", [])
