"""Lease #18 — multi-signal calibrated_confidence fuse (§26 / blueprint §7)."""

from __future__ import annotations

from mnemosyne.calibration import (
    FUSE_WEIGHT_AGREEMENT,
    FUSE_WEIGHT_CERTAINTY,
    FUSE_WEIGHT_FIDELITY,
    FUSE_WEIGHT_PROVENANCE,
    FUSE_WEIGHT_RAW,
    calibrated_confidence_signals_from_hit,
    explain_calibrated_confidence,
    fuse_calibrated_confidence,
    fuse_calibrated_confidence_from_hit,
)
from mnemosyne.models import Hit


def test_fuse_weights_sum_to_one() -> None:
    total = (
        FUSE_WEIGHT_RAW
        + FUSE_WEIGHT_CERTAINTY
        + FUSE_WEIGHT_AGREEMENT
        + FUSE_WEIGHT_PROVENANCE
        + FUSE_WEIGHT_FIDELITY
    )
    assert abs(total - 1.0) < 1e-9


def test_fuse_unit_interval_and_pure() -> None:
    a = fuse_calibrated_confidence(
        raw_confidence=0.8,
        semantic_entropy=0.2,
        retrieval_agreement=0.7,
        provenance_strength=0.6,
        fidelity_score=0.9,
    )
    b = fuse_calibrated_confidence(
        raw_confidence=0.8,
        semantic_entropy=0.2,
        retrieval_agreement=0.7,
        provenance_strength=0.6,
        fidelity_score=0.9,
    )
    assert a == b
    assert 0.0 <= a <= 1.0


def test_fuse_pinned_formula() -> None:
    raw, entropy, agreement, provenance, fidelity = 0.80, 0.25, 0.60, 0.40, 0.50
    expected = (
        FUSE_WEIGHT_RAW * raw
        + FUSE_WEIGHT_CERTAINTY * (1.0 - entropy)
        + FUSE_WEIGHT_AGREEMENT * agreement
        + FUSE_WEIGHT_PROVENANCE * provenance
        + FUSE_WEIGHT_FIDELITY * fidelity
    )
    got = fuse_calibrated_confidence(
        raw_confidence=raw,
        semantic_entropy=entropy,
        retrieval_agreement=agreement,
        provenance_strength=provenance,
        fidelity_score=fidelity,
    )
    assert abs(got - expected) < 1e-12


def test_diverge_high_raw_high_entropy_low_provenance() -> None:
    """Acceptance: fused != raw (and strictly lower) under diverge signals."""
    raw = 0.95
    fused = fuse_calibrated_confidence(
        raw_confidence=raw,
        semantic_entropy=0.90,
        retrieval_agreement=0.20,
        provenance_strength=0.10,
        fidelity_score=0.10,
    )
    assert fused != raw
    assert fused < raw
    assert fused < 0.50


def test_fail_closed_missing_provenance_and_fidelity() -> None:
    """High raw alone must not identity-alias when provenance/fidelity default 0."""
    raw = 0.90
    fused = fuse_calibrated_confidence(raw_confidence=raw)
    # defaults: entropy=0 → certainty=1; agreement=1; provenance=0; fidelity=0
    expected = FUSE_WEIGHT_RAW * raw + FUSE_WEIGHT_CERTAINTY * 1.0 + FUSE_WEIGHT_AGREEMENT * 1.0
    assert abs(fused - expected) < 1e-12
    assert fused != raw
    assert fused < raw


def test_explain_matches_fuse() -> None:
    kwargs = dict(
        raw_confidence=0.7,
        semantic_entropy=0.3,
        retrieval_agreement=0.5,
        provenance_strength=0.4,
        fidelity_score=0.6,
    )
    explain = explain_calibrated_confidence(**kwargs)
    assert explain["calibrated_confidence"] == fuse_calibrated_confidence(**kwargs)
    assert explain["weights"]["raw"] == FUSE_WEIGHT_RAW


def test_signals_from_hit_maps_trust_tier_and_reality() -> None:
    signals = calibrated_confidence_signals_from_hit(
        metadata={"confidence": 0.88, "semantic_entropy": 0.1},
        reality_class="grounded",
        trust_tier=0,
    )
    assert signals["raw_confidence"] == 0.88
    assert signals["semantic_entropy"] == 0.1
    assert signals["provenance_strength"] == 1.0  # tier 0
    assert signals["fidelity_score"] == 1.0  # grounded
    assert signals["retrieval_agreement"] == 1.0


def test_from_hit_diverges_from_raw_confidence_alias() -> None:
    """Standing helper must not exclusively identity-alias metadata confidence."""
    meta = {
        "confidence": 0.95,
        "semantic_entropy": 0.85,
        "retrieval_agreement": 0.15,
        "provenance_strength": 0.05,
        "fidelity_score": 0.05,
    }
    fused = fuse_calibrated_confidence_from_hit(
        metadata=meta,
        reality_class="self_generated",
        trust_tier=5,
    )
    assert fused != 0.95
    assert fused < 0.95


def test_bounded_unit_rejects_nan_and_inf() -> None:
    assert fuse_calibrated_confidence(raw_confidence=float("nan")) == fuse_calibrated_confidence(
        raw_confidence=0.0
    )
    assert fuse_calibrated_confidence(raw_confidence=float("inf")) == fuse_calibrated_confidence(
        raw_confidence=0.0
    )
    # Non-finite raw must not inflate fused score toward 1.0
    assert fuse_calibrated_confidence(raw_confidence=float("nan"), provenance_strength=0.0) < 0.8


def test_none_aliases_fall_through_to_lower_priority_keys() -> None:
    signals = calibrated_confidence_signals_from_hit(
        metadata={
            "verbalized_confidence": None,
            "confidence": 0.9,
            "fidelity": None,
            "fidelity_score": 0.75,
            "semantic_entropy": None,
            "entropy": 0.2,
        },
        reality_class="",
        trust_tier=5,
    )
    assert signals["raw_confidence"] == 0.9
    assert signals["fidelity_score"] == 0.75
    assert signals["semantic_entropy"] == 0.2


def test_independent_corroboration_feeds_provenance() -> None:
    signals = calibrated_confidence_signals_from_hit(
        metadata={
            "confidence": 0.5,
            "independent_corroboration": {"independent_corroboration_weight": 0.8},
        },
        reality_class="self_generated",
        trust_tier=5,  # would map to provenance 0.0 without IC
    )
    assert signals["provenance_strength"] == 0.8


def test_local_standing_signals_use_fuse_not_identity_alias() -> None:
    """Local engine standing builder replaces confidence identity alias with fuse."""
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine.__new__(LocalMemoryEngine)
    # Minimal stubs for corroboration path without full storage init.
    engine.evidence = {}
    engine._evidence_key = lambda tenant_id, branch, cid: f"{tenant_id}:{branch}:{cid}"
    engine._independent_corroboration_report = lambda **kwargs: {
        "independent_corroboration_count": 0,
        "independent_corroboration_weight": 0.0,
        "self_generated_corroboration_count": 0,
        "rejected_corroboration_count": 0,
    }
    engine._hit_source_evidence_cids = lambda hit: []

    hit = Hit(
        id="h1",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="x",
        score=1.0,
        channel="dense",
        trust_tier=5,
        metadata={
            "confidence": 0.95,
            "semantic_entropy": 0.9,
            "retrieval_agreement": 0.1,
            "provenance_strength": 0.05,
            "fidelity_score": 0.05,
        },
    )
    signals = LocalMemoryEngine._standing_signals_for_hit(engine, hit, "self_generated")
    raw = 0.95
    assert signals["calibrated_confidence"] != raw
    # Standing path injects computed corroboration into fuse inputs.
    expected_meta = dict(hit.metadata)
    expected_meta["independent_corroboration"] = {
        "independent_corroboration_count": 0,
        "independent_corroboration_weight": 0.0,
        "self_generated_corroboration_count": 0,
        "rejected_corroboration_count": 0,
    }
    assert signals["calibrated_confidence"] == fuse_calibrated_confidence_from_hit(
        metadata=expected_meta,
        reality_class="self_generated",
        trust_tier=5,
    )


def test_local_standing_injects_computed_corroboration_into_fuse() -> None:
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine.__new__(LocalMemoryEngine)
    engine.evidence = {}
    engine._evidence_key = lambda tenant_id, branch, cid: f"{tenant_id}:{branch}:{cid}"
    engine._independent_corroboration_report = lambda **kwargs: {
        "independent_corroboration_count": 2,
        "independent_corroboration_weight": 0.85,
        "self_generated_corroboration_count": 0,
        "rejected_corroboration_count": 0,
    }
    engine._hit_source_evidence_cids = lambda hit: ["e1", "e2"]

    hit = Hit(
        id="h2",
        kind="assertion",
        tenant_id="t",
        branch="main",
        text="y",
        score=1.0,
        channel="dense",
        trust_tier=5,
        metadata={"confidence": 0.7},
    )
    with_ic = LocalMemoryEngine._standing_signals_for_hit(engine, hit, "grounded")
    # Without IC injection, trust_tier=5 ⇒ provenance 0.0; with weight 0.85 fused is higher.
    no_ic = fuse_calibrated_confidence_from_hit(
        metadata={"confidence": 0.7},
        reality_class="grounded",
        trust_tier=5,
    )
    assert with_ic["calibrated_confidence"] > no_ic
    assert with_ic["independent_corroboration_weight"] == 0.85
