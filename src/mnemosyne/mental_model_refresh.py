"""Opt-in, durable scheduling for scope-bound maintained answers.

Leases fence publication, not provider execution: a provider may still be running
after a worker loses its lease. Such a worker cannot publish or finish its job.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from mnemosyne.answering import AnswerReadContext
from mnemosyne.security import SecurityPolicy

if TYPE_CHECKING:
    from mnemosyne.mental_models import MentalModelService

_SCHEMA = "mnemosyne.refresh-schedule/v1"
_OUTCOMES = {"running", "refreshed", "unchanged", "abstained", "retry"}
_FIELDS = {"schema_version", "enabled", "interval_seconds", "next_run_at",
           "consecutive_failures", "last_started_at", "last_finished_at", "last_outcome", "lease"}


class MentalModelLeaseLost(ValueError):
    """This worker no longer owns permission to publish its computation."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("schedule timestamp must be timezone-aware ISO text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("schedule timestamp must be timezone-aware ISO text")
    return parsed.astimezone(UTC)


def parse_schedule(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _FIELDS or value["schema_version"] != _SCHEMA:
        raise ValueError("invalid refresh schedule")
    if type(value["enabled"]) is not bool:
        raise ValueError("invalid schedule enabled flag")
    bounded_int(value["interval_seconds"], "interval_seconds", 60, 604800)
    bounded_int(value["consecutive_failures"], "consecutive_failures", 0, 30)
    timestamp(value["next_run_at"])
    for key in ("last_started_at", "last_finished_at"):
        if value[key] is not None:
            timestamp(value[key])
    if value["last_outcome"] is not None and (
            not isinstance(value["last_outcome"], str) or value["last_outcome"] not in _OUTCOMES):
        raise ValueError("invalid schedule outcome")
    lease = value["lease"]
    if lease is not None:
        if (not isinstance(lease, dict) or set(lease) != {"token", "expires_at"}
                or not isinstance(lease["token"], str) or not 1 <= len(lease["token"]) <= 128):
            raise ValueError("invalid refresh lease")
        timestamp(lease["expires_at"])
    return copy.deepcopy(value)


def new_schedule(enabled: bool, interval_seconds: int) -> dict[str, Any]:
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    bounded_int(interval_seconds, "interval_seconds", 60, 604800)
    return {"schema_version": _SCHEMA, "enabled": enabled, "interval_seconds": interval_seconds,
            "next_run_at": utc_now().isoformat(), "consecutive_failures": 0,
            "last_started_at": None, "last_finished_at": None, "last_outcome": None, "lease": None}


def public_schedule(record: dict[str, Any]) -> dict[str, Any]:
    try:
        value = parse_schedule(record.get("refresh_schedule"))
        if value is None:
            return {"enabled": False}
        lease = value.pop("lease")
        value.pop("schema_version")
        value["running"] = bool(lease and timestamp(lease["expires_at"]) > utc_now())
        return value
    except (ValueError, TypeError, OverflowError):
        return {"enabled": False, "invalid": True}


def require_lease(record: dict[str, Any], token: str) -> None:
    try:
        schedule = parse_schedule(record.get("refresh_schedule"))
        lease = schedule["lease"] if schedule and schedule["enabled"] else None
        if lease and lease["token"] == token and timestamp(lease["expires_at"]) > utc_now():
            return
    except (ValueError, TypeError, OverflowError):
        pass
    raise MentalModelLeaseLost("mental model refresh lease lost")


def cancel_lease(record: dict[str, Any], *, due_now: bool = False) -> None:
    schedule = parse_schedule(record.get("refresh_schedule"))
    if schedule is not None:
        schedule["lease"] = None
        if due_now:
            schedule.update(next_run_at=utc_now().isoformat(), consecutive_failures=0)
        record["refresh_schedule"] = schedule


class MentalModelRefreshWorker:
    """A worker for one explicitly supplied owner and read scope, never all users."""

    def __init__(self, service: MentalModelService, context: AnswerReadContext, *,
                 max_batch: int = 10, lease_seconds: int = 300,
                 check_changes: bool = False,
                 authorize: Callable[[], None] | None = None,
                 validate_authority: Callable[[], None] | None = None):
        self.service, self.context = service, context
        self.max_batch = bounded_int(max_batch, "max_batch", 1, 100)
        self.lease_seconds = bounded_int(lease_seconds, "lease_seconds", 30, 3600)
        if type(check_changes) is not bool:
            raise ValueError("check_changes must be a boolean")
        self.check_changes = check_changes
        self._authorize_callback = authorize
        if authorize is not None and validate_authority is None:
            raise ValueError("authorize requires a side-effect-free validate_authority callback")
        self._validate_callback = validate_authority

    def _validate(self) -> None:
        self.service._write(self.context)
        decision = SecurityPolicy().authorize_write(
            operation="mental_model_refresh", role=self.context.role,
            source_trust_tier=self.context.source_trust_tier if self.context.source_trust_tier is not None else 1,
            target_sink="belief")
        if not decision.allowed:
            raise PermissionError("mental model worker requires trusted write authority")
        if self._validate_callback is not None:
            self._validate_callback()

    def _authorize(self) -> None:
        self._validate()
        if self._authorize_callback is not None:
            self._authorize_callback()

    def _change_candidate(self, record: dict[str, Any], schedule: dict[str, Any], now: datetime) -> bool:
        """Check scheduling eligibility; source freshness is checked separately.

        Early attempts wait at least 60 seconds after both the start and finish
        of the preceding attempt. Failed attempts retain their durable backoff.
        """
        if (not self.check_changes or not schedule["enabled"]
                or timestamp(schedule["next_run_at"]) <= now
                or schedule["consecutive_failures"] or schedule["last_outcome"] == "retry"
                or not isinstance(record.get("status"), str)
                or record["status"] not in {"ready", "abstained", "stale"}):
            return False
        if schedule["lease"] and timestamp(schedule["lease"]["expires_at"]) > now:
            return False
        return all(value is None or now >= timestamp(value) + timedelta(seconds=60)
                   for value in (schedule["last_started_at"], schedule["last_finished_at"]))

    def _claim(self, model_id: str, *, changed_version: int | None = None) -> tuple[str, int] | None:
        self._authorize()
        with self.service._publication_guard(self.context):
            record = self.service._load(self.context, model_id)
            schedule = parse_schedule(record.get("refresh_schedule"))
            now = utc_now()
            if not schedule or not schedule["enabled"]:
                return None
            if changed_version is not None and record["version"] != changed_version:
                return None
            if timestamp(schedule["next_run_at"]) > now and (
                    changed_version is None or not self._change_candidate(record, schedule, now)):
                return None
            if schedule["lease"] and timestamp(schedule["lease"]["expires_at"]) > now:
                return None
            token = str(uuid4())
            schedule.update(lease={"token": token, "expires_at": (now + timedelta(seconds=self.lease_seconds)).isoformat()},
                            last_started_at=now.isoformat(), last_outcome="running")
            record["refresh_schedule"] = schedule
            self._validate()
            saved = self.service.engine.save_mental_model_record(
                self.context.tenant_id, model_id, record, branch=self.context.branch,
                expected_version=record["version"])
            return token, saved["version"]

    def _finish(self, model_id: str, token: str, outcome: str) -> str:
        self._authorize()
        with self.service._publication_guard(self.context):
            record = self.service._load(self.context, model_id)
            require_lease(record, token)
            schedule = parse_schedule(record["refresh_schedule"])
            assert schedule is not None
            now = utc_now()
            failures = min(30, schedule["consecutive_failures"] + 1) if outcome == "retry" else 0
            delay = (min(3600, min(3600, schedule["interval_seconds"]) * 2 ** min(failures - 1, 6))
                     if failures else schedule["interval_seconds"])
            schedule.update(lease=None, consecutive_failures=failures, last_outcome=outcome,
                            last_finished_at=now.isoformat(), next_run_at=(now + timedelta(seconds=delay)).isoformat())
            record["refresh_schedule"] = schedule
            self._validate()
            self.service.engine.save_mental_model_record(
                self.context.tenant_id, model_id, record, branch=self.context.branch,
                expected_version=record["version"])
            return outcome

    def run_once(self) -> dict[str, Any]:
        from mnemosyne.mental_models import _scope

        self._authorize()
        scope = _scope(self.context)
        report: dict[str, Any] = {key: 0 for key in
                                 ("processed", "refreshed", "unchanged", "abstained", "retry", "lost", "invalid",
                                  "change_check_failed")}
        report["models"] = []
        due = []
        change_candidates = []
        now = utc_now()
        for record in self.service.engine.list_mental_model_records(self.context.tenant_id, self.context.branch):
            if record.get("owner_id") != self.context.user_id or record.get("scope") != scope:
                continue
            try:
                schedule = parse_schedule(record.get("refresh_schedule"))
                if schedule and schedule["enabled"]:
                    if timestamp(schedule["next_run_at"]) <= now:
                        if not schedule["lease"] or timestamp(schedule["lease"]["expires_at"]) <= now:
                            due.append((0, timestamp(schedule["next_run_at"]), record["model_id"], None))
                    elif self._change_candidate(record, schedule, now):
                        change_candidates.append((record, schedule))
            except (ValueError, TypeError, OverflowError):
                report["invalid"] += 1
        if change_candidates:
            try:
                # One authorized corpus scan per poll, not per model or append.
                # This is only a scheduling hint: _refresh independently checks
                # current sources before any provider call and at publication.
                with self.service._lock():
                    snapshot = self.service._snapshot(self.context)
            except Exception:
                report["change_check_failed"] += 1
            else:
                for record, schedule in change_candidates:
                    try:
                        if self.service._view(record, self.context, snapshot)["stale"]:
                            due.append((1, timestamp(schedule["next_run_at"]), record["model_id"], record["version"]))
                    except (KeyError, ValueError, TypeError, OverflowError):
                        report["invalid"] += 1
        for _, _, model_id, changed_version in sorted(due):
            if report["processed"] >= self.max_batch:
                break
            try:
                claim = self._claim(model_id, changed_version=changed_version)
            except (LookupError, ValueError):
                continue  # A competing worker or edit won the version check.
            if claim is None:
                continue
            token, version = claim
            report["processed"] += 1
            try:
                result = self.service._refresh(self.context, model_id, lease_token=token,
                                               authorize=self._authorize, validate_authority=self._validate)
                if result["version"] == version and result["status"] in {"ready", "abstained"}:
                    outcome = "unchanged"
                elif result["status"] == "ready" and not result["refresh_error"]:
                    outcome = "refreshed"
                elif result["status"] == "abstained" and not result["refresh_error"]:
                    outcome = "abstained"
                else:
                    outcome = "retry"
            except PermissionError:
                raise  # Revoked/expired worker authority stops work; its lease expires.
            except (LookupError, MentalModelLeaseLost):
                outcome = "lost"
            except Exception:
                outcome = "retry"
            if outcome != "lost":
                try:
                    outcome = self._finish(model_id, token, outcome)
                except (LookupError, ValueError):
                    outcome = "lost"
            report[outcome] += 1
            report["models"].append({"model_id": model_id, "outcome": outcome})
        return report
