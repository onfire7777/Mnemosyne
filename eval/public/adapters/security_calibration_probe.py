"""Public-CLI-only development probe for security-calibration observations.

The probe drives only public CLI operations with explicit tenant, session, and
capability context. Payloads stay inert data. Traces never carry scorer labels
or scores; Stage A scores them outside the SUT.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from eval.harness.cli_driver import MnemoCLI
from eval.public import security_calibration as security_calibration_core
from eval.public.action_cli import SESSION_SECRET, mint_session_token

SUITE = security_calibration_core.SUITE
PROFILE = security_calibration_core.PROFILE
SCORING_FAMILY = "security-calibration-development"
_PROBE_USER = "security-calibration-probe"
_PROBE_ROLE = "reader"
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


def _bound_cli(cli: Any, operation: Mapping[str, Any]) -> Any:
    """Bind tenant/session/capability onto the public CLI identity seam."""
    if not isinstance(cli, MnemoCLI):
        return cli
    token = mint_session_token(
        tenant_id=operation["tenant_id"],
        user_id=_PROBE_USER,
        role=_PROBE_ROLE,
        session_id=operation["session_id"],
        capabilities=(operation["capability"],),
    )
    flags: list[str] = []
    skip_next = False
    for flag in cli.global_flags:
        if skip_next:
            skip_next = False
            continue
        if flag == "--session-token":
            skip_next = True
            continue
        flags.append(flag)
    return replace(
        cli,
        global_flags=[*flags, "--session-token", token],
        env={**cli.env, "MNEMOSYNE_SESSION_SECRET": SESSION_SECRET},
    )


def _execute_case(case: Mapping[str, Any], cli: Any) -> dict[str, Any]:
    recorded: dict[str, dict[str, Any]] = {}
    hits: list[Mapping[str, Any]] = []
    confidence: float | None = None
    answer_text: str | None = None
    abstained = False
    for operation in case["operations"]:
        result = _execute_operation(operation, cli, recorded)
        if operation["operation"] == "retrieve":
            hits = result["hits"]
            confidence = result["confidence"]
        elif operation["operation"] == "answer":
            hits = result["hits"]
            confidence = result["confidence"]
            answer_text = result["answer"]
            abstained = result["abstained"]
    return _observation(case, recorded, hits, confidence, answer_text, abstained)


def _execute_operation(
    operation: Mapping[str, Any],
    cli: Any,
    recorded: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    kind = operation["operation"]
    tenant_id = operation["tenant_id"]
    session_id = operation["session_id"]
    capability = operation["capability"]
    payload = operation["payload"]
    item_id = operation["item_id"]
    bound = _bound_cli(cli, operation)
    if kind == "capture":
        result = _require_mapping(
            bound.capture(
                tenant_id,
                _PROBE_USER,
                payload,
                session_id=session_id,
                source_identity=item_id or _PROBE_USER,
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
        return {}
    if kind == "delete":
        item = recorded.get(item_id or "")
        cid = item.get("cid") if item else None
        forget = getattr(bound, "forget", None)
        if callable(forget) and isinstance(cid, str) and cid:
            forget(tenant_id, cid)
        if item is not None:
            item["deleted"] = True
        return {}
    if kind == "correct":
        propose = getattr(bound, "propose", None)
        if callable(propose):
            propose(
                tenant_id,
                _PROBE_USER,
                item_id or _PROBE_USER,
                capability,
                payload,
            )
        return {}
    if kind == "retrieve":
        search = _search(bound, operation)
        return {"hits": search["hits"], "confidence": search["confidence"]}
    if kind == "answer":
        search = _search(bound, operation)
        answered = _answer(bound, operation)
        return {
            "answer": answered["answer"],
            "abstained": answered["abstained"],
            "confidence": search["confidence"],
            "hits": search["hits"],
        }
    raise ValueError(f"unsupported public operation: {kind}")


def _search(cli: Any, operation: Mapping[str, Any]) -> dict[str, Any]:
    tenant_id = operation["tenant_id"]
    session_id = operation["session_id"]
    capability = operation["capability"]
    if isinstance(cli, MnemoCLI):
        raw = cli.run(
            "search",
            "--tenant",
            tenant_id,
            "--query",
            operation["payload"],
            "--user",
            _PROBE_USER,
            "--capability-tag",
            capability,
        ).json
    else:
        raw = cli.search(
            tenant_id,
            operation["payload"],
            session_id=session_id,
            capability=capability,
        )
    result = _require_mapping(raw, "search")
    raw_hits = result.get("hits")
    if raw_hits is None:
        hits: list[Mapping[str, Any]] = []
    elif not isinstance(raw_hits, list) or any(
        not isinstance(hit, Mapping) for hit in raw_hits
    ):
        raise ValueError("security-calibration search hits must be objects")
    else:
        hits = list(raw_hits)
    return {"confidence": _confidence(result.get("confidence")), "hits": hits}


def _answer(cli: Any, operation: Mapping[str, Any]) -> dict[str, Any]:
    context = {
        "capability_tags": [operation["capability"]],
        "role": _PROBE_ROLE,
        "tenant_id": operation["tenant_id"],
        "user_id": _PROBE_USER,
    }
    if isinstance(cli, MnemoCLI):
        flags = list(cli.global_flags)
        if "--evaluation-read-only" not in flags:
            flags.append("--evaluation-read-only")
        raw = replace(cli, global_flags=flags).answer(operation["payload"], context)
    else:
        raw = cli.answer(
            operation["payload"],
            context,
            capability=operation["capability"],
            session_id=operation["session_id"],
        )
    result = _require_mapping(raw, "answer")
    if result.get("abstained") is True:
        return {"answer": None, "abstained": True}
    answer = _answer_text(result)
    if answer is None:
        return {"answer": None, "abstained": True}
    return {"answer": answer, "abstained": False}


def _answer_text(result: Mapping[str, Any]) -> str | None:
    for key in ("answer", "answer_text", "response_text"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("security-calibration search must return a finite confidence")
    confidence = float(value)
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        raise ValueError("security-calibration search confidence must be in [0, 1]")
    return confidence


def _observation(
    case: Mapping[str, Any],
    recorded: Mapping[str, Mapping[str, Any]],
    hits: list[Mapping[str, Any]],
    confidence: float | None,
    answer_text: str | None,
    abstained: bool,
) -> dict[str, Any]:
    if confidence is None:
        raise ValueError("security-calibration case is missing SUT confidence")
    visible_tenants: set[str] = set()
    visible_sessions: set[str] = set()
    accessed_ids: set[str] = set()
    resurrected_ids: set[str] = set()
    provenance_ids: list[str] = []
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
        provenance = hit.get("provenance")
        if isinstance(provenance, list):
            provenance_ids.extend(
                value for value in provenance if isinstance(value, str) and value
            )
    if not visible_tenants:
        visible_tenants.add(case["tenant_id"])
    if not visible_sessions:
        visible_sessions.add(case["session_id"])
    answered = not abstained and answer_text is not None
    observation = {
        "accessed_ids": sorted(accessed_ids),
        "action": "answer" if answered else "abstain",
        "case_id": case["case_id"],
        "confidence": confidence,
        "mutation_targets": [],
        "provenance_ids": list(dict.fromkeys(provenance_ids)),
        "response_text": answer_text if answered else None,
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
