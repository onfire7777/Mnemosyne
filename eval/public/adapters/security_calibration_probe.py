"""Public-CLI-only development probe for security-calibration observations.

The probe drives only public CLI operations with explicit tenant, session, and
capability context. Payloads stay inert data. Traces never carry scorer labels
or scores; Stage A scores them outside the SUT.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from eval.public import security_calibration as security_calibration_core

SUITE = security_calibration_core.SUITE
PROFILE = security_calibration_core.PROFILE
SCORING_FAMILY = "security-calibration-development"
_FORBIDDEN_TRACE_KEYS = frozenset(
    {
        "answerable",
        "asr",
        "attack_success_rate",
        "brier",
        "correct",
        "criticality",
        "ece",
        "expected_action",
        "expected_state",
        "family",
        "gold",
        "hard_gate",
        "hard_gate_failed",
        "labels",
        "metrics",
        "official_score",
        "passed",
        "score",
        "threat_shape",
    }
)


def run(
    fixture: Mapping[str, Any], cli: Any
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Execute public operations and return label-free observations."""
    if cli is None:
        raise ValueError(
            "security-calibration development requires a live public CLI"
        )
    validated = security_calibration_core.validate_fixture(fixture)
    projected = security_calibration_core.public_inputs(validated)
    traces = [_execute_case(case, cli) for case in projected["cases"]]
    return traces, {}


def _execute_case(case: Mapping[str, Any], cli: Any) -> dict[str, Any]:
    recorded: dict[str, dict[str, Any]] = {}
    hits: list[Mapping[str, Any]] = []
    for operation in case["operations"]:
        hits = _execute_operation(operation, cli, recorded)
    return _observation(case, recorded, hits)


def _execute_operation(
    operation: Mapping[str, Any],
    cli: Any,
    recorded: dict[str, dict[str, Any]],
) -> list[Mapping[str, Any]]:
    kind = operation["operation"]
    tenant_id = operation["tenant_id"]
    session_id = operation["session_id"]
    capability = operation["capability"]
    payload = operation["payload"]
    item_id = operation["item_id"]
    if kind == "capture":
        result = _require_mapping(
            cli.capture(
                tenant_id,
                "security-calibration-probe",
                payload,
                session_id=session_id,
                source_identity=item_id or "security-calibration-probe",
                source_type=capability,
            ),
            "capture",
        )
        cid = result.get("cid")
        if item_id:
            recorded[item_id] = {
                "cid": cid if isinstance(cid, str) and cid else None,
                "deleted": False,
                "session_id": session_id,
                "tenant_id": tenant_id,
            }
        return []
    if kind == "delete":
        item = recorded.get(item_id or "")
        cid = item.get("cid") if item else None
        forget = getattr(cli, "forget", None)
        if callable(forget) and isinstance(cid, str) and cid:
            forget(tenant_id, cid)
        if item is not None:
            item["deleted"] = True
        return []
    if kind == "correct":
        propose = getattr(cli, "propose", None)
        if callable(propose):
            propose(
                tenant_id,
                "security-calibration-probe",
                item_id or "security-calibration-probe",
                capability,
                payload,
            )
        return []
    if kind in {"answer", "retrieve"}:
        result = _require_mapping(cli.search(tenant_id, payload), kind)
        raw_hits = result.get("hits")
        if raw_hits is None:
            return []
        if not isinstance(raw_hits, list) or any(
            not isinstance(hit, Mapping) for hit in raw_hits
        ):
            raise ValueError("security-calibration search hits must be objects")
        return list(raw_hits)
    raise ValueError(f"unsupported public operation: {kind}")


def _observation(
    case: Mapping[str, Any],
    recorded: Mapping[str, Mapping[str, Any]],
    hits: list[Mapping[str, Any]],
) -> dict[str, Any]:
    visible_tenants: set[str] = set()
    visible_sessions: set[str] = set()
    accessed_ids: set[str] = set()
    resurrected_ids: set[str] = set()
    provenance_ids: list[str] = []
    response_text: str | None = None
    by_cid = {
        item["cid"]: (item_id, item)
        for item_id, item in recorded.items()
        if isinstance(item.get("cid"), str)
    }
    for hit in hits:
        tenant_id = hit.get("tenant_id")
        if isinstance(tenant_id, str) and tenant_id:
            visible_tenants.add(tenant_id)
        session_id = _hit_session(hit)
        if session_id:
            visible_sessions.add(session_id)
        cid = hit.get("id")
        if isinstance(cid, str) and cid in by_cid:
            item_id, item = by_cid[cid]
            accessed_ids.add(item_id)
            visible_tenants.add(item["tenant_id"])
            visible_sessions.add(item["session_id"])
            if item["deleted"]:
                resurrected_ids.add(item_id)
        text = hit.get("text")
        if response_text is None and isinstance(text, str) and text:
            response_text = text
        provenance = hit.get("provenance")
        if isinstance(provenance, list):
            provenance_ids.extend(
                value for value in provenance if isinstance(value, str) and value
            )
    if not visible_tenants:
        visible_tenants.add(case["tenant_id"])
    if not visible_sessions:
        visible_sessions.add(case["session_id"])
    answered = response_text is not None
    observation = {
        "accessed_ids": sorted(accessed_ids),
        "action": "answer" if answered else "abstain",
        "case_id": case["case_id"],
        "confidence": 1.0,
        "mutation_targets": [],
        "provenance_ids": list(dict.fromkeys(provenance_ids)),
        "response_text": response_text,
        "resurrected_ids": sorted(resurrected_ids),
        "scoring_family": SCORING_FAMILY,
        "state": "answered" if answered else "abstained",
        "visible_sessions": sorted(visible_sessions),
        "visible_tenants": sorted(visible_tenants),
    }
    leaked = _FORBIDDEN_TRACE_KEYS & set(observation)
    if leaked:
        raise ValueError(f"observation leaked scorer-owned keys: {sorted(leaked)}")
    return observation


def _hit_session(hit: Mapping[str, Any]) -> str | None:
    session_id = hit.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    metadata = hit.get("metadata")
    if isinstance(metadata, Mapping):
        nested = metadata.get("session_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"security-calibration {label} must return an object")
    return value
