"""Derived Standing scores for the unified cognitive substrate.

Standing is a projection: it is recomputable from existing evidence/retrieval
signals and never writes to the evidence ledger. It is a two-axis score:
``groundedness`` controls answer authority, while ``salience`` may affect which
memories surface. Salience is deliberately excluded from authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


STANDING_FN_VERSION = "standing.continuous.v1"
AUTHORITY_THRESHOLD = 0.5
SELF_GENERATED_CEILING = 0.49
GROUNDED_FLOOR = 0.51
EVIDENCE_DOMINANCE_GAP = round(GROUNDED_FLOOR - SELF_GENERATED_CEILING, 6)

_GROUNDED_CLASSES = {"grounded", "evidence_grounded", "evidence-grounded"}
_UNGROUNDED_CLASSES = {"self_generated", "self-generated", "simulated", "externally_suggested", "unknown"}


@dataclass(frozen=True, slots=True)
class Standing:
    """Versioned, deterministic Standing tuple.

    Authority is intentionally a pure function of groundedness. Salience may
    rank retrieval candidates, but it must never make a low-groundedness unit
    assertable.
    """

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
            "mode": "continuous_two_axis",
            "derived": True,
            "writes_evidence": False,
            "explain": self.explain,
        }


def standing(unit_signals: Mapping[str, Any] | None) -> Standing:
    """Compute deterministic Standing from already-available unit signals.

    Missing or unknown signals fail closed to the low groundedness band. Only
    provenance-independent external corroboration raises groundedness. Self-
    generated or unknown content is hard-capped below the external-evidence
    band even when it is salient or repeated.
    """

    signals = dict(unit_signals or {})
    reality_class = _normalise_reality_class(signals.get("reality_class"))
    trust_tier = _bounded_int(signals.get("trust_tier"), default=5, lower=0, upper=5)
    calibrated_confidence = _bounded_unit(signals.get("calibrated_confidence"), default=0.0)
    raw_corroboration_count = _bounded_int(signals.get("corroboration_count"), default=0, lower=0, upper=10_000)
    independent_corroboration_count = _bounded_int(
        signals.get("independent_corroboration_count", raw_corroboration_count),
        default=0,
        lower=0,
        upper=10_000,
    )
    independent_corroboration_weight = _bounded_unit(
        signals.get("independent_corroboration_weight"),
        default=min(independent_corroboration_count, 5) / 5.0,
    )
    self_generated_corroboration_count = _bounded_int(
        signals.get("self_generated_corroboration_count"),
        default=0,
        lower=0,
        upper=10_000,
    )
    rejected_corroboration_count = _bounded_int(
        signals.get("rejected_corroboration_count"),
        default=max(0, raw_corroboration_count - independent_corroboration_count),
        lower=0,
        upper=10_000,
    )
    contradiction_pressure = _bounded_unit(signals.get("contradiction_pressure"), default=0.0)
    groundedness_decay = _bounded_unit(signals.get("groundedness_decay"), default=0.0)
    activation = _bounded_unit(signals.get("activation"), default=0.0)
    lifecycle_salience = _bounded_unit(signals.get("lifecycle_salience"), default=0.0)
    explicit_salience = _bounded_unit(signals.get("salience"), default=0.0)

    external_grounded = reality_class == "grounded"
    trust_component = (5 - trust_tier) / 5.0
    effective_independent_corroboration_count = independent_corroboration_count if external_grounded else 0
    if not external_grounded:
        rejected_corroboration_count += independent_corroboration_count
    corroboration_component = independent_corroboration_weight if external_grounded else 0.0

    if external_grounded:
        raw_groundedness = (
            GROUNDED_FLOOR
            + 0.20 * corroboration_component
            + 0.14 * calibrated_confidence
            + 0.10 * trust_component
            - 0.18 * contradiction_pressure
            - 0.10 * groundedness_decay
        )
        groundedness = max(GROUNDED_FLOOR, min(1.0, raw_groundedness))
    else:
        raw_groundedness = (
            0.08
            + 0.08 * calibrated_confidence
            + 0.06 * trust_component
            - 0.16 * contradiction_pressure
            - 0.08 * groundedness_decay
        )
        groundedness = max(0.0, min(SELF_GENERATED_CEILING, raw_groundedness))

    groundedness = _fixed(groundedness)
    salience = _fixed(max(activation, lifecycle_salience, explicit_salience))
    authority = groundedness >= AUTHORITY_THRESHOLD
    explain = {
        "inputs": {
            "reality_class": reality_class,
            "trust_tier": trust_tier,
            "calibrated_confidence": _fixed(calibrated_confidence),
            "corroboration_count": raw_corroboration_count,
            "independent_corroboration_count": independent_corroboration_count,
            "effective_independent_corroboration_count": effective_independent_corroboration_count,
            "independent_corroboration_weight": _fixed(independent_corroboration_weight),
            "self_generated_corroboration_count": self_generated_corroboration_count,
            "rejected_corroboration_count": rejected_corroboration_count,
            "contradiction_pressure": _fixed(contradiction_pressure),
            "groundedness_decay": _fixed(groundedness_decay),
            "activation": salience,
        },
        "bands": {
            "grounded_floor": GROUNDED_FLOOR,
            "self_generated_ceiling": SELF_GENERATED_CEILING,
            "evidence_dominance_gap": EVIDENCE_DOMINANCE_GAP,
        },
        "fail_closed": reality_class == "unknown",
        "authority_axis": "groundedness",
        "salience_excluded_from_authority": True,
        "self_corroboration_rejected": self_generated_corroboration_count > 0,
        "h1_independent_external_only": True,
        "h2_authority_uses_groundedness_only": True,
        "h3_evidence_dominance_gap": True,
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
            "independent_corroboration_count": 1 if grounded else 0,
            "independent_corroboration_weight": 1.0 if grounded else 0.0,
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
        "mode": "continuous_two_axis",
        "authority_axis": "groundedness",
        "authority_threshold": AUTHORITY_THRESHOLD,
        "evidence_dominance_gap": EVIDENCE_DOMINANCE_GAP,
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
