"""§7 #17 G-consol — consolidation uses evaluate_fact_external_corroboration.

Ends CID dual-standard: fact promote consumes Standing independent external
counts via the engine oracle + gate helper, not raw source_evidence_cid length.
"""

from __future__ import annotations

from mnemosyne.consolidation import ConsolidationJob, ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase, evaluate_fact_external_corroboration
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy

TENANT = "tenant-g-consol"
USER = "user-g-consol"


def _evidence(engine: LocalMemoryEngine, content: str, *, source_type: str = "episode") -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type=source_type,
            content=content,
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )


def _job(cids: list[str], *, signature: str = "fact-sig") -> ConsolidationJob:
    return ConsolidationJob(
        tenant_id=TENANT,
        signature=signature,
        query="preferred database",
        candidate_subject="preferred database",
        candidate_predicate="is",
        candidate_object="Postgres",
        source_evidence_cids=list(cids),
    )


def _case() -> RegressionCase:
    return RegressionCase(
        id="case-postgres",
        signature="fact-sig preferred database",
        query="preferred database",
        expected_substring="Postgres",
        protected=True,
    )


def test_worker_default_floor_matches_policy_min_external() -> None:
    engine = LocalMemoryEngine()
    worker = ConsolidationWorker(engine, [_case()])
    policy = OperatingPolicy()
    assert worker.min_corroboration == policy.min_external_corroboration_for_fact == 2


def test_single_source_fails_closed_via_external_rail() -> None:
    engine = LocalMemoryEngine()
    cid = _evidence(engine, "The preferred database is Postgres.")
    worker = ConsolidationWorker(engine, [_case()])
    result = worker.run_job(_job([cid]))
    assert result.promoted is False
    assert any("fact_external_corroboration" in item for item in result.failed_cases)


def test_two_independent_grounded_sources_may_promote() -> None:
    engine = LocalMemoryEngine()
    cid_a = _evidence(engine, "The preferred database is Postgres.")
    cid_b = _evidence(engine, "Independent note: preferred database remains Postgres.", source_type="chat")
    worker = ConsolidationWorker(engine, [_case()])
    result = worker.run_job(_job([cid_a, cid_b]))
    assert result.promoted is True
    assert result.failed_cases == []


def test_unit_signals_use_engine_oracle_not_raw_cid_cardinality() -> None:
    """Self-generated multi-CID must not satisfy the external floor."""
    engine = LocalMemoryEngine()
    # Mark both as self_generated via metadata so independent oracle rejects them.
    cid_a = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="agent",
            source_type="self",
            content="I think the preferred database is Postgres.",
            trust_tier=0,
            metadata={"reality_class": "self_generated"},
            access_policy={"tenant": TENANT},
        )
    )
    cid_b = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="agent",
            source_type="self",
            content="I still think preferred database is Postgres.",
            trust_tier=0,
            metadata={"reality_class": "self_generated"},
            access_policy={"tenant": TENANT},
        )
    )
    worker = ConsolidationWorker(engine, [_case()])
    signals = worker._fact_unit_signals_for_job(_job([cid_a, cid_b]))
    assert signals["independent_corroboration_count"] == 0
    assert signals["self_generated_corroboration_count"] >= 1 or signals["reality_class"] != "grounded"
    verdict = evaluate_fact_external_corroboration(unit_signals=signals, policy=OperatingPolicy())
    assert verdict.allowed is False
    result = worker.run_job(_job([cid_a, cid_b], signature="self-echo"))
    assert result.promoted is False
    assert any("fact_external_corroboration" in item for item in result.failed_cases)


def test_candidate_carries_unit_signals_into_promotion_gate() -> None:
    """run_job must attach unit_signals so gate uses full policy floor (not transitional 1)."""
    engine = LocalMemoryEngine()
    cid_a = _evidence(engine, "The preferred database is Postgres.")
    cid_b = _evidence(engine, "Second source: preferred database is Postgres.", source_type="note")
    worker = ConsolidationWorker(engine, [_case()])
    signals = worker._fact_unit_signals_for_job(_job([cid_a, cid_b]))
    assert int(signals["independent_corroboration_count"]) >= 2
    result = worker.run_job(_job([cid_a, cid_b], signature="with-signals"))
    assert result.promoted is True


def test_oracle_portable_when_engine_report_requires_cursor() -> None:
    """Postgres-style TypeError on report(cur=...) must fall back to get_evidence path."""
    engine = LocalMemoryEngine()
    cid_a = _evidence(engine, "The preferred database is Postgres.")
    cid_b = _evidence(engine, "Independent: preferred database is Postgres.", source_type="chat")
    worker = ConsolidationWorker(engine, [_case()])
    original = engine._independent_corroboration_report

    def _boom(*_a, **_k):  # noqa: ANN001
        raise TypeError("missing required positional argument: 'cur'")

    engine._independent_corroboration_report = _boom  # type: ignore[method-assign]
    try:
        signals = worker._fact_unit_signals_for_job(_job([cid_a, cid_b]))
    finally:
        engine._independent_corroboration_report = original  # type: ignore[method-assign]
    assert int(signals["independent_corroboration_count"]) >= 2
    assert signals["reality_class"] == "grounded"
    # Full promote path with restored oracle (signals path already exercised above).
    result = worker.run_job(_job([cid_a, cid_b], signature="pg-portable"))
    assert result.promoted is True