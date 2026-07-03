"""L4 poison corpus against ``SqliteEngine`` (Phase-2 Task 12).

This mirrors ``test_poison_corpus.py`` case-for-case, but points the runner's
only engine-swap seam (``tools_factory``) at a fresh, isolated ``SqliteEngine``
per case instead of the default ``LocalMemoryEngine``. It asserts the identical
SLO floors — the poison corpus is a protected ratchet (FR-7 / G7, blueprint §16
>=95% poison-block, §33 MINJA tier) and may never be weakened. If a category
regresses under SQLite, the engine is fixed, not the corpus.

Per-case isolation: the factory is invoked once per case (``evaluate_case``
builds ``tools = tools_factory()``), and each invocation creates a brand-new
tenant-file root under a fresh tmp dir, so corpus order can never leak state
between cases. The tombstone-replay evaluator no longer reaches into
``LocalMemoryEngine`` internals — it probes the engine-neutral
``engine.evidence_is_erased`` contract, which SqliteEngine implements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mnemosyne.mcp_tools import MemoryTools  # noqa: E402
from mnemosyne.sqlite_engine import SqliteEngine  # noqa: E402

from poison_corpus import (  # noqa: E402
    ATTACK_CATEGORIES,
    POISON_BLOCK_SLO,
    PoisonCategory,
    attack_cases,
    benign_cases,
)
from poison_runner import evaluate_case, run_corpus  # noqa: E402


@pytest.fixture
def sqlite_tools_factory(tmp_path_factory: pytest.TempPathFactory):
    """A ``tools_factory`` that builds ``MemoryTools(SqliteEngine(fresh root))``
    per call — one isolated per-tenant SQLite store per corpus case."""

    created: list[SqliteEngine] = []

    def factory() -> MemoryTools:
        root = tmp_path_factory.mktemp("poison-sqlite")
        engine = SqliteEngine(root)
        created.append(engine)
        return MemoryTools(engine)

    yield factory

    for engine in created:
        engine.close()


# --------------------------------------------------------------------------- #
# SLO enforcement (same floors as test_poison_corpus.py)
# --------------------------------------------------------------------------- #

def test_sqlite_overall_block_rate_meets_slo(sqlite_tools_factory) -> None:
    report = run_corpus(tools_factory=sqlite_tools_factory)
    assert report.meets_slo, (
        f"sqlite poison-block rate {report.overall_block_rate:.1%} < SLO {POISON_BLOCK_SLO:.0%}; "
        f"failures: {[r.case_id for r in report.failures()]}"
    )


def test_sqlite_every_attack_case_is_blocked(sqlite_tools_factory) -> None:
    # Deterministic gates must block 100% under SQLite, exactly as under Local.
    report = run_corpus(attack_cases(), tools_factory=sqlite_tools_factory)
    failures = report.failures()
    assert not failures, f"unblocked poison cases (sqlite): {[r.case_id for r in failures]}"
    assert report.overall_block_rate == 1.0


def test_sqlite_per_category_block_rates_meet_slo(sqlite_tools_factory) -> None:
    report = run_corpus(tools_factory=sqlite_tools_factory)
    for cat in ATTACK_CATEGORIES:
        rep = report.per_category[cat.value]
        assert rep.block_rate >= POISON_BLOCK_SLO, (
            f"sqlite category {cat.value} block rate {rep.block_rate:.1%} < {POISON_BLOCK_SLO:.0%}"
        )


def test_sqlite_no_false_positives_on_benign_controls(sqlite_tools_factory) -> None:
    report = run_corpus(tools_factory=sqlite_tools_factory)
    fps = report.false_positives()
    assert report.false_positive_rate == 0.0, (
        f"sqlite wrongly blocked benign content: {[r.case_id for r in fps]}"
    )


def test_sqlite_benign_controls_are_actually_retrievable(sqlite_tools_factory) -> None:
    # Guards against a vacuous FP rate: benign markers must really surface via SQLite.
    for case in benign_cases():
        result = evaluate_case(case, sqlite_tools_factory)
        assert result.evidence["surfaced"] is True, case.id


# --------------------------------------------------------------------------- #
# Per-vector defense semantics (identical to Local; engine must earn each floor)
# --------------------------------------------------------------------------- #

def test_sqlite_direct_injection_ingested_as_untrusted_then_filtered(sqlite_tools_factory) -> None:
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.DIRECT_PROMPT_INJECTION):
        result = evaluate_case(case, sqlite_tools_factory)
        assert result.blocked is True, case.id
        assert result.evidence["ingest_trust_tier"] == 5, case.id


def test_sqlite_trust_escalation_writes_are_denied(sqlite_tools_factory) -> None:
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.TRUST_TIER_ESCALATION):
        result = evaluate_case(case, sqlite_tools_factory)
        assert result.blocked is True, case.id
        assert result.evidence["allowed"] is False, case.id
        assert result.evidence["reason"], case.id


def test_sqlite_tombstone_replay_collides_and_stays_erased(sqlite_tools_factory) -> None:
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.TOMBSTONE_EVIDENCE_REPLAY):
        result = evaluate_case(case, sqlite_tools_factory)
        assert result.blocked is True, case.id
        # Re-ingest collides on the same content id and the row stays erased —
        # proven through the engine-neutral evidence_is_erased probe, not internals.
        assert result.evidence["same_cid"] is True, case.id
        assert result.evidence["still_erased"] is True, case.id


def test_sqlite_cross_tenant_secret_is_isolated_not_just_missing(sqlite_tools_factory) -> None:
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.CROSS_TENANT_LEAKAGE):
        result = evaluate_case(case, sqlite_tools_factory)
        assert result.blocked is True, case.id
        # One-file-per-tenant isolation, not a retrieval miss: own tenant surfaces it.
        assert result.evidence["own_tenant_surfaced"] is True, case.id


def test_sqlite_poisoned_corrections_below_user_trust_are_denied(sqlite_tools_factory) -> None:
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.POISONED_CORRECTION):
        result = evaluate_case(case, sqlite_tools_factory)
        assert result.blocked is True, case.id
        assert result.evidence["allowed"] is False, case.id


def test_sqlite_gradual_drift_repetition_does_not_surface_low_trust(sqlite_tools_factory) -> None:
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.GRADUAL_DRIFT):
        result = evaluate_case(case, sqlite_tools_factory)
        assert result.blocked is True, case.id
        assert result.evidence["drift_count"] >= 24, case.id
