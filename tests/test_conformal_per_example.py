"""Lease #12 — per-example conformal nonconformity (I8 / blueprint §7)."""

from __future__ import annotations

from mnemosyne.calibration import (
    CalibrationSet,
    conformal_prediction_set,
    conformal_prediction_set_size_for_hits,
    conformal_should_abstain,
    example_confidence_from_hit,
    nonconformity_score,
    packet_relative_prediction_set_size,
    scored_labels_from_hits,
    should_abstain,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Hit
from mnemosyne.postgres_engine import PostgresEngine


def _hit(
    *,
    hit_id: str,
    score: float,
    confidence: float | None = None,
    kind: str = "evidence",
) -> Hit:
    meta: dict = {}
    if confidence is not None:
        meta["confidence"] = confidence
    return Hit(
        id=hit_id,
        kind=kind,  # type: ignore[arg-type]
        tenant_id="t",
        branch="main",
        text=hit_id,
        score=score,
        channel="dense",
        metadata=meta,
    )


def test_nonconformity_score_is_one_minus_confidence() -> None:
    assert abs(nonconformity_score(0.8) - 0.2) < 1e-12
    assert nonconformity_score(1.0) == 0.0
    assert nonconformity_score(0.0) == 1.0


def test_example_confidence_prefers_metadata_over_score() -> None:
    hit = _hit(hit_id="a", score=0.95, confidence=0.2)
    assert example_confidence_from_hit(hit) == 0.2


def test_per_example_set_size_diverges_from_packet_relative() -> None:
    """Acceptance: set size != packet-only path under mixed conf vs score."""
    # High retrieval scores, low explicit confidences, moderate threshold.
    hits = [
        _hit(hit_id="h1", score=1.0, confidence=0.15),
        _hit(hit_id="h2", score=0.9, confidence=0.12),
        _hit(hit_id="h3", score=0.85, confidence=0.80),
    ]
    threshold = 0.5
    per_example = conformal_prediction_set_size_for_hits(hits, threshold=threshold)
    packet = packet_relative_prediction_set_size(hits, threshold=threshold)
    assert packet >= 2  # relative to max_score keeps high-score hits
    assert per_example == 1  # only h3 clears confidence bar
    assert per_example != packet


def test_engine_prediction_set_size_uses_per_example() -> None:
    hits = [
        _hit(hit_id="h1", score=1.0, confidence=0.1),
        _hit(hit_id="h2", score=0.95, confidence=0.9),
    ]
    size = LocalMemoryEngine._prediction_set_size(hits, 0.5)
    assert size == 1
    assert size == conformal_prediction_set_size_for_hits(hits, threshold=0.5)
    # Postgres shares the same pure helper path.
    assert PostgresEngine._prediction_set_size(hits, 0.5) == size


def test_conformal_prediction_set_and_should_abstain_wire() -> None:
    calibration = CalibrationSet(
        tenant_id="t",
        memory_type="fact",
        scores=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        target_coverage=0.8,
    )
    hits = [
        _hit(hit_id="a", score=1.0, confidence=0.05),
        _hit(hit_id="b", score=0.9, confidence=0.08),
        _hit(hit_id="c", score=0.8, confidence=0.07),
        _hit(hit_id="d", score=0.7, confidence=0.06),
    ]
    labels = scored_labels_from_hits(hits)
    # Packet path keeps many high-score hits; per-example set is empty/tiny.
    packet = packet_relative_prediction_set_size(hits, threshold=0.2)
    assert packet >= 3
    pred = conformal_prediction_set(labels, calibration)
    eng_size = LocalMemoryEngine._prediction_set_size(hits, threshold=0.5)
    assert eng_size == len(pred) or eng_size <= 1
    # Empty/tiny per-example set ⇒ conformal abstain.
    assert conformal_should_abstain(labels, calibration, max_set_size=3) is True
    # Packet-relative size is large; per-example engine size is small/empty — diverge.
    assert packet != eng_size
    assert should_abstain(0.99, calibration, prediction_set_size=0, max_set_size=3) is True
    # High conf + small per-example set size (1) may still accept if conf clears bar.
    if eng_size == 1:
        assert should_abstain(0.99, calibration, prediction_set_size=eng_size, max_set_size=3) is False


def test_calibration_explain_marks_per_example_nonconformity() -> None:
    engine = LocalMemoryEngine()
    explain = engine._calibration_explain(
        CalibrationSet(tenant_id="t", memory_type="fact", scores=[0.5], target_coverage=0.9),
        0.5,
    )
    assert explain["nonconformity"] == "per_example"
    assert explain["source"] == "conformal"
