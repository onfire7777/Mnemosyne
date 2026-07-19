"""Local Mnemosyne engine implementation."""

from __future__ import annotations

import copy
import json
import math
import os
import secrets
import threading
import weakref
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from mnemosyne import text as text_kernels
from mnemosyne.access_policy import (
    VECTOR_PARTITION_PUBLIC,
    apply_relation_redactions,
    apply_statement_redactions,
    apply_text_redactions,
    effective_max_sensitivity,
    expiry_deadline,
    filter_export_for_context,
    may_embed_item,
    may_read_item,
    may_use_stored_embedding,
    merge_access_policies,
    validate_access_policy,
    vector_partition_for_item,
)
from mnemosyne.algorithms import fit_budget, mmr_select, ppr_power_iteration, rrf_fuse, u_curve_order
from mnemosyne.calibration import CalibrationSet
from mnemosyne.consciousness import RealityMonitor
from mnemosyne.ids import content_cid, evidence_cid, evidence_unscoped_cid, new_id
from mnemosyne.journal import CIDJournal, journal_filename
from mnemosyne.models import (
    Assertion,
    Contradiction,
    Evidence,
    Hit,
    Justification,
    MergeReport,
    Preference,
    Relation,
    RetrievalResult,
    utc_now,
)
from mnemosyne.pipeline import run_retrieval_pipeline
from mnemosyne.policy import OperatingPolicy
from mnemosyne.privacy import ErasureMode
from mnemosyne.retrieval import (
    HashingEmbeddingProvider,
    LocalSimilarityReranker,
    QUERY_SUPPORT_THRESHOLD,
    RetrievalAdapters,
    embed_query,
    is_retired_summary_metadata,
    query_support,
    validate_adapter_hit_scope,
    workspace_broadcast_from_context,
)
from mnemosyne.security import (
    TrustTier,
    assemble_system_prompt as assemble_guarded_system_prompt,
    is_write_tainted,
    more_trusted,
    sanitize_retrieved_text,
    trust_weight,
)
from mnemosyne.erasure_ids import (
    build_erasure_placeholder_map,
    erasure_deletion_record_id,
    redact_erased_cids,
)
from mnemosyne.standing import (
    standing,
    standing_abstention_report,
    standing_erasure_cascade_report,
    standing_observability_record,
)
from mnemosyne.text import cosine, lexical_score, tokenize
from mnemosyne.workspace import self_generation_budget_report


def _normalize_json_value(value: Any, *, path: str) -> Any:
    """Return a plain JSON value without invoking caller-defined copy hooks."""

    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain finite JSON numbers")
        return value
    if type(value) is list:
        return [
            _normalize_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} keys must be strings")
            normalized[key] = _normalize_json_value(item, path=f"{path}.{key}")
        return normalized
    raise ValueError(f"{path} must contain JSON data only")


_TRIGGER_TYPES: frozenset[str] = frozenset(
    {"exact_time", "time_window", "event", "condition", "dependency_completion"}
)

_CONDITION_OPERATORS: frozenset[str] = frozenset(
    {"eq", "ne", "lt", "lte", "gt", "gte", "in"}
)


def _parse_aware_iso(value: Any, *, field: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ProspectiveOperatingPoint:
    """A caller-supplied precision/recall operating point for trigger evaluation.

    There is no constructor, engine, CLI, or MCP default. A caller must supply
    this object on every evaluation; invalid or missing values fail before
    state mutation. The ``threshold`` gates event/condition signal confidence;
    deterministic time/dependency triggers do not trade correctness for
    threshold, but the supplied operating point is still recorded in the
    firing audit.
    """

    operating_point_id: str
    threshold: float
    measured_precision: float
    measured_recall: float
    measurement_cid: str

    def __post_init__(self) -> None:
        if type(self.operating_point_id) is not str or not self.operating_point_id.strip():
            raise ValueError("operating_point_id must be a non-empty string")
        if type(self.measurement_cid) is not str or not self.measurement_cid.strip():
            raise ValueError("measurement_cid must be a non-empty string")
        for name in ("threshold", "measured_precision", "measured_recall"):
            value = getattr(self, name)
            if type(value) is not float or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number expressed as float")
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operating_point_id": self.operating_point_id,
            "threshold": self.threshold,
            "measured_precision": self.measured_precision,
            "measured_recall": self.measured_recall,
            "measurement_cid": self.measurement_cid,
        }


@dataclass(slots=True)
class TriggerEvaluationContext:
    """A data-only, prevalidated context for evaluating due intentions.

    ``events`` is a sequence of JSON objects with ``event_id`` (non-empty,
    unique within context), ``event_type``, ``occurred_at`` (aware ISO-8601),
    ``payload`` (JSON object), and ``confidence`` in [0, 1].
    ``conditions`` maps ``condition_id`` to a JSON object with ``value``,
    ``observed_at`` (aware ISO-8601), and ``confidence`` in [0, 1].
    Malformed, naive-time, cross-tenant, or non-JSON input fails closed.
    """

    infrastructure_available: bool
    tenant_id: str
    events: list[dict[str, Any]]
    conditions: dict[str, dict[str, Any]]

    def __post_init__(self) -> None:
        if type(self.infrastructure_available) is not bool:
            raise ValueError("infrastructure_available must be a bool")
        if type(self.tenant_id) is not str or not self.tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        if type(self.events) is not list:
            raise ValueError("events must be a list of JSON objects")
        if type(self.conditions) is not dict:
            raise ValueError("conditions must be a mapping of condition_id -> JSON object")
        seen_event_ids: set[str] = set()
        normalized_events: list[dict[str, Any]] = []
        for index, event in enumerate(self.events):
            if type(event) is not dict:
                raise ValueError(f"events[{index}] must be a JSON object")
            event = _normalize_json_value(event, path=f"events[{index}]")
            unknown_keys = set(event) - {
                "event_id",
                "event_type",
                "occurred_at",
                "payload",
                "confidence",
                "tenant_id",
            }
            if unknown_keys:
                raise ValueError(
                    f"events[{index}] contains unknown keys: {sorted(unknown_keys)}"
                )
            event_id = event.get("event_id")
            if type(event_id) is not str or not event_id.strip():
                raise ValueError(f"events[{index}].event_id must be a non-empty string")
            if event_id in seen_event_ids:
                raise ValueError(f"events[{index}].event_id must be unique within context")
            seen_event_ids.add(event_id)
            event_tenant_id = event.get("tenant_id")
            if type(event_tenant_id) is not str or not event_tenant_id.strip():
                raise ValueError(f"events[{index}].tenant_id must be a non-empty string")
            if event_tenant_id != self.tenant_id:
                raise ValueError(f"events[{index}].tenant_id must match context tenant_id")
            event["tenant_id"] = event_tenant_id
            event_type = event.get("event_type")
            if type(event_type) is not str or not event_type.strip():
                raise ValueError(f"events[{index}].event_type must be a non-empty string")
            occurred_at = event.get("occurred_at")
            if type(occurred_at) is not str:
                raise ValueError(f"events[{index}].occurred_at must be an ISO-8601 string")
            try:
                parsed = datetime.fromisoformat(occurred_at)
            except ValueError as exc:
                raise ValueError(f"events[{index}].occurred_at must be ISO-8601") from exc
            if parsed.tzinfo is None:
                raise ValueError(f"events[{index}].occurred_at must be timezone-aware")
            event["occurred_at"] = parsed.astimezone(UTC).isoformat()
            payload = event.get("payload")
            if type(payload) is not dict:
                raise ValueError(f"events[{index}].payload must be a JSON object")
            payload_tenant_id = payload.get("tenant_id")
            if payload_tenant_id is not None and payload_tenant_id != self.tenant_id:
                raise ValueError(f"events[{index}].payload tenant_id must match context tenant_id")
            event["payload"] = _normalize_json_value(payload, path=f"events[{index}].payload")
            confidence = event.get("confidence")
            if type(confidence) not in {int, float} or not math.isfinite(float(confidence)):
                raise ValueError(f"events[{index}].confidence must be a finite number")
            if not (0.0 <= float(confidence) <= 1.0):
                raise ValueError(f"events[{index}].confidence must be in [0, 1]")
            event["confidence"] = float(confidence)
            normalized_events.append(event)
        self.events = normalized_events
        normalized_conditions: dict[str, dict[str, Any]] = {}
        for condition_id, observation in self.conditions.items():
            if type(condition_id) is not str or not condition_id.strip():
                raise ValueError("conditions keys must be non-empty strings")
            if type(observation) is not dict:
                raise ValueError(f"conditions[{condition_id}] must be a JSON object")
            observation = _normalize_json_value(
                observation, path=f"conditions[{condition_id}]"
            )
            unknown_keys = set(observation) - {"value", "observed_at", "confidence", "tenant_id"}
            if unknown_keys:
                raise ValueError(
                    f"conditions[{condition_id}] contains unknown keys: "
                    f"{sorted(unknown_keys)}"
                )
            if "value" not in observation:
                raise ValueError(f"conditions[{condition_id}].value is required")
            observation_tenant_id = observation.get("tenant_id")
            if type(observation_tenant_id) is not str or not observation_tenant_id.strip():
                raise ValueError(f"conditions[{condition_id}].tenant_id must be a non-empty string")
            if observation_tenant_id != self.tenant_id:
                raise ValueError(f"conditions[{condition_id}].tenant_id must match context tenant_id")
            observation["tenant_id"] = observation_tenant_id
            observed_at = observation.get("observed_at")
            if type(observed_at) is not str:
                raise ValueError(
                    f"conditions[{condition_id}].observed_at must be an ISO-8601 string"
                )
            try:
                parsed = datetime.fromisoformat(observed_at)
            except ValueError as exc:
                raise ValueError(
                    f"conditions[{condition_id}].observed_at must be ISO-8601"
                ) from exc
            if parsed.tzinfo is None:
                raise ValueError(
                    f"conditions[{condition_id}].observed_at must be timezone-aware"
                )
            observation["observed_at"] = parsed.astimezone(UTC).isoformat()
            confidence = observation.get("confidence")
            if type(confidence) not in {int, float} or not math.isfinite(float(confidence)):
                raise ValueError(
                    f"conditions[{condition_id}].confidence must be a finite number"
                )
            if not (0.0 <= float(confidence) <= 1.0):
                raise ValueError(f"conditions[{condition_id}].confidence must be in [0, 1]")
            observation["confidence"] = float(confidence)
            normalized_conditions[condition_id] = observation
        self.conditions = normalized_conditions


@dataclass(slots=True)
class Intention:
    """A data-only prospective-memory record evaluated by an explicit clock."""

    intention_id: str
    tenant_id: str
    user_id: str
    agent_id: str
    trigger_type: str
    trigger_expression: dict[str, Any]
    action: dict[str, Any]
    due_at: datetime
    status: str = "scheduled"
    priority: str = "normal"
    dependencies: list[str] = field(default_factory=list)
    reschedule_history: list[dict[str, Any]] = field(default_factory=list)
    cancellation_state: dict[str, Any] | None = None
    evidence_ids: list[str] = field(default_factory=list)
    session_id: str | None = None
    recurrence_policy: dict[str, Any] = field(default_factory=lambda: {"type": "none"})
    recurrence_state: dict[str, Any] = field(default_factory=lambda: {"occurrence": 0})

    def __post_init__(self) -> None:
        for name in ("intention_id", "tenant_id", "user_id", "agent_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.trigger_type) is not str or self.trigger_type not in _TRIGGER_TYPES:
            raise ValueError(
                f"trigger_type must be one of {sorted(_TRIGGER_TYPES)}"
            )
        if type(self.status) is not str or self.status != "scheduled":
            raise ValueError("new intentions must be scheduled")
        if type(self.priority) is not str or not self.priority.strip():
            raise ValueError("priority must be a non-empty string")
        if not isinstance(self.due_at, datetime) or self.due_at.tzinfo is None:
            raise ValueError("due_at must be timezone-aware")
        if type(self.trigger_expression) is not dict:
            raise ValueError("trigger_expression must be a JSON object")
        if type(self.action) is not dict:
            raise ValueError("action must be a JSON object")
        self.trigger_expression = _normalize_json_value(
            self.trigger_expression, path="trigger_expression"
        )
        self.action = _normalize_json_value(self.action, path="action")
        due_at = self.due_at.astimezone(UTC)
        self.due_at = due_at
        self._validate_trigger_expression(due_at)
        if type(self.dependencies) is not list or any(
            type(item) is not str or not item.strip() for item in self.dependencies
        ):
            raise ValueError("dependencies must be a list of non-empty strings")
        if self.dependencies and self.trigger_type != "dependency_completion":
            raise ValueError(
                "dependencies are only valid for dependency_completion triggers"
            )
        if self.trigger_type == "dependency_completion":
            if not self.dependencies:
                raise ValueError(
                    "dependency_completion trigger requires non-empty dependencies"
                )
            if len(set(self.dependencies)) != len(self.dependencies):
                raise ValueError("dependencies must not contain duplicates")
            if self.intention_id in self.dependencies:
                raise ValueError("an intention cannot depend on itself")
        if type(self.reschedule_history) is not list:
            raise ValueError("reschedule_history must be a list of JSON objects")
        normalized_history: list[dict[str, Any]] = []
        for index, item in enumerate(self.reschedule_history):
            if type(item) is not dict:
                raise ValueError("reschedule_history must be a list of JSON objects")
            normalized_history.append(
                _normalize_json_value(item, path=f"reschedule_history[{index}]")
            )
        self.reschedule_history = normalized_history
        if self.cancellation_state is not None:
            raise ValueError("new scheduled intentions cannot have cancellation state")
        if type(self.evidence_ids) is not list or not self.evidence_ids:
            raise ValueError("evidence_ids must contain originating evidence")
        if any(type(item) is not str or not item.strip() for item in self.evidence_ids):
            raise ValueError("evidence_ids must contain non-empty strings")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must not contain duplicates")
        if self.session_id is not None and (
            type(self.session_id) is not str or not self.session_id.strip()
        ):
            raise ValueError("session_id must be a non-empty string when provided")
        self.recurrence_policy = _normalize_recurrence_policy(self.recurrence_policy)
        self.recurrence_state = _normalize_recurrence_state(self.recurrence_state)

    def _validate_trigger_expression(self, due_at: datetime) -> None:
        expr = self.trigger_expression
        if self.trigger_type == "exact_time":
            at_raw = expr.get("at")
            if type(at_raw) is not str:
                raise ValueError(
                    "exact_time trigger_expression.at must be an ISO-8601 string"
                )
            trigger_at = _parse_aware_iso(at_raw, field="exact_time.at")
            if trigger_at != due_at:
                raise ValueError(
                    "trigger_expression.at must identify the same instant as due_at"
                )
            self.trigger_expression["at"] = due_at.isoformat()
        elif self.trigger_type == "time_window":
            start_raw = expr.get("start")
            end_raw = expr.get("end")
            if type(start_raw) is not str:
                raise ValueError(
                    "time_window trigger_expression.start must be an ISO-8601 string"
                )
            if type(end_raw) is not str:
                raise ValueError(
                    "time_window trigger_expression.end must be an ISO-8601 string"
                )
            start = _parse_aware_iso(start_raw, field="time_window.start")
            end = _parse_aware_iso(end_raw, field="time_window.end")
            if start >= end:
                raise ValueError("time_window start must precede end")
            if start != due_at:
                raise ValueError(
                    "time_window.start must identify the same instant as due_at"
                )
            self.trigger_expression["start"] = start.isoformat()
            self.trigger_expression["end"] = end.isoformat()
        elif self.trigger_type == "event":
            event_type = expr.get("event_type")
            if type(event_type) is not str or not event_type.strip():
                raise ValueError(
                    "event trigger_expression.event_type must be a non-empty string"
                )
            if "match" not in expr:
                raise ValueError("event trigger_expression.match is required")
            match = expr["match"]
            if type(match) is not dict:
                raise ValueError("event trigger_expression.match must be a JSON object")
        elif self.trigger_type == "condition":
            condition_id = expr.get("condition_id")
            if type(condition_id) is not str or not condition_id.strip():
                raise ValueError(
                    "condition trigger_expression.condition_id must be a non-empty string"
                )
            operator = expr.get("operator")
            if type(operator) is not str or operator not in _CONDITION_OPERATORS:
                raise ValueError(
                    f"condition trigger_expression.operator must be one of "
                    f"{sorted(_CONDITION_OPERATORS)}"
                )
            if "value" not in expr:
                raise ValueError("condition trigger_expression.value is required")
        elif self.trigger_type == "dependency_completion":
            require = expr.get("require")
            if require != "all":
                raise ValueError(
                    "dependency_completion trigger_expression.require must be 'all'"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "intention_id": self.intention_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "trigger_type": self.trigger_type,
            "trigger_expression": copy.deepcopy(self.trigger_expression),
            "action": copy.deepcopy(self.action),
            "due_at": self.due_at.isoformat(),
            "status": self.status,
            "priority": self.priority,
            "dependencies": list(self.dependencies),
            "reschedule_history": copy.deepcopy(self.reschedule_history),
            "cancellation_state": copy.deepcopy(self.cancellation_state),
            "evidence_ids": list(self.evidence_ids),
            "session_id": self.session_id,
            "recurrence_policy": copy.deepcopy(self.recurrence_policy),
            "recurrence_state": copy.deepcopy(self.recurrence_state),
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> Intention:
        if type(row) is not dict:
            raise ValueError("stored intention must be a JSON object")
        status = row.get("status", "scheduled")
        if type(status) is not str or status not in {"scheduled", "cancelled", "fired"}:
            raise ValueError(f"unsupported stored intention status: {status!r}")
        due_at = row.get("due_at")
        if type(due_at) is not str:
            raise ValueError("stored intention due_at must be an ISO-8601 string")
        dependencies = row.get("dependencies", [])
        reschedule_history = row.get("reschedule_history", [])
        evidence_ids = row.get("evidence_ids", [])
        if type(dependencies) is not list:
            raise ValueError("stored intention dependencies must be a list")
        if type(reschedule_history) is not list:
            raise ValueError("stored intention reschedule_history must be a list")
        if type(evidence_ids) is not list:
            raise ValueError("stored intention evidence_ids must be a list")
        cancellation_state = copy.deepcopy(row.get("cancellation_state"))
        record = cls(
            intention_id=row["intention_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            trigger_type=row["trigger_type"],
            trigger_expression=copy.deepcopy(row["trigger_expression"]),
            action=copy.deepcopy(row["action"]),
            due_at=datetime.fromisoformat(due_at),
            status="scheduled",
            priority=row.get("priority", "normal"),
            dependencies=copy.deepcopy(dependencies),
            reschedule_history=copy.deepcopy(reschedule_history),
            cancellation_state=None,
            evidence_ids=copy.deepcopy(evidence_ids),
            session_id=row.get("session_id"),
            recurrence_policy=copy.deepcopy(row.get("recurrence_policy", {"type": "none"})),
            recurrence_state=copy.deepcopy(row.get("recurrence_state", {"occurrence": 0})),
        )
        record.status = status
        if status == "cancelled":
            if type(cancellation_state) is not dict:
                raise ValueError("cancelled intentions require cancellation state")
            record.cancellation_state = _normalize_json_value(
                cancellation_state, path="cancellation_state"
            )
            cancelled_by = record.cancellation_state.get("cancelled_by")
            if (
                type(cancelled_by) is not str
                or not cancelled_by.strip()
                or cancelled_by not in {record.user_id, record.agent_id}
            ):
                raise ValueError(
                    "cancelled intention state must identify its owning user or agent"
                )
        elif cancellation_state is not None:
            raise ValueError("only cancelled intentions may carry cancellation state")
        return record


def _normalize_recurrence_policy(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("recurrence_policy must be a JSON object")
    normalized = _normalize_json_value(value, path="recurrence_policy")
    recurrence_type = normalized.get("type", "none")
    if recurrence_type == "none":
        if set(normalized) - {"type"}:
            raise ValueError("non-recurring policy only accepts type")
        return {"type": "none"}
    if recurrence_type != "interval":
        raise ValueError("recurrence_policy.type must be 'none' or 'interval'")
    seconds = normalized.get("interval_seconds")
    if type(seconds) is not int or seconds <= 0:
        raise ValueError("recurrence_policy.interval_seconds must be a positive integer")
    maximum = normalized.get("max_occurrences")
    if maximum is not None and (type(maximum) is not int or maximum <= 0):
        raise ValueError("recurrence_policy.max_occurrences must be a positive integer")
    if set(normalized) - {"type", "interval_seconds", "max_occurrences"}:
        raise ValueError("recurrence_policy contains unsupported fields")
    return normalized


def _normalize_recurrence_state(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"occurrence"}:
        raise ValueError("recurrence_state must contain only occurrence")
    occurrence = value.get("occurrence")
    if type(occurrence) is not int or occurrence < 0:
        raise ValueError("recurrence_state.occurrence must be a non-negative integer")
    return {"occurrence": occurrence}


def _updated_intention(
    current: Intention,
    *,
    user_id: str,
    agent_id: str,
    session_id: str,
    due_at: datetime | None,
    action: dict[str, Any] | None,
    recurrence_policy: dict[str, Any] | None,
) -> Intention:
    """Validate and build one detached scheduled-intention mutation."""
    if current.status != "scheduled":
        raise ValueError("only scheduled intentions may be updated")
    if user_id != current.user_id or agent_id != current.agent_id:
        raise PermissionError("only the owning user and agent may update an intention")
    if type(session_id) is not str or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if current.session_id is not None and session_id != current.session_id:
        raise PermissionError("intention session does not match authenticated session")
    if due_at is None and action is None and recurrence_policy is None:
        raise ValueError("an intention update requires at least one change")
    if due_at is not None and (not isinstance(due_at, datetime) or due_at.tzinfo is None):
        raise ValueError("due_at must be timezone-aware")
    if action is not None and type(action) is not dict:
        raise ValueError("action must be a JSON object")
    row = current.to_dict()
    row["status"] = "scheduled"
    row["session_id"] = session_id
    if due_at is not None:
        normalized_due = due_at.astimezone(UTC)
        row["reschedule_history"] = [
            *current.reschedule_history,
            {"from": current.due_at.isoformat(), "to": normalized_due.isoformat()},
        ]
        row["due_at"] = normalized_due.isoformat()
        if current.trigger_type == "exact_time":
            row["trigger_expression"]["at"] = normalized_due.isoformat()
        elif current.trigger_type == "time_window":
            old_end = _parse_aware_iso(
                current.trigger_expression["end"], field="time_window.end"
            )
            duration = old_end - current.due_at
            row["trigger_expression"]["start"] = normalized_due.isoformat()
            row["trigger_expression"]["end"] = (normalized_due + duration).isoformat()
    if action is not None:
        row["action"] = copy.deepcopy(action)
    if recurrence_policy is not None:
        row["recurrence_policy"] = copy.deepcopy(recurrence_policy)
    return Intention.from_dict(row)


def _json_deep_contains(haystack: Any, needle: Any) -> bool:
    """Return True if ``haystack`` deeply equals ``needle`` for every key in needle."""
    if type(needle) is dict:
        if type(haystack) is not dict:
            return False
        for key, value in needle.items():
            if key not in haystack or not _json_deep_contains(haystack[key], value):
                return False
        return True
    if type(needle) is list:
        if type(haystack) is not list:
            return False
        return len(needle) == len(haystack) and all(
            _json_deep_contains(haystack[i], needle[i]) for i in range(len(needle))
        )
    return type(haystack) is type(needle) and haystack == needle
_WORKING_MEMORY_KINDS = {
    "active_goal",
    "current_plan",
    "active_constraint",
    "constraint",
    "unresolved_question",
    "tool_result",
    "recent_tool_result",
    "intermediate_conclusion",
}


@dataclass(slots=True)
class WorkingMemoryItem:
    """A bounded, data-only item in the local working-memory plane."""

    item_id: str
    tenant_id: str
    session_id: str
    user_id: str
    agent_id: str
    kind: str
    task_id: str
    content: str
    created_at: datetime
    expires_at: datetime
    evidence_ids: list[str]
    trust_tier: int = 0
    access_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    capability_tags: list[str] = field(default_factory=list)
    sensitivity: int = 0
    # Lifecycle state is intentionally excluded from value identity: callers
    # can retain the item submitted to put_working while expiry returns its
    # transitioned detached copy.
    status: Literal["active", "expired"] = field(default="active", compare=False)
    expired_at: datetime | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "item_id",
            "tenant_id",
            "session_id",
            "user_id",
            "agent_id",
            "task_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.kind) is not str or self.kind not in _WORKING_MEMORY_KINDS:
            raise ValueError(f"unsupported working-memory kind: {self.kind!r}")
        if type(self.content) is not str or not self.content.strip():
            raise ValueError("content must be a non-empty string")
        for name in ("created_at", "expires_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        created_at = self.created_at.astimezone(UTC)
        expires_at = self.expires_at.astimezone(UTC)
        if expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")
        if expires_at - created_at > timedelta(hours=24):
            raise ValueError("working-memory TTL must not exceed 24 hours")
        self.created_at = created_at
        self.expires_at = expires_at

        if type(self.evidence_ids) is not list or not self.evidence_ids:
            raise ValueError("evidence_ids must contain originating evidence")
        if any(type(item) is not str or not item.strip() for item in self.evidence_ids):
            raise ValueError("evidence_ids must contain non-empty strings")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must not contain duplicates")
        if type(self.trust_tier) is not int or isinstance(self.trust_tier, bool):
            raise ValueError("trust_tier must be an integer")
        if not int(TrustTier.DIRECT_USER) <= self.trust_tier <= int(TrustTier.UNTRUSTED_EXTERNAL):
            raise ValueError("trust_tier is out of range")
        for name in ("access_policy", "metadata"):
            value = getattr(self, name)
            if type(value) is not dict:
                raise ValueError(f"{name} must be a JSON object")
            setattr(self, name, _normalize_json_value(value, path=name))
        self.access_policy = validate_access_policy(
            self.access_policy,
            tenant_id=self.tenant_id,
            location="working_memory.access_policy",
        )
        if type(self.capability_tags) is not list or any(
            type(tag) is not str or not tag.strip() for tag in self.capability_tags
        ):
            raise ValueError("capability_tags must be a list of non-empty strings")
        if len(set(self.capability_tags)) != len(self.capability_tags):
            raise ValueError("capability_tags must not contain duplicates")
        if type(self.sensitivity) is not int or isinstance(self.sensitivity, bool):
            raise ValueError("sensitivity must be an integer")
        if self.sensitivity < 0:
            raise ValueError("sensitivity must not be negative")
        if self.status not in {"active", "expired"}:
            raise ValueError("status must be active or expired")
        if self.expired_at is not None:
            if not isinstance(self.expired_at, datetime) or self.expired_at.tzinfo is None:
                raise ValueError("expired_at must be timezone-aware")
            self.expired_at = self.expired_at.astimezone(UTC)
        if self.status == "active" and self.expired_at is not None:
            raise ValueError("active working-memory items cannot have expired_at")
        if self.status == "expired" and self.expired_at is None:
            raise ValueError("expired working-memory items require expired_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "task_id": self.task_id,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "evidence_ids": list(self.evidence_ids),
            "trust_tier": self.trust_tier,
            "access_policy": copy.deepcopy(self.access_policy),
            "metadata": copy.deepcopy(self.metadata),
            "capability_tags": list(self.capability_tags),
            "sensitivity": self.sensitivity,
            "status": self.status,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "WorkingMemoryItem":
        if type(row) is not dict:
            raise ValueError("stored working-memory item must be a JSON object")
        parsed = copy.deepcopy(row)
        for name in ("created_at", "expires_at", "expired_at"):
            value = parsed.get(name)
            if value is not None:
                if type(value) is not str:
                    raise ValueError(f"stored working-memory {name} must be ISO-8601")
                try:
                    parsed[name] = datetime.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(
                        f"stored working-memory {name} must be ISO-8601"
                    ) from exc
        return cls(**parsed)


def _compare_condition(
    observed: Any, operator: str, expected: Any
) -> bool:
    """Typed deterministic comparison for condition triggers."""
    if operator == "eq":
        return type(observed) is type(expected) and observed == expected
    if operator == "ne":
        return not (type(observed) is type(expected) and observed == expected)
    if operator == "in":
        if type(expected) is not list:
            raise ValueError("condition 'in' operator requires a JSON-list value")
        return any(
            type(observed) is type(item) and observed == item for item in expected
        )
    if operator in {"lt", "lte", "gt", "gte"}:
        if type(observed) not in {int, float, str} or type(expected) not in {
            int,
            float,
            str,
        }:
            raise ValueError(
                f"condition {operator} operator requires same-type finite numbers or strings"
            )
        if type(observed) is not type(expected):
            raise ValueError(
                f"condition {operator} operator requires same-type operands"
            )
        if type(observed) in {int, float}:
            if not math.isfinite(float(observed)) or not math.isfinite(float(expected)):
                raise ValueError(
                    f"condition {operator} operator requires finite numbers"
                )
        if operator == "lt":
            return observed < expected
        if operator == "lte":
            return observed <= expected
        if operator == "gt":
            return observed > expected
        return observed >= expected
    raise ValueError(f"unsupported condition operator: {operator!r}")


def _evaluate_trigger(
    intention: Intention,
    *,
    evaluated_at: datetime,
    context: TriggerEvaluationContext,
    operating_point: ProspectiveOperatingPoint,
    tenant_intentions: dict[tuple[str, str], Intention],
) -> tuple[bool, dict[str, Any]]:
    """Return (fires, matched_signal) for a single intention.

    ``matched_signal`` carries ``event_id`` or ``condition_id`` when applicable.
    Raises ``ValueError`` if a due candidate's trigger inputs are malformed
    (fail-closed before any state mutation).
    """
    expr = intention.trigger_expression
    evaluated_utc = evaluated_at.astimezone(UTC)
    due_utc = intention.due_at.astimezone(UTC)

    if intention.trigger_type == "exact_time":
        at = _parse_aware_iso(expr["at"], field="exact_time.at")
        fires = evaluated_utc >= at
        return fires, {}

    if intention.trigger_type == "time_window":
        start = _parse_aware_iso(expr["start"], field="time_window.start")
        end = _parse_aware_iso(expr["end"], field="time_window.end")
        fires = start <= evaluated_utc < end
        return fires, {}

    if intention.trigger_type == "event":
        event_type = expr["event_type"]
        match = expr.get("match", {})
        threshold = operating_point.threshold
        candidates = []
        for event in context.events:
            if event["event_type"] != event_type:
                continue
            if event["confidence"] < threshold:
                continue
            occurred = _parse_aware_iso(
                event["occurred_at"], field="event.occurred_at"
            )
            if not (due_utc <= occurred <= evaluated_utc):
                continue
            payload = event.get("payload", {})
            if not _json_deep_contains(payload, match):
                continue
            candidates.append(event)
        if not candidates:
            return False, {}
        canonical = min(
            candidates,
            key=lambda e: (
                _parse_aware_iso(e["occurred_at"], field="event.occurred_at"),
                e["event_id"],
            ),
        )
        return True, {"event_id": canonical["event_id"]}

    if intention.trigger_type == "condition":
        condition_id = expr["condition_id"]
        operator = expr["operator"]
        expected = expr["value"]
        observation = context.conditions.get(condition_id)
        if observation is None:
            return False, {}
        if observation["confidence"] < operating_point.threshold:
            return False, {}
        observed_at = _parse_aware_iso(
            observation["observed_at"], field="condition.observed_at"
        )
        if not (due_utc <= observed_at <= evaluated_utc):
            return False, {}
        if _compare_condition(observation["value"], operator, expected):
            return True, {"condition_id": condition_id}
        return False, {}

    if intention.trigger_type == "dependency_completion":
        for dep_id in intention.dependencies:
            dep = tenant_intentions.get((intention.tenant_id, dep_id))
            if dep is None:
                raise ValueError(
                    f"dependency {dep_id!r} is missing or cross-tenant"
                )
            if dep.status != "fired":
                return False, {}
        fires = evaluated_utc >= due_utc
        return fires, {}

    raise ValueError(f"unsupported trigger_type: {intention.trigger_type!r}")


def canonicalize_intention(
    intention: Intention, *, require_scheduled: bool = False
) -> Intention:
    """Return the canonical, detached representation used by every backend."""

    if not isinstance(intention, Intention):
        raise ValueError("intention must be an Intention")
    normalized = Intention.from_dict(intention.to_dict())
    if require_scheduled and normalized.status != "scheduled":
        raise ValueError("only scheduled intentions may be persisted")
    return normalized


def validate_intention_provenance_claim(
    intention: Intention,
    *,
    evidence_id: str,
    user_id: str,
    erased: bool,
    trust_tier: int,
    capability_tags: list[str],
    max_trust_tier: int,
) -> None:
    """Apply the canonical provenance and write-capability checks."""

    if erased or evidence_id not in intention.evidence_ids:
        raise ValueError(
            f"evidence {evidence_id!r} is missing or outside the intention tenant"
        )
    if user_id != intention.user_id:
        raise ValueError("intention user must match originating evidence")
    if trust_tier > max_trust_tier:
        raise PermissionError("originating evidence exceeds the write trust ceiling")
    if is_write_tainted(capability_tags):
        raise PermissionError("data-only evidence cannot authorize an intention write")


def intention_audit_context(provenance: list[Evidence | dict[str, Any]]) -> tuple[int, list[str]]:
    """Build the canonical trust and capability context for an audit row."""

    def field(source: Evidence | dict[str, Any], name: str) -> Any:
        return getattr(source, name) if isinstance(source, Evidence) else source[name]

    trust_tier = max(int(field(item, "trust_tier")) for item in provenance)
    capability_tags = sorted(
        {tag for item in provenance for tag in field(item, "capability_tags")}
    )
    return trust_tier, capability_tags


def intention_audit_diff(intention: Intention, *, status: str) -> dict[str, Any]:
    """Build the canonical immutable intention audit payload."""

    immutable_snapshot = {
        "intention_id": intention.intention_id,
        "tenant_id": intention.tenant_id,
        "user_id": intention.user_id,
        "agent_id": intention.agent_id,
        "trigger_type": intention.trigger_type,
        "trigger_expression": intention.trigger_expression,
        "action": intention.action,
        "priority": intention.priority,
        "due_at": intention.due_at.isoformat(),
        "dependencies": intention.dependencies,
        "reschedule_history": intention.reschedule_history,
        "evidence_ids": intention.evidence_ids,
    }
    return {
        "intention_digest": content_cid("prospective_intention", immutable_snapshot),
        "trigger_type": intention.trigger_type,
        "due_at": intention.due_at.isoformat(),
        "evidence_ids": list(intention.evidence_ids),
        "status": status,
    }


def intention_fire_receipt_id(tenant_id: str, intention_id: str) -> str:
    """Return the single canonical identity for a logical fire transition."""

    return content_cid(
        "fire_intention",
        {"tenant_id": tenant_id, "intention_id": intention_id, "op": "fire"},
    )


def validate_intention_dependencies(
    intention: Intention,
    tenant_intentions: dict[tuple[str, str], Intention],
) -> None:
    """Validate tenant-local dependencies and reject transitive cycles."""

    for dependency_id in intention.dependencies:
        if (intention.tenant_id, dependency_id) not in tenant_intentions:
            raise ValueError(f"dependency {dependency_id!r} is missing or cross-tenant")
    if intention.trigger_type != "dependency_completion":
        return
    pending = list(intention.dependencies)
    visited: set[str] = set()
    while pending:
        dependency_id = pending.pop()
        if dependency_id == intention.intention_id:
            raise ValueError("dependency cycle detected involving the new intention")
        if dependency_id in visited:
            continue
        visited.add(dependency_id)
        dependency = tenant_intentions.get((intention.tenant_id, dependency_id))
        if dependency is not None and dependency.trigger_type == "dependency_completion":
            pending.extend(dependency.dependencies)


def validate_intention_evaluation_inputs(
    tenant_id: str,
    *,
    evaluated_at: datetime,
    trigger_context: TriggerEvaluationContext,
    operating_point: ProspectiveOperatingPoint,
    infrastructure_error: str = "evaluate_due_intentions requires infrastructure_available=True",
) -> datetime:
    """Validate shared evaluator inputs and return a UTC evaluation instant."""

    if type(tenant_id) is not str or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    if not isinstance(evaluated_at, datetime) or evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if not isinstance(trigger_context, TriggerEvaluationContext):
        raise ValueError("trigger_context must be a TriggerEvaluationContext")
    if trigger_context.tenant_id != tenant_id:
        raise ValueError("trigger_context tenant_id must match tenant_id")
    if not isinstance(operating_point, ProspectiveOperatingPoint):
        raise ValueError("operating_point must be a ProspectiveOperatingPoint")
    if not trigger_context.infrastructure_available:
        raise RuntimeError(infrastructure_error)
    return evaluated_at.astimezone(UTC)


def _bounded_float(value: object, *, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _normalise_privacy_tags(pii_tags: list[str]) -> list[str]:
    return sorted({str(tag).strip().lower() for tag in pii_tags if str(tag).strip()})


def _int_or_default(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _relation_windows_overlap(left: Relation, right: Relation) -> bool:
    """Return whether two half-open relation validity windows overlap."""

    return (left.valid_to is None or right.valid_from < left.valid_to) and (
        right.valid_to is None or left.valid_from < right.valid_to
    )


def _merge_relation_state(target: Relation, incoming: Relation) -> None:
    """Reinforce one overlapping semantic relation without widening policy."""

    target.confidence = max(target.confidence, incoming.confidence)
    target.valid_from = min(target.valid_from, incoming.valid_from)
    target.valid_to = (
        None
        if target.valid_to is None or incoming.valid_to is None
        else max(target.valid_to, incoming.valid_to)
    )
    target.source_evidence_cids = sorted(
        set(target.source_evidence_cids + incoming.source_evidence_cids)
    )
    target.access_policy = merge_access_policies(
        [target.access_policy, incoming.access_policy],
        tenant_id=target.tenant_id,
    )


def _merge_relation_overlap_component(
    incoming: Relation,
    peers: list[Relation],
) -> tuple[Relation | None, list[Relation]]:
    """Fold every transitively overlapping peer into one deterministic winner."""

    remaining = sorted(peers, key=lambda item: (item.valid_from, item.id))
    component: list[Relation] = []
    expanded = copy.deepcopy(incoming)
    while remaining:
        pending: list[Relation] = []
        matched = False
        for peer in remaining:
            if _relation_windows_overlap(peer, expanded):
                _merge_relation_state(expanded, peer)
                component.append(peer)
                matched = True
            else:
                pending.append(peer)
        if not matched:
            break
        remaining = pending
    if not component:
        return None, []

    winner = min(component, key=lambda item: (item.valid_from, item.id))
    for peer in component:
        if peer is not winner:
            _merge_relation_state(winner, peer)
    _merge_relation_state(winner, incoming)
    return winner, [peer for peer in component if peer is not winner]


def _privacy_backfill_access_policy(
    access_policy: dict[str, Any],
    *,
    tenant_id: str,
    pii_tags: list[str],
    target_sensitivity: int,
) -> dict[str, Any]:
    policy = dict(access_policy or {})
    if pii_tags:
        policy["data_class"] = "pii"
        policy["max_sensitivity"] = max(
            _int_or_default(policy.get("max_sensitivity"), default=target_sensitivity),
            target_sensitivity,
        )
    return validate_access_policy(policy, tenant_id=tenant_id, location="evidence.access_policy")


def _privacy_backfill_metadata(
    metadata: dict[str, Any],
    *,
    access_policy: dict[str, Any],
    pii_tags: list[str],
    embedding_partition: str,
) -> dict[str, Any]:
    updated = dict(metadata or {})
    privacy = updated.get("privacy") if isinstance(updated.get("privacy"), dict) else {}
    updated["privacy"] = {
        **dict(privacy),
        "pii_tags": pii_tags,
        "residency": privacy.get("residency") or access_policy.get("residency") or "local",
        "detector": "mnemosyne.privacy.classify_privacy",
        "backfilled": True,
    }
    updated["embedding_partition"] = embedding_partition
    return updated


def _privacy_backfill_controls(
    sensitivity: int,
    access_policy: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    policy = dict(access_policy or {})
    return {
        "sensitivity": int(sensitivity),
        "data_class": str(policy.get("data_class") or "standard"),
        "policy_max_sensitivity": _int_or_default(policy.get("max_sensitivity"), default=int(sensitivity)),
        "embedding_partition": str((metadata or {}).get("embedding_partition") or "public"),
    }


@dataclass(slots=True)
class RoutePlan:
    """Result of the cheap fast-vs-deep retrieval router (§22.1 / §30.4)."""

    mode: Literal["fast", "deep"]
    reason: str
    signals: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "reason": self.reason, "signals": dict(self.signals)}


# Lexical markers that signal a query needs exhaustive deep retrieval
# (reconstruction, multi-hop history, decision tracing) rather than the fast
# current-truth path. Kept as a cheap substring heuristic — never an LLM call.
_DEEP_ROUTE_MARKERS: tuple[str, ...] = (
    "why",
    "histor",
    "reconstruct",
    "trace",
    "timeline",
    "as of",
    "as-of",
    "originally",
    "evolve",
    "evolution",
    "decision",
    "how did",
    "what changed",
    "root cause",
    "over time",
    "across sessions",
    "back then",
)


def route(query: str, ctx: dict[str, Any] | None = None) -> RoutePlan:
    """Cheap fast-vs-deep retrieval router (§22.1 plan step / §30.4 fast path).

    A deterministic heuristic — explicitly *not* an LLM call on the fast path —
    that decides whether a query needs the exhaustive deep path (LLM planning,
    live PPR multi-hop, exhaustive evidence traversal) or the fast current-truth
    path. ``ctx`` may carry an explicit ``mode`` override, a ``required_accuracy``
    hint, or an ``as_of`` timestamp. This replaces the hardcoded ``deep`` boolean:
    callers ``route(q, ctx)`` then dispatch ``engine.deep_search`` vs
    ``engine.retrieve`` on any :class:`MemoryEngine`, so routing stays decoupled
    from the backend.
    """
    ctx = ctx or {}
    workspace_broadcast = workspace_broadcast_from_context(ctx)
    override = ctx.get("mode")
    if override in ("fast", "deep"):
        return RoutePlan(
            override,
            f"explicit mode override -> {override}",
            {"override": override, "workspace_broadcast": workspace_broadcast},
        )

    normalized = query.lower().strip()
    tokens = normalized.split()
    matched_markers = [marker for marker in _DEEP_ROUTE_MARKERS if marker in normalized]
    long_query = len(tokens) >= 12
    exhaustive = ctx.get("required_accuracy") == "exhaustive"
    as_of_requested = bool(ctx.get("as_of"))
    signals: dict[str, Any] = {
        "deep_markers": matched_markers,
        "token_count": len(tokens),
        "long_query": long_query,
        "required_accuracy": ctx.get("required_accuracy"),
        "as_of": as_of_requested,
        "workspace_broadcast": workspace_broadcast,
    }

    if matched_markers:
        return RoutePlan("deep", f"deep markers fired: {', '.join(matched_markers)}", signals)
    if exhaustive:
        return RoutePlan("deep", "caller requested exhaustive accuracy", signals)
    if as_of_requested:
        return RoutePlan("deep", "historical as-of reconstruction requested", signals)
    if long_query:
        return RoutePlan("deep", "long multi-clause query suggests decomposition", signals)
    return RoutePlan("fast", "current-truth fast path; no deep signals", signals)


@runtime_checkable
class MemoryEngine(Protocol):
    """Promoted runtime engine contract shared by every backend.

    Both :class:`LocalMemoryEngine` and the Postgres adapter are substitutable
    behind this protocol, so the CLI/MCP runtime can bind either implementation
    by type. Marked ``@runtime_checkable`` so callers can assert substitutability
    at runtime (``isinstance(engine, MemoryEngine)``) in addition to static
    type-checking. Method bodies raise :class:`NotImplementedError` because the
    class is a structural contract, never instantiated directly.
    """

    def append_evidence(self, ev: Evidence, branch: str = "main") -> str:
        raise NotImplementedError

    def backfill_evidence_privacy(
        self,
        tenant_id: str,
        cid: str,
        pii_tags: list[str],
        branch: str = "main",
        *,
        pii_sensitivity: int = 3,
        actor: str = "privacy_backfill",
        source: str = "privacy_backfill",
    ) -> bool:
        raise NotImplementedError

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        raise NotImplementedError

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
        raise NotImplementedError

    def add_preference(self, preference: Preference) -> str:
        raise NotImplementedError

    def record_audit_event(
        self,
        tenant_id: str | None,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
    ) -> None:
        raise NotImplementedError

    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        raise NotImplementedError

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        raise NotImplementedError

    def graph_ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
        use_cache: bool = False,
        filt: dict[str, Any] | None = None,
    ) -> list[Hit]:
        raise NotImplementedError

    def as_of(self, subject: str, predicate: str, t: datetime, tenant_id: str | None = None, branch: str = "main") -> list[Assertion]:
        raise NotImplementedError

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        branch: str = "main",
        deep: bool = False,
        filt: dict[str, Any] | None = None,
        *,
        record_access: bool = True,
    ) -> RetrievalResult:
        raise NotImplementedError

    def set_calibration(self, calibration: CalibrationSet) -> None:
        raise NotImplementedError

    def register_entity(
        self,
        tenant_id: str,
        canonical: str,
        *,
        alias: str | None = None,
        entity_type: str = "unknown",
        summary: str | None = None,
        source_evidence_cids: list[str] | None = None,
        access_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def deep_search(self, query: str, tenant_id: str, branch: str = "main", filt: dict[str, Any] | None = None) -> RetrievalResult:
        raise NotImplementedError

    def put_working(self, item: WorkingMemoryItem) -> str:
        raise NotImplementedError

    def get_working(
        self,
        tenant_id: str,
        session_id: str,
        item_id: str,
        *,
        as_of: datetime,
    ) -> WorkingMemoryItem | None:
        raise NotImplementedError

    def list_working(
        self,
        tenant_id: str,
        session_id: str,
        *,
        as_of: datetime,
    ) -> list[WorkingMemoryItem]:
        raise NotImplementedError

    def expire_working(
        self,
        tenant_id: str,
        *,
        expired_at: datetime,
        session_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        branch: str | None = None,
    ) -> list[WorkingMemoryItem]:
        raise NotImplementedError

    def explain(self, query: str, tenant_id: str, branch: str = "main") -> dict[str, Any]:
        raise NotImplementedError

    def correct(
        self,
        tenant_id: str,
        user_id: str,
        subject: str,
        predicate: str,
        object_value: str,
        correction_text: str,
        branch: str = "main",
        confidence: float = 0.95,
    ) -> str:
        raise NotImplementedError

    def forget(
        self,
        tenant_id: str,
        cid: str,
        branch: str = "main",
        requested_by: str = "user",
        erasure_mode: ErasureMode | str = ErasureMode.TOMBSTONE_RECOMPUTE,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def evidence_is_erased(self, tenant_id: str, cid: str, branch: str = "main") -> bool:
        """Engine-neutral tombstone probe.

        Returns True iff a row for ``cid`` still exists for (tenant, branch) AND
        it is erased/tombstoned. Distinct from :meth:`get_evidence`, which masks
        erased rows (returns ``None``): the adversarial poison corpus needs to
        confirm the erased row is *retained-but-hidden* (the replay blocklist)
        without reaching into any engine's private storage. Local retains the row
        in-memory, Postgres/SQLite retain it as ``erased = true`` in the evidence
        table; a hard-deleted (legal) row is gone and returns False.
        """
        raise NotImplementedError

    def export_tenant(self, tenant_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def export_tenant_filtered(self, tenant_id: str, access_context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def branch(self, name: str, frm: str = "main", kind: str = "scratch", tenant_id: str | None = None) -> None:
        raise NotImplementedError

    def merge(self, frm: str, into: str = "main", tenant_id: str | None = None) -> MergeReport:
        raise NotImplementedError

    def discard(self, branch: str, tenant_id: str | None = None) -> None:
        raise NotImplementedError

    def schedule_intention(self, intention: Intention) -> str:
        raise NotImplementedError

    def cancel_intention(
        self, tenant_id: str, intention_id: str, *, cancelled_by: str
    ) -> None:
        raise NotImplementedError

    def update_intention(
        self,
        tenant_id: str,
        intention_id: str,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
        due_at: datetime | None = None,
        action: dict[str, Any] | None = None,
        recurrence_policy: dict[str, Any] | None = None,
    ) -> Intention:
        raise NotImplementedError

    def evaluate_due_intentions(
        self,
        tenant_id: str,
        *,
        evaluated_at: datetime,
        trigger_context: TriggerEvaluationContext,
        operating_point: ProspectiveOperatingPoint,
    ) -> list[Intention]:
        raise NotImplementedError

    def list_intentions(self, tenant_id: str) -> list[Intention]:
        raise NotImplementedError


#: Kill-switch for the candidate-scan memo (default ON — byte-parity-proven in
#: tests/test_engine_perf_lanes.py; registered in CONFIG-DRIFT-CHECKS.md).
_CANDIDATE_MEMO_ENV = "MNEMOSYNE_CANDIDATE_MEMO"
_CANDIDATE_MEMO_SIZE = 4


def _candidate_memo_enabled() -> bool:
    return os.environ.get(_CANDIDATE_MEMO_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def _copy_jsonish(value: Any) -> Any:
    """Deep-copy the JSON-shaped (dict/list/scalar) metadata trees Hit carries.

    Equivalent to copy.deepcopy for _candidate_hits output — its metadata is
    built exclusively from dicts, lists, and immutable scalars — without
    deepcopy's per-object dispatch overhead.
    """
    if isinstance(value, dict):
        return {key: _copy_jsonish(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_jsonish(item) for item in value]
    return value


def _clone_candidate_hit(hit: Hit) -> Hit:
    """Independent, equal clone of a cached candidate Hit.

    Channels mutate score/channel and write into metadata (e.g.
    ``stored_embedding_used``), so every _candidate_hits caller gets its own
    Hit and its own metadata tree — the cached entry stays pristine.
    """
    return Hit(
        id=hit.id,
        kind=hit.kind,
        tenant_id=hit.tenant_id,
        branch=hit.branch,
        text=hit.text,
        score=hit.score,
        channel=hit.channel,
        provenance=list(hit.provenance),
        trust_tier=hit.trust_tier,
        sensitivity=hit.sensitivity,
        metadata=_copy_jsonish(hit.metadata),
    )


class LocalMemoryEngine:
    """A deterministic local engine that implements the blueprint contract.

    It is intentionally dependency-light so the regression suite can run
    anywhere. Production storage is represented by sql/schema.sql; this local
    engine preserves the same invariants and API surface for development,
    counterfactual replay, and single-user operation.
    """

    _writer_owners_lock = threading.Lock()
    _writer_owners: weakref.WeakValueDictionary[str, LocalMemoryEngine] = (
        weakref.WeakValueDictionary()
    )

    def __init__(
        self,
        store_path: str | os.PathLike[str] | None = None,
        policy: OperatingPolicy | None = None,
        adapters: RetrievalAdapters | None = None,
        journal_dir: str | os.PathLike[str] | None = None,
        read_only: bool = False,
    ):
        self.store_path = Path(store_path).expanduser() if store_path else None
        self._writer_path_key: str | None = None
        self._journal_dir = Path(journal_dir).expanduser() if journal_dir else None
        self._read_only = read_only
        self._persistence_defer_depth = 0
        self._persistence_deferred_dirty = False
        self._persistence_aborted = False
        self.policy = policy or OperatingPolicy()
        if adapters is None:
            embedding = HashingEmbeddingProvider()
            adapters = RetrievalAdapters(
                embedding=embedding,
                reranker=LocalSimilarityReranker(embedding_provider=embedding),
            )
        self.adapters = adapters
        self._lock = threading.RLock()
        self.branches: dict[str, dict[str, Any]] = {
            "main": {"from": None, "kind": "protected", "created_at": utc_now().isoformat()}
        }
        self.evidence: dict[str, Evidence] = {}
        self.assertions: dict[str, Assertion] = {}
        self.relations: dict[str, Relation] = {}
        self.preferences: dict[str, Preference] = {}
        self.justifications: dict[str, Justification] = {}
        self.contradictions: dict[str, Contradiction] = {}
        self.calibrations: dict[tuple[str, str], CalibrationSet] = {}
        self.entities: dict[tuple[str, str], dict[str, Any]] = {}
        self.intentions: dict[tuple[str, str], Intention] = {}
        self.working_memory: dict[tuple[str, str, str], WorkingMemoryItem] = {}
        self.audit_log: list[dict[str, Any]] = []
        self.deletion_log: list[dict[str, Any]] = []
        self.merge_log: list[dict[str, Any]] = []
        # Candidate-scan memo (see _candidate_hits): _store_version is bumped
        # by every _persist() call — the single write choke point all mutators
        # (including belief.py's direct-dict writers) already reach, even when
        # store_path is unset — so any committed write invalidates the memo.
        self._store_version = 0
        self._retrieval_result_cache_nonce = secrets.token_hex(16)
        # Entries carry the earliest future access-policy expiry in scope: the
        # scan is time-dependent through expires_at, so a cached result is only
        # valid until that first allow→deny flip (None = no pending flip).
        self._candidate_memo: OrderedDict[tuple[Any, ...], tuple[datetime | None, list[Hit]]] = OrderedDict()
        self._candidate_memo_lock = threading.Lock()
        if self.store_path and not self._read_only:
            writer_path_key = str(self.store_path.resolve(strict=False))
            with self._writer_owners_lock:
                owner = self._writer_owners.get(writer_path_key)
                if owner is not None and owner is not self:
                    raise RuntimeError(
                        f"local memory store already has a writer: {writer_path_key}"
                    )
                self._writer_owners[writer_path_key] = self
                self._writer_path_key = writer_path_key
        try:
            if self.store_path and self.store_path.exists():
                self._load()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Release this engine's writable store-path ownership."""

        writer_path_key = getattr(self, "_writer_path_key", None)
        if writer_path_key is None:
            return
        with self._writer_owners_lock:
            if self._writer_owners.get(writer_path_key) is self:
                del self._writer_owners[writer_path_key]
        self._writer_path_key = None

    def __enter__(self) -> LocalMemoryEngine:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def _retrieval_result_cache_token(
        self, tenant_id: str, branch: str, effective_filter: dict[str, Any]
    ) -> tuple[Any, ...] | None:
        return (
            "local",
            self._retrieval_result_cache_nonce,
            tenant_id,
            branch,
            self._store_version,
            effective_filter.get("_retrieval_deep", False),
        )

    @staticmethod
    def _evidence_key(tenant_id: str, branch: str, cid: str) -> str:
        return f"{tenant_id}:{branch}:{cid}"

    @staticmethod
    def _branch_key(tenant_id: str, branch: str, item_id: str) -> str:
        return f"{tenant_id}:{branch}:{item_id}"

    @staticmethod
    def _working_key(
        tenant_id: str, session_id: str, item_id: str
    ) -> tuple[str, str, str]:
        return tenant_id, session_id, item_id

    def _audit(
        self,
        tenant_id: str | None,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        event_time = occurred_at or utc_now()
        if event_time.tzinfo is None:
            raise ValueError("audit event time must be timezone-aware")
        normalized_tags = sorted(set(capability_tags or []))
        audit_diff = dict(diff)
        audit_diff.setdefault("source", source or actor)
        if trust_tier is not None:
            audit_diff.setdefault("trust_tier", trust_tier)
        if normalized_tags:
            audit_diff.setdefault("capability_tags", normalized_tags)
        if event_id is not None and any(
            row.get("id") == event_id for row in self.audit_log
        ):
            return
        self.audit_log.append(
            {
                "id": event_id or new_id(),
                "tenant_id": tenant_id,
                "actor": actor,
                "op": op,
                "target_id": target_id,
                "source": source or actor,
                "trust_tier": trust_tier,
                "capability_tags": normalized_tags,
                "diff": audit_diff,
                "at": event_time.astimezone(UTC).isoformat(),
            }
        )

    def record_audit_event(
        self,
        tenant_id: str | None,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
    ) -> None:
        self._audit(
            tenant_id,
            actor,
            op,
            target_id,
            diff,
            source=source,
            trust_tier=trust_tier,
            capability_tags=capability_tags,
        )
        self._persist()

    def _intention_provenance(self, intention: Intention) -> list[Evidence]:
        evidence: list[Evidence] = []
        for cid in intention.evidence_ids:
            matches = [
                item
                for item in self.evidence.values()
                if (
                    item.cid == cid
                    and item.tenant_id == intention.tenant_id
                    and item.branch == "main"
                    and not item.erased
                )
            ]
            if not matches:
                raise ValueError(f"evidence {cid!r} is missing or outside the intention tenant")
            source = matches[0]
            validate_intention_provenance_claim(
                intention,
                evidence_id=cid,
                user_id=source.user_id,
                erased=source.erased,
                trust_tier=source.trust_tier,
                capability_tags=source.capability_tags,
                max_trust_tier=self.policy.max_trust_tier,
            )
            evidence.append(source)
        return evidence

    @contextmanager
    def _prospective_transaction(self):
        """Roll back prospective state and audit if persistence does not commit."""

        intentions_before = copy.deepcopy(self.intentions)
        audit_before = copy.deepcopy(self.audit_log)
        store_version_before = self._store_version
        try:
            yield
        except BaseException:
            self.intentions = intentions_before
            self.audit_log = audit_before
            self._store_version = store_version_before
            raise

    def schedule_intention(self, intention: Intention) -> str:
        """Store an intention after tenant, provenance, trust, and taint checks."""

        with self._lock:
            intention = canonicalize_intention(intention, require_scheduled=True)
            receipt_id = intention_fire_receipt_id(
                intention.tenant_id, intention.intention_id
            )
            if any(
                row.get("op") == "fire_intention" and row.get("id") == receipt_id
                for row in self.audit_log
            ):
                raise ValueError(
                    f"intention {intention.intention_id!r} already has a durable firing receipt"
                )
            provenance = self._intention_provenance(intention)
            key = (intention.tenant_id, intention.intention_id)
            if key in self.intentions:
                raise ValueError(f"intention {intention.intention_id!r} already exists")
            validate_intention_dependencies(intention, self.intentions)
            stored = copy.deepcopy(intention)
            trust_tier, capability_tags = intention_audit_context(provenance)
            with self._prospective_transaction():
                self.intentions[key] = stored
                self._audit(
                    stored.tenant_id,
                    stored.agent_id,
                    "schedule_intention",
                    stored.intention_id,
                    intention_audit_diff(stored, status=stored.status),
                    source="prospective_memory",
                    trust_tier=trust_tier,
                    capability_tags=capability_tags,
                )
                self._persist()
            return stored.intention_id

    def cancel_intention(self, tenant_id: str, intention_id: str, *, cancelled_by: str) -> None:
        with self._lock:
            if type(cancelled_by) is not str or not cancelled_by.strip():
                raise ValueError("cancelled_by must be a non-empty string")
            key = (tenant_id, intention_id)
            intention = self.intentions.get(key)
            if intention is None:
                raise KeyError(intention_id)
            if intention.status == "fired":
                raise ValueError("a fired intention cannot be cancelled")
            if intention.status == "cancelled":
                return
            if cancelled_by not in {intention.user_id, intention.agent_id}:
                raise PermissionError(
                    "only the owning user or agent may cancel an intention"
                )
            provenance = self._intention_provenance(intention)
            trust_tier, capability_tags = intention_audit_context(provenance)
            with self._prospective_transaction():
                intention.status = "cancelled"
                intention.cancellation_state = {"cancelled_by": cancelled_by}
                self._audit(
                    tenant_id,
                    cancelled_by,
                    "cancel_intention",
                    intention_id,
                    intention_audit_diff(intention, status="cancelled"),
                    source="prospective_memory",
                    trust_tier=trust_tier,
                    capability_tags=capability_tags,
                )
                self._persist()

    def update_intention(
        self, tenant_id: str, intention_id: str, *, user_id: str, agent_id: str,
        session_id: str, due_at: datetime | None = None, action: dict[str, Any] | None = None,
        recurrence_policy: dict[str, Any] | None = None,
    ) -> Intention:
        with self._lock:
            key = (tenant_id, intention_id)
            current = self.intentions.get(key)
            if current is None:
                raise KeyError(intention_id)
            updated = _updated_intention(current, user_id=user_id, agent_id=agent_id,
                                         session_id=session_id, due_at=due_at, action=action,
                                         recurrence_policy=recurrence_policy)
            provenance = self._intention_provenance(updated)
            trust_tier, capability_tags = intention_audit_context(provenance)
            with self._prospective_transaction():
                self.intentions[key] = updated
                self._audit(tenant_id, user_id, "update_intention", intention_id,
                            intention_audit_diff(updated, status="scheduled"),
                            source="prospective_memory", trust_tier=trust_tier,
                            capability_tags=capability_tags)
                self._persist()
            return copy.deepcopy(updated)

    def evaluate_due_intentions(
        self,
        tenant_id: str,
        *,
        evaluated_at: datetime,
        trigger_context: TriggerEvaluationContext,
        operating_point: ProspectiveOperatingPoint,
    ) -> list[Intention]:
        """Fire due intentions once, ordered deterministically by due time and id.

        Returns detached :class:`Intention` copies actually transitioned
        ``scheduled -> fired`` in this call, ordered by ``(due_at UTC,
        intention_id)``. Re-evaluation returns ``[]``. All candidate inputs,
        provenance, and audit contexts are prevalidated before any transition.
        ``infrastructure_available=False`` raises :class:`RuntimeError` with
        zero mutation/audit.
        """

        evaluated_at = validate_intention_evaluation_inputs(
            tenant_id,
            evaluated_at=evaluated_at,
            trigger_context=trigger_context,
            operating_point=operating_point,
        )
        with self._lock:
            tenant_items = {
                key: item
                for key, item in self.intentions.items()
                if key[0] == tenant_id
            }
            evaluated_utc = evaluated_at
            frozen_intentions = copy.deepcopy(self.intentions)
            candidate_results: list[tuple[Intention, dict[str, Any]]] = []
            for item in tenant_items.values():
                if item.status != "scheduled":
                    continue
                fires, signal = _evaluate_trigger(
                    item,
                    evaluated_at=evaluated_utc,
                    context=trigger_context,
                    operating_point=operating_point,
                    tenant_intentions=frozen_intentions,
                )
                if fires:
                    candidate_results.append((item, signal))
            candidate_results.sort(
                key=lambda result: (result[0].due_at, result[0].intention_id)
            )
            audit_contexts = [
                intention_audit_context(self._intention_provenance(intention))
                for intention, _signal in candidate_results
            ]
            fired: list[Intention] = []
            with self._prospective_transaction():
                for (intention, signal), (trust_tier, capability_tags) in zip(
                    candidate_results, audit_contexts, strict=True
                ):
                    intention.status = "fired"
                    fire_diff = {
                        **intention_audit_diff(intention, status="fired"),
                        "evaluated_at": evaluated_utc.isoformat(),
                        "operating_point": operating_point.to_dict(),
                    }
                    if "event_id" in signal:
                        fire_diff["matched_event_id"] = signal["event_id"]
                    if "condition_id" in signal:
                        fire_diff["matched_condition_id"] = signal["condition_id"]
                    self._audit(
                        tenant_id,
                        intention.agent_id,
                        "fire_intention",
                        intention.intention_id,
                        fire_diff,
                        source="prospective_memory",
                        trust_tier=trust_tier,
                        capability_tags=capability_tags,
                        event_id=intention_fire_receipt_id(
                            tenant_id, intention.intention_id
                        ),
                        occurred_at=evaluated_utc,
                    )
                    fired.append(copy.deepcopy(intention))
                if fired:
                    self._persist()
            return fired

    def list_intentions(self, tenant_id: str) -> list[Intention]:
        with self._lock:
            return [
                copy.deepcopy(item)
                for (item_tenant, _), item in sorted(self.intentions.items())
                if item_tenant == tenant_id
            ]

    @staticmethod
    def _working_clock(value: datetime, name: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
        return value.astimezone(UTC)

    def _working_provenance(
        self, item: WorkingMemoryItem
    ) -> tuple[int, list[str], int, dict[str, Any]]:
        """Validate backing evidence and derive the effective security envelope.

        Working memory is a transient view over evidence, but it still has to
        carry the evidence ownership and security rails with it.  The most
        restrictive trust, capability, sensitivity, and access-policy values
        therefore win across the item and every originating evidence row.
        """

        access_policy = validate_access_policy(
            item.access_policy,
            tenant_id=item.tenant_id,
            location="working_memory.access_policy",
        )
        trust_tiers: list[int] = [item.trust_tier]
        capability_tags = {tag.strip().lower() for tag in item.capability_tags}
        sensitivities = [int(item.sensitivity)]
        source_policies: list[dict[str, Any]] = [access_policy]
        for cid in item.evidence_ids:
            evidence = self.evidence.get(self._evidence_key(item.tenant_id, "main", cid))
            if evidence is None:
                raise ValueError(
                    f"evidence {cid!r} is missing or outside the working tenant"
                )
            if evidence.erased:
                raise ValueError(f"evidence {cid!r} is erased")
            if evidence.user_id != item.user_id:
                raise ValueError("working item user must match originating evidence")
            if evidence.session_id != item.session_id:
                raise ValueError("working item session must match originating evidence")
            if type(evidence.trust_tier) is not int:
                raise ValueError("originating evidence trust tier is invalid")
            trust_tier = evidence.trust_tier
            if not int(TrustTier.DIRECT_USER) <= trust_tier <= int(TrustTier.UNTRUSTED_EXTERNAL):
                raise ValueError("originating evidence trust tier is out of range")
            if trust_tier > int(self.policy.max_trust_tier):
                raise PermissionError(
                    "originating evidence exceeds the working write trust ceiling"
                )
            trust_tiers.append(trust_tier)
            if type(evidence.capability_tags) is not list or any(
                type(tag) is not str or not tag.strip() for tag in evidence.capability_tags
            ):
                raise ValueError("originating evidence capability tags are invalid")
            capability_tags.update(tag.strip().lower() for tag in evidence.capability_tags)
            if type(evidence.sensitivity) is not int or isinstance(evidence.sensitivity, bool):
                raise ValueError("originating evidence sensitivity is invalid")
            if evidence.sensitivity < 0:
                raise ValueError("originating evidence sensitivity is negative")
            sensitivities.append(evidence.sensitivity)
            source_policies.append(
                validate_access_policy(
                    evidence.access_policy,
                    tenant_id=item.tenant_id,
                    location="evidence.access_policy",
                )
            )
        effective_policy = merge_access_policies(
            source_policies,
            tenant_id=item.tenant_id,
        )
        return (
            max(trust_tiers),
            sorted(capability_tags),
            max(sensitivities),
            effective_policy,
        )

    @staticmethod
    def _working_snapshot(item: WorkingMemoryItem) -> dict[str, Any]:
        return {
            "item_id": item.item_id,
            "tenant_id": item.tenant_id,
            "session_id": item.session_id,
            "user_id": item.user_id,
            "agent_id": item.agent_id,
            "kind": item.kind,
            "task_id": item.task_id,
            "content": item.content,
            "created_at": item.created_at.isoformat(),
            "expires_at": item.expires_at.isoformat(),
            "evidence_ids": list(item.evidence_ids),
            "trust_tier": item.trust_tier,
            "access_policy": copy.deepcopy(item.access_policy),
            "metadata": copy.deepcopy(item.metadata),
            "capability_tags": list(item.capability_tags),
            "sensitivity": item.sensitivity,
        }

    @classmethod
    def _working_audit_diff(
        cls,
        item: WorkingMemoryItem,
        *,
        status: str,
        sweep: datetime | None = None,
    ) -> dict[str, Any]:
        diff: dict[str, Any] = {
            "working_item_digest": content_cid("working_memory", cls._working_snapshot(item)),
            "tenant_id": item.tenant_id,
            "session_id": item.session_id,
            "item_id": item.item_id,
            "task_id": item.task_id,
            "kind": item.kind,
            "created_at": item.created_at.isoformat(),
            "expires_at": item.expires_at.isoformat(),
            "evidence_ids": list(item.evidence_ids),
            "deadline": item.expires_at.isoformat(),
            "status": status,
        }
        if sweep is not None:
            diff["sweep"] = sweep.isoformat()
        return diff

    @staticmethod
    def _working_event_id(item: WorkingMemoryItem, op: str) -> str:
        return content_cid(
            "working_memory_audit",
            {
                "tenant_id": item.tenant_id,
                "session_id": item.session_id,
                "item_id": item.item_id,
                "op": op,
            },
        )

    def _working_detached(self, item: WorkingMemoryItem) -> WorkingMemoryItem:
        trust_tier, capability_tags, sensitivity, access_policy = self._working_provenance(item)
        detached = copy.deepcopy(item)
        detached.trust_tier = trust_tier
        detached.capability_tags = capability_tags
        detached.sensitivity = sensitivity
        detached.access_policy = access_policy
        return detached

    def put_working(self, item: WorkingMemoryItem) -> str:
        """Store one working item under its tenant/session/item composite key."""

        if not isinstance(item, WorkingMemoryItem):
            raise TypeError("item must be a WorkingMemoryItem")
        if item.status != "active":
            raise ValueError("put_working accepts only active working items")
        with self._lock:
            key = self._working_key(item.tenant_id, item.session_id, item.item_id)
            if key in self.working_memory:
                raise ValueError(f"working item {item.item_id!r} already exists")
            before = (
                copy.deepcopy(self.working_memory),
                copy.deepcopy(self.audit_log),
                self._store_version,
            )
            stored = copy.deepcopy(item)
            try:
                trust_tier, capability_tags, sensitivity, access_policy = self._working_provenance(stored)
                stored.trust_tier = trust_tier
                stored.capability_tags = capability_tags
                stored.sensitivity = sensitivity
                stored.access_policy = access_policy
                self.working_memory[key] = stored
                self._audit(
                    stored.tenant_id,
                    stored.agent_id,
                    "put_working",
                    stored.item_id,
                    self._working_audit_diff(stored, status=stored.status),
                    source="working_memory",
                    trust_tier=trust_tier,
                    capability_tags=capability_tags,
                    event_id=self._working_event_id(stored, "put_working"),
                    occurred_at=stored.created_at,
                )
                self._persist()
            except BaseException:
                self.working_memory, self.audit_log, self._store_version = before
                raise
            # Expose the canonical derived envelope to the caller while the
            # stored record remains detached from all caller-owned containers.
            item.trust_tier = stored.trust_tier
            item.capability_tags = list(stored.capability_tags)
            item.sensitivity = stored.sensitivity
            item.access_policy = copy.deepcopy(stored.access_policy)
            return stored.item_id

    def get_working(
        self,
        tenant_id: str,
        session_id: str,
        item_id: str,
        *,
        as_of: datetime,
    ) -> WorkingMemoryItem | None:
        clock = self._working_clock(as_of, "as_of")
        with self._lock:
            item = self.working_memory.get(
                self._working_key(tenant_id, session_id, item_id)
            )
            if (
                item is None
                or item.status != "active"
                or clock < item.created_at
                or clock >= item.expires_at
            ):
                return None
            return self._working_detached(item)

    def list_working(
        self,
        tenant_id: str,
        session_id: str,
        *,
        as_of: datetime,
    ) -> list[WorkingMemoryItem]:
        clock = self._working_clock(as_of, "as_of")
        with self._lock:
            items = [
                item
                for (item_tenant, item_session, _), item in self.working_memory.items()
                if item_tenant == tenant_id
                and item_session == session_id
                and item.status == "active"
                and item.created_at <= clock
                and clock < item.expires_at
            ]
            return [
                self._working_detached(item)
                for item in sorted(
                    items, key=lambda value: (-value.created_at.timestamp(), value.item_id)
                )
            ]

    def expire_working(
        self,
        tenant_id: str,
        *,
        expired_at: datetime,
        session_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        branch: str | None = None,
    ) -> list[WorkingMemoryItem]:
        sweep = self._working_clock(expired_at, "expired_at")
        with self._lock:
            due = sorted(
                (
                    item
                    for (item_tenant, item_session, _), item in self.working_memory.items()
                    if item_tenant == tenant_id
                    and (session_id is None or item_session == session_id)
                    and (user_id is None or item.user_id == user_id)
                    and (agent_id is None or item.agent_id == agent_id)
                    and (task_id is None or item.task_id == task_id)
                    and (branch is None or item.metadata.get("branch") == branch)
                    and item.status == "active"
                    and item.expires_at <= sweep
                ),
                key=lambda value: (value.expires_at, value.session_id, value.item_id),
            )
            if not due:
                return []
            provenance = [self._working_provenance(item) for item in due]
            before = (
                copy.deepcopy(self.working_memory),
                copy.deepcopy(self.audit_log),
                self._store_version,
            )
            expired: list[WorkingMemoryItem] = []
            try:
                for item, (trust_tier, capability_tags, sensitivity, access_policy) in zip(
                    due, provenance, strict=True
                ):
                    item.capability_tags = capability_tags
                    item.sensitivity = sensitivity
                    item.access_policy = access_policy
                    item.status = "expired"
                    item.expired_at = sweep
                    self._audit(
                        item.tenant_id,
                        item.agent_id,
                        "expire_working",
                        item.item_id,
                        self._working_audit_diff(item, status=item.status, sweep=sweep),
                        source="working_memory",
                        trust_tier=trust_tier,
                        capability_tags=capability_tags,
                        event_id=self._working_event_id(item, "expire_working"),
                        occurred_at=sweep,
                    )
                    expired.append(copy.deepcopy(item))
                self._persist()
            except BaseException:
                self.working_memory, self.audit_log, self._store_version = before
                raise
            return expired

    def _persist(self) -> None:
        # Every mutator funnels through here; bump BEFORE the store_path early
        # return so in-memory engines invalidate the candidate memo too.
        self._store_version += 1
        if self._persistence_aborted:
            raise RuntimeError("deferred persistence transaction was aborted")
        if self._read_only:
            return
        if self._persistence_defer_depth:
            self._persistence_deferred_dirty = True
            return
        if not self.store_path:
            return
        writer_path_key = self._writer_path_key
        with self._writer_owners_lock:
            if (
                writer_path_key is None
                or self._writer_owners.get(writer_path_key) is not self
            ):
                raise RuntimeError("local memory engine does not own its writable store")
        if self.store_path.is_symlink():
            raise ValueError("local memory store must be a real file")
        parent = self.store_path.parent
        parent_created = not parent.exists()
        parent.mkdir(parents=True, exist_ok=True)
        if parent_created:
            parent.chmod(0o700)
        data = {
            "policy": self.policy.to_dict(),
            "branches": self.branches,
            "evidence": [item.to_dict() for item in self.evidence.values()],
            "assertions": [item.to_dict() for item in self.assertions.values()],
            "relations": [item.to_dict() for item in self.relations.values()],
            "preferences": [item.to_dict() for item in self.preferences.values()],
            "justifications": [item.to_dict() for item in self.justifications.values()],
            "contradictions": [item.to_dict() for item in self.contradictions.values()],
            "calibrations": [item.to_dict() for item in self.calibrations.values()],
            "entities": list(self.entities.values()),
            "intentions": [item.to_dict() for item in self.intentions.values()],
            "working_memory": [item.to_dict() for item in self.working_memory.values()],
            "audit_log": self.audit_log,
            "deletion_log": self.deletion_log,
            "merge_log": self.merge_log,
        }
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        payload = json.dumps(data, indent=2, sort_keys=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        tmp.chmod(0o600)
        tmp.replace(self.store_path)

    @contextmanager
    def defer_persistence(self):
        """Flush many in-process mutations once, or discard the deferred flush."""
        self._persistence_defer_depth += 1
        try:
            yield
        except BaseException:
            self._persistence_aborted = True
            self._persistence_defer_depth -= 1
            if self._persistence_defer_depth == 0:
                self._persistence_deferred_dirty = False
            raise
        else:
            self._persistence_defer_depth -= 1
            if self._persistence_defer_depth == 0 and self._persistence_aborted:
                raise RuntimeError("deferred persistence transaction was aborted")
            if self._persistence_defer_depth == 0 and self._persistence_deferred_dirty:
                self._persistence_deferred_dirty = False
                self._persist()

    def _load(self) -> None:
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.policy = OperatingPolicy.from_dict(data.get("policy"))
        branches = data.get("branches")
        if isinstance(branches, list):
            loaded_branches: dict[str, dict[str, Any]] = {}
            for row in branches:
                if not isinstance(row, dict) or not row.get("name"):
                    continue
                name = str(row["name"])
                meta = loaded_branches.setdefault(
                    name,
                    {
                        "from": row.get("from_branch"),
                        "kind": row.get("kind") or "scratch",
                        "created_at": row.get("created_at") or utc_now().isoformat(),
                        "tenants": [],
                    },
                )
                tenant_id = row.get("tenant_id")
                if tenant_id is not None:
                    meta["tenants"] = sorted(set(meta.get("tenants") or []) | {tenant_id})
            self.branches = loaded_branches or self.branches
        else:
            self.branches = branches or self.branches
        self.evidence = {
            self._evidence_key(ev.tenant_id, ev.branch, ev.cid or ""): ev
            for ev in (Evidence.from_dict(item) for item in data.get("evidence", []))
        }
        self.assertions = {
            self._branch_key(item.tenant_id, item.branch, item.id): item
            for item in (Assertion.from_dict(row) for row in data.get("assertions", []))
        }
        self.relations = {
            self._branch_key(item.tenant_id, item.branch, item.id): item
            for item in (Relation.from_dict(row) for row in data.get("relations", []))
        }
        self.preferences = {item.id: item for item in (Preference.from_dict(row) for row in data.get("preferences", []))}
        self.justifications = {item.id: item for item in (Justification.from_dict(row) for row in data.get("justifications", []))}
        self.contradictions = {item.id: item for item in (Contradiction.from_dict(row) for row in data.get("contradictions", []))}
        self.calibrations = {
            (item.tenant_id, item.memory_type): item
            for item in (CalibrationSet(**row) for row in data.get("calibrations", []))
        }
        self.entities = {
            (str(row["tenant_id"]), str(row["canonical"])): dict(row)
            for row in data.get("entities", [])
            if row.get("tenant_id") and row.get("canonical")
        }
        self.intentions = {
            (item.tenant_id, item.intention_id): item
            for item in (
                Intention.from_dict(row) for row in data.get("intentions", [])
            )
        }
        self.working_memory = {
            self._working_key(item.tenant_id, item.session_id, item.item_id): item
            for item in (
                WorkingMemoryItem.from_dict(row)
                for row in data.get("working_memory", [])
            )
        }
        self.audit_log = list(data.get("audit_log", []))
        self.deletion_log = list(data.get("deletion_log", []))
        self.merge_log = list(data.get("merge_log", []))

    def append_evidence(self, ev: Evidence, branch: str = "main") -> str:
        access_policy = validate_access_policy(ev.access_policy, tenant_id=ev.tenant_id, location="evidence.access_policy")
        with self._lock:
            self._require_branch(branch)
            cid = evidence_cid(
                ev.content,
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
                source_type=ev.source_type,
                content_pointer=ev.content_pointer,
                modality=ev.modality,
                sensitivity=int(ev.sensitivity),
            )
            unscoped_cid = evidence_unscoped_cid(
                ev.content,
                tenant_id=ev.tenant_id,
                source_type=ev.source_type,
                content_pointer=ev.content_pointer,
                modality=ev.modality,
            )
            for existing in self.evidence.values():
                if (
                    existing.tenant_id == ev.tenant_id
                    and existing.branch == branch
                    and existing.erased
                    and existing.source_type == ev.source_type
                    and existing.content_pointer == ev.content_pointer
                    and existing.modality == ev.modality
                    and existing.cid
                ):
                    replay_cid = evidence_cid(
                        ev.content,
                        tenant_id=ev.tenant_id,
                        user_id=existing.user_id,
                        source_type=ev.source_type,
                        content_pointer=ev.content_pointer,
                        modality=ev.modality,
                        sensitivity=int(existing.sensitivity),
                    )
                    if replay_cid == existing.cid or unscoped_cid == existing.cid:
                        cid = existing.cid
                        break
            key = self._evidence_key(ev.tenant_id, branch, cid)
            existing = self.evidence.get(key)
            reality_class = self._classify_evidence_reality(ev)
            if existing:
                op = "append_evidence.blocked_erased_replay" if existing.erased else "append_evidence.noop_dedup"
                self._audit(
                    ev.tenant_id,
                    ev.actor,
                    op,
                    cid,
                    {"branch": branch, "source_type": ev.source_type, "source_identity": ev.source_identity},
                    source=ev.source_type,
                    trust_tier=ev.trust_tier,
                    capability_tags=ev.capability_tags,
                )
                self._persist()
                return cid
            budget_report: dict[str, Any] | None = None
            if reality_class in {"self_generated", "simulated"}:
                current_events, current_bytes = self._self_generation_budget_usage(
                    tenant_id=ev.tenant_id,
                    branch=branch,
                )
                budget_report = self_generation_budget_report(
                    current_events=current_events,
                    incoming_events=1,
                    current_bytes=current_bytes,
                    incoming_bytes=len(ev.content),
                    max_events=self.policy.self_generation_budget_max_events,
                    window_ticks=self.policy.self_generation_budget_window_ticks,
                )
                if not budget_report["allowed"]:
                    self._audit(
                        ev.tenant_id,
                        ev.actor,
                        "append_evidence.self_generation_budget_deferred",
                        cid,
                        {
                            "branch": branch,
                            "source_type": ev.source_type,
                            "source_identity": ev.source_identity,
                            "reality_class": reality_class,
                            "self_generation_budget": budget_report,
                            "stored": False,
                            "reversible_pointer_preserved": bool(ev.content_pointer),
                        },
                        source=ev.source_type,
                        trust_tier=ev.trust_tier,
                        capability_tags=ev.capability_tags,
                    )
                    self._persist()
                    return cid
            stored = copy.deepcopy(ev)
            stored.cid = cid
            stored.branch = branch
            stored.access_policy = access_policy
            if stored.embedding and not may_embed_item(
                sensitivity=int(stored.sensitivity),
                access_policy=stored.access_policy,
            ):
                stored.embedding = None
            stored.metadata = dict(stored.metadata)
            stored.metadata.setdefault("reality_class", reality_class)
            stored.metadata["embedding_partition"] = vector_partition_for_item(
                sensitivity=int(stored.sensitivity),
                access_policy=stored.access_policy,
            )
            if budget_report is not None:
                stored.metadata["self_generation_budget"] = budget_report
                stored.metadata["self_generation_lifecycle"] = {
                    "status": "budgeted_low_groundedness",
                    "demotable": True,
                    "gc_after_idle_ticks": self.policy.self_generation_gc_after_idle_ticks,
                    "pointer_preserved": bool(stored.content_pointer or stored.cid),
                    "critical_path_allowed": False,
                }
            self.evidence[key] = stored
            self._audit(
                ev.tenant_id,
                ev.actor,
                "append_evidence",
                cid,
                {"source_type": ev.source_type, "source_identity": ev.source_identity, "branch": branch},
                source=ev.source_type,
                trust_tier=ev.trust_tier,
                capability_tags=ev.capability_tags,
            )
            self._persist()
            if self._journal_dir is not None:
                CIDJournal(self._journal_dir / journal_filename(stored.tenant_id)).append(
                    {
                        "cid": stored.cid,
                        "tenant_id": stored.tenant_id,
                        "kind": "evidence",
                        "content": stored.content,
                        "created_at": stored.created_at.isoformat(),
                    }
                )
            return cid

    def _self_generation_budget_usage(self, *, tenant_id: str, branch: str) -> tuple[int, int]:
        events = 0
        byte_count = 0
        for key, item in self.evidence.items():
            key_tenant, key_branch, _ = key.split(":", 2)
            if key_tenant != tenant_id or key_branch != branch or item.erased:
                continue
            if self._classify_evidence_reality(item) not in {"self_generated", "simulated"}:
                continue
            events += 1
            byte_count += len(item.content or "")
        return events, byte_count

    def get_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Evidence | None:
        with self._lock:
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            if ev and not ev.erased:
                return copy.deepcopy(ev)
            return None

    def evidence_is_erased(self, tenant_id: str, cid: str, branch: str = "main") -> bool:
        """Engine-neutral tombstone probe (see ``MemoryEngine.evidence_is_erased``).

        The erased row is retained in-memory as the replay blocklist; a legal
        hard-delete removes it entirely and returns False.
        """
        with self._lock:
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            return bool(ev and ev.erased)

    def set_evidence_embedding(
        self,
        tenant_id: str,
        cid: str,
        embedding: list[float],
        branch: str = "main",
        *,
        actor: str = "consolidation",
        source: str = "embedder",
    ) -> bool:
        with self._lock:
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            if ev is None or ev.erased:
                return False
            if not may_embed_item(
                sensitivity=int(ev.sensitivity),
                access_policy=ev.access_policy,
                erased=ev.erased,
            ):
                self._audit(
                    tenant_id,
                    actor,
                    "set_evidence_embedding.blocked_policy",
                    cid,
                    {"branch": branch, "source_type": ev.source_type, "reason": "embedding_not_allowed"},
                    source=source,
                    trust_tier=ev.trust_tier,
                    capability_tags=ev.capability_tags,
                )
                self._persist()
                return False
            ev.embedding = list(embedding)
            ev.metadata = dict(ev.metadata)
            ev.metadata["embedding_partition"] = vector_partition_for_item(
                sensitivity=int(ev.sensitivity),
                access_policy=ev.access_policy,
            )
            self._audit(
                tenant_id,
                actor,
                "set_evidence_embedding",
                cid,
                {"branch": branch, "embedding_dims": len(embedding), "source_type": ev.source_type},
                source=source,
                trust_tier=ev.trust_tier,
                capability_tags=ev.capability_tags,
            )
            self._persist()
            return True

    def update_evidence_metadata(
        self,
        tenant_id: str,
        cid: str,
        metadata_patch: dict[str, Any],
        branch: str = "main",
        *,
        actor: str = "consolidation",
        source: str = "metadata_update",
    ) -> bool:
        if "access_policy" in metadata_patch:
            raise ValueError("metadata_patch.access_policy cannot shadow evidence.access_policy")
        with self._lock:
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            if ev is None or ev.erased:
                return False
            before_keys = sorted(ev.metadata.keys())
            ev.metadata = {**ev.metadata, **metadata_patch}
            self._audit(
                tenant_id,
                actor,
                "update_evidence_metadata",
                cid,
                {
                    "branch": branch,
                    "patch": metadata_patch,
                    "before_keys": before_keys,
                    "after_keys": sorted(ev.metadata.keys()),
                    "source_type": ev.source_type,
                },
                source=source,
                trust_tier=ev.trust_tier,
                capability_tags=ev.capability_tags,
            )
            self._persist()
            return True

    def backfill_evidence_privacy(
        self,
        tenant_id: str,
        cid: str,
        pii_tags: list[str],
        branch: str = "main",
        *,
        pii_sensitivity: int = 3,
        actor: str = "privacy_backfill",
        source: str = "privacy_backfill",
    ) -> bool:
        tags = _normalise_privacy_tags(pii_tags)
        if tags and int(pii_sensitivity) < 3:
            raise ValueError("pii_sensitivity must be at least 3 for detected PII")
        with self._lock:
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            if ev is None or ev.erased:
                return False
            before = _privacy_backfill_controls(ev.sensitivity, ev.access_policy, ev.metadata)
            target_sensitivity = max(int(ev.sensitivity), int(pii_sensitivity) if tags else int(ev.sensitivity))
            access_policy = _privacy_backfill_access_policy(
                ev.access_policy,
                tenant_id=tenant_id,
                pii_tags=tags,
                target_sensitivity=target_sensitivity,
            )
            embedding_partition = vector_partition_for_item(
                sensitivity=target_sensitivity,
                access_policy=access_policy,
            )
            ev.sensitivity = target_sensitivity
            ev.access_policy = access_policy
            ev.metadata = _privacy_backfill_metadata(
                ev.metadata,
                access_policy=access_policy,
                pii_tags=tags,
                embedding_partition=embedding_partition,
            )
            if embedding_partition == "none":
                ev.embedding = None
            self._audit(
                tenant_id,
                actor,
                "backfill_evidence_privacy",
                cid,
                {
                    "branch": branch,
                    "pii_tags": tags,
                    "before": before,
                    "after": _privacy_backfill_controls(ev.sensitivity, ev.access_policy, ev.metadata),
                    "source_type": ev.source_type,
                },
                source=source,
                trust_tier=ev.trust_tier,
                capability_tags=ev.capability_tags,
            )
            self._persist()
            return True

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        access_policy = validate_access_policy(
            assertion.access_policy,
            tenant_id=assertion.tenant_id,
            location="assertion.access_policy",
        )
        with self._lock:
            self._require_branch(branch)
            incoming = copy.deepcopy(assertion)
            incoming.access_policy = access_policy
            incoming.branch = branch
            incoming.transaction_time = utc_now()
            requested_status = incoming.status
            incoming.status = "active" if incoming.status == "candidate" else incoming.status
            self._apply_projection_reality_monitoring(incoming)
            self._apply_schema_fast_path_projection_status(incoming, requested_status=requested_status)
            peers = [
                item
                for item in self.assertions.values()
                if item.tenant_id == incoming.tenant_id
                and item.branch == branch
                and item.subject == incoming.subject
                and item.predicate == incoming.predicate
                and item.scope == incoming.scope
                and item.status in {"active", "contested"}
            ]
            same = [item for item in peers if item.object == incoming.object]
            if same:
                winner = max(same, key=lambda item: item.confidence)
                before = winner.to_dict()
                winner.access_policy = merge_access_policies(
                    [winner.access_policy, incoming.access_policy],
                    tenant_id=winner.tenant_id,
                )
                winner.confidence = max(winner.confidence, incoming.confidence)
                winner.source_evidence_cids = sorted(set(winner.source_evidence_cids + incoming.source_evidence_cids))
                winner.trust_tier = more_trusted(winner.trust_tier, incoming.trust_tier)
                winner.last_accessed = utc_now()
                self._apply_projection_reality_monitoring(winner)
                self._audit(
                    winner.tenant_id,
                    "engine",
                    "upsert_assertion.noop_or_reinforce",
                    winner.id,
                    {"before": before, "after": winner.to_dict(), "source_evidence_cids": winner.source_evidence_cids},
                    source="assertion",
                    trust_tier=winner.trust_tier,
                )
                self._persist()
                return winner.id

            conflicts = [item for item in peers if item.object != incoming.object]
            if conflicts:
                current = min(conflicts, key=lambda item: (item.trust_tier, -item.valid_from.timestamp()))
                if incoming.trust_tier < current.trust_tier:
                    if incoming.valid_from > current.valid_from:
                        current.valid_to = incoming.valid_from
                    else:
                        current.valid_to = current.valid_from + timedelta(microseconds=1)
                    current.status = "superseded"
                    current.superseded_by = incoming.id
                    incoming.version = current.version + 1
                    incoming.justification_id = new_id()
                    op = "upsert_assertion.trust_supersede"
                elif incoming.trust_tier > current.trust_tier:
                    incoming.status = "superseded"
                    incoming.superseded_by = current.id
                    op = "upsert_assertion.trust_rejected"
                elif incoming.valid_from > current.valid_from:
                    current.valid_to = incoming.valid_from
                    current.status = "superseded"
                    incoming.version = current.version + 1
                    incoming.justification_id = new_id()
                    current.superseded_by = incoming.id
                    op = "upsert_assertion.supersede"
                elif incoming.valid_from == current.valid_from:
                    current.status = "contested"
                    incoming.status = "contested"
                    incoming.justification_id = current.justification_id or new_id()
                    self._rebalance_contested([current, incoming])
                    op = "upsert_assertion.contest"
                else:
                    incoming.status = "superseded"
                    incoming.valid_to = current.valid_from
                    op = "upsert_assertion.historical_superseded"
                self._audit(
                    incoming.tenant_id,
                    "engine",
                    op,
                    incoming.id,
                    {"conflict_with": current.id, "source_evidence_cids": incoming.source_evidence_cids},
                    source="assertion",
                    trust_tier=incoming.trust_tier,
                )

            key = self._branch_key(incoming.tenant_id, branch, incoming.id)
            self.assertions[key] = incoming
            self._audit(
                incoming.tenant_id,
                "engine",
                "upsert_assertion",
                incoming.id,
                {
                    "statement": incoming.statement(),
                    "status": incoming.status,
                    "source_evidence_cids": incoming.source_evidence_cids,
                },
                source="assertion",
                trust_tier=incoming.trust_tier,
            )
            self._persist()
            return incoming.id

    def assemble_system_prompt(self, *, tenant_id: str, hits: Any, sink: str = "system_prompt") -> str:
        """§31 RAIL-6 serve-time sink guard: ``untrusted_to_system_prompt`` forbidden.

        Assembles instruction text from retrieved ``hits`` for the given ``sink``.
        When ``sink`` is a privileged instruction sink (system_prompt / system /
        developer / instruction / tool), routing an untrusted-external or
        ``sanitize-as-data`` hit into it is REFUSED with ``PermissionError`` —
        retrieved text is data, never instruction (§31 immutable rail). Non-
        privileged sinks assemble all admissible hits. This is the missing runtime
        enforcement point: ingestion already tags untrusted content data-only, but
        nothing previously refused routing a flagged hit into a system-prompt sink.
        """
        return assemble_guarded_system_prompt(hits or [], sink=str(sink).strip().lower())

    def _rebalance_contested(self, items: list[Assertion]) -> None:
        total = sum(max(item.confidence, 0.01) for item in items)
        for item in items:
            item.calibration["hypothesis_prob"] = max(item.confidence, 0.01) / total

    def _apply_schema_fast_path_projection_status(
        self,
        incoming: Assertion,
        *,
        requested_status: str,
    ) -> None:
        if not bool(getattr(self.policy, "schema_fast_path_enabled", True)):
            return
        if requested_status not in {"candidate", "active"}:
            return
        calibration = dict(incoming.calibration)
        schema_fast_path = calibration.get("schema_fast_path")
        schema_fast_path = dict(schema_fast_path) if isinstance(schema_fast_path, dict) else {}
        scope = incoming.scope if isinstance(incoming.scope, dict) else {}
        congruent = bool(
            calibration.get("schema_congruent")
            or schema_fast_path.get("schema_congruent")
            or scope.get("schema_congruent")
            or scope.get("schema_fast_path")
        )
        if not congruent:
            return
        minimum = max(1, int(getattr(self.policy, "schema_fast_path_min_corroboration", 2)))
        corroboration_report = self._independent_corroboration_report(
            tenant_id=incoming.tenant_id,
            branch=incoming.branch,
            source_evidence_cids=incoming.source_evidence_cids,
        )
        corroboration = int(corroboration_report["independent_corroboration_count"])
        schema_fast_path.update(
            {
                "schema_congruent": True,
                "corroboration_count": corroboration,
                "raw_source_count": len({cid for cid in incoming.source_evidence_cids if cid}),
                "independent_corroboration_weight": corroboration_report["independent_corroboration_weight"],
                "rejected_corroboration_count": corroboration_report["rejected_corroboration_count"],
                "rejected_corroborators": corroboration_report["rejected_corroborators"],
                "min_corroboration": minimum,
            }
        )
        if corroboration < minimum:
            incoming.status = "contested"
            schema_fast_path["reason"] = "uncorroborated_but_congruent"
        else:
            schema_fast_path["reason"] = "corroborated_schema_fast_path"
        calibration["schema_fast_path"] = schema_fast_path
        incoming.calibration = calibration

    def _apply_projection_reality_monitoring(self, assertion: Assertion) -> None:
        calibration = dict(assertion.calibration)
        monitoring = self._projection_reality_monitoring_for_sources(
            tenant_id=assertion.tenant_id,
            branch=assertion.branch,
            source_evidence_cids=assertion.source_evidence_cids,
        )
        calibration["reality_monitoring"] = monitoring
        calibration["reality_class"] = monitoring["reality_class"]
        assertion.calibration = calibration

    def _projection_reality_monitoring_for_sources(
        self,
        *,
        tenant_id: str,
        branch: str,
        source_evidence_cids: list[str],
    ) -> dict[str, Any]:
        classes: dict[str, int] = {}
        source_classes: dict[str, str] = {}
        for cid in sorted({str(item) for item in source_evidence_cids if item}):
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            reality_class = self._classify_evidence_reality(ev) if ev is not None and not ev.erased else "unknown"
            classes[reality_class] = classes.get(reality_class, 0) + 1
            source_classes[cid] = reality_class
        risky = {"self_generated", "simulated", "externally_suggested"}
        grounded_count = classes.get("grounded", 0)
        risky_count = sum(classes.get(item, 0) for item in risky)
        if not source_classes:
            reality_class = "unknown"
        elif grounded_count:
            reality_class = "grounded"
        elif classes.get("simulated", 0):
            reality_class = "simulated"
        elif classes.get("self_generated", 0):
            reality_class = "self_generated"
        elif classes.get("externally_suggested", 0):
            reality_class = "externally_suggested"
        else:
            reality_class = "unknown"
        return {
            "source": "g1_projection_reality_monitoring",
            "applied": True,
            "reality_class": reality_class,
            "classes": classes,
            "source_classes": source_classes,
            "source_count": len(source_classes),
            "grounded_source_count": grounded_count,
            "risky_source_count": risky_count,
            "missing_source_count": classes.get("unknown", 0),
            "mixed": bool(grounded_count and risky_count),
        }

    @classmethod
    def _projection_reality_monitoring_from_calibration(cls, calibration: dict[str, Any]) -> dict[str, Any]:
        monitoring = calibration.get("reality_monitoring") if isinstance(calibration, dict) else None
        if isinstance(monitoring, dict):
            normalized = cls._normalise_reality_class(monitoring.get("reality_class")) or "unknown"
            return {**monitoring, "reality_class": normalized}
        normalized = cls._normalise_reality_class(monitoring) or cls._normalise_reality_class(
            calibration.get("reality_class") if isinstance(calibration, dict) else None
        )
        return {
            "source": "legacy_or_unclassified_projection",
            "applied": False,
            "reality_class": normalized or "unknown",
        }

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
        access_policy = validate_access_policy(
            relation.access_policy,
            tenant_id=relation.tenant_id,
            location="relation.access_policy",
        )
        with self._lock:
            self._require_branch(branch)
            item = copy.deepcopy(relation)
            item.access_policy = access_policy
            item.branch = branch
            key = self._branch_key(item.tenant_id, branch, item.id)
            self.relations[key] = item
            self._audit(
                item.tenant_id,
                "engine",
                "add_relation",
                item.id,
                {"relation_source": item.source, "target": item.target, "source_evidence_cids": item.source_evidence_cids},
                source="relation",
            )
            self._persist()
            return item.id

    def add_justification(self, justification: Justification) -> str:
        with self._lock:
            item = copy.deepcopy(justification)
            self.justifications[item.id] = item
            self._audit(
                item.tenant_id,
                "engine",
                "add_justification",
                item.id,
                {
                    "assertion_id": item.assertion_id,
                    "evidence_cids": item.evidence_cids,
                    "dependencies": item.dependency_ids,
                },
                source="justification",
            )
            self._persist()
            return item.id

    def add_contradiction(self, contradiction: Contradiction) -> str:
        with self._lock:
            item = copy.deepcopy(contradiction)
            existing = [
                row
                for row in self.contradictions.values()
                if row.tenant_id == item.tenant_id
                and {row.a, row.b} == {item.a, item.b}
                and row.status == "open"
            ]
            if existing:
                return existing[0].id
            self.contradictions[item.id] = item
            self._audit(
                item.tenant_id,
                "engine",
                "add_contradiction",
                item.id,
                {"a": item.a, "b": item.b},
                source="contradiction",
            )
            self._persist()
            return item.id

    def add_preference(self, preference: Preference) -> str:
        access_policy = validate_access_policy(
            preference.access_policy,
            tenant_id=preference.tenant_id,
            location="preference.access_policy",
        )
        with self._lock:
            pref = copy.deepcopy(preference)
            pref.access_policy = access_policy
            existing = [
                item
                for item in self.preferences.values()
                if item.tenant_id == pref.tenant_id
                and item.user_id == pref.user_id
                and item.category == pref.category
                and item.scope == pref.scope
                and item.status == "active"
            ]
            for item in existing:
                if item.statement != pref.statement:
                    if pref.explicit or not item.explicit:
                        item.status = "superseded"
                        item.valid_to = pref.valid_from
                    else:
                        pref.status = "retracted"
            self.preferences[pref.id] = pref
            self._audit(
                pref.tenant_id,
                "engine",
                "add_preference",
                pref.id,
                {
                    "category": pref.category,
                    "explicit": pref.explicit,
                    "source_evidence_cids": pref.source_evidence_cids,
                    "access_policy": pref.access_policy,
                },
                source="preference",
                trust_tier=0 if pref.explicit else None,
            )
            self._persist()
            return pref.id

    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        query_vec = embed_query(self.adapters.embedding, query)
        hits: list[Hit] = []
        if text_kernels.NATIVE is not None:
            # Batched fast path: embedding acquisition stays per-hit in Python
            # (same security-gated _embedding_for_hit call, same metadata side
            # effects, once per hit, in candidate order), then ONE dense_scan
            # FFI crossing scores every row. The kernel is byte-parity-proven
            # against the per-hit cosine loop (tests/test_native_parity.py);
            # None vectors pass through as None, keeping results index-aligned.
            # NOTE: dense_scan_packed (flat LE-f64 bytes) was measured here and
            # NOT adopted — packing list vectors with array.array('d') per call
            # costs more than the list FFI path end-to-end (see the seam-choice
            # comment in tests/benchmarks/test_retrieval_baselines.py).
            candidates = self._candidate_hits(filt)
            vectors = [self._embedding_for_hit(hit, filt) for hit in candidates]
            scores = text_kernels.NATIVE.dense_scan(query_vec, vectors)
            for hit, hit_vec, score in zip(candidates, vectors, scores, strict=True):
                if hit_vec is None:
                    continue
                if score > 0:
                    hit.score = score
                    stored_raw = bool(hit.metadata.get("stored_embedding_used"))
                    hit.channel = "dense_media" if stored_raw and hit.metadata.get("stored_media_embedding") else "dense_hash"
                    hits.append(hit)
        else:
            for hit in self._candidate_hits(filt):
                hit_vec = self._embedding_for_hit(hit, filt)
                if hit_vec is None:
                    continue
                score = cosine(query_vec, hit_vec)
                if score > 0:
                    hit.score = score
                    stored_raw = bool(hit.metadata.get("stored_embedding_used"))
                    hit.channel = "dense_media" if stored_raw and hit.metadata.get("stored_media_embedding") else "dense_hash"
                    hits.append(hit)
        return self._mark_retrieved_text_as_data(sorted(hits, key=lambda item: item.score, reverse=True)[:k])

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        tenant_id = str(filt.get("tenant_id") or "")
        branch = str(filt.get("branch") or "main")
        if self.adapters.lexical_retriever is not None:
            hits = self.adapters.lexical_retriever.search(
                query,
                tenant_id=tenant_id,
                branch=branch,
                k=k,
                filt=filt,
            )
            hits = validate_adapter_hit_scope(
                hits,
                tenant_id=tenant_id,
                branch=branch,
                k=k,
                adapter_name="lexical",
            )
            return self._mark_retrieved_text_as_data(hits)
        hits: list[Hit] = []
        if text_kernels.NATIVE is not None:
            # Batched fast path (adapterless fallback only): ONE lexical_scan
            # FFI crossing scores every candidate text; byte-parity-proven
            # against the per-hit lexical_score loop (tests/test_native_parity.py).
            candidates = self._candidate_hits(filt)
            scores = text_kernels.NATIVE.lexical_scan(query, [hit.text for hit in candidates])
            for hit, score in zip(candidates, scores, strict=True):
                if score > 0:
                    hit.score = score
                    hit.channel = "lexical"
                    hits.append(hit)
        else:
            for hit in self._candidate_hits(filt):
                score = lexical_score(query, hit.text)
                if score > 0:
                    hit.score = score
                    hit.channel = "lexical"
                    hits.append(hit)
        return self._mark_retrieved_text_as_data(sorted(hits, key=lambda item: item.score, reverse=True)[:k])

    def graph_ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
        use_cache: bool = False,
        filt: dict[str, Any] | None = None,
    ) -> list[Hit]:
        seed_set = {seed.lower() for seed in seeds}
        if not seed_set:
            return []
        moment = as_of or utc_now()
        moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
        graph_filter = dict(filt or {})
        if tenant_id is not None:
            graph_filter.setdefault("tenant_id", tenant_id)
        if branch is not None:
            graph_filter.setdefault("branch", branch)
        include_quarantined = bool(graph_filter.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(graph_filter.get("max_trust_tier", graph_filter.get("min_trust_tier", default_max_trust)))
        max_sensitivity = effective_max_sensitivity(graph_filter, self.policy.max_sensitivity)
        if self.adapters.graph_retriever is not None and tenant_id:
            hits = self.adapters.graph_retriever.search(
                seeds,
                tenant_id=tenant_id,
                branch=branch or "main",
                k=k,
                as_of=moment,
                filt=graph_filter,
            )
            hits = validate_adapter_hit_scope(
                hits,
                tenant_id=tenant_id,
                branch=branch or "main",
                k=k,
                adapter_name="graph",
            )
            hits = self._filter_graph_adapter_hits(
                hits,
                branch=branch or "main",
                include_quarantined=include_quarantined,
                max_trust=max_trust,
                max_sensitivity=max_sensitivity,
                access_context=graph_filter,
            )
            return self._mark_retrieved_text_as_data(hits)

        def matches_seed(node: str) -> bool:
            node_lower = node.lower()
            return node_lower in seed_set or bool(set(tokenize(node_lower)) & seed_set)

        adjacency: dict[str, set[str]] = defaultdict(set)
        relation_by_pair: dict[tuple[str, str], tuple[Relation, dict[str, Any], Any]] = {}
        for rel in self.relations.values():
            if tenant_id is not None and rel.tenant_id != tenant_id:
                continue
            if branch is not None and rel.branch != branch:
                continue
            if not self._valid_at(rel.valid_from, rel.valid_to, moment):
                continue
            security = self._relation_hit_security(
                rel,
                branch=rel.branch,
                include_quarantined=include_quarantined,
                max_trust=max_trust,
                max_sensitivity=max_sensitivity,
                access_context=graph_filter,
            )
            if security is None:
                continue
            relation_decision = may_read_item(
                item_tenant_id=rel.tenant_id,
                sensitivity=int(security["sensitivity"]),
                access_policy=rel.access_policy,
                context=graph_filter,
                policy_max_sensitivity=self.policy.max_sensitivity,
                status="active",
            )
            if not relation_decision.allowed:
                continue
            adjacency[rel.source.lower()].add(rel.target.lower())
            adjacency[rel.target.lower()].add(rel.source.lower())
            relation_by_pair[(rel.source.lower(), rel.target.lower())] = (rel, security, relation_decision)
            relation_by_pair[(rel.target.lower(), rel.source.lower())] = (rel, security, relation_decision)
        hits: list[Hit] = []
        seen_relation_ids: set[str] = set()
        for rel, security, relation_decision in {row[0].id: row for row in relation_by_pair.values()}.values():
            if not (matches_seed(rel.source) and matches_seed(rel.target)):
                continue
            text, privacy_metadata = apply_relation_redactions(
                source=rel.source,
                predicate=rel.predicate,
                target=rel.target,
                access_policy=rel.access_policy,
                decision=relation_decision,
            )
            relation_fields = privacy_metadata.get("redacted_record")
            if not isinstance(relation_fields, dict):
                relation_fields = {"source": rel.source, "predicate": rel.predicate, "target": rel.target}
            seen_relation_ids.add(rel.id)
            hits.append(
                Hit(
                    id=rel.id,
                    kind="relation",
                    tenant_id=rel.tenant_id,
                    branch=rel.branch,
                    text=text,
                    score=float(rel.confidence),
                    channel="graph_ppr",
                    provenance=rel.source_evidence_cids,
                    trust_tier=security["trust_tier"],
                    sensitivity=security["sensitivity"],
                    metadata={
                        "source": relation_fields["source"],
                        "predicate": relation_fields["predicate"],
                        "target": relation_fields["target"],
                        "confidence": rel.confidence,
                        "source_evidence_cids": list(rel.source_evidence_cids),
                        "reality_class": security["reality_class"],
                        "source_evidence_status": security["source_evidence_status"],
                        "source_evidence_security": security["source_evidence_security"],
                        "direct_seed_relation": True,
                        "privacy": privacy_metadata,
                    },
                )
            )
            if len(hits) >= k:
                return self._mark_retrieved_text_as_data(hits)
        for seed in seed_set:
            adjacency.setdefault(seed, [])
        ranks = ppr_power_iteration(adjacency, matches_seed)
        # node -> relation row index, built once (was an O(V*E) per-node linear
        # scan). First-match semantics replicated exactly: for each node the
        # winning row is the one the linear scan found FIRST in relation_by_pair
        # insertion order — the earliest pair mentioning the node in either slot.
        relation_by_node: dict[str, tuple[Relation, dict[str, Any], Any]] = {}
        for pair, row in relation_by_pair.items():
            for pair_node in pair:
                if pair_node not in relation_by_node:
                    relation_by_node[pair_node] = row
        for node, score in sorted(ranks.items(), key=lambda item: item[1], reverse=True):
            if matches_seed(node) or score <= 0:
                continue
            relation_row = relation_by_node.get(node)
            if relation_row:
                rel, security, relation_decision = relation_row
                if rel.id in seen_relation_ids:
                    continue
                text, privacy_metadata = apply_relation_redactions(
                    source=rel.source,
                    predicate=rel.predicate,
                    target=rel.target,
                    access_policy=rel.access_policy,
                    decision=relation_decision,
                )
                relation_fields = privacy_metadata.get("redacted_record")
                if not isinstance(relation_fields, dict):
                    relation_fields = {"source": rel.source, "predicate": rel.predicate, "target": rel.target}
                seen_relation_ids.add(rel.id)
                hits.append(
                    Hit(
                        id=rel.id,
                        kind="relation",
                        tenant_id=rel.tenant_id,
                        branch=rel.branch,
                        text=text,
                        score=score,
                        channel="graph_ppr",
                        provenance=rel.source_evidence_cids,
                        trust_tier=security["trust_tier"],
                        sensitivity=security["sensitivity"],
                        metadata={
                            "source": relation_fields["source"],
                            "predicate": relation_fields["predicate"],
                            "target": relation_fields["target"],
                            "confidence": rel.confidence,
                            "source_evidence_cids": list(rel.source_evidence_cids),
                            "reality_class": security["reality_class"],
                            "source_evidence_status": security["source_evidence_status"],
                            "source_evidence_security": security["source_evidence_security"],
                            "privacy": privacy_metadata,
                        },
                    )
                )
            if len(hits) >= k:
                break
        return self._mark_retrieved_text_as_data(hits)

    #: explain["channels"] key names consumed by the shared pipeline.
    retrieval_explain_channel_keys: tuple[str, str, str] = ("dense_hash", "lexical", "graph_ppr")

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        branch: str = "main",
        deep: bool = False,
        filt: dict[str, Any] | None = None,
        *,
        record_access: bool = True,
    ) -> RetrievalResult:
        return run_retrieval_pipeline(
            self,
            query=query,
            tenant_id=tenant_id,
            branch=branch,
            deep=deep,
            filt=filt,
            policy=self.policy,
            record_access=record_access,
        )

    def set_calibration(self, calibration: CalibrationSet) -> None:
        with self._lock:
            self.calibrations[(calibration.tenant_id, calibration.memory_type)] = copy.deepcopy(calibration)
            self._audit(
                calibration.tenant_id,
                "engine",
                "set_calibration",
                calibration.memory_type,
                {"scores": len(calibration.scores), "target_coverage": calibration.target_coverage},
            )
            self._persist()

    def register_entity(
        self,
        tenant_id: str,
        canonical: str,
        *,
        alias: str | None = None,
        entity_type: str = "unknown",
        summary: str | None = None,
        source_evidence_cids: list[str] | None = None,
        access_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        canonical = canonical.strip() or "unknown-entity"
        incoming_access_policy = validate_access_policy(
            access_policy if access_policy is not None else {"tenant": tenant_id},
            tenant_id=tenant_id,
            location="entity.access_policy",
        )
        source_cids = list(source_evidence_cids or [])
        aliases = {canonical}
        if alias and alias.strip():
            aliases.add(alias.strip())
        with self._lock:
            key = (tenant_id, canonical)
            existing = self.entities.get(key)
            if existing is None:
                effective_access_policy = incoming_access_policy
                row = {
                    "id": new_id(),
                    "tenant_id": tenant_id,
                    "canonical": canonical,
                    "type": entity_type,
                    "summary": summary,
                    "salience": 0.5,
                    "aliases": [],
                    "source_evidence_cids": [],
                    "access_policy": effective_access_policy,
                    "updated_at": utc_now().isoformat(),
                }
            else:
                row = existing
                current_access_policy = validate_access_policy(
                    row.get("access_policy") or {"tenant": tenant_id},
                    tenant_id=tenant_id,
                    location="entity.access_policy",
                )
                effective_access_policy = (
                    merge_access_policies([current_access_policy, incoming_access_policy], tenant_id=tenant_id)
                    if access_policy is not None
                    else current_access_policy
                )
            row["type"] = row.get("type") or entity_type
            if summary:
                row["summary"] = summary
            row["access_policy"] = effective_access_policy
            row["aliases"] = sorted(set(row.get("aliases", [])) | aliases)
            row["source_evidence_cids"] = sorted(set(row.get("source_evidence_cids", [])) | set(source_cids))
            row["updated_at"] = utc_now().isoformat()
            self.entities[key] = row
            self._audit(tenant_id, "engine", "register_entity", canonical, {"aliases": row["aliases"]})
            self._persist()
            return dict(row)

    def _calibration_for(self, tenant_id: str, memory_type: str) -> CalibrationSet | None:
        return self.calibrations.get((tenant_id, memory_type))

    def _calibration_explain(self, calibration: CalibrationSet | None, threshold: float) -> dict[str, Any]:
        if calibration is None:
            return {"source": "policy", "memory_type": "fact", "threshold": threshold}
        return {
            "source": "conformal",
            "memory_type": calibration.memory_type,
            "threshold": threshold,
            "target_coverage": calibration.target_coverage,
            "scores": len(calibration.scores),
        }

    def _record_retrieval_access(self, hits: list[Hit]) -> dict[str, int]:
        if self._read_only:
            return {"assertions": 0, "evidence": 0}
        touched_assertions = 0
        touched_evidence = 0
        now = utc_now()
        with self._lock:
            evidence_cids: set[tuple[str, str, str]] = set()
            for hit in hits:
                if hit.kind == "working":
                    continue
                if hit.kind == "evidence" and hit.id:
                    evidence_cids.add((hit.tenant_id, hit.branch, hit.id))
                for cid in hit.provenance:
                    if cid:
                        evidence_cids.add((hit.tenant_id, hit.branch, str(cid)))
                if hit.kind == "assertion":
                    assertion = self.assertions.get(self._branch_key(hit.tenant_id, hit.branch, hit.id))
                    if assertion is None:
                        continue
                    assertion.last_accessed = now
                    assertion.access_count += 1
                    touched_assertions += 1
                    for cid in assertion.source_evidence_cids:
                        if cid:
                            evidence_cids.add((assertion.tenant_id, assertion.branch, str(cid)))
            for tenant_id, branch, cid in sorted(evidence_cids):
                ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
                if ev is None or ev.erased:
                    continue
                metadata = dict(ev.metadata)
                lifecycle = metadata.get("lifecycle")
                lifecycle = dict(lifecycle) if isinstance(lifecycle, dict) else {}
                try:
                    access_count = int(lifecycle.get("access_count", 0))
                except (TypeError, ValueError):
                    access_count = 0
                access_count += 1
                lifecycle["access_count"] = access_count
                lifecycle["last_accessed"] = now.isoformat()
                lifecycle["salience"] = min(1.0, _bounded_float(lifecycle.get("salience", 0.5), default=0.5) + 0.05)
                metadata["lifecycle"] = lifecycle
                ev.metadata = metadata
                touched_evidence += 1
            if touched_assertions or touched_evidence:
                self._persist()
        return {"assertions": touched_assertions, "evidence": touched_evidence}

    @staticmethod
    def _normalise_reality_class(value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower().replace("-", "_")
        aliases = {
            "grounded": "grounded",
            "evidence_grounded": "grounded",
            "external": "externally_suggested",
            "external_grounded": "grounded",
            "observed": "grounded",
            "user_grounded": "grounded",
            "self_generated": "self_generated",
            "self": "self_generated",
            "generated": "self_generated",
            "assistant_generated": "self_generated",
            "simulation": "simulated",
            "simulated": "simulated",
            "externally_suggested": "externally_suggested",
            "suggested": "externally_suggested",
            "untrusted_suggestion": "externally_suggested",
        }
        return aliases.get(normalized)

    @classmethod
    def _classify_evidence_reality(cls, ev: Evidence) -> str:
        explicit = cls._normalise_reality_class(ev.metadata.get("reality_class"))
        source_type = ev.source_type.lower()
        actor = ev.actor.lower()
        if any(marker in source_type for marker in ("simulation", "synthetic", "generated", "hypothesis")):
            base_class = "simulated"
        elif any(marker in source_type for marker in ("summary", "trace", "analysis", "consolidation")):
            base_class = "self_generated"
        elif actor == "assistant":
            base_class = "self_generated"
        elif actor in {"system", "tool"} and any(
            marker in source_type for marker in ("scratchpad", "workspace", "thought", "reflection")
        ):
            base_class = "self_generated"
        elif actor == "external" or ev.trust_tier >= int(TrustTier.LOW):
            base_class = "externally_suggested"
        else:
            base_class = "grounded"
        if explicit == "grounded" and base_class != "grounded":
            return "unknown"
        return explicit or base_class

    @staticmethod
    def _hit_source_evidence_cids(hit: Hit) -> list[str]:
        raw = hit.metadata.get("source_evidence_cids")
        if isinstance(raw, list | tuple):
            return [str(cid) for cid in raw if str(cid)]
        if isinstance(raw, str) and raw:
            return [raw]
        return [str(cid) for cid in hit.provenance if str(cid)]

    def _filter_graph_adapter_hits(
        self,
        hits: list[Hit],
        *,
        branch: str,
        include_quarantined: bool,
        max_trust: int,
        max_sensitivity: int,
        access_context: dict[str, Any] | None,
    ) -> list[Hit]:
        filtered: list[Hit] = []
        for hit in hits:
            if hit.kind != "relation":
                continue
            source_cids = self._hit_source_evidence_cids(hit)
            relation = Relation(
                tenant_id=hit.tenant_id,
                source=str(hit.metadata.get("source") or hit.text),
                predicate=str(hit.metadata.get("predicate") or "related_to"),
                target=str(hit.metadata.get("target") or hit.text),
                branch=hit.branch,
                source_evidence_cids=source_cids,
            )
            security = self._relation_hit_security(
                relation,
                branch=hit.branch or branch,
                include_quarantined=include_quarantined,
                max_trust=max_trust,
                max_sensitivity=max_sensitivity,
                access_context=access_context,
            )
            if security is None:
                continue
            hit.trust_tier = int(security["trust_tier"])
            hit.sensitivity = int(security["sensitivity"])
            hit.provenance = list(source_cids)
            hit.metadata = {
                **hit.metadata,
                "source_evidence_cids": list(source_cids),
                "source_evidence_status": security["source_evidence_status"],
                "source_evidence_security": security["source_evidence_security"],
                "independent_corroboration": security["independent_corroboration"],
                "reality_class": security["reality_class"],
            }
            filtered.append(hit)
        return filtered

    def _relation_hit_security(
        self,
        relation: Relation,
        *,
        branch: str,
        include_quarantined: bool,
        max_trust: int,
        max_sensitivity: int,
        access_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        source_cids = [cid for cid in relation.source_evidence_cids if cid]
        if not source_cids:
            return None

        source_rows: list[Evidence] = []
        for cid in source_cids:
            ev = self.evidence.get(self._evidence_key(relation.tenant_id, branch, cid))
            if ev is None or ev.erased:
                return None
            if not include_quarantined and ev.metadata.get("quarantine_reason"):
                return None
            if is_retired_summary_metadata(ev.metadata):
                return None
            decision = may_read_item(
                item_tenant_id=ev.tenant_id,
                sensitivity=int(ev.sensitivity),
                access_policy=ev.access_policy,
                context={**dict(access_context or {}), "tenant_id": relation.tenant_id},
                policy_max_sensitivity=self.policy.max_sensitivity,
                status="active",
                erased=ev.erased,
            )
            if not decision.allowed:
                return None
            source_rows.append(ev)

        trust_tier = max(int(ev.trust_tier) for ev in source_rows)
        sensitivity = max(int(ev.sensitivity) for ev in source_rows)
        if trust_tier > max_trust or sensitivity > max_sensitivity:
            return None

        reality_classes = [self._classify_evidence_reality(ev) for ev in source_rows]
        corroboration = self._independent_corroboration_report_from_evidence(source_rows)
        return {
            "trust_tier": trust_tier,
            "sensitivity": sensitivity,
            "reality_class": self._aggregate_reality_classes(reality_classes),
            "source_evidence_status": "source_evidence_visible",
            "independent_corroboration": corroboration,
            "source_evidence_security": [
                {
                    "cid": ev.cid,
                    "trust_tier": int(ev.trust_tier),
                    "sensitivity": int(ev.sensitivity),
                    "reality_class": self._classify_evidence_reality(ev),
                    "access_policy_enforced": True,
                }
                for ev in source_rows
            ],
        }

    def _standing_signals_for_hit(self, hit: Hit, reality_class: str) -> dict[str, Any]:
        activation = hit.metadata.get("activation") if isinstance(hit.metadata, dict) else {}
        lifecycle = hit.metadata.get("lifecycle") if isinstance(hit.metadata, dict) else {}
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        earned_autonomy = hit.metadata.get("earned_autonomy") if isinstance(hit.metadata, dict) else {}
        earned_autonomy = earned_autonomy if isinstance(earned_autonomy, dict) else {}
        source_cids = self._hit_source_evidence_cids(hit)
        if hit.kind == "evidence" and hit.id:
            source_cids = sorted(set(source_cids + [hit.id]))
        corroboration = hit.metadata.get("independent_corroboration") if isinstance(hit.metadata, dict) else None
        if not isinstance(corroboration, dict):
            corroboration = self._independent_corroboration_report(
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                source_evidence_cids=source_cids,
            )
        return {
            "reality_class": reality_class,
            "trust_tier": hit.trust_tier,
            "calibrated_confidence": hit.metadata.get("confidence", 0.0),
            "corroboration_count": len(source_cids),
            "independent_corroboration_count": corroboration["independent_corroboration_count"],
            "independent_corroboration_weight": corroboration["independent_corroboration_weight"],
            "self_generated_corroboration_count": corroboration["self_generated_corroboration_count"],
            "rejected_corroboration_count": corroboration["rejected_corroboration_count"],
            "contradiction_pressure": 1.0 if hit.metadata.get("status") == "contested" else 0.0,
            "groundedness_decay": lifecycle.get("decay", lifecycle.get("groundedness_decay", 0.0)),
            "activation": activation.get("score") if isinstance(activation, dict) else 0.0,
            "lifecycle_salience": lifecycle.get("salience", 0.0),
            "birth_groundedness": earned_autonomy.get(
                "birth_groundedness",
                hit.metadata.get("birth_groundedness") if isinstance(hit.metadata, dict) else None,
            ),
        }

    def _independent_corroboration_report(
        self,
        *,
        tenant_id: str,
        branch: str,
        source_evidence_cids: list[str],
    ) -> dict[str, Any]:
        rows: list[Evidence] = []
        missing: list[str] = []
        for cid in sorted({str(item) for item in source_evidence_cids if item}):
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            if ev is None:
                missing.append(cid)
            else:
                rows.append(ev)
        report = self._independent_corroboration_report_from_evidence(rows)
        for cid in missing:
            report["rejected_corroborators"].append({"cid": cid, "reason": "missing"})
        report["rejected_corroboration_count"] = len(report["rejected_corroborators"])
        return report

    def _independent_corroboration_report_from_evidence(self, rows: list[Evidence]) -> dict[str, Any]:
        roots: set[str] = set()
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        self_generated_count = 0
        trust_sum = 0.0
        for ev in rows:
            cid = ev.cid or ""
            metadata = ev.metadata if isinstance(ev.metadata, dict) else {}
            reason = None
            if ev.erased:
                reason = "erased"
            elif metadata.get("quarantine_reason"):
                reason = "quarantined"
            elif is_retired_summary_metadata(metadata):
                reason = "retired"
            elif is_write_tainted(ev.capability_tags):
                reason = "sanitized_data_only"
            reality_class = self._classify_evidence_reality(ev)
            if reason is None and reality_class != "grounded":
                reason = f"not_grounded:{reality_class}"
                if reality_class in {"self_generated", "simulated"}:
                    self_generated_count += 1
            if reason is None and self._has_self_generated_ancestor(metadata):
                reason = "shares_self_generated_ancestor"
            root = self._independent_source_key(ev)
            if reason is None and root in roots:
                reason = "duplicate_source_root"
            if reason is not None:
                rejected.append({"cid": cid, "reason": reason, "reality_class": reality_class})
                continue
            roots.add(root)
            weight = trust_weight(int(ev.trust_tier))
            trust_sum += weight
            accepted.append(
                {
                    "cid": cid,
                    "root": root,
                    "trust_tier": int(ev.trust_tier),
                    "weight": round(weight, 6),
                }
            )
        return {
            "independent_corroboration_count": len(accepted),
            "independent_corroboration_weight": round(min(trust_sum, 5.0) / 5.0, 6),
            "self_generated_corroboration_count": self_generated_count,
            "rejected_corroboration_count": len(rejected),
            "accepted_corroborators": accepted,
            "rejected_corroborators": rejected,
        }

    @staticmethod
    def _has_self_generated_ancestor(metadata: dict[str, Any]) -> bool:
        keys = (
            "self_generated_ancestor_cids",
            "self_generated_ancestors",
            "derived_from_self_cids",
            "source_self_cids",
        )
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, list | tuple | set) and any(str(item) for item in value):
                return True
            if isinstance(value, str) and value.strip():
                return True
        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            return bool(provenance.get("self_generated") or provenance.get("self_generated_ancestor"))
        return False

    @staticmethod
    def _independent_source_key(ev: Evidence) -> str:
        identity = ev.source_identity or ev.content_pointer or ev.cid or ev.content
        return f"{ev.source_type}:{identity}"

    def _apply_standing_scores(self, hits: list[Hit]) -> list[Hit]:
        weighted: list[Hit] = []
        for hit in hits:
            reality_class = self._normalise_reality_class(hit.metadata.get("reality_class")) or "unknown"
            score = standing(self._standing_signals_for_hit(hit, reality_class))
            multiplier = 0.75 + 0.20 * score.groundedness + 0.05 * score.salience
            source_cids = self._hit_source_evidence_cids(hit)
            if hit.kind == "evidence" and hit.id:
                source_cids = sorted(set(source_cids + [hit.id]))
            metadata = {
                **hit.metadata,
                "standing": score.to_dict(),
                "standing_rank_multiplier": round(multiplier, 6),
                "standing_observability": standing_observability_record(
                    target_id=hit.id,
                    kind=hit.kind,
                    tenant_id=hit.tenant_id,
                    branch=hit.branch,
                    source_evidence_cids=source_cids,
                    score=score,
                    surface="retrieval.rank",
                ),
            }
            weighted.append(
                Hit(
                    id=hit.id,
                    kind=hit.kind,
                    tenant_id=hit.tenant_id,
                    branch=hit.branch,
                    text=hit.text,
                    score=max(hit.score, 0.0) * multiplier,
                    channel=hit.channel,
                    provenance=list(hit.provenance),
                    trust_tier=hit.trust_tier,
                    sensitivity=hit.sensitivity,
                    metadata=metadata,
                )
            )
        return sorted(weighted, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _aggregate_reality_classes(classes: list[str]) -> str:
        normalized = [item for item in classes if item]
        if not normalized:
            return "unknown"
        if all(item == "grounded" for item in normalized):
            return "grounded"
        if "self_generated" in normalized:
            return "self_generated"
        if "simulated" in normalized:
            return "simulated"
        if "externally_suggested" in normalized:
            return "externally_suggested"
        return "unknown"

    def _reality_monitoring_report(self, hits: list[Hit]) -> dict[str, Any]:
        risky = {"self_generated", "simulated", "externally_suggested"}
        ungrounded = risky | {"unknown"}
        counts: dict[str, int] = {}
        grounded_cids: set[str] = set()
        risky_hit_ids: list[str] = []
        shadow_tags: dict[str, dict[str, Any]] = {}
        standing_rows: list[dict[str, Any]] = []
        monitor = RealityMonitor()
        for index, hit in enumerate(hits):
            raw = hit.metadata.get("reality_class")
            reality_class = self._normalise_reality_class(raw) or "unknown"
            counts[reality_class] = counts.get(reality_class, 0) + 1
            tag = self._shadow_reality_monitor_tag(monitor, hit)
            shadow_tags[hit.id or f"{hit.kind}:{index}"] = tag
            if reality_class == "grounded":
                grounded_cids.update(str(cid) for cid in hit.provenance if cid)
                if hit.kind == "evidence" and hit.id:
                    grounded_cids.add(hit.id)
            elif reality_class in ungrounded:
                risky_hit_ids.append(hit.id)
            score = standing(self._standing_signals_for_hit(hit, reality_class))
            standing_rows.append(
                {
                    "hit_id": hit.id or f"{hit.kind}:{index}",
                    "kind": hit.kind,
                    "authority": score.authority,
                    "groundedness": score.groundedness,
                    "salience": score.salience,
                    "standing_fn_version": score.standing_fn_version,
                    "reality_class": reality_class,
                    "explain": score.explain,
                }
            )
        hit_count = len(hits)
        grounded = counts.get("grounded", 0)
        ungrounded_only = hit_count > 0 and grounded == 0 and any(counts.get(item, 0) for item in ungrounded)
        standing_report = standing_abstention_report(standing_rows)
        standing_report["p1_mirror"] = {
            "boolean_ungrounded_only": ungrounded_only,
            "standing_ungrounded_only": standing_report["abstention_gate"]["active"],
            "zero_divergence": standing_report["abstention_gate"]["active"] is ungrounded_only,
        }
        standing_report["legacy_reality_monitoring"] = {
            "ungrounded_only": ungrounded_only,
            "explain_only": True,
        }
        return {
            "applied": True,
            "classes": counts,
            "grounded_hit_count": grounded,
            "grounded_source_count": len(grounded_cids),
            "risky_hit_ids": risky_hit_ids,
            "ungrounded_only": ungrounded_only,
            "shadow_only": False,
            "critical_path": True,
            "abstention_gate": {
                "critical_path": True,
                "shadow_only": False,
                "trigger": "ungrounded_only",
                "active": ungrounded_only,
            },
            "shadow_source": "RealityMonitor",
            "shadow_tags_shadow_only": True,
            "shadow_tags_critical_path": False,
            "shadow_tags": shadow_tags,
            "standing": standing_report,
        }

    @staticmethod
    def _shadow_reality_monitor_tag(monitor: RealityMonitor, hit: Hit) -> dict[str, Any]:
        metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
        tag = monitor.tag(
            source_type=str(metadata.get("source_type") or hit.kind),
            actor=str(metadata.get("actor") or ""),
            trust_tier=int(hit.trust_tier),
            metadata={"reality_class": metadata.get("reality_class")},
            provenance_count=len(hit.provenance),
        )
        explicit_class = str(metadata.get("reality_class") or "").strip().lower().replace("-", "_")
        source_type = str(metadata.get("source_type") or hit.kind).strip().lower()
        preserve_simulated = explicit_class in {"simulated", "simulation"} and (
            hit.kind == "assertion"
            or any(marker in source_type for marker in ("simulation", "synthetic", "generated", "hypothesis"))
        )
        reality_class = "simulated" if preserve_simulated else tag.reality_class
        return {
            "reality_class": reality_class,
            "confidence": tag.confidence,
            "calibrated": tag.calibrated,
            "signals": tag.signals,
        }

    @staticmethod
    def _merge_schema_fast_path_reports(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
        boosted = sorted(set(first.get("boosted_hit_ids") or []) | set(second.get("boosted_hit_ids") or []))
        reasons: dict[str, Any] = {}
        if isinstance(first.get("reasons"), dict):
            reasons.update(first["reasons"])
        if isinstance(second.get("reasons"), dict):
            reasons.update(second["reasons"])
        return {
            "applied": bool(first.get("applied")) or bool(second.get("applied")),
            "boost": second.get("boost", first.get("boost")),
            "boosted_hit_ids": boosted,
            "reasons": reasons,
            "passes": [first, second],
        }

    def deep_search(self, query: str, tenant_id: str, branch: str = "main", filt: dict[str, Any] | None = None) -> RetrievalResult:
        return self.retrieve(query=query, tenant_id=tenant_id, branch=branch, deep=True, filt=filt)

    def explain(self, query: str, tenant_id: str, branch: str = "main") -> dict[str, Any]:
        result = self.retrieve(query=query, tenant_id=tenant_id, branch=branch, deep=True)
        return result.to_dict()

    def as_of(self, subject: str, predicate: str, t: datetime, tenant_id: str | None = None, branch: str = "main") -> list[Assertion]:
        moment = t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC)
        matches = []
        for item in self.assertions.values():
            if tenant_id and item.tenant_id != tenant_id:
                continue
            if item.branch != branch:
                continue
            if item.subject == subject and item.predicate == predicate and self._valid_at(item.valid_from, item.valid_to, moment):
                if item.status in {"active", "superseded", "contested"}:
                    matches.append(copy.deepcopy(item))
        return sorted(matches, key=lambda item: item.valid_from)

    def correct(
        self,
        tenant_id: str,
        user_id: str,
        subject: str,
        predicate: str,
        object_value: str,
        correction_text: str,
        branch: str = "main",
        confidence: float = 0.95,
    ) -> str:
        cid = self.append_evidence(
            Evidence(
                tenant_id=tenant_id,
                user_id=user_id,
                actor="user",
                source_type="correction",
                content=correction_text,
                trust_tier=0,
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )
        return self.upsert_assertion(
            Assertion(
                tenant_id=tenant_id,
                user_id=user_id,
                subject=subject,
                predicate=predicate,
                object=object_value,
                confidence=confidence,
                source_evidence_cids=[cid],
                status="active",
                trust_tier=0,
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )

    def forget(
        self,
        tenant_id: str,
        cid: str,
        branch: str = "main",
        requested_by: str = "user",
        erasure_mode: ErasureMode | str = ErasureMode.TOMBSTONE_RECOMPUTE,
    ) -> dict[str, Any]:
        with self._lock:
            before = (
                copy.deepcopy(self.evidence),
                copy.deepcopy(self.assertions),
                copy.deepcopy(self.relations),
                copy.deepcopy(self.preferences),
                copy.deepcopy(self.entities),
                copy.deepcopy(self.intentions),
                copy.deepcopy(self.working_memory),
                copy.deepcopy(self.audit_log),
                copy.deepcopy(self.deletion_log),
                copy.deepcopy(self.merge_log),
                self._store_version,
            )
            try:
                return self._forget_impl(
                    tenant_id,
                    cid,
                    branch=branch,
                    requested_by=requested_by,
                    erasure_mode=erasure_mode,
                )
            except BaseException:
                (
                    self.evidence,
                    self.assertions,
                    self.relations,
                    self.preferences,
                    self.entities,
                    self.intentions,
                    self.working_memory,
                    self.audit_log,
                    self.deletion_log,
                    self.merge_log,
                    self._store_version,
                ) = before
                raise

    @staticmethod
    def _redact_working_digests(
        value: Any, placeholder_map: dict[str, str]
    ) -> Any:
        redacted = redact_erased_cids(value, placeholder_map)
        placeholders = set(placeholder_map.values())

        def scrub(node: Any) -> Any:
            if isinstance(node, dict):
                result = {key: scrub(item) for key, item in node.items()}
                evidence_ids = result.get("evidence_ids")
                diff = result.get("diff")
                diff_evidence_ids = diff.get("evidence_ids") if isinstance(diff, dict) else None
                affected = (
                    isinstance(evidence_ids, list) and placeholders.intersection(evidence_ids)
                ) or (
                    isinstance(diff_evidence_ids, list)
                    and placeholders.intersection(diff_evidence_ids)
                )
                if affected:
                    result.pop("working_digest", None)
                    result.pop("working_item_digest", None)
                    if "id" in result:
                        result["id"] = new_id()
                return result
            if isinstance(node, list):
                return [scrub(item) for item in node]
            return node

        return scrub(redacted)

    def _forget_impl(
        self,
        tenant_id: str,
        cid: str,
        branch: str = "main",
        requested_by: str = "user",
        erasure_mode: ErasureMode | str = ErasureMode.TOMBSTONE_RECOMPUTE,
    ) -> dict[str, Any]:
        mode = ErasureMode(erasure_mode)
        with self._lock:
            key = self._evidence_key(tenant_id, branch, cid)
            ev = self.evidence.get(key)
            if not ev:
                return {"erased": False, "reason": "evidence_not_found", "cid": cid, "erasure_mode": mode.value}
            legal_blind = mode is ErasureMode.HARD_DELETE_LEGAL and requested_by == "legal"
            if legal_blind:
                derived_cids = self._derived_evidence_cids_forget(tenant_id, branch, cid)
                retained_derived: dict[str, dict[str, Any]] = {}
            else:
                derived_cids, retained_derived = self._derived_evidence_forget_plan(tenant_id, branch, cid)
            affected_cids = {cid, *derived_cids}
            cascade_metadata: dict[str, dict[str, Any]] = {}
            for affected_cid in affected_cids | set(retained_derived):
                affected = self.evidence.get(self._evidence_key(tenant_id, branch, affected_cid))
                if affected:
                    cascade_metadata[affected_cid] = {**dict(affected.metadata), "source_type": affected.source_type}
            if mode is ErasureMode.HARD_DELETE_LEGAL and requested_by != "legal":
                # §31 RAIL-2 / FR-8 (min_corroboration_for_delete): an operator-initiated
                # hard delete must not strand a projection. Refuse when removing this source
                # (and its derived footprint) would leave an active assertion with no
                # surviving support and fewer than `min_corroboration_for_delete` distinct
                # independent sources. A legal right-to-be-forgotten erasure
                # (requested_by="legal") is corroboration-blind and shreds regardless.
                minimum = self.policy.min_corroboration_for_delete
                blocking = [
                    assertion.id
                    for assertion in self.assertions.values()
                    if assertion.tenant_id == tenant_id
                    and assertion.branch == branch
                    and assertion.status == "active"
                    and affected_cids & set(assertion.source_evidence_cids)
                    and not (set(assertion.source_evidence_cids) - affected_cids)
                    and len(set(assertion.source_evidence_cids)) < minimum
                ]
                if blocking:
                    return {
                        "erased": False,
                        "reason": "min_corroboration_for_delete",
                        "cid": cid,
                        "erasure_mode": mode.value,
                        "min_corroboration_for_delete": minimum,
                        "blocking_assertions": blocking,
                    }
            if mode is ErasureMode.HARD_DELETE_LEGAL:
                self.evidence.pop(key, None)
                for derived_cid in derived_cids:
                    self.evidence.pop(self._evidence_key(tenant_id, branch, derived_cid), None)
            else:
                ev.content = ""
                ev.erased = True
                for derived_cid in derived_cids:
                    derived = self.evidence.get(self._evidence_key(tenant_id, branch, derived_cid))
                    if derived:
                        derived.content = ""
                        derived.erased = True
            for retained_cid, metadata in retained_derived.items():
                retained = self.evidence.get(self._evidence_key(tenant_id, branch, retained_cid))
                if retained:
                    retained.metadata = metadata
            retained_cascade_metadata = {
                retained_cid: {
                    **dict(metadata),
                    "source_type": cascade_metadata.get(retained_cid, {}).get("source_type", ""),
                }
                for retained_cid, metadata in retained_derived.items()
            }
            working_removals: list[tuple[tuple[str, str, str], dict[str, str]]] = []
            working_trims: list[tuple[tuple[str, str, str], list[str]]] = []
            for working_key, item in sorted(self.working_memory.items()):
                if item.tenant_id != tenant_id:
                    continue
                surviving = [cid for cid in item.evidence_ids if cid not in affected_cids]
                if len(surviving) == len(item.evidence_ids):
                    continue
                descriptor = {
                    "tenant_id": item.tenant_id,
                    "session_id": item.session_id,
                    "item_id": item.item_id,
                }
                if surviving:
                    working_trims.append((working_key, surviving))
                else:
                    working_removals.append((working_key, descriptor))
            propagated: dict[str, Any] = {
                "retracted_assertions": [],
                "trimmed_assertions": [],
                "retracted_preferences": [],
                "trimmed_preferences": [],
                "expired_relations": [],
                "trimmed_relations": [],
                "removed_entities": [],
                "trimmed_entities": [],
                "removed_intentions": [],
                "erased_derived_evidence": derived_cids,
                "retained_derived_evidence": sorted(retained_derived),
                "trimmed_derived_evidence": sorted(retained_derived),
                "removed_working_items": [
                    descriptor for _, descriptor in working_removals
                ],
                "trimmed_working_items": [
                    {
                        "tenant_id": self.working_memory[key].tenant_id,
                        "session_id": self.working_memory[key].session_id,
                        "item_id": self.working_memory[key].item_id,
                    }
                    for key, _ in working_trims
                ],
            }
            for intention_key, intention in list(self.intentions.items()):
                if intention.tenant_id != tenant_id:
                    continue
                if not affected_cids.intersection(intention.evidence_ids):
                    continue
                self.intentions.pop(intention_key, None)
                propagated["removed_intentions"].append(intention.intention_id)
            propagated["standing_cascade"] = standing_erasure_cascade_report(
                source_cid=cid,
                erasure_mode=mode.value,
                affected_cids=affected_cids | set(retained_derived),
                erased_derived_cids=derived_cids,
                retained_metadata_by_cid=retained_cascade_metadata,
                metadata_by_cid=cascade_metadata,
            )
            for assertion in self.assertions.values():
                if assertion.tenant_id != tenant_id or assertion.branch != branch:
                    continue
                if not affected_cids.intersection(assertion.source_evidence_cids):
                    continue
                surviving_sources = [item for item in assertion.source_evidence_cids if item not in affected_cids]
                if not surviving_sources:
                    assertion.status = "retracted"
                    assertion.expired_at = utc_now()
                    assertion.source_evidence_cids = []
                    propagated["retracted_assertions"].append(assertion.id)
                else:
                    assertion.source_evidence_cids = surviving_sources
                    propagated["trimmed_assertions"].append(assertion.id)
            for preference in self.preferences.values():
                if preference.tenant_id != tenant_id:
                    continue
                if not affected_cids.intersection(preference.source_evidence_cids):
                    continue
                surviving_sources = [item for item in preference.source_evidence_cids if item not in affected_cids]
                if not surviving_sources:
                    preference.status = "retracted"
                    preference.valid_to = utc_now()
                    preference.source_evidence_cids = []
                    propagated["retracted_preferences"].append(preference.id)
                else:
                    preference.source_evidence_cids = surviving_sources
                    propagated["trimmed_preferences"].append(preference.id)
            for relation in self.relations.values():
                if relation.tenant_id != tenant_id or relation.branch != branch:
                    continue
                if not affected_cids.intersection(relation.source_evidence_cids):
                    continue
                surviving_sources = [item for item in relation.source_evidence_cids if item not in affected_cids]
                if not surviving_sources:
                    relation.valid_to = utc_now()
                    relation.source_evidence_cids = []
                    propagated["expired_relations"].append(relation.id)
                else:
                    relation.source_evidence_cids = surviving_sources
                    propagated["trimmed_relations"].append(relation.id)
            for key, entity in list(self.entities.items()):
                if entity.get("tenant_id") != tenant_id:
                    continue
                current_sources = list(entity.get("source_evidence_cids") or [])
                if not current_sources or not affected_cids.intersection(current_sources):
                    continue
                surviving_sources = [item for item in current_sources if item not in affected_cids]
                if surviving_sources:
                    entity["source_evidence_cids"] = surviving_sources
                    entity["updated_at"] = utc_now().isoformat()
                    propagated["trimmed_entities"].append(entity["canonical"])
                else:
                    self.entities.pop(key, None)
                    propagated["removed_entities"].append(entity["canonical"])
            for working_key, surviving in working_trims:
                working = self.working_memory.get(working_key)
                if working is None:
                    continue
                working.evidence_ids = surviving
                trust_tier, capability_tags, sensitivity, access_policy = self._working_provenance(working)
                working.trust_tier = trust_tier
                working.capability_tags = capability_tags
                working.sensitivity = sensitivity
                working.access_policy = access_policy
            for working_key, _ in working_removals:
                self.working_memory.pop(working_key, None)
            # Spec §7 privacy invariant 13: a hard delete is unrecoverable, so NO
            # retained record may carry the erased cid — not the deletion_log
            # evidence_cid, not the provenance arrays / standing-cascade refs inside
            # `propagated`, and not the audit row's target_id (all are retained). A
            # plaintext cid (a salted sha256 of the content) would let sha256(guess)
            # confirm the erasure. Build one per-erasure placeholder map (erased
            # source + erased-derived cids) and redact every retained copy; the map
            # is stable within the record (so it stays internally analyzable) yet
            # each token is a discarded-salt HMAC that sha256(guess) can't reproduce.
            # The dict RETURNED to the caller keeps the real cids — only the
            # persisted copies are redacted. tombstone_recompute keeps the real cids
            # (the tombstone row still lives in the ledger as the replay blocklist).
            if mode is ErasureMode.HARD_DELETE_LEGAL:
                placeholder_map = build_erasure_placeholder_map({cid, *derived_cids}, tenant_id)
                stored_propagated = redact_erased_cids(propagated, placeholder_map)
                # A legal hard delete must redact the erased provenance from
                # every retained custody record, including audits emitted
                # before this erasure was requested.
                self.audit_log[:] = [
                    self._redact_working_digests(record, placeholder_map)
                    for record in self.audit_log
                ]
                self.deletion_log[:] = [
                    self._redact_working_digests(record, placeholder_map)
                    for record in self.deletion_log
                ]
                self.merge_log[:] = [
                    self._redact_working_digests(record, placeholder_map)
                    for record in self.merge_log
                ]
                deletion_record_cid = erasure_deletion_record_id(cid, tenant_id, ev.user_id)
                audit_target_id = placeholder_map[cid]
            else:
                stored_propagated = propagated
                deletion_record_cid = cid
                audit_target_id = cid
            entry = {
                "id": new_id(),
                "tenant_id": tenant_id,
                "evidence_cid": deletion_record_cid,
                "requested_by": requested_by,
                "erasure_mode": mode.value,
                "propagated": stored_propagated,
                "at": utc_now().isoformat(),
            }
            self.deletion_log.append(entry)
            self._audit(
                tenant_id,
                requested_by,
                "forget",
                audit_target_id,
                {**stored_propagated, "erasure_mode": mode.value, "source_type": ev.source_type},
                source=ev.source_type,
                trust_tier=ev.trust_tier,
                capability_tags=ev.capability_tags,
            )
            self._persist()
            return {"erased": True, "cid": cid, "erasure_mode": mode.value, "propagated": propagated}

    def export_tenant(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "evidence": [item.to_dict() for item in self.evidence.values() if item.tenant_id == tenant_id and not item.erased],
            "assertions": [item.to_dict() for item in self.assertions.values() if item.tenant_id == tenant_id],
            "relations": [item.to_dict() for item in self.relations.values() if item.tenant_id == tenant_id],
            "preferences": [item.to_dict() for item in self.preferences.values() if item.tenant_id == tenant_id],
            "calibrations": [item.to_dict() for item in self.calibrations.values() if item.tenant_id == tenant_id],
            "entities": [dict(item) for item in self.entities.values() if item.get("tenant_id") == tenant_id],
            "justifications": [item.to_dict() for item in self.justifications.values() if item.tenant_id == tenant_id],
            "contradictions": [item.to_dict() for item in self.contradictions.values() if item.tenant_id == tenant_id],
            "working_memory": [
                item.to_dict()
                for item in self.working_memory.values()
                if item.tenant_id == tenant_id
            ],
            "audit_log": [item for item in self.audit_log if item.get("tenant_id") == tenant_id],
            "deletion_log": [item for item in self.deletion_log if item.get("tenant_id") == tenant_id],
            "merge_log": [
                item
                for item in self.merge_log
                if any(
                    audit.get("op") == "merge"
                    and audit.get("target_id") == item.get("from_branch")
                    and audit.get("tenant_id") in {tenant_id, "*"}
                    for audit in self.audit_log
                )
            ],
        }

    def export_tenant_filtered(self, tenant_id: str, access_context: dict[str, Any]) -> dict[str, Any]:
        return filter_export_for_context(
            self.export_tenant(tenant_id),
            {**dict(access_context or {}), "tenant_id": tenant_id},
            policy_max_sensitivity=self.policy.max_sensitivity,
        )

    def branch(self, name: str, frm: str = "main", kind: str = "scratch", tenant_id: str | None = None) -> None:
        with self._lock:
            if name in self.branches and tenant_id is None:
                return
            self._require_branch(frm)
            branch_meta = self.branches.setdefault(
                name,
                {"from": frm, "kind": kind, "created_at": utc_now().isoformat(), "tenants": []},
            )
            branch_tenants = set(branch_meta.get("tenants") or [])
            if tenant_id is not None and tenant_id in branch_tenants:
                return
            for ev in list(self.evidence.values()):
                if ev.branch == frm and (tenant_id is None or ev.tenant_id == tenant_id):
                    cloned = copy.deepcopy(ev)
                    cloned.branch = name
                    if cloned.cid:
                        self.evidence[self._evidence_key(cloned.tenant_id, name, cloned.cid)] = cloned
            for assertion in list(self.assertions.values()):
                if assertion.branch == frm and (tenant_id is None or assertion.tenant_id == tenant_id):
                    cloned = copy.deepcopy(assertion)
                    cloned.branch = name
                    self.assertions[self._branch_key(cloned.tenant_id, name, cloned.id)] = cloned
            for rel in list(self.relations.values()):
                if rel.branch == frm and (tenant_id is None or rel.tenant_id == tenant_id):
                    cloned = copy.deepcopy(rel)
                    cloned.branch = name
                    self.relations[self._branch_key(cloned.tenant_id, name, cloned.id)] = cloned
            if tenant_id is not None:
                branch_meta["tenants"] = sorted(branch_tenants | {tenant_id})
            self._audit(tenant_id or "*", "engine", "branch", name, {"from": frm, "kind": kind})
            self._persist()

    def merge(self, frm: str, into: str = "main", tenant_id: str | None = None) -> MergeReport:
        with self._lock:
            self._require_branch(frm)
            self._require_branch(into)
            report = MergeReport(frm, into, 0, 0, 0, 0, [])
            for ev in [
                item
                for item in self.evidence.values()
                if item.branch == frm and not item.erased and (tenant_id is None or item.tenant_id == tenant_id)
            ]:
                if not ev.cid:
                    continue
                target_key = self._evidence_key(ev.tenant_id, into, ev.cid)
                if target_key not in self.evidence:
                    cloned = copy.deepcopy(ev)
                    cloned.branch = into
                    self.evidence[target_key] = cloned
                    report.evidence_added += 1
            for assertion in [
                item
                for item in self.assertions.values()
                if item.branch == frm and (tenant_id is None or item.tenant_id == tenant_id)
            ]:
                before_count = len(self.assertions)
                cloned = copy.deepcopy(assertion)
                cloned.branch = into
                self.upsert_assertion(cloned, branch=into)
                if len(self.assertions) > before_count:
                    report.assertions_added += 1
                else:
                    report.assertions_merged += 1
            for rel in [
                item
                for item in self.relations.values()
                if item.branch == frm and (tenant_id is None or item.tenant_id == tenant_id)
            ]:
                peers = [
                    item
                    for item in self.relations.values()
                    if item.tenant_id == rel.tenant_id
                    and item.branch == into
                    and item.source == rel.source
                    and item.predicate == rel.predicate
                    and item.target == rel.target
                ]
                winner, redundant = _merge_relation_overlap_component(rel, peers)
                if winner is not None:
                    for peer in redundant:
                        self.relations.pop(
                            self._branch_key(peer.tenant_id, into, peer.id),
                            None,
                        )
                    continue
                cloned = copy.deepcopy(rel)
                cloned.branch = into
                target_key = self._branch_key(cloned.tenant_id, into, cloned.id)
                if target_key in self.relations:
                    cloned.id = new_id()
                    target_key = self._branch_key(cloned.tenant_id, into, cloned.id)
                self.relations[target_key] = cloned
                report.relations_added += 1
            self.merge_log.append(report.to_dict())
            self._audit(tenant_id or "*", "engine", "merge", frm, report.to_dict())
            self._persist()
            return report

    def discard(self, branch: str, tenant_id: str | None = None) -> None:
        if branch == "main":
            raise ValueError("main branch cannot be discarded")
        with self._lock:
            self._require_branch(branch)
            discarded_assertion_ids = {
                item.id
                for item in self.assertions.values()
                if item.branch == branch and (tenant_id is None or item.tenant_id == tenant_id)
            }
            self.evidence = {
                key: item
                for key, item in self.evidence.items()
                if not (item.branch == branch and (tenant_id is None or item.tenant_id == tenant_id))
            }
            self.assertions = {
                key: item
                for key, item in self.assertions.items()
                if not (item.branch == branch and (tenant_id is None or item.tenant_id == tenant_id))
            }
            self.relations = {
                key: item
                for key, item in self.relations.items()
                if not (item.branch == branch and (tenant_id is None or item.tenant_id == tenant_id))
            }
            surviving_assertion_ids = {
                item.id for item in self.assertions.values() if tenant_id is None or item.tenant_id == tenant_id
            }
            orphaned_assertion_ids = discarded_assertion_ids - surviving_assertion_ids
            if orphaned_assertion_ids:
                self.justifications = {
                    key: item
                    for key, item in self.justifications.items()
                    if (tenant_id is not None and item.tenant_id != tenant_id)
                    or (
                        item.assertion_id not in orphaned_assertion_ids
                        and not (set(item.dependency_ids) & orphaned_assertion_ids)
                    )
                }
                self.contradictions = {
                    key: item
                    for key, item in self.contradictions.items()
                    if (tenant_id is not None and item.tenant_id != tenant_id)
                    or (item.a not in orphaned_assertion_ids and item.b not in orphaned_assertion_ids)
                }
            branch_rows_remain = any(
                item.branch == branch for item in [*self.evidence.values(), *self.assertions.values(), *self.relations.values()]
            )
            if tenant_id is not None and branch_rows_remain:
                branch_meta = self.branches.get(branch)
                if branch_meta:
                    branch_meta["tenants"] = sorted(set(branch_meta.get("tenants") or []) - {tenant_id})
            else:
                self.branches.pop(branch, None)
            self._audit(tenant_id or "*", "engine", "discard", branch, {})
            self._persist()

    def _candidate_hits(self, filt: dict[str, Any]) -> list[Hit]:
        """Candidate projection with a small cross-call memo.

        The expensive scan (may_read_item + redactions over every evidence /
        assertion / preference row) is cached keyed on (tenant, branch, store
        version, store sizes, policy ceilings, access-context fingerprint), so
        one retrieve()'s vector and lexical channels share ONE scan. Callers
        always receive independent clones (see _clone_candidate_hit) — byte
        parity with an uncached scan is proven in
        tests/test_engine_perf_lanes.py. Kill-switch:
        MNEMOSYNE_CANDIDATE_MEMO=0.
        """
        if not _candidate_memo_enabled():
            return self._candidate_hits_uncached(filt)
        key = (
            filt.get("tenant_id"),
            filt.get("branch", "main"),
            self._store_version,
            len(self.evidence),
            len(self.assertions),
            len(self.preferences),
            int(self.policy.max_trust_tier),
            int(self.policy.max_sensitivity),
            # Access-context fingerprint: may_read_item / redactions read
            # arbitrary filt keys, so the whole mapping participates. Distinct
            # reprs of equal contexts only cost a miss, never a wrong hit.
            repr(sorted(filt.items())),
        )
        now = utc_now()
        cached: list[Hit] | None = None
        with self._candidate_memo_lock:
            entry = self._candidate_memo.get(key)
            if entry is not None:
                deadline, cached = entry
                if deadline is not None and now >= deadline:
                    # An access_policy.expires_at in scope has passed: the
                    # scan's may_read_item decisions changed with NO write, so
                    # the entry is stale despite the unchanged version key.
                    del self._candidate_memo[key]
                    cached = None
                else:
                    self._candidate_memo.move_to_end(key)
        if cached is None:
            cached = self._candidate_hits_uncached(filt)
            # Cutoff at the pre-scan `now`: an expiry crossing during the scan
            # lands <= a later lookup's clock, forcing a rescan (never a stale
            # serve). Expiries already past never flip back — no deadline.
            deadline = self._candidate_memo_deadline(
                filt.get("tenant_id"), filt.get("branch", "main"), now
            )
            with self._candidate_memo_lock:
                self._candidate_memo[key] = (deadline, cached)
                self._candidate_memo.move_to_end(key)
                while len(self._candidate_memo) > _CANDIDATE_MEMO_SIZE:
                    self._candidate_memo.popitem(last=False)
        return [_clone_candidate_hit(hit) for hit in cached]

    def _candidate_memo_deadline(self, tenant_id: Any, branch: Any, now: datetime) -> datetime | None:
        """Earliest future ``expires_at`` across the rows a candidate scan reads.

        ``may_read_item`` is time-dependent only through ``expires_at`` (a
        monotone allow→deny flip), so a memoized scan stays valid exactly until
        the first future deadline in scope. Denied-for-other-reasons rows are
        included conservatively: their deadline costs one extra rescan, never a
        wrong cached hit.
        """
        deadline: datetime | None = None
        policies = (
            *(ev.access_policy for ev in self.evidence.values() if ev.tenant_id == tenant_id and ev.branch == branch),
            *(a.access_policy for a in self.assertions.values() if a.tenant_id == tenant_id and a.branch == branch),
            *(p.access_policy for p in self.preferences.values() if p.tenant_id == tenant_id),
        )
        for policy in policies:
            if not policy:
                continue
            candidate = expiry_deadline(policy.get("expires_at"))
            if candidate is not None and candidate > now and (deadline is None or candidate < deadline):
                deadline = candidate
        return deadline

    def _candidate_hits_uncached(self, filt: dict[str, Any]) -> list[Hit]:
        tenant_id = filt.get("tenant_id")
        branch = filt.get("branch", "main")
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = effective_max_sensitivity(filt, self.policy.max_sensitivity)
        hits: list[Hit] = []
        for ev in self.evidence.values():
            if ev.erased or ev.tenant_id != tenant_id or ev.branch != branch:
                continue
            if ev.trust_tier > max_trust or ev.sensitivity > max_sensitivity:
                continue
            decision = may_read_item(
                item_tenant_id=ev.tenant_id,
                sensitivity=int(ev.sensitivity),
                access_policy=ev.access_policy,
                context=filt,
                policy_max_sensitivity=self.policy.max_sensitivity,
                status="active",
                erased=ev.erased,
            )
            if not decision.allowed:
                continue
            if not include_quarantined and ev.metadata.get("quarantine_reason"):
                continue
            if is_retired_summary_metadata(ev.metadata):
                continue
            text, privacy_metadata = apply_text_redactions(
                ev.content or ev.content_pointer or f"{ev.modality} evidence",
                ev.access_policy,
                decision,
            )
            metadata = {
                "actor": ev.actor,
                "source_type": ev.source_type,
                "modality": ev.modality,
                "content_pointer": ev.content_pointer,
                "reality_class": self._classify_evidence_reality(ev),
                "stored_media_embedding": bool(ev.embedding and ev.modality != "text"),
                "embedding_partition": vector_partition_for_item(
                    sensitivity=int(ev.sensitivity),
                    access_policy=ev.access_policy,
                ),
                "privacy": privacy_metadata,
            }
            if isinstance(ev.metadata.get("media_embedding"), dict):
                metadata["media_embedding"] = dict(ev.metadata["media_embedding"])
            if isinstance(ev.metadata.get("summary"), dict):
                metadata["summary"] = dict(ev.metadata["summary"])
            if isinstance(ev.metadata.get("lifecycle"), dict):
                metadata["lifecycle"] = dict(ev.metadata["lifecycle"])
            if "confidence" in ev.metadata:
                metadata["confidence"] = ev.metadata["confidence"]
            if isinstance(ev.metadata.get("earned_autonomy"), dict):
                metadata["earned_autonomy"] = dict(ev.metadata["earned_autonomy"])
            if "birth_groundedness" in ev.metadata:
                metadata["birth_groundedness"] = ev.metadata["birth_groundedness"]
            hits.append(
                Hit(
                    id=ev.cid or "",
                    kind="evidence",
                    tenant_id=ev.tenant_id,
                    branch=ev.branch,
                    text=text,
                    score=0.0,
                    channel="candidate",
                    provenance=[ev.cid] if ev.cid else [],
                    trust_tier=ev.trust_tier,
                    sensitivity=ev.sensitivity,
                    metadata=metadata,
                )
            )
        for assertion in self.assertions.values():
            if assertion.tenant_id != tenant_id or assertion.branch != branch:
                continue
            if assertion.status not in {"active", "contested"}:
                continue
            if assertion.trust_tier > max_trust or assertion.sensitivity > max_sensitivity:
                continue
            decision = may_read_item(
                item_tenant_id=assertion.tenant_id,
                sensitivity=int(assertion.sensitivity),
                access_policy=assertion.access_policy,
                context=filt,
                policy_max_sensitivity=self.policy.max_sensitivity,
                status=assertion.status,
                erased=False,
            )
            if not decision.allowed:
                continue
            text, privacy_metadata = apply_statement_redactions(
                subject=assertion.subject,
                predicate=assertion.predicate,
                object_value=assertion.object,
                access_policy=assertion.access_policy,
                decision=decision,
            )
            reality_monitoring = self._projection_reality_monitoring_from_calibration(assertion.calibration)
            hits.append(
                Hit(
                    id=assertion.id,
                    kind="assertion",
                    tenant_id=assertion.tenant_id,
                    branch=assertion.branch,
                    text=text,
                    score=0.0,
                    channel="candidate",
                    provenance=list(assertion.source_evidence_cids),
                    trust_tier=assertion.trust_tier,
                    sensitivity=assertion.sensitivity,
                    metadata={
                        "status": assertion.status,
                        "confidence": assertion.confidence,
                        "reality_class": reality_monitoring["reality_class"],
                        "reality_monitoring": reality_monitoring,
                        "last_accessed": assertion.last_accessed.isoformat() if assertion.last_accessed else None,
                        "access_count": assertion.access_count,
                        "privacy": privacy_metadata,
                    },
                )
            )
        for pref in self.preferences.values():
            if pref.tenant_id != tenant_id or pref.status != "active":
                continue
            decision = may_read_item(
                item_tenant_id=pref.tenant_id,
                sensitivity=0,
                access_policy=pref.access_policy,
                context=filt,
                policy_max_sensitivity=self.policy.max_sensitivity,
                status=pref.status,
                erased=False,
            )
            if not decision.allowed:
                continue
            text, privacy_metadata = apply_text_redactions(pref.statement, pref.access_policy, decision)
            hits.append(
                Hit(
                    id=pref.id,
                    kind="preference",
                    tenant_id=pref.tenant_id,
                    branch=branch,
                    text=text,
                    score=0.0,
                    channel="candidate",
                    provenance=list(pref.source_evidence_cids),
                    trust_tier=0 if pref.explicit else 3,
                    sensitivity=0,
                    metadata={"category": pref.category, "explicit": pref.explicit, "privacy": privacy_metadata},
                )
            )
        return hits

    @staticmethod
    def _mark_retrieved_text_as_data(hits: list[Hit]) -> list[Hit]:
        for hit in hits:
            hit.metadata = {
                **hit.metadata,
                "retrieved_text": sanitize_retrieved_text(hit.text, hit.trust_tier),
            }
        return hits

    def _embedding_for_hit(
        self,
        hit: Hit,
        filt: dict[str, Any] | None = None,
        *,
        allow_fallback: bool = True,
    ) -> list[float] | None:
        if hit.kind == "evidence":
            ev = self.evidence.get(self._evidence_key(hit.tenant_id, hit.branch, hit.id))
            if ev and ev.embedding:
                decision = may_read_item(
                    item_tenant_id=ev.tenant_id,
                    sensitivity=int(ev.sensitivity),
                    access_policy=ev.access_policy,
                    context=filt,
                    policy_max_sensitivity=self.policy.max_sensitivity,
                    status="active",
                    erased=ev.erased,
                )
                if may_use_stored_embedding(
                    decision=decision,
                    sensitivity=int(ev.sensitivity),
                    access_policy=ev.access_policy,
                    embedding_partition=ev.metadata.get("embedding_partition"),
                ):
                    hit.metadata["stored_embedding_used"] = True
                    return ev.embedding
        if not allow_fallback:
            return None
        partition = str(hit.metadata.get("embedding_partition") or VECTOR_PARTITION_PUBLIC)
        if partition == "none":
            return None
        hit.metadata["stored_embedding_used"] = False
        return self._embed_text(hit.text)

    def _embed_text(self, text: str) -> list[float]:
        return self.adapters.embedding.embed(text)

    def _rrf(self, ranked_lists: list[list[Hit]], k: int) -> list[Hit]:
        return rrf_fuse(ranked_lists, k, rrf_k=self.policy.rrf_k)

    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        # Embedding sourcing stays security-gated via _embedding_for_hit
        # (deliberately divergent from PostgresEngine, spec §4.0).
        return mmr_select(
            hits,
            k,
            query_vec=embed_query(self.adapters.embedding, query),
            embed_hit=lambda hit: self._embedding_for_hit(hit, allow_fallback=True),
            mmr_lambda=self.policy.mmr_lambda,
        )

    @staticmethod
    def _u_curve_order(hits: list[Hit]) -> list[Hit]:
        return u_curve_order(hits)

    @staticmethod
    def _fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]:
        return fit_budget(hits, budget)

    @staticmethod
    def _confidence(query: str, hits: list[Hit], *, support_score: float | None = None) -> float:
        if not hits:
            return 0.0
        max_score = max((max(hit.score, 0.0) for hit in hits), default=0.0)
        weighted = 0.0
        total = 0.0
        ranked_scores = sorted((max(hit.score, 0.0) for hit in hits), reverse=True)
        for rank, hit in enumerate(hits, start=1):
            score = max(hit.score, 0.0)
            relevance = score / max(max_score, 0.01)
            trust = trust_weight(hit.trust_tier)
            explicit = hit.metadata.get("confidence")
            channel_count = len({part for part in hit.channel.split("+") if part and part != "candidate"})
            channel_support = min(channel_count / 3.0, 1.0)
            provenance_support = min(len(hit.provenance) / 3.0, 1.0)
            quality = (
                0.03
                + 0.25 * relevance
                + 0.35 * trust
                + 0.10 * channel_support
                + 0.27 * provenance_support
            )
            if explicit is not None:
                quality = 0.55 * _bounded_float(explicit, default=0.0) + 0.45 * quality
            quality *= 0.55 + 0.45 * trust
            rank_weight = (score + 0.01) / max(rank, 1)
            weighted += max(0.0, min(1.0, quality)) * rank_weight
            total += rank_weight
        confidence = weighted / max(total, 0.01)
        if len(ranked_scores) > 1:
            margin = (ranked_scores[0] - ranked_scores[1]) / max(ranked_scores[0], 0.01)
            confidence *= 0.90 + 0.10 * max(0.0, min(1.0, margin))
        support = min(len(hits) / 3.0, 1.0)
        confidence *= 0.85 + 0.15 * support
        evidence_quality = max(0.0, min(1.0, confidence))
        query_support_score = support_score if support_score is not None else query_support(query, hits)["score"]
        query_support_score = max(0.0, min(1.0, query_support_score))
        if query_support_score < QUERY_SUPPORT_THRESHOLD:
            return min(evidence_quality, 0.05 * (query_support_score / QUERY_SUPPORT_THRESHOLD))
        support_floor = 0.96 + 0.04 * (
            (query_support_score - QUERY_SUPPORT_THRESHOLD) / max(1.0 - QUERY_SUPPORT_THRESHOLD, 0.01)
        )
        return max(evidence_quality, min(1.0, support_floor))

    @staticmethod
    def _prediction_set_size(hits: list[Hit], threshold: float) -> int:
        if not hits:
            return 0
        max_score = max((max(hit.score, 0.0) for hit in hits), default=0.0)
        if max_score <= 0.0:
            return 0
        cutoff = max_score * max(0.05, min(0.95, threshold))
        return sum(1 for hit in hits if max(hit.score, 0.0) >= cutoff)

    @staticmethod
    def _metadata_source_cids(metadata: dict[str, Any]) -> set[str]:
        sources: set[str] = set()
        single = metadata.get("source_evidence_cid")
        if single:
            sources.add(str(single))
        values = metadata.get("source_evidence_cids")
        if isinstance(values, list):
            sources.update(str(item) for item in values if item)
        summary = metadata.get("summary")
        if isinstance(summary, dict):
            summary_values = summary.get("source_evidence_cids")
            if isinstance(summary_values, list):
                sources.update(str(item) for item in summary_values if item)
        return sources

    def _derived_evidence_cids_forget(self, tenant_id: str, branch: str, cid: str) -> list[str]:
        affected = {cid}
        derived: list[str] = []
        changed = True
        while changed:
            changed = False
            for item in self.evidence.values():
                item_cid = item.cid
                if (
                    item.tenant_id != tenant_id
                    or item.branch != branch
                    or item.erased
                    or not item_cid
                    or item_cid in affected
                ):
                    continue
                if affected.intersection(self._metadata_source_cids(item.metadata)):
                    affected.add(item_cid)
                    derived.append(item_cid)
                    changed = True
        return derived

    def _derived_evidence_forget_plan(
        self,
        tenant_id: str,
        branch: str,
        cid: str,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        affected = {cid}
        erased: list[str] = []
        retained: dict[str, dict[str, Any]] = {}
        changed = True
        while changed:
            changed = False
            for item in self.evidence.values():
                item_cid = item.cid
                if (
                    item.tenant_id != tenant_id
                    or item.branch != branch
                    or item.erased
                    or not item_cid
                    or item_cid in affected
                ):
                    continue
                sources = self._metadata_source_cids(item.metadata)
                if not affected.intersection(sources):
                    continue
                surviving_sources = sources - affected
                if surviving_sources:
                    retained[item_cid] = self._trim_metadata_source_cids(item.metadata, affected)
                    continue
                affected.add(item_cid)
                retained.pop(item_cid, None)
                erased.append(item_cid)
                changed = True
        return erased, retained

    @staticmethod
    def _trim_metadata_source_cids(metadata: dict[str, Any], affected_cids: set[str]) -> dict[str, Any]:
        trimmed = copy.deepcopy(metadata)
        if str(trimmed.get("source_evidence_cid") or "") in affected_cids:
            trimmed.pop("source_evidence_cid", None)
        values = trimmed.get("source_evidence_cids")
        if isinstance(values, list):
            trimmed["source_evidence_cids"] = [str(item) for item in values if str(item) not in affected_cids]
        summary = trimmed.get("summary")
        if isinstance(summary, dict):
            summary_values = summary.get("source_evidence_cids")
            if isinstance(summary_values, list):
                kept = [str(item) for item in summary_values if str(item) not in affected_cids]
                summary["source_evidence_cids"] = kept
                summary["source_count"] = len(kept)
                summary.pop("source_fingerprint", None)
        return trimmed

    @staticmethod
    def _valid_at(valid_from: datetime, valid_to: datetime | None, moment: datetime) -> bool:
        start = valid_from.astimezone(UTC) if valid_from.tzinfo else valid_from.replace(tzinfo=UTC)
        end = valid_to.astimezone(UTC) if valid_to and valid_to.tzinfo else valid_to
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        return start <= moment and (end is None or moment < end)

    def _require_branch(self, branch: str) -> None:
        if branch not in self.branches:
            raise ValueError(f"unknown branch: {branch}")

    def to_json(self) -> str:
        return json.dumps(self.export_all(), indent=2, sort_keys=True)

    def _export_branches(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name, meta in self.branches.items():
            tenants = {
                item.tenant_id
                for item in [*self.evidence.values(), *self.assertions.values(), *self.relations.values()]
                if item.branch == name
            }
            tenants.update(meta.get("tenants") or [])
            if not tenants:
                tenants = {None}
            for tenant in sorted(tenants, key=lambda item: item or ""):
                rows.append(
                    {
                        "tenant_id": tenant,
                        "name": name,
                        "from_branch": meta.get("from"),
                        "kind": meta.get("kind"),
                        "head": None,
                        "created_at": meta.get("created_at"),
                    }
                )
        return rows

    def export_all(self) -> dict[str, Any]:
        tenant_ids: set[str] = set()
        for collection in (
            self.evidence.values(),
            self.assertions.values(),
            self.relations.values(),
            self.preferences.values(),
            self.justifications.values(),
            self.contradictions.values(),
            self.calibrations.values(),
        ):
            for item in collection:
                tenant_id = getattr(item, "tenant_id", None)
                if tenant_id and tenant_id != "*":
                    tenant_ids.add(tenant_id)
        for item in self.entities.values():
            tenant_id = item.get("tenant_id")
            if tenant_id and tenant_id != "*":
                tenant_ids.add(tenant_id)
        for item in (*self.audit_log, *self.deletion_log, *self.merge_log):
            tenant_id = item.get("tenant_id") if isinstance(item, dict) else None
            if tenant_id and tenant_id != "*":
                tenant_ids.add(tenant_id)
        for meta in self.branches.values():
            for tenant_id in meta.get("tenants") or []:
                if tenant_id and tenant_id != "*":
                    tenant_ids.add(tenant_id)
        tenant_exports = [self.export_tenant(tenant_id) for tenant_id in sorted(tenant_ids)]
        return {
            "policy": self.policy.to_dict(),
            "branches": self._export_branches(),
            "evidence": [item for exported in tenant_exports for item in exported["evidence"]],
            "assertions": [item for exported in tenant_exports for item in exported["assertions"]],
            "relations": [item for exported in tenant_exports for item in exported["relations"]],
            "preferences": [item for exported in tenant_exports for item in exported["preferences"]],
            "justifications": [item for exported in tenant_exports for item in exported["justifications"]],
            "contradictions": [item for exported in tenant_exports for item in exported["contradictions"]],
            "calibrations": [item for exported in tenant_exports for item in exported["calibrations"]],
            "entities": [item for exported in tenant_exports for item in exported["entities"]],
            "audit_log": [item for exported in tenant_exports for item in exported["audit_log"]],
            "deletion_log": [item for exported in tenant_exports for item in exported["deletion_log"]],
            "merge_log": self.merge_log,
            "tenants": tenant_exports,
            "working_memory": [
                item
                for tenant_export in tenant_exports
                for item in tenant_export["working_memory"]
            ],
        }
