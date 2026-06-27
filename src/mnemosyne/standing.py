"""Derived Standing scores for the unified cognitive substrate.

Standing is a projection: it is recomputable from existing evidence/retrieval
signals and never writes to the evidence ledger. Phase 7 P1 deliberately keeps
the authority decision byte-stable by mirroring the existing reality-monitoring
boolean path while exposing a deterministic numeric shape for later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


STANDING_FN_VERSION = "standing.mirror.v1"
AUTHORITY_THRESHOLD = 0.5
SELF_GENERATED_CEILING = 0.49
GROUNDED_FLOOR = 0.51

_GROUNDED_CLASSES = {"grounded", "evidence_grounded", "evidence-grounded"}
_UNGROUNDED_CLASSES = {"self_generated", "self-generated", "simulated", "externally_suggested", "unknown"}


@dataclass(frozen=True, slots=True)
class Standing:
    """Versioned, deterministic Standing tuple plus P1 mirror decision."""

    groundedness: float
    salience: float
    standing_fn_version: str
    authority_threshold: float
    authority: bool
    explain: dict[str, Any]

    @property
    def value(self) -> float:
        """P1 scalar compatibility value; authority uses groundedness only."""

        return self.groundedness

    def to_dict(self) -> dict[str, Any]:
        return {
            "standing_fn_version": self.standing_fn_version,
            "value": self.value,
            "groundedness": self.groundedness,
            "salience": self.salience,
            "authority_threshold": self.authority_threshold,
            "authority": self.authority,
            "authority_axis": "groundedness",
            "mode": "byte_stable_mirror",
            "derived": True,
            "writes_evidence": False,
            "explain": self.explain,
        }


def standing(unit_signals: Mapping[str, Any] | None) -> Standing:
    """Compute deterministic Standing from already-available unit signals.

    Missing or unknown signals fail closed to the low groundedness band. The
    score is monotonic within the external and self-generated bands, while the
    P1 authority threshold preserves the existing grounded-vs-ungrounded
    decision exactly.
    """

    signals = dict(unit_signals or {})
    reality_class = _normalise_reality_class(signals.get("reality_class"))
    trust_tier = _bounded_int(signals.get("trust_tier"), default=5, lower=0, upper=5)
    calibrated_confidence = _bounded_unit(signals.get("calibrated_confidence"), default=0.0)
    corroboration_count = _bounded_int(signals.get("corroboration_count"), default=0, lower=0, upper=10_000)
    contradiction_pressure = _bounded_unit(signals.get("contradiction_pressure"), default=0.0)
    activation = _bounded_unit(signals.get("activation"), default=0.0)

    external_grounded = reality_class == "grounded"
    trust_component = (5 - trust_tier) / 5.0
    corroboration_component = min(corroboration_count, 5) / 5.0

    if external_grounded:
        raw_groundedness = (
            0.72
            + 0.10 * calibrated_confidence
            + 0.10 * trust_component
            + 0.08 * corroboration_component
            - 0.20 * contradiction_pressure
        )
        groundedness = max(GROUNDED_FLOOR, min(1.0, raw_groundedness))
    else:
        raw_groundedness = (
            0.08
            + 0.08 * calibrated_confidence
            + 0.06 * trust_component
            + 0.06 * corroboration_component
            - 0.20 * contradiction_pressure
        )
        groundedness = max(0.0, min(SELF_GENERATED_CEILING, raw_groundedness))

    groundedness = _fixed(groundedness)
    salience = _fixed(activation)
    authority = groundedness >= AUTHORITY_THRESHOLD
    explain = {
        "inputs": {
            "reality_class": reality_class,
            "trust_tier": trust_tier,
            "calibrated_confidence": _fixed(calibrated_confidence),
            "corroboration_count": corroboration_count,
            "contradiction_pressure": _fixed(contradiction_pressure),
            "activation": salience,
        },
        "bands": {
            "grounded_floor": GROUNDED_FLOOR,
            "self_generated_ceiling": SELF_GENERATED_CEILING,
            "evidence_dominance_gap": _fixed(GROUNDED_FLOOR - SELF_GENERATED_CEILING),
        },
        "fail_closed": reality_class == "unknown",
        "p1_mirror": True,
    }
    return Standing(
        groundedness=groundedness,
        salience=salience,
        standing_fn_version=STANDING_FN_VERSION,
        authority_threshold=AUTHORITY_THRESHOLD,
        authority=authority,
        explain=explain,
    )


def standing_from_shadow_flag(*, shadow_only: bool, critical_path: bool) -> dict[str, Any]:
    """Mirror an existing shadow/critical-path boolean pair as Standing."""

    grounded = not shadow_only and critical_path
    score = standing(
        {
            "reality_class": "grounded" if grounded else "self_generated",
            "trust_tier": 0 if grounded else 5,
            "calibrated_confidence": 1.0 if grounded else 0.0,
            "corroboration_count": 1 if grounded else 0,
            "contradiction_pressure": 0.0,
            "activation": 0.0,
        }
    )
    payload = score.to_dict()
    payload["mirror"] = {
        "shadow_only": bool(shadow_only),
        "critical_path": bool(critical_path),
        "standing_authority_matches_boolean": score.authority is grounded,
    }
    return payload


def standing_abstention_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize hit-level Standing rows and mirror the existing abstention gate."""

    hit_count = len(rows)
    authoritative = [row for row in rows if row.get("authority") is True]
    active = hit_count > 0 and not authoritative
    return {
        "standing_fn_version": STANDING_FN_VERSION,
        "mode": "byte_stable_mirror",
        "authority_axis": "groundedness",
        "authority_threshold": AUTHORITY_THRESHOLD,
        "hit_count": hit_count,
        "authoritative_hit_count": len(authoritative),
        "low_standing_hit_ids": [row["hit_id"] for row in rows if row.get("authority") is not True],
        "abstention_gate": {
            "trigger": "standing_low_authority_only",
            "active": active,
            "critical_path": True,
            "shadow_only": False,
        },
        "hits": rows,
    }


def _normalise_reality_class(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {item.replace("-", "_") for item in _GROUNDED_CLASSES}:
        return "grounded"
    if raw in {item.replace("-", "_") for item in _UNGROUNDED_CLASSES}:
        return raw
    return "unknown"


def _bounded_unit(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric != numeric:
        return default
    return max(0.0, min(1.0, numeric))


def _bounded_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(upper, numeric))


def _fixed(value: float) -> float:
    return round(float(value), 6)
