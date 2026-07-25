"""Lease #12 — per-example conformal nonconformity (I8 / blueprint §7)."""

from __future__ import annotations

from mnemosyne.calibration import (
    CalibrationSet,
    conformal_prediction_set,
    conformal_prediction_set_size_for_hits,
    conformal_should_abstain,
    conformal_threshold,
    copy_confidence_metadata,
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


def test_example_confidence_rejects_nan_and_inf() -> None:
    hit = Hit(
        id="n",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="n",
        score=0.3,
        channel="dense",
        metadata={"confidence": float("nan"), "calibrated_confidence": float("inf")},
    )
    # Non-finite metadata skipped → fall through to finite score.
    assert example_confidence_from_hit(hit) == 0.3


def test_copy_confidence_metadata_preserves_aliases() -> None:
    dest: dict = {}
    copy_confidence_metadata(
        {
            "calibrated_confidence": 0.7,
            "verbalized_confidence": 0.6,
            "confidence": 0.5,
        },
        dest,
    )
    assert dest == {
        "calibrated_confidence": 0.7,
        "verbalized_confidence": 0.6,
        "confidence": 0.5,
    }


def test_example_confidence_ignores_untrusted_calibrated_alias() -> None:
    """Client-forged calibrated_confidence must not drive conformal accept."""
    hit = Hit(
        id="x",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="x",
        score=0.1,
        channel="dense",
        metadata={
            "calibrated_confidence": 0.99,
            "verbalized_confidence": 0.98,
            # no trusted confidence key
        },
    )
    assert example_confidence_from_hit(hit) == 0.1  # falls back to score
    hit2 = Hit(
        id="y",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="y",
        score=0.1,
        channel="dense",
        metadata={"confidence": 0.4, "calibrated_confidence": 0.99},
    )
    assert example_confidence_from_hit(hit2) == 0.4  # trusted confidence wins


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


def test_score_only_hits_keep_packet_relative_sizing() -> None:
    """Raw evidence retrieve (no confidence meta) must not mass-abstain."""
    hits = [
        _hit(hit_id="s1", score=1.0, confidence=None),
        _hit(hit_id="s2", score=0.9, confidence=None),
        _hit(hit_id="s3", score=0.2, confidence=None),
    ]
    threshold = 0.5
    assert conformal_prediction_set_size_for_hits(hits, threshold=threshold) == (
        packet_relative_prediction_set_size(hits, threshold=threshold)
    )


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
    thr = conformal_threshold(calibration)
    packet = packet_relative_prediction_set_size(hits, threshold=thr)
    assert packet >= 3
    pred = conformal_prediction_set(labels, calibration)
    eng_size = LocalMemoryEngine._prediction_set_size(hits, threshold=thr)
    assert eng_size == len(pred)
    # Empty/tiny per-example set ⇒ conformal abstain; packet size diverges.
    assert conformal_should_abstain(labels, calibration, max_set_size=3) is True
    assert packet != eng_size
    assert should_abstain(0.99, calibration, prediction_set_size=0, max_set_size=3) is True


def test_calibration_explain_marks_per_example_nonconformity() -> None:
    engine = LocalMemoryEngine()
    explain = engine._calibration_explain(
        CalibrationSet(tenant_id="t", memory_type="fact", scores=[0.5], target_coverage=0.9),
        0.5,
    )
    assert explain["nonconformity"] == "per_example"
    assert explain["source"] == "conformal"
