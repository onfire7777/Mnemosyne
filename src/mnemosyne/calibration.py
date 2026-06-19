"""Conformal calibration for confidence and abstention."""

from __future__ import annotations

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


def conformal_threshold(calibration: CalibrationSet) -> float:
    if not calibration.scores:
        return 1.0
    bounded = sorted(max(0.0, min(1.0, score)) for score in calibration.scores)
    alpha = 1.0 - calibration.target_coverage
    index = min(len(bounded) - 1, max(0, int((len(bounded) + 1) * alpha) - 1))
    return bounded[index]


def should_abstain(confidence: float, calibration: CalibrationSet, prediction_set_size: int = 1, max_set_size: int = 3) -> bool:
    if prediction_set_size == 0 or prediction_set_size > max_set_size:
        return True
    return confidence < conformal_threshold(calibration)

