"""In-process durable-shape queue used by local-first runtime jobs."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from mnemosyne.ids import new_id


@dataclass(slots=True)
class QueueJob:
    kind: str
    payload: dict[str, Any]
    max_attempts: int = 3
    id: str = field(default_factory=new_id)
    status: str = "queued"
    attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None
    result: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.astimezone(UTC).isoformat()
        data["updated_at"] = self.updated_at.astimezone(UTC).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueueJob":
        copy = dict(data)
        copy["created_at"] = _parse_dt(copy.get("created_at"))
        copy["updated_at"] = _parse_dt(copy.get("updated_at"))
        return cls(**copy)


class InProcessQueue:
    """Small queue with the same lifecycle as a production worker queue."""

    def __init__(self) -> None:
        self._order: deque[str] = deque()
        self.jobs: dict[str, QueueJob] = {}

    def enqueue(self, kind: str, payload: dict[str, Any], max_attempts: int = 3) -> QueueJob:
        job = QueueJob(kind=kind, payload=dict(payload), max_attempts=max_attempts)
        self.jobs[job.id] = job
        self._order.append(job.id)
        return job

    def lease(self, kind: str | None = None) -> QueueJob | None:
        for _ in range(len(self._order)):
            job_id = self._order.popleft()
            job = self.jobs[job_id]
            if job.status not in {"queued", "retry"}:
                continue
            if kind and job.kind != kind:
                self._order.append(job_id)
                continue
            job.status = "running"
            job.attempts += 1
            job.updated_at = datetime.now(UTC)
            return job
        return None

    def complete(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job.status = "complete"
        job.updated_at = datetime.now(UTC)

    def fail(self, job_id: str, error: str) -> None:
        job = self.jobs[job_id]
        job.last_error = error
        job.updated_at = datetime.now(UTC)
        if job.attempts >= job.max_attempts:
            job.status = "dead"
        else:
            job.status = "retry"
            self._order.append(job_id)

    def snapshot(self) -> dict[str, int]:
        counts: Counter[str] = Counter(job.status for job in self.jobs.values())
        return dict(counts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": list(self._order),
            "jobs": [job.to_dict() for job in self.jobs.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "InProcessQueue":
        queue = cls()
        if not data:
            return queue
        queue.jobs = {job.id: job for job in (QueueJob.from_dict(row) for row in data.get("jobs", []))}
        queue._order = deque(job_id for job_id in data.get("order", []) if job_id in queue.jobs)
        queued_ids = {job_id for job_id in queue._order}
        for job in queue.jobs.values():
            if job.status in {"queued", "retry"} and job.id not in queued_ids:
                queue._order.append(job.id)
        return queue


class QueueWorker:
    def __init__(self, queue: InProcessQueue, handlers: dict[str, Callable[[dict[str, Any]], Any]]):
        self.queue = queue
        self.handlers = handlers

    def run_once(self, kind: str | None = None) -> QueueJob | None:
        job = self.queue.lease(kind)
        if not job:
            return None
        handler = self.handlers.get(job.kind)
        if not handler:
            self.queue.fail(job.id, f"no handler for job kind {job.kind}")
            return job
        try:
            result = handler(job.payload)
            job.result = result.to_dict() if hasattr(result, "to_dict") else result
        except Exception as exc:  # noqa: BLE001 - worker queue must record arbitrary job errors.
            self.queue.fail(job.id, str(exc))
        else:
            self.queue.complete(job.id)
        return job


def _parse_dt(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
