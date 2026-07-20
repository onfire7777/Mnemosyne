"""Signed-session translator from the public action seam to production intentions.

The public harness mints its own Mnemosyne session tokens exactly as an agent
host would — a client responsibility — and presents them through the public
``--session-token`` seam.  Minting is pure standard-library HMAC-SHA256 over the
canonical claim payload; it never imports a memory engine and reproduces
``mnemosyne.security.SessionTokenVerifier.sign`` byte-for-byte so the production
CLI verifies the token without any private coupling.

``ActionCLI`` translates the deterministic-action probe's symbolic seam
(``task.create``/``task.update``/``clock.inject``/``event.inject``/
``intention.query``/``action.select``) into authenticated production intention
subprocess commands (``intention-schedule``/``intention-update``/
``intention-cancel``/``intention-evaluate``).  It only ever returns the opaque
data-only action IDs the production evaluator fires; it never sees or forwards
fixture gold, and it never executes an observation payload — the narrative and
channel observations are treated as inert data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from eval.harness.cli_driver import MnemoCLI


# Deterministic HMAC secret the harness uses on both sides of the public seam:
# it signs the session token with this secret and hands the same secret to the
# CLI subprocess (via ``MNEMOSYNE_SESSION_SECRET``) so verification succeeds.
# It is not a production credential and never enters any bundle or trace.
SESSION_SECRET = "mnemosyne-public-eval-session-secret"

# TrustTier.DIRECT_USER (0) — the strongest first-party trust tier, accepted by
# every authenticated working-memory and prospective-memory write.
_DIRECT_USER_TRUST_TIER = 0

# Prospective-memory scheduling/evaluation requires an authenticated agent
# identity, and evaluation additionally requires this capability.
_PROSPECTIVE_ROLE = "operator"
_PROSPECTIVE_EVALUATE_CAPABILITY = "prospective:evaluate"
# Deterministic first-party principals the evaluator drives every case as; the
# per-scope token binds them to the case tenant/session, and they never surface
# in any trace or bundle (traces carry only opaque fixture action IDs).
_EVAL_USER_ID = "mnemosyne-public-eval-user"
_EVAL_AGENT_ID = "mnemosyne-public-eval-agent"
_EVAL_OPERATING_POINT_ID = "public-eval-action-v1"
_EVAL_THRESHOLD = 1.0


class ActionCLIError(RuntimeError):
    """The action seam received an unsupported or fail-closed request."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def mint_session_token(
    *,
    tenant_id: str,
    user_id: str,
    role: str,
    source_trust_tier: int = _DIRECT_USER_TRUST_TIER,
    agent_id: str | None = None,
    session_id: str | None = None,
    capabilities: Sequence[str] = (),
    secret: str = SESSION_SECRET,
) -> str:
    """Return a signed ``payload.signature`` Mnemosyne session token.

    The claim canonicalization (sorted keys, compact separators, optional agent,
    session, and capability fields) mirrors ``SessionIdentity.to_payload`` and
    ``SessionTokenVerifier.sign`` so a single shared secret verifies the token.
    """
    payload_data: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "source_trust_tier": source_trust_tier,
    }
    if agent_id:
        payload_data["agent_id"] = agent_id
    if session_id:
        payload_data["session_id"] = session_id
    if capabilities:
        payload_data["capabilities"] = list(capabilities)
    payload = _b64url(
        json.dumps(payload_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64url(
        hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{payload}.{signature}"


@dataclass
class _ScopeState:
    """Per-case authenticated session state keyed by the probe's store path."""

    cli: MnemoCLI
    tenant_id: str
    evidence_cid: str
    now: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    conditions: dict[str, dict[str, Any]] = field(default_factory=dict)
    intention_by_task: dict[str, str] = field(default_factory=dict)


class ActionCLI:
    """Translate the symbolic action seam into signed intention subprocesses.

    A single instance serves every case; state is partitioned by the per-case
    store path the probe threads through ``scope["store"]`` so tenant/session
    scopes never bleed across cases.
    """

    def __init__(self, mnemo: MnemoCLI) -> None:
        self._mnemo = mnemo
        self._scopes: dict[str, _ScopeState] = {}

    def run(self, command: str, *args: Mapping[str, Any]) -> dict[str, Any]:
        if not args or not isinstance(args[0], Mapping):
            raise ActionCLIError(f"{command} requires a scope mapping")
        scope = args[0]
        payload = args[1] if len(args) > 1 and isinstance(args[1], Mapping) else {}
        state = self._scope(scope)
        handler = {
            "task.create": self._task_create,
            "task.update": self._task_update,
            "clock.inject": self._clock_inject,
            "event.inject": self._event_inject,
            "intention.query": self._intention_query,
            "action.select": self._action_select,
        }.get(command)
        if handler is None:
            raise ActionCLIError(f"unsupported action command: {command}")
        return handler(state, payload)

    # ---- scope / session lifecycle -------------------------------------

    def _scope(self, scope: Mapping[str, Any]) -> _ScopeState:
        store = scope.get("store")
        tenant_id = scope.get("tenant_id")
        session_id = scope.get("session_id")
        if not isinstance(store, str) or not store:
            raise ActionCLIError("scope store path is required")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ActionCLIError("scope tenant_id is required")
        if not isinstance(session_id, str) or not session_id:
            raise ActionCLIError("scope session_id is required")
        existing = self._scopes.get(store)
        if existing is not None:
            if existing.tenant_id != tenant_id:
                raise ActionCLIError("scope store reused across tenants")
            return existing
        token = mint_session_token(
            tenant_id=tenant_id,
            user_id=_EVAL_USER_ID,
            agent_id=_EVAL_AGENT_ID,
            session_id=session_id,
            role=_PROSPECTIVE_ROLE,
            capabilities=(_PROSPECTIVE_EVALUATE_CAPABILITY,),
        )
        cli = replace(
            self._mnemo,
            store=store,
            global_flags=[*self._mnemo.global_flags, "--session-token", token],
            env={**self._mnemo.env, "MNEMOSYNE_SESSION_SECRET": SESSION_SECRET},
        )
        evidence_cid = self._capture_evidence(cli, tenant_id)
        state = _ScopeState(cli=cli, tenant_id=tenant_id, evidence_cid=evidence_cid)
        self._scopes[store] = state
        return state

    def _capture_evidence(self, cli: MnemoCLI, tenant_id: str) -> str:
        captured = cli.run(
            "capture",
            "--tenant", tenant_id,
            "--user", _EVAL_USER_ID,
            "--actor", "user",
            "--source-type", "public-action-probe",
            "--source-identity", "public-action-probe",
            "--content", "inert prospective-memory scheduling evidence",
        ).json
        cid = captured.get("cid") if isinstance(captured, Mapping) else None
        if not isinstance(cid, str) or not cid:
            raise ActionCLIError("capture omitted scheduling evidence CID")
        return cid

    # ---- symbolic command handlers -------------------------------------

    def _task_create(self, state: _ScopeState, task: Mapping[str, Any]) -> dict[str, Any]:
        task_id = _require_str(task.get("task_id"), "task_id")
        action_id = _require_str(task.get("action_id"), "action_id")
        trigger = task.get("trigger")
        if not isinstance(trigger, Mapping):
            raise ActionCLIError("task trigger is required")
        expression, due_at = _trigger_to_expression(trigger)
        dependency_args: list[str] = []
        for dependency in task.get("dependency_ids", []):
            intention_id = state.intention_by_task.get(dependency)
            if intention_id is None:
                raise ActionCLIError(f"dependency {dependency!r} scheduled out of order")
            dependency_args += ["--dependency", intention_id]
        result = state.cli.run(
            "intention-schedule",
            "--tenant", state.tenant_id,
            "--user", _EVAL_USER_ID,
            "--agent", _EVAL_AGENT_ID,
            "--trigger-type", trigger["type"],
            "--trigger-expression", _json(expression),
            "--action", _json({"ref": action_id}),
            "--due-at", due_at,
            "--evidence-cid", state.evidence_cid,
            *dependency_args,
        ).json
        intention_id = result.get("intention_id") if isinstance(result, Mapping) else None
        if not isinstance(intention_id, str) or not intention_id:
            raise ActionCLIError("intention-schedule omitted an intention id")
        state.intention_by_task[task_id] = intention_id
        return {}

    def _task_update(self, state: _ScopeState, update: Mapping[str, Any]) -> dict[str, Any]:
        update_type = update.get("type")
        task_id = _require_str(update.get("task_id"), "update task_id")
        intention_id = state.intention_by_task.get(task_id)
        if intention_id is None:
            raise ActionCLIError(f"update references unscheduled task {task_id!r}")
        if update_type == "cancel":
            state.cli.run(
                "intention-cancel",
                "--tenant", state.tenant_id,
                "--intention-id", intention_id,
            )
            return {}
        if update_type not in {"override", "reschedule"}:
            raise ActionCLIError(f"unsupported task.update type: {update_type!r}")
        args = [
            "intention-update",
            "--tenant", state.tenant_id,
            "--intention-id", intention_id,
            "--user", _EVAL_USER_ID,
            "--agent", _EVAL_AGENT_ID,
            "--action", _json({"ref": _require_str(update.get("action_id"), "action_id")}),
        ]
        if update_type == "reschedule":
            args += ["--due-at", _require_str(update.get("due_at"), "reschedule due_at")]
        state.cli.run(*args)
        return {}

    def _clock_inject(self, state: _ScopeState, payload: Mapping[str, Any]) -> dict[str, Any]:
        state.now = _require_str(payload.get("now"), "clock now")
        return {}

    def _event_inject(self, state: _ScopeState, event: Mapping[str, Any]) -> dict[str, Any]:
        kind = event.get("kind")
        if kind == "event":
            state.events.append(
                {
                    "event_id": _require_str(event.get("event_id"), "event_id"),
                    "event_type": _require_str(event.get("event_type"), "event_type"),
                    "occurred_at": _require_str(event.get("occurred_at"), "occurred_at"),
                    "payload": dict(event.get("payload", {})),
                    "confidence": float(event.get("confidence", _EVAL_THRESHOLD)),
                    "tenant_id": state.tenant_id,
                }
            )
        elif kind == "condition":
            state.conditions[_require_str(event.get("condition_id"), "condition_id")] = {
                "value": event.get("value"),
                "observed_at": _require_str(event.get("observed_at"), "observed_at"),
                "confidence": float(event.get("confidence", _EVAL_THRESHOLD)),
                "tenant_id": state.tenant_id,
            }
        # Any other observation kind is inert scene-setting and is never executed.
        return {}

    def _intention_query(
        self, state: _ScopeState, observations: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not state.now:
            raise ActionCLIError("intention.query requires an injected clock")
        trigger_context = {
            "infrastructure_available": True,
            "tenant_id": state.tenant_id,
            "events": state.events,
            "conditions": state.conditions,
        }
        operating_point = {
            "operating_point_id": _EVAL_OPERATING_POINT_ID,
            "threshold": _EVAL_THRESHOLD,
            "measured_precision": 1.0,
            "measured_recall": 1.0,
            "measurement_cid": state.evidence_cid,
        }
        result = state.cli.run(
            "intention-evaluate",
            "--tenant", state.tenant_id,
            "--evaluated-at", state.now,
            "--trigger-context", _json(trigger_context),
            "--operating-point", _json(operating_point),
        ).json
        fired = result.get("intentions") if isinstance(result, Mapping) else None
        if not isinstance(fired, list):
            raise ActionCLIError("intention-evaluate omitted fired intentions")
        action_ids = sorted({_fired_action_id(intention) for intention in fired})
        # Each intention fires once; per-step signals are consumed with it.
        state.events = []
        state.conditions = {}
        return {
            "action_ids": action_ids,
            "queried_channels": _channels(observations.get("channel_observations", [])),
        }

    def _action_select(self, state: _ScopeState, payload: Mapping[str, Any]) -> dict[str, Any]:
        del state
        available = {
            row.get("action_id")
            for row in payload.get("available_actions", [])
            if isinstance(row, Mapping)
        }
        candidates = payload.get("candidate_action_ids", [])
        if not isinstance(candidates, list):
            raise ActionCLIError("action.select candidate_action_ids must be a list")
        selected = sorted(set(candidates) & available)
        return {"action_ids": selected}


def _trigger_to_expression(trigger: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    trigger_type = trigger.get("type")
    payload = trigger.get("payload")
    if not isinstance(payload, Mapping) or not payload:
        raise ActionCLIError("trigger payload must be a non-empty object")
    if trigger_type == "exact_time":
        at = _require_str(payload.get("at"), "exact_time.at")
        return {"at": at}, at
    if trigger_type == "time_window":
        start = _require_str(payload.get("start"), "time_window.start")
        end = _require_str(payload.get("end"), "time_window.end")
        return {"start": start, "end": end}, start
    if trigger_type == "event":
        match = payload.get("match", {})
        if not isinstance(match, Mapping):
            raise ActionCLIError("event.match must be an object")
        return (
            {"event_type": _require_str(payload.get("event_type"), "event.event_type"), "match": dict(match)},
            _require_str(payload.get("due_at"), "event.due_at"),
        )
    if trigger_type == "condition":
        return (
            {
                "condition_id": _require_str(payload.get("condition_id"), "condition.condition_id"),
                "operator": _require_str(payload.get("operator"), "condition.operator"),
                "value": payload.get("value"),
            },
            _require_str(payload.get("due_at"), "condition.due_at"),
        )
    if trigger_type == "dependency_completion":
        return {"require": "all"}, _require_str(payload.get("due_at"), "dependency.due_at")
    raise ActionCLIError(f"unsupported trigger type: {trigger_type!r}")


def _fired_action_id(intention: Any) -> str:
    action = intention.get("action") if isinstance(intention, Mapping) else None
    ref = action.get("ref") if isinstance(action, Mapping) else None
    if not isinstance(ref, str) or not ref:
        raise ActionCLIError("fired intention omitted its opaque action reference")
    return ref


def _channels(observations: Any) -> list[str]:
    if not isinstance(observations, list):
        raise ActionCLIError("channel_observations must be a list")
    channels: set[str] = set()
    for row in observations:
        if not isinstance(row, Mapping) or "channel" not in row:
            raise ActionCLIError("channel observation must carry a channel id")
        channels.add(_require_str(row.get("channel"), "channel"))
    return sorted(channels)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActionCLIError(f"{name} must be a non-empty string")
    return value
