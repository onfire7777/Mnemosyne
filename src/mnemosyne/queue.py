"""In-process durable-shape queue used by local-first runtime jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from mnemosyne.ids import new_id
from mnemosyne.journal import safe_tenant_filename
from mnemosyne.models import dt_to_json
from mnemosyne.postgres_security import assert_postgres_safe_role, postgres_safe_role_required
from mnemosyne.sqlite_schema import ENSURE_STATEMENTS, PRAGMA_STATEMENTS


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
        best_id: str | None = None
        best_key: tuple[float, datetime, str] | None = None
        for job_id in list(self._order):
            job = self.jobs[job_id]
            if job.status not in {"queued", "retry"}:
                self._order.remove(job_id)
                continue
            if kind and job.kind != kind:
                continue
            key = (_job_priority(job), job.created_at, job.id)
            if best_key is None or key[0] > best_key[0] or (key[0] == best_key[0] and key[1:] < best_key[1:]):
                best_id = job_id
                best_key = key
        if best_id is None:
            return None
        self._order.remove(best_id)
        job = self.jobs[best_id]
        job.status = "running"
        job.attempts += 1
        job.updated_at = datetime.now(UTC)
        return job

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


class PostgresQueueUnavailableError(RuntimeError):
    """Raised when the optional Postgres queue dependency is not installed."""


class PostgresQueue:
    """Tenant-scoped durable queue backed by PostgreSQL row leasing."""

    def __init__(self, dsn: str, tenant_id: str, require_safe_role: bool | None = None):
        self.dsn = dsn
        self.tenant_id = tenant_id
        self.require_safe_role = (
            postgres_safe_role_required() if require_safe_role is None else bool(require_safe_role)
        )
        self._psycopg, self._jsonb, self._dict_row = _require_psycopg_queue()
        self._leased: dict[str, QueueJob] = {}
        self.ensure_schema()

    def connect(self) -> Any:
        conn = self._psycopg.connect(self.dsn)
        if self.require_safe_role:
            assert_postgres_safe_role(conn, surface="PostgresQueue")
        return conn

    @property
    def jobs(self) -> dict[str, QueueJob]:
        return {job.id: job for job in self.list_jobs()}

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runtime_jobs (
                      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                      tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                      kind TEXT NOT NULL,
                      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                      status TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'retry', 'complete', 'dead')),
                      attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                      max_attempts INT NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
                      last_error TEXT,
                      result JSONB,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS runtime_jobs_tenant_status_kind_idx
                    ON runtime_jobs(tenant_id, status, kind, created_at)
                    """
                )
                cur.execute("ALTER TABLE runtime_jobs ENABLE ROW LEVEL SECURITY")
                cur.execute("ALTER TABLE runtime_jobs FORCE ROW LEVEL SECURITY")
                cur.execute("DROP POLICY IF EXISTS runtime_jobs_tenant_isolation ON runtime_jobs")
                cur.execute(
                    """
                    CREATE POLICY runtime_jobs_tenant_isolation ON runtime_jobs
                      USING (tenant_id = mnemosyne_current_tenant())
                      WITH CHECK (tenant_id = mnemosyne_current_tenant())
                    """
                )

    def enqueue(self, kind: str, payload: dict[str, Any], max_attempts: int = 3) -> QueueJob:
        job = QueueJob(kind=kind, payload=dict(payload), max_attempts=max_attempts)
        db_tenant_id = self._tenant_db_id()
        with self.connect() as conn:
            with conn.cursor(row_factory=self._dict_row) as cur:
                self._ensure_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    INSERT INTO runtime_jobs(
                      id, tenant_id, kind, payload, status, attempts, max_attempts,
                      last_error, result, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        job.id,
                        db_tenant_id,
                        job.kind,
                        self._jsonb(job.payload),
                        job.status,
                        job.attempts,
                        job.max_attempts,
                        job.last_error,
                        self._jsonb(job.result),
                        job.created_at,
                        job.updated_at,
                    ),
                )
                return _job_from_row(cur.fetchone())

    def lease(self, kind: str | None = None) -> QueueJob | None:
        db_tenant_id = self._tenant_db_id()
        with self.connect() as conn:
            with conn.cursor(row_factory=self._dict_row) as cur:
                self._ensure_tenant(cur, db_tenant_id)
                if kind:
                    cur.execute(
                        """
                        SELECT id
                        FROM runtime_jobs
                        WHERE tenant_id = %s
                          AND status IN ('queued', 'retry')
                          AND kind = %s
                        ORDER BY
                          CASE
                            WHEN payload #>> '{write_priority,effective_score}' ~ '^[0-9]+([.][0-9]+)?$'
                            THEN (payload #>> '{write_priority,effective_score}')::DOUBLE PRECISION
                            WHEN payload #>> '{write_priority,score}' ~ '^[0-9]+([.][0-9]+)?$'
                            THEN (payload #>> '{write_priority,score}')::DOUBLE PRECISION
                            ELSE 0.0
                          END DESC,
                          created_at ASC,
                          id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """,
                        (db_tenant_id, kind),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id
                        FROM runtime_jobs
                        WHERE tenant_id = %s
                          AND status IN ('queued', 'retry')
                        ORDER BY
                          CASE
                            WHEN payload #>> '{write_priority,effective_score}' ~ '^[0-9]+([.][0-9]+)?$'
                            THEN (payload #>> '{write_priority,effective_score}')::DOUBLE PRECISION
                            WHEN payload #>> '{write_priority,score}' ~ '^[0-9]+([.][0-9]+)?$'
                            THEN (payload #>> '{write_priority,score}')::DOUBLE PRECISION
                            ELSE 0.0
                          END DESC,
                          created_at ASC,
                          id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """,
                        (db_tenant_id,),
                    )
                row = cur.fetchone()
                if row is None:
                    return None
                cur.execute(
                    """
                    UPDATE runtime_jobs
                    SET status = 'running',
                        attempts = attempts + 1,
                        updated_at = now()
                    WHERE id = %s AND tenant_id = %s
                    RETURNING *
                    """,
                    (row["id"], db_tenant_id),
                )
                job = _job_from_row(cur.fetchone())
                self._leased[job.id] = job
                return job

    def complete(self, job_id: str) -> None:
        job = self._leased.pop(job_id, None)
        if job:
            job.status = "complete"
            job.updated_at = datetime.now(UTC)
        self._update_status(job_id, status="complete", result=job.result if job else None)

    def fail(self, job_id: str, error: str) -> None:
        job = self._leased.pop(job_id, None) or self._get_job(job_id)
        status = "dead" if job and job.attempts >= job.max_attempts else "retry"
        if job:
            job.status = status
            job.last_error = error
            job.updated_at = datetime.now(UTC)
        self._update_status(job_id, status=status, last_error=error)

    def snapshot(self) -> dict[str, int]:
        db_tenant_id = self._tenant_db_id()
        with self.connect() as conn:
            with conn.cursor(row_factory=self._dict_row) as cur:
                self._ensure_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT status, count(*) AS count
                    FROM runtime_jobs
                    WHERE tenant_id = %s
                    GROUP BY status
                    """,
                    (db_tenant_id,),
                )
                return {str(row["status"]): int(row["count"]) for row in cur.fetchall()}

    def list_jobs(self) -> list[QueueJob]:
        db_tenant_id = self._tenant_db_id()
        with self.connect() as conn:
            with conn.cursor(row_factory=self._dict_row) as cur:
                self._ensure_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    SELECT *
                    FROM runtime_jobs
                    WHERE tenant_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (db_tenant_id,),
                )
                return [_job_from_row(row) for row in cur.fetchall()]

    def _update_status(
        self,
        job_id: str,
        *,
        status: str,
        result: Any | None = None,
        last_error: str | None = None,
    ) -> None:
        db_tenant_id = self._tenant_db_id()
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._ensure_tenant(cur, db_tenant_id)
                cur.execute(
                    """
                    UPDATE runtime_jobs
                    SET status = %s,
                        result = COALESCE(%s, result),
                        last_error = COALESCE(%s, last_error),
                        updated_at = now()
                    WHERE id = %s AND tenant_id = %s
                    """,
                    (status, self._jsonb(result), last_error, job_id, db_tenant_id),
                )

    def _get_job(self, job_id: str) -> QueueJob | None:
        db_tenant_id = self._tenant_db_id()
        with self.connect() as conn:
            with conn.cursor(row_factory=self._dict_row) as cur:
                self._ensure_tenant(cur, db_tenant_id)
                cur.execute(
                    "SELECT * FROM runtime_jobs WHERE id = %s AND tenant_id = %s",
                    (job_id, db_tenant_id),
                )
                row = cur.fetchone()
                return _job_from_row(row) if row else None

    def _tenant_db_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"mnemosyne:tenant:{self.tenant_id}"))

    def _ensure_tenant(self, cur: Any, db_tenant_id: str) -> None:
        cur.execute(
            "INSERT INTO tenants(id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (db_tenant_id, self.tenant_id),
        )
        cur.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)", (db_tenant_id,))


class SqliteQueue:
    """Tenant-scoped durable queue over the per-tenant SQLite file's
    ``runtime_jobs`` table (the SqliteEngine store lane, spec §4.2).

    Mirrors the ``InProcessQueue`` / ``PostgresQueue`` public surface —
    ``enqueue`` / ``lease`` / ``complete`` / ``fail`` / ``snapshot`` plus
    ``list_jobs`` and the ``jobs`` property — over the shared :class:`QueueJob`
    shape. Selection ordering matches ``InProcessQueue`` byte-for-byte:
    ``write_priority.effective_score`` → ``score`` (numeric, else 0.0) DESC,
    then ``created_at`` ASC, then ``id`` ASC (via the shared ``_job_priority``).

    ``lease`` is a single ``BEGIN IMMEDIATE`` claim — the SQLite analogue of
    PostgresQueue's ``FOR UPDATE SKIP LOCKED``: the reserved write lock
    serialises concurrent leasers so one job is never handed out twice. There is
    NO lease timeout / visibility reclaim, matching BOTH shipped queues (the
    grounding is explicit: do not invent one). The connection runs in autocommit
    mode (``isolation_level=None``) so the explicit ``BEGIN IMMEDIATE`` claim is
    the sole transaction and single-statement writes commit immediately.
    """

    def __init__(self, root_dir: str | Path, tenant_id: str, *, db_path: str | Path | None = None):
        self.tenant_id = tenant_id
        if db_path is not None:
            self._path = Path(db_path).expanduser()
            self._path.parent.mkdir(parents=True, exist_ok=True)
        else:
            root = Path(root_dir).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            self._path = root / safe_tenant_filename(tenant_id, ".db")
        existed = self._path.exists()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        for pragma in PRAGMA_STATEMENTS:
            self._conn.execute(pragma)
        self.ensure_schema()
        if not existed:
            self._path.chmod(0o600)
        self._leased: dict[str, QueueJob] = {}

    def ensure_schema(self) -> None:
        """Apply the shared per-tenant SQLite schema idempotently (the same
        ``ENSURE_STATEMENTS`` the engine applies — reused so the runtime_jobs DDL
        never drifts; all statements are ``IF NOT EXISTS`` so co-opening the file
        the SqliteEngine already created is a no-op)."""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                for statement in ENSURE_STATEMENTS:
                    self._conn.execute(statement)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def enqueue(self, kind: str, payload: dict[str, Any], max_attempts: int = 3) -> QueueJob:
        job = QueueJob(kind=kind, payload=dict(payload), max_attempts=max_attempts)
        with self._lock:
            self._conn.execute(
                "INSERT INTO runtime_jobs(id, tenant_id, kind, payload, status, attempts, "
                "max_attempts, last_error, result, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    self.tenant_id,
                    job.kind,
                    json.dumps(job.payload, sort_keys=True),
                    job.status,
                    job.attempts,
                    job.max_attempts,
                    job.last_error,
                    None if job.result is None else json.dumps(job.result, sort_keys=True),
                    dt_to_json(job.created_at),
                    dt_to_json(job.updated_at),
                ),
            )
        return job

    def lease(self, kind: str | None = None) -> QueueJob | None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if kind:
                    rows = self._conn.execute(
                        "SELECT * FROM runtime_jobs WHERE tenant_id = ? "
                        "AND status IN ('queued', 'retry') AND kind = ?",
                        (self.tenant_id, kind),
                    ).fetchall()
                else:
                    rows = self._conn.execute(
                        "SELECT * FROM runtime_jobs WHERE tenant_id = ? "
                        "AND status IN ('queued', 'retry')",
                        (self.tenant_id,),
                    ).fetchall()
                best_job: QueueJob | None = None
                best_key: tuple[float, datetime, str] | None = None
                for row in rows:
                    job = _sqlite_job_from_row(row)
                    key = (_job_priority(job), job.created_at, job.id)
                    if (
                        best_key is None
                        or key[0] > best_key[0]
                        or (key[0] == best_key[0] and key[1:] < best_key[1:])
                    ):
                        best_job = job
                        best_key = key
                if best_job is None:
                    self._conn.execute("ROLLBACK")
                    return None
                now = datetime.now(UTC)
                self._conn.execute(
                    "UPDATE runtime_jobs SET status = 'running', attempts = attempts + 1, "
                    "updated_at = ? WHERE id = ? AND tenant_id = ?",
                    (dt_to_json(now), best_job.id, self.tenant_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            best_job.status = "running"
            best_job.attempts += 1
            best_job.updated_at = now
            self._leased[best_job.id] = best_job
            return best_job

    def complete(self, job_id: str) -> None:
        with self._lock:
            job = self._leased.pop(job_id, None)
            result = job.result if job else None
            now = datetime.now(UTC)
            self._conn.execute(
                "UPDATE runtime_jobs SET status = 'complete', result = COALESCE(?, result), "
                "updated_at = ? WHERE id = ? AND tenant_id = ?",
                (
                    None if result is None else json.dumps(result, sort_keys=True),
                    dt_to_json(now),
                    job_id,
                    self.tenant_id,
                ),
            )
            if job:
                job.status = "complete"
                job.updated_at = now

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._leased.pop(job_id, None) or self._get_job(job_id)
            status = "dead" if job and job.attempts >= job.max_attempts else "retry"
            now = datetime.now(UTC)
            self._conn.execute(
                "UPDATE runtime_jobs SET status = ?, last_error = COALESCE(?, last_error), "
                "updated_at = ? WHERE id = ? AND tenant_id = ?",
                (status, error, dt_to_json(now), job_id, self.tenant_id),
            )
            if job:
                job.status = status
                job.last_error = error
                job.updated_at = now

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS count FROM runtime_jobs WHERE tenant_id = ? GROUP BY status",
                (self.tenant_id,),
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def list_jobs(self) -> list[QueueJob]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runtime_jobs WHERE tenant_id = ? ORDER BY created_at ASC, id ASC",
                (self.tenant_id,),
            ).fetchall()
        return [_sqlite_job_from_row(row) for row in rows]

    @property
    def jobs(self) -> dict[str, QueueJob]:
        return {job.id: job for job in self.list_jobs()}

    def _get_job(self, job_id: str) -> QueueJob | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_jobs WHERE id = ? AND tenant_id = ?",
                (job_id, self.tenant_id),
            ).fetchone()
        return _sqlite_job_from_row(row) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class QueueWorker:
    def __init__(
        self,
        queue: InProcessQueue | PostgresQueue | SqliteQueue,
        handlers: dict[str, Callable[[dict[str, Any]], Any]],
        metrics: Any | None = None,
    ):
        self.queue = queue
        self.handlers = handlers
        self.metrics = metrics

    def run_once(self, kind: str | None = None) -> QueueJob | None:
        job = self.queue.lease(kind)
        if not job:
            return None
        self._metric(f"queue.job.{job.kind}.started")
        handler = self.handlers.get(job.kind)
        if not handler:
            self.queue.fail(job.id, f"no handler for job kind {job.kind}")
            self._metric(f"queue.job.{job.kind}.failed")
            return job
        try:
            result = handler(job.payload)
            job.result = result.to_dict() if hasattr(result, "to_dict") else result
        except Exception as exc:  # noqa: BLE001 - worker queue must record arbitrary job errors.
            self.queue.fail(job.id, str(exc))
            self._metric(f"queue.job.{job.kind}.failed")
        else:
            self.queue.complete(job.id)
            self._metric(f"queue.job.{job.kind}.complete")
        return job

    def drain(self, limit: int = 10, kind: str | None = None) -> list[QueueJob]:
        completed: list[QueueJob] = []
        for _ in range(max(limit, 0)):
            job = self.run_once(kind)
            if job is None:
                break
            completed.append(job)
        return completed

    def _metric(self, name: str) -> None:
        if self.metrics and hasattr(self.metrics, "increment"):
            self.metrics.increment(name)


def _parse_dt(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _job_priority(job: QueueJob) -> float:
    write_priority = job.payload.get("write_priority") if isinstance(job.payload, dict) else None
    if not isinstance(write_priority, dict):
        return 0.0
    try:
        score = float(write_priority.get("effective_score", write_priority.get("score", 0.0)))
    except (TypeError, ValueError):
        return 0.0
    if score != score:
        return 0.0
    return max(0.0, min(1.0, score))


def _require_psycopg_queue() -> tuple[Any, Any, Any]:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
        from psycopg.types.json import Jsonb  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised when optional dep absent.
        raise PostgresQueueUnavailableError("Install mnemosyne-memory[postgres] to use PostgresQueue.") from exc
    return psycopg, Jsonb, dict_row


def _job_from_row(row: dict[str, Any]) -> QueueJob:
    return QueueJob(
        id=str(row["id"]),
        kind=str(row["kind"]),
        payload=dict(row["payload"] or {}),
        max_attempts=int(row["max_attempts"]),
        status=str(row["status"]),
        attempts=int(row["attempts"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        last_error=row.get("last_error"),
        result=row.get("result"),
    )


def _sqlite_job_from_row(row: sqlite3.Row) -> QueueJob:
    """Rehydrate a QueueJob from a runtime_jobs SQLite row (payload/result are
    JSON TEXT, created_at/updated_at are dt_to_json TEXT parsed via _parse_dt)."""
    payload = row["payload"]
    result = row["result"]
    return QueueJob(
        id=str(row["id"]),
        kind=str(row["kind"]),
        payload=json.loads(payload) if payload else {},
        max_attempts=int(row["max_attempts"]),
        status=str(row["status"]),
        attempts=int(row["attempts"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        last_error=row["last_error"],
        result=json.loads(result) if result else None,
    )
