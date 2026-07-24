"""Derived Standing scores for the unified cognitive substrate.

Standing is a projection: it is recomputable from existing evidence/retrieval
signals and never writes to the evidence ledger. It is a two-axis score:
``groundedness`` controls answer authority, while ``salience`` may affect which
memories surface. Salience is deliberately excluded from authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


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
    birth_groundedness = _optional_bounded_unit(signals.get("birth_groundedness"))

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
        self_birth_groundedness = 0.08
        if birth_groundedness is not None:
            self_birth_groundedness = min(SELF_GENERATED_CEILING, birth_groundedness)
        raw_groundedness = (
            self_birth_groundedness
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
            "birth_groundedness": _fixed(self_birth_groundedness if not external_grounded else GROUNDED_FLOOR),
            "credential_birth_groundedness_applied": birth_groundedness is not None and not external_grounded,
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
        "h11_earned_autonomy_bounded": birth_groundedness is None or groundedness <= SELF_GENERATED_CEILING,
    }
    return Standing(
        groundedness=groundedness,
        salience=salience,
        standing_fn_version=STANDING_FN_VERSION,
        authority_threshold=AUTHORITY_THRESHOLD,
        authority=authority,
        explain=explain,
    )


def effective_independent_external_count(unit_signals: Mapping[str, Any] | None) -> int:
    """Return Standing's effective independent *external* corroboration count.

    Self-generated / unknown reality classes always yield 0 — the §23.3 fact
    gate must never treat self-echo as external corroboration.
    """

    score = standing(unit_signals)
    inputs = score.explain.get("inputs", {})
    return int(inputs.get("effective_independent_corroboration_count", 0) or 0)


def standing_from_authority_state(*, answer_authority: bool, critical_path: bool) -> dict[str, Any]:
    """Mirror an authority/critical-path state as a Standing report."""

    grounded = bool(answer_authority) and bool(critical_path)
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
    payload["authority_state"] = {
        "answer_authority": bool(answer_authority),
        "critical_path": bool(critical_path),
        "standing_authority_matches_state": score.authority is grounded,
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


def standing_observability_record(
    *,
    target_id: str,
    kind: str,
    tenant_id: str,
    branch: str,
    source_evidence_cids: Iterable[Any],
    score: Standing,
    surface: str,
) -> dict[str, Any]:
    """Return a replayable trace for one derived Standing value.

    This is intentionally metadata, not authority. The record gives operators a
    stable place to find the derived value, the provenance used to recompute it,
    and the fact that replay is bitemporal/projection-based.
    """

    source_cids = _sorted_texts(source_evidence_cids)
    return {
        "schema_version": "standing.observability.v1",
        "standing_fn_version": score.standing_fn_version,
        "surface": str(surface or "unknown"),
        "target": {
            "id": str(target_id or ""),
            "kind": str(kind or "unknown"),
            "tenant_id": str(tenant_id or ""),
            "branch": str(branch or "main"),
        },
        "values": {
            "groundedness": score.groundedness,
            "salience": score.salience,
            "authority": score.authority,
        },
        "source_evidence_cids": source_cids,
        "provenance_available": bool(source_cids),
        "derived": True,
        "writes_evidence": False,
        "replayable": True,
        "bitemporal_replay": {
            "supported": True,
            "projection_recomputes_from_ledger": True,
        },
        "h12_observability": True,
    }


def standing_erasure_cascade_report(
    *,
    source_cid: str,
    erasure_mode: str,
    affected_cids: Iterable[Any],
    erased_derived_cids: Iterable[Any],
    retained_metadata_by_cid: Mapping[str, Mapping[str, Any]] | None = None,
    metadata_by_cid: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the H8/H12 audit projection for an erasure cascade.

    Standing is recomputed on read, so erasure does not mutate a stored Standing
    column. The cascade report records exactly which derived units were erased
    or source-trimmed, and marks self-derivations as demoted/erased so the audit
    log is replayable.
    """

    retained = {str(cid): dict(metadata) for cid, metadata in (retained_metadata_by_cid or {}).items()}
    metadata = {str(cid): dict(value) for cid, value in (metadata_by_cid or {}).items()}
    erased = _sorted_texts(erased_derived_cids)
    actions: list[dict[str, Any]] = []
    for cid in erased:
        before = metadata.get(cid, {})
        self_derivation = _metadata_is_self_derivation(before)
        actions.append(
            {
                "cid": cid,
                "action": "erased_self_derivation" if self_derivation else "erased_derived",
                "self_derivation": self_derivation,
                "source_evidence_cids_before": _metadata_source_cids(before),
                "source_evidence_cids_after": [],
                "standing_recomputed_on_read": True,
            }
        )
    for cid, after in sorted(retained.items()):
        before = metadata.get(cid, {})
        self_derivation = _metadata_is_self_derivation(before) or _metadata_is_self_derivation(after)
        actions.append(
            {
                "cid": cid,
                "action": "trimmed_self_derivation" if self_derivation else "trimmed_derived",
                "self_derivation": self_derivation,
                "source_evidence_cids_before": _metadata_source_cids(before),
                "source_evidence_cids_after": _metadata_source_cids(after),
                "standing_recomputed_on_read": True,
            }
        )
    return {
        "schema_version": "standing.erasure-cascade.v1",
        "standing_fn_version": STANDING_FN_VERSION,
        "source_cid": str(source_cid or ""),
        "erasure_mode": str(erasure_mode or ""),
        "affected_cids": _sorted_texts(affected_cids),
        "erased_derived_cids": erased,
        "retained_derived_cids": sorted(retained),
        "self_derivation_actions": [item for item in actions if item["self_derivation"]],
        "derived_actions": actions,
        "standing_recomputed_on_read": True,
        "cascade_bounded_by_single_forget": True,
        "h8_cascade_to_self_derivations": True,
        "h12_observable_replayable_reversible": str(erasure_mode) != "hard_delete_legal",
        "reversibility": {
            "ledger_rebuild_supported": str(erasure_mode) != "hard_delete_legal",
            "tombstone_modes_reversible": str(erasure_mode) != "hard_delete_legal",
            "hard_delete_legal_is_intentionally_irreversible": str(erasure_mode) == "hard_delete_legal",
        },
    }


def _normalise_reality_class(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {item.replace("-", "_") for item in _GROUNDED_CLASSES}:
        return "grounded"
    if raw in {item.replace("-", "_") for item in _UNGROUNDED_CLASSES}:
        return raw
    return "unknown"


def _metadata_source_cids(metadata: Mapping[str, Any]) -> list[str]:
    sources: set[str] = set()
    single = metadata.get("source_evidence_cid")
    if single:
        sources.add(str(single))
    values = metadata.get("source_evidence_cids")
    if isinstance(values, list | tuple | set):
        sources.update(str(item) for item in values if str(item))
    summary = metadata.get("summary")
    if isinstance(summary, Mapping):
        summary_values = summary.get("source_evidence_cids")
        if isinstance(summary_values, list | tuple | set):
            sources.update(str(item) for item in summary_values if str(item))
    return sorted(sources)


def _metadata_is_self_derivation(metadata: Mapping[str, Any]) -> bool:
    reality_class = _normalise_reality_class(metadata.get("reality_class"))
    if reality_class in {"self_generated", "simulated"}:
        return True
    if isinstance(metadata.get("self_generation_lifecycle"), Mapping):
        return True
    source_type = str(metadata.get("source_type") or metadata.get("source") or "").lower()
    if any(marker in source_type for marker in ("summary", "trace", "analysis", "consolidation", "reflection")):
        return True
    summary = metadata.get("summary")
    if isinstance(summary, Mapping):
        summary_source = str(summary.get("source") or summary.get("kind") or "").lower()
        return any(marker in summary_source for marker in ("summary", "consolidation", "reflection"))
    return False


def _sorted_texts(values: Iterable[Any]) -> list[str]:
    return sorted({str(item) for item in values if str(item)})


def _bounded_unit(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric != numeric:
        return default
    return max(0.0, min(1.0, numeric))


def _optional_bounded_unit(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return max(0.0, min(1.0, numeric))


def _bounded_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(upper, numeric))


def _fixed(value: float) -> float:
    return round(float(value), 6)
