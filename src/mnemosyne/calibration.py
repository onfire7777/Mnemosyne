"""Conformal calibration for confidence and abstention."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class CalibrationSet:
    tenant_id: str
    memory_type: str
    scores: list[float]
    target_coverage: float = 0.9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CalibrationExample:
    confidence: float
    correct: bool
    prediction_set_size: int = 1

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "CalibrationExample":
        if "confidence" not in row:
            raise ValueError("calibration example requires confidence")
        if "correct" not in row:
            raise ValueError("calibration example requires correct")
        confidence = max(0.0, min(1.0, float(row["confidence"])))
        correct = row["correct"]
        if type(correct) is not bool:
            raise ValueError("calibration example correct must be a JSON boolean")
        prediction_set_size = int(row.get("prediction_set_size", 1))
        if prediction_set_size < 0:
            raise ValueError("calibration example prediction_set_size must be non-negative")
        return cls(
            confidence=confidence,
            correct=correct,
            prediction_set_size=prediction_set_size,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CalibrationTuneResult:
    calibration: CalibrationSet
    threshold: float
    metrics: dict[str, Any]
    failures: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "calibration": self.calibration.to_dict(),
            "threshold": self.threshold,
            "metrics": dict(self.metrics),
            "failures": list(self.failures),
        }


def conformal_threshold(calibration: CalibrationSet) -> float:
    """Return the split-conformal accept threshold for a calibration set.

    Computes the lower ``alpha``-quantile (``alpha = 1 - target_coverage``) of
    the calibration scores so that at least ``target_coverage`` of correctly
    answered memories clear the bar. An empty calibration set returns ``1.0``,
    which makes the system abstain on everything (fail-closed metacognition).
    """
    if not calibration.scores:
        return 1.0
    bounded = sorted(max(0.0, min(1.0, score)) for score in calibration.scores)
    alpha = 1.0 - calibration.target_coverage
    index = min(len(bounded) - 1, max(0, int((len(bounded) + 1) * alpha) - 1))
    return bounded[index]


def should_abstain(confidence: float, calibration: CalibrationSet, prediction_set_size: int = 1, max_set_size: int = 3) -> bool:
    """Decide whether to abstain rather than answer from this memory.

    Abstains when the conformal prediction set is empty or larger than
    ``max_set_size`` (the evidence is too thin or too ambiguous), or when the
    calibrated ``confidence`` falls below :func:`conformal_threshold`.
    """
    if prediction_set_size == 0 or prediction_set_size > max_set_size:
        return True
    return confidence < conformal_threshold(calibration)


def nonconformity_score(confidence: float) -> float:
    """Conformal nonconformity score for a calibrated confidence.

    Uses ``1 - confidence`` so that a more confident memory is *less*
    nonconforming. This is the per-example score the conformal prediction set is
    thresholded against.
    """
    return 1.0 - max(0.0, min(1.0, confidence))


def conformal_prediction_set(
    scored_labels: list[tuple[str, float]],
    calibration: CalibrationSet,
) -> list[str]:
    """Build the conformal prediction set for one query's candidate labels.

    Keeps every candidate whose :func:`nonconformity_score` is within the
    calibrated quantile — equivalently, whose confidence clears
    :func:`conformal_threshold` — ordered by descending confidence. An empty set
    signals that no candidate is supported strongly enough, so the caller should
    abstain rather than guess.
    """
    cutoff = nonconformity_score(conformal_threshold(calibration))
    chosen = [
        (label, max(0.0, min(1.0, confidence)))
        for label, confidence in scored_labels
        if nonconformity_score(confidence) <= cutoff
    ]
    chosen.sort(key=lambda row: row[1], reverse=True)
    return [label for label, _ in chosen]


def conformal_should_abstain(
    scored_labels: list[tuple[str, float]],
    calibration: CalibrationSet,
    max_set_size: int = 3,
) -> bool:
    """Abstain when the computed conformal prediction set is empty or too large.

    Unlike :func:`should_abstain`, which takes a pre-computed prediction-set
    size, this derives the set from the candidate labels via
    :func:`conformal_prediction_set` and abstains when it is empty (evidence too
    thin) or larger than ``max_set_size`` (too ambiguous to answer).
    """
    prediction_set = conformal_prediction_set(scored_labels, calibration)
    return not prediction_set or len(prediction_set) > max_set_size


# Confidence fields preserved on retrieval hit metadata for per-example conformal (I8).
CONFIDENCE_METADATA_KEYS = (
    "calibrated_confidence",
    "verbalized_confidence",
    "confidence",
)


def copy_confidence_metadata(source: Mapping[str, Any] | None, dest: dict[str, Any]) -> None:
    """Copy calibrated/verbalized/raw confidence fields into a hit metadata envelope."""
    if not isinstance(source, Mapping):
        return
    for key in CONFIDENCE_METADATA_KEYS:
        if key in source and source[key] is not None:
            dest[key] = source[key]


def example_confidence_from_hit(hit: Any) -> float:
    """Per-example confidence used for conformal nonconformity (I8 / §7 #12).

    Trusted sources only (fail closed against client-forged aliases):

    1. ``metadata["confidence"]`` — server/assertion confidence on projections
    2. retrieval ``score`` as a weak proxy when no explicit confidence

    ``calibrated_confidence`` / ``verbalized_confidence`` from arbitrary evidence
    metadata are *not* used for the conformal accept bar (CWE-345: clients must
    not inflate aliases to bypass abstention). Those fields may still be copied
    onto hit envelopes for explain/display via :func:`copy_confidence_metadata`.
    Non-finite values are rejected.
    """
    meta = getattr(hit, "metadata", None)
    if isinstance(meta, Mapping) and meta.get("confidence") is not None:
        try:
            value = float(meta["confidence"])
        except (TypeError, ValueError):
            value = None
        else:
            if math.isfinite(value):
                return max(0.0, min(1.0, value))
    score = getattr(hit, "score", None)
    if score is not None:
        try:
            value = float(score)
        except (TypeError, ValueError):
            return 0.0
        if math.isfinite(value):
            return max(0.0, min(1.0, value))
    return 0.0


def scored_labels_from_hits(hits: list[Any]) -> list[tuple[str, float]]:
    """Build ``(label, confidence)`` pairs for conformal_prediction_set."""
    labels: list[tuple[str, float]] = []
    for hit in hits:
        label = str(getattr(hit, "id", None) or getattr(hit, "kind", "hit") or "hit")
        labels.append((label, example_confidence_from_hit(hit)))
    return labels


def conformal_prediction_set_size_for_hits(
    hits: list[Any],
    *,
    threshold: float,
) -> int:
    """Count hits whose nonconformity clears the conformal accept bar.

    ``threshold`` is the conformal *confidence* threshold (accept bar). A hit
    with example-confidence ``c`` is in the set iff
    ``nonconformity_score(c) <= nonconformity_score(threshold)`` (i.e. ``c >= threshold``).

    This is the per-example residual for blueprint §7 #12 — distinct from the
    historical packet-relative size ``count(score >= max_score * threshold)``.
    """
    if not hits:
        return 0
    try:
        bar = max(0.0, min(1.0, float(threshold)))
    except (TypeError, ValueError):
        bar = 1.0
    cutoff = nonconformity_score(bar)
    return sum(
        1
        for hit in hits
        if nonconformity_score(example_confidence_from_hit(hit)) <= cutoff
    )


def packet_relative_prediction_set_size(
    hits: list[Any],
    *,
    threshold: float,
) -> int:
    """Legacy packet-relative set size (score vs max_score * threshold).

    Kept for diverge fixtures / characterization — retrieve must *not* use this
    after #12; engines call :func:`conformal_prediction_set_size_for_hits`.
    """
    if not hits:
        return 0
    scores = [max(float(getattr(hit, "score", 0.0) or 0.0), 0.0) for hit in hits]
    max_score = max(scores) if scores else 0.0
    if max_score <= 0.0:
        return 0
    try:
        bar = max(0.05, min(0.95, float(threshold)))
    except (TypeError, ValueError):
        bar = 0.05
    cutoff = max_score * bar
    return sum(1 for score in scores if score >= cutoff)


def calibration_examples_from_rows(rows: list[dict[str, Any]]) -> list[CalibrationExample]:
    return [CalibrationExample.from_mapping(row) for row in rows]


def tune_calibration_set(
    *,
    tenant_id: str,
    memory_type: str,
    examples: list[CalibrationExample],
    target_coverage: float = 0.9,
    min_examples: int = 20,
    min_correct: int = 1,
    min_incorrect: int = 1,
    min_empirical_coverage: float | None = None,
    max_false_accept_rate: float = 0.1,
    max_prediction_set_size: int = 3,
) -> CalibrationTuneResult:
    """Fit a calibration set from labelled examples and gate its quality.

    Builds the calibration scores from the correctly answered examples, derives
    the conformal threshold, and validates the resulting accept/abstain policy
    against minimum sample sizes, an empirical-coverage floor, and a
    false-accept ceiling. The returned :class:`CalibrationTuneResult` is
    ``ok`` only when every gate passes, so an under-powered or poorly separated
    calibration set fails closed instead of silently shipping.
    """
    target_coverage = max(0.0, min(1.0, target_coverage))
    min_empirical_coverage = (
        max(0.0, target_coverage - 0.05)
        if min_empirical_coverage is None
        else max(0.0, min(1.0, min_empirical_coverage))
    )
    correct_examples = [example for example in examples if example.correct]
    incorrect_examples = [example for example in examples if not example.correct]
    calibration = CalibrationSet(
        tenant_id=tenant_id,
        memory_type=memory_type,
        scores=[example.confidence for example in correct_examples],
        target_coverage=target_coverage,
    )
    threshold = conformal_threshold(calibration)
    accepted = [
        example
        for example in examples
        if not should_abstain(
            example.confidence,
            calibration,
            prediction_set_size=example.prediction_set_size,
            max_set_size=max_prediction_set_size,
        )
    ]
    accepted_correct = [example for example in accepted if example.correct]
    accepted_incorrect = [example for example in accepted if not example.correct]
    correct_coverage = len(accepted_correct) / len(correct_examples) if correct_examples else 0.0
    false_accept_rate = len(accepted_incorrect) / len(incorrect_examples) if incorrect_examples else 0.0
    abstention_rate = 1.0 - (len(accepted) / len(examples)) if examples else 1.0
    failures: list[str] = []
    if len(examples) < min_examples:
        failures.append(f"example count {len(examples)} is below required minimum {min_examples}")
    if len(correct_examples) < min_correct:
        failures.append(f"correct example count {len(correct_examples)} is below required minimum {min_correct}")
    if len(incorrect_examples) < min_incorrect:
        failures.append(f"incorrect example count {len(incorrect_examples)} is below required minimum {min_incorrect}")
    if correct_coverage < min_empirical_coverage:
        failures.append(
            f"empirical correct coverage {correct_coverage:.6f} is below required minimum {min_empirical_coverage:.6f}"
        )
    if false_accept_rate > max_false_accept_rate:
        failures.append(
            f"false accept rate {false_accept_rate:.6f} exceeds allowed maximum {max_false_accept_rate:.6f}"
        )
    return CalibrationTuneResult(
        calibration=calibration,
        threshold=threshold,
        metrics={
            "examples": len(examples),
            "correct_examples": len(correct_examples),
            "incorrect_examples": len(incorrect_examples),
            "accepted": len(accepted),
            "accepted_correct": len(accepted_correct),
            "accepted_incorrect": len(accepted_incorrect),
            "correct_coverage": correct_coverage,
            "false_accept_rate": false_accept_rate,
            "abstention_rate": abstention_rate,
            "target_coverage": target_coverage,
            "min_empirical_coverage": min_empirical_coverage,
            "max_false_accept_rate": max_false_accept_rate,
            "max_prediction_set_size": max_prediction_set_size,
        },
        failures=failures,
    )


def reality_monitor_confidence(
    *,
    reality_class: str,
    trust_tier: int,
    provenance_count: int,
    explicit_label: bool,
) -> float:
    """Return a conservative confidence for a reality-monitoring label.

    This is label confidence, not answer confidence. Abstention must continue to
    key off the reality class and grounded-evidence signals, not this scalar
    alone. Learned discriminators can replace the scoring policy later, but must
    keep the same calibrated confidence semantics and must pass G0 gates.
    """

    label = reality_class.strip().lower().replace("-", "_")
    score = 0.45
    if label == "evidence_grounded":
        score = 0.70
        if trust_tier <= 0:
            score += 0.15
        if provenance_count > 0:
            score += 0.10
    elif label in {"self_generated", "externally_suggested"}:
        score = 0.70
    elif label == "unknown":
        score = 0.55
    if explicit_label:
        score += 0.05
    return round(max(0.0, min(1.0, score)), 6)


# §26 / blueprint §7 #18 — multi-signal calibrated_confidence fuse (L2 pure).
# Weights pinned by tests/test_calibrated_confidence_fuse.py.
FUSE_WEIGHT_RAW = 0.35
FUSE_WEIGHT_CERTAINTY = 0.20  # (1 - semantic_entropy)
FUSE_WEIGHT_AGREEMENT = 0.20
FUSE_WEIGHT_PROVENANCE = 0.15
FUSE_WEIGHT_FIDELITY = 0.10


def _bounded_unit(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Return the first non-None value among keys (None aliases treated as absent)."""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _fidelity_from_reality_class(reality_class: str) -> float:
    reality = str(reality_class or "").strip().lower().replace("-", "_")
    if reality in {"grounded", "evidence_grounded"}:
        return 1.0
    if reality in {"self_generated", "externally_suggested"}:
        return 0.2
    if reality == "unknown":
        return 0.4
    return 0.0


def fuse_calibrated_confidence(
    *,
    raw_confidence: float,
    semantic_entropy: float = 0.0,
    retrieval_agreement: float = 1.0,
    provenance_strength: float = 0.0,
    fidelity_score: float = 0.0,
) -> float:
    """Return fused calibrated_confidence in [0, 1]. Pure. Deterministic.

    ENGINE-CONTRACT L2 — engines store/return only; they must not reimplement
    fusion. Missing provenance/fidelity default fail-closed (0.0). Agreement
    defaults to 1.0 (no channel conflict evidence). Entropy defaults to 0.0
    (no uncertainty evidence). Identity alias ``fused == raw`` is *not*
    guaranteed once non-raw signals diverge.
    """
    raw = _bounded_unit(raw_confidence, default=0.0)
    entropy = _bounded_unit(semantic_entropy, default=0.0)
    certainty = 1.0 - entropy
    agreement = _bounded_unit(retrieval_agreement, default=1.0)
    provenance = _bounded_unit(provenance_strength, default=0.0)
    fidelity = _bounded_unit(fidelity_score, default=0.0)
    fused = (
        FUSE_WEIGHT_RAW * raw
        + FUSE_WEIGHT_CERTAINTY * certainty
        + FUSE_WEIGHT_AGREEMENT * agreement
        + FUSE_WEIGHT_PROVENANCE * provenance
        + FUSE_WEIGHT_FIDELITY * fidelity
    )
    return max(0.0, min(1.0, float(fused)))


def explain_calibrated_confidence(
    *,
    raw_confidence: float,
    semantic_entropy: float = 0.0,
    retrieval_agreement: float = 1.0,
    provenance_strength: float = 0.0,
    fidelity_score: float = 0.0,
) -> dict[str, Any]:
    """Attribution companion for fuse_calibrated_confidence (standing/packet)."""
    raw = _bounded_unit(raw_confidence, default=0.0)
    entropy = _bounded_unit(semantic_entropy, default=0.0)
    certainty = 1.0 - entropy
    agreement = _bounded_unit(retrieval_agreement, default=1.0)
    provenance = _bounded_unit(provenance_strength, default=0.0)
    fidelity = _bounded_unit(fidelity_score, default=0.0)
    fused = fuse_calibrated_confidence(
        raw_confidence=raw,
        semantic_entropy=entropy,
        retrieval_agreement=agreement,
        provenance_strength=provenance,
        fidelity_score=fidelity,
    )
    return {
        "calibrated_confidence": fused,
        "raw_confidence": raw,
        "semantic_entropy": entropy,
        "certainty": certainty,
        "retrieval_agreement": agreement,
        "provenance_strength": provenance,
        "fidelity_score": fidelity,
        "weights": {
            "raw": FUSE_WEIGHT_RAW,
            "certainty": FUSE_WEIGHT_CERTAINTY,
            "agreement": FUSE_WEIGHT_AGREEMENT,
            "provenance": FUSE_WEIGHT_PROVENANCE,
            "fidelity": FUSE_WEIGHT_FIDELITY,
        },
    }


def calibrated_confidence_signals_from_hit(
    *,
    metadata: Mapping[str, Any] | None,
    reality_class: str = "",
    trust_tier: int = 5,
) -> dict[str, float]:
    """Collect fuse kwargs from a retrieval hit's metadata envelope (§19/§26)."""
    meta = dict(metadata) if isinstance(metadata, Mapping) else {}
    raw = _first_present(meta, "verbalized_confidence", "confidence", "calibrated_confidence")
    if raw is None:
        raw = 0.0

    entropy = _first_present(meta, "semantic_entropy", "entropy")
    if entropy is None:
        entropy = 0.0

    agreement = _first_present(meta, "retrieval_agreement", "channel_agreement")
    if agreement is None:
        activation = meta.get("activation")
        if isinstance(activation, Mapping) and activation.get("score") is not None:
            agreement = activation.get("score")
        else:
            agreement = 1.0

    # Prefer explicit key when non-None; else independent_corroboration; else trust tier.
    provenance = _first_present(meta, "provenance_strength")
    if provenance is None:
        ic = meta.get("independent_corroboration")
        if isinstance(ic, Mapping) and ic.get("independent_corroboration_weight") is not None:
            provenance = ic.get("independent_corroboration_weight")
        else:
            try:
                tier = int(trust_tier)
            except (TypeError, ValueError):
                tier = 5
            # trust_tier 0 is strongest external; map to provenance strength [0,1]
            provenance = max(0.0, min(1.0, 1.0 - (tier / 5.0)))

    fidelity = _first_present(meta, "fidelity", "fidelity_score")
    if fidelity is None:
        lifecycle = meta.get("lifecycle")
        if isinstance(lifecycle, Mapping) and lifecycle.get("fidelity_score") is not None:
            fidelity = lifecycle.get("fidelity_score")
        if fidelity is None:
            fidelity = _fidelity_from_reality_class(
                reality_class or str(meta.get("reality_class") or "")
            )

    return {
        "raw_confidence": _bounded_unit(raw, default=0.0),
        "semantic_entropy": _bounded_unit(entropy, default=0.0),
        "retrieval_agreement": _bounded_unit(agreement, default=1.0),
        "provenance_strength": _bounded_unit(provenance, default=0.0),
        "fidelity_score": _bounded_unit(fidelity, default=0.0),
    }


def fuse_calibrated_confidence_from_hit(
    *,
    metadata: Mapping[str, Any] | None,
    reality_class: str = "",
    trust_tier: int = 5,
) -> float:
    """Standing-path helper: collect hit signals then fuse (shared Local/Postgres)."""
    signals = calibrated_confidence_signals_from_hit(
        metadata=metadata,
        reality_class=reality_class,
        trust_tier=trust_tier,
    )
    return fuse_calibrated_confidence(**signals)

