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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.astimezone(UTC).isoformat()
        data["updated_at"] = self.updated_at.astimezone(UTC).isoformat()
        return data


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
            handler(job.payload)
        except Exception as exc:  # noqa: BLE001 - worker queue must record arbitrary job errors.
            self.queue.fail(job.id, str(exc))
        else:
            self.queue.complete(job.id)
        return job
