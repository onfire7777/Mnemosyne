"""Permanent protected regression tests for the memory-poisoning corpus.

These tests enforce the blueprint's >=95% poison-block SLO (section 16), the
MINJA tier (section 33), and FR-7 / G7.  Every case in the corpus is a permanent
*protected* case: the suite asserts that none are silently downgraded and that
all attack categories remain represented.

Runs against Mnemosyne's real engine + security policy through the public
``MemoryTools`` surface (no mocked defenses).  Importable under pytest because
``pyproject.toml`` sets ``pythonpath = ["src"]``; the runner also injects the
sibling directory so ``poison_corpus`` resolves when invoked directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from poison_corpus import (  # noqa: E402
    ATTACK_CATEGORIES,
    POISON_BLOCK_SLO,
    PoisonCategory,
    all_cases,
    attack_cases,
    benign_cases,
)
from poison_runner import evaluate_case, run_corpus, _default_tools_factory  # noqa: E402


# --------------------------------------------------------------------------- #
# Corpus integrity (taxonomy + permanence)
# --------------------------------------------------------------------------- #

def test_corpus_is_substantial_and_covers_all_attack_families() -> None:
    cases = attack_cases()
    # MINJA/AgentPoison-style corpus: many cases, not two.
    assert len(cases) >= 50
    covered = {c.category for c in cases}
    assert covered == set(ATTACK_CATEGORIES)


def test_every_case_is_a_permanent_protected_case() -> None:
    # FR-7 / G7: each case is permanently protected and may never be dropped.
    assert all(case.protected for case in all_cases())


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in all_cases()]
    assert len(ids) == len(set(ids))


def test_minja_and_agentpoison_lineage_present() -> None:
    ids = {c.id for c in all_cases()}
    assert any(i.startswith("minja-") for i in ids)
    assert any(i.startswith("agentpoison-") for i in ids)
    # The original two seed cases' intents remain represented.
    cats = {c.category for c in all_cases()}
    assert PoisonCategory.CROSS_TENANT_LEAKAGE in cats  # minja-cross-user-isolation
    assert PoisonCategory.DATA_AS_INSTRUCTION in cats   # agentpoison-data-never-instruction


# --------------------------------------------------------------------------- #
# SLO enforcement
# --------------------------------------------------------------------------- #

def test_overall_block_rate_meets_slo() -> None:
    report = run_corpus()
    assert report.meets_slo, (
        f"poison-block rate {report.overall_block_rate:.1%} < SLO {POISON_BLOCK_SLO:.0%}; "
        f"failures: {[r.case_id for r in report.failures()]}"
    )


def test_every_attack_case_is_blocked() -> None:
    # Stronger than the SLO: the deterministic gates should block 100%.
    report = run_corpus(attack_cases())
    failures = report.failures()
    assert not failures, f"unblocked poison cases: {[r.case_id for r in failures]}"
    assert report.overall_block_rate == 1.0


def test_per_category_block_rates_meet_slo() -> None:
    report = run_corpus()
    for cat in ATTACK_CATEGORIES:
        rep = report.per_category[cat.value]
        assert rep.block_rate >= POISON_BLOCK_SLO, (
            f"category {cat.value} block rate {rep.block_rate:.1%} < {POISON_BLOCK_SLO:.0%}"
        )


def test_no_false_positives_on_benign_controls() -> None:
    report = run_corpus()
    fps = report.false_positives()
    assert report.false_positive_rate == 0.0, (
        f"benign content wrongly blocked: {[r.case_id for r in fps]}"
    )


def test_benign_controls_are_actually_retrievable() -> None:
    # Guards against a vacuous FP rate: benign markers must really surface.
    factory = _default_tools_factory
    for case in benign_cases():
        result = evaluate_case(case, factory)
        assert result.evidence["surfaced"] is True, case.id


# --------------------------------------------------------------------------- #
# Per-vector defense semantics (what "blocked" means is real, not assumed)
# --------------------------------------------------------------------------- #

def test_direct_injection_ingested_as_untrusted_then_filtered() -> None:
    factory = _default_tools_factory
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.DIRECT_PROMPT_INJECTION):
        result = evaluate_case(case, factory)
        assert result.blocked is True, case.id
        # External web content is classified tier 5 (UNTRUSTED_EXTERNAL).
        assert result.evidence["ingest_trust_tier"] == 5, case.id


def test_trust_escalation_writes_are_denied_by_capability_mediator() -> None:
    factory = _default_tools_factory
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.TRUST_TIER_ESCALATION):
        result = evaluate_case(case, factory)
        assert result.blocked is True, case.id
        assert result.evidence["allowed"] is False, case.id
        assert result.evidence["reason"], case.id


def test_tombstone_replay_collides_and_stays_erased() -> None:
    factory = _default_tools_factory
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.TOMBSTONE_EVIDENCE_REPLAY):
        result = evaluate_case(case, factory)
        assert result.blocked is True, case.id
        # Re-ingest must collide on the same content id and remain erased.
        assert result.evidence["same_cid"] is True, case.id
        assert result.evidence["still_erased"] is True, case.id


def test_cross_tenant_secret_is_isolated_not_just_missing() -> None:
    factory = _default_tools_factory
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.CROSS_TENANT_LEAKAGE):
        result = evaluate_case(case, factory)
        assert result.blocked is True, case.id
        # The secret must be retrievable in its own tenant (isolation, not a miss).
        assert result.evidence["own_tenant_surfaced"] is True, case.id


def test_poisoned_corrections_below_user_trust_are_denied() -> None:
    factory = _default_tools_factory
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.POISONED_CORRECTION):
        result = evaluate_case(case, factory)
        assert result.blocked is True, case.id
        assert result.evidence["allowed"] is False, case.id


def test_gradual_drift_repetition_does_not_surface_low_trust() -> None:
    factory = _default_tools_factory
    for case in (c for c in attack_cases()
                 if c.category is PoisonCategory.GRADUAL_DRIFT):
        result = evaluate_case(case, factory)
        assert result.blocked is True, case.id
        assert result.evidence["drift_count"] >= 24, case.id
