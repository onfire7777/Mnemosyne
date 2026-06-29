"""PostgreSQL-backed runtime side-state for CLI and MCP tools."""

from __future__ import annotations

from typing import Any

from mnemosyne.gate import RegressionCase
from mnemosyne.learning import FailureAttribution, LearningSystem, Lesson, Procedure, Trajectory
from mnemosyne.observability import MetricsRegistry
from mnemosyne.postgres_engine import (
    _bytes_list_to_cids,
    _cid_list_to_bytes,
    _require_psycopg,
    _stable_uuid,
    _vector_literal,
)
from mnemosyne.queue import InProcessQueue
from mnemosyne.retrieval import HashingEmbeddingProvider
from mnemosyne.user_model import (
    LatentUserProfile,
    SupportStrategy,
    UserMemoryKind,
    UserMistakeEvent,
    UserModel,
    UserModelEntry,
)


_DEFAULT_RUNTIME_PAYLOAD: dict[str, Any] = {
    "user_model": {
        "entries": [],
        "latent_profiles": [],
        "mistake_events": [],
        "support_strategies": [],
        "support_strategy_threshold": 2,
    },
    "learning": {"trajectories": [], "attributions": [], "lessons": [], "procedures": []},
    "queue": {"order": [], "jobs": []},
    "metrics": {"counters": {}, "gauges": {}, "samples": {}},
    "gate_cases": [],
}

_PREFERENCE_CATEGORIES = {"format", "tone", "workflow", "tooling", "domain", "constraint"}


def _support_strategy_threshold(value: Any) -> int:
    try:
        return max(2, int(value))
    except (TypeError, ValueError):
        return 2


class PostgresRuntimeState:
    """Tenant-scoped Postgres implementation of the RuntimeState API.

    Exact JSON payloads preserve local RuntimeState round-trip semantics while
    canonical runtime tables keep profile and learning state queryable under
    tenant RLS.
    """

    def __init__(self, dsn: str, tenant_id: str = "system"):
        self.dsn = dsn
        self.tenant_id = tenant_id or "system"
        self.db_tenant_id = _stable_uuid("tenant", self.tenant_id)
        self._psycopg, self._jsonb = _require_psycopg()
        self.embedding = HashingEmbeddingProvider(dims=1024)
        self.data = dict(_DEFAULT_RUNTIME_PAYLOAD)
        self._ensure_schema()

    def connect(self) -> Any:
        return self._psycopg.connect(self.dsn)

    def _set_tenant(self, cur: Any) -> None:
        cur.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)", (str(self.db_tenant_id),))

    def _ensure_schema(self) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tenants(id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (self.db_tenant_id, self.tenant_id),
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runtime_state (
                      tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                      key TEXT NOT NULL,
                      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      PRIMARY KEY (tenant_id, key)
                    )
                    """
                )
                cur.execute("ALTER TABLE runtime_state ENABLE ROW LEVEL SECURITY")
                cur.execute("ALTER TABLE runtime_state FORCE ROW LEVEL SECURITY")
                cur.execute("DROP POLICY IF EXISTS runtime_state_tenant_isolation ON runtime_state")
                cur.execute(
                    """
                    CREATE POLICY runtime_state_tenant_isolation ON runtime_state
                      USING (tenant_id = mnemosyne_current_tenant())
                      WITH CHECK (tenant_id = mnemosyne_current_tenant())
                    """
                )

    def _load_payload(self, key: str, default: Any) -> Any:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur)
                cur.execute(
                    "SELECT payload FROM runtime_state WHERE tenant_id = %s AND key = %s",
                    (self.db_tenant_id, key),
                )
                row = cur.fetchone()
        return row[0] if row else default

    def _save_payload(self, key: str, payload: Any) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur)
                cur.execute(
                    """
                    INSERT INTO runtime_state(tenant_id, key, payload, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (tenant_id, key)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    (self.db_tenant_id, key, self._jsonb(payload)),
                )

    def load_user_model(self) -> UserModel:
        payload = self._load_payload("user_model", None)
        if payload is None:
            return self._load_user_model_from_tables()
        model = UserModel(
            support_strategy_threshold=_support_strategy_threshold(
                payload.get("support_strategy_threshold", 2)
            )
        )
        for row in payload.get("entries", []):
            entry = UserModelEntry.from_dict(row)
            if entry.tenant_id == self.tenant_id:
                model.add_entry(entry)
        for row in payload.get("latent_profiles", []):
            profile = LatentUserProfile.from_dict(row)
            if profile.tenant_id == self.tenant_id:
                model.set_latent_profile(profile)
        model.mistake_events = [
            event
            for event in (UserMistakeEvent.from_dict(row) for row in payload.get("mistake_events", []))
            if event.tenant_id == self.tenant_id
        ]
        event_scopes = {
            event.id: (event.user_id, event.pattern, event.scope)
            for event in model.mistake_events
        }
        model.support_strategies = {
            strategy.id: strategy
            for strategy in (
                SupportStrategy.from_dict(row) for row in payload.get("support_strategies", [])
            )
            if strategy.tenant_id == self.tenant_id
        }
        for strategy in model.support_strategies.values():
            strategy.supporting_event_ids = [
                event_id
                for event_id in strategy.supporting_event_ids
                if event_scopes.get(event_id) == (strategy.user_id, strategy.pattern, strategy.scope)
            ]
        return model

    def save_user_model(self, model: UserModel) -> None:
        entries = [entry for entry in model.entries.values() if entry.tenant_id == self.tenant_id]
        latent_profiles = [
            profile for profile in model.latent_profiles.values() if profile.tenant_id == self.tenant_id
        ]
        mistake_events = [event for event in model.mistake_events if event.tenant_id == self.tenant_id]
        event_scopes = {
            event.id: (event.user_id, event.pattern, event.scope)
            for event in mistake_events
        }
        support_strategies = [
            strategy for strategy in model.support_strategies.values() if strategy.tenant_id == self.tenant_id
        ]
        serialized_support_strategies = []
        for strategy in support_strategies:
            row = strategy.to_dict()
            row["supporting_event_ids"] = [
                event_id
                for event_id in row["supporting_event_ids"]
                if event_scopes.get(event_id) == (strategy.user_id, strategy.pattern, strategy.scope)
            ]
            serialized_support_strategies.append(row)
        self._save_payload(
            "user_model",
            {
                "entries": [entry.to_dict() for entry in entries],
                "latent_profiles": [profile.to_dict() for profile in latent_profiles],
                "mistake_events": [event.to_dict() for event in mistake_events],
                "support_strategies": serialized_support_strategies,
                "support_strategy_threshold": model.support_strategy_threshold,
            },
        )
        self._mirror_user_model(entries, latent_profiles)

    def load_learning(self, learning: LearningSystem) -> LearningSystem:
        payload = self._load_payload("learning", None)
        if payload is None:
            return self._load_learning_from_tables(learning)
        learning.trajectories = {
            item.id: item for item in (Trajectory.from_dict(row) for row in payload.get("trajectories", []))
        }
        learning.attributions = {
            item.trajectory_id: item
            for item in (FailureAttribution.from_dict(row) for row in payload.get("attributions", []))
        }
        learning.lessons = {item.id: item for item in (Lesson.from_dict(row) for row in payload.get("lessons", []))}
        learning.procedures = {
            item.id: item for item in (Procedure.from_dict(row) for row in payload.get("procedures", []))
        }
        return learning

    def save_learning(self, learning: LearningSystem) -> None:
        trajectories = [item for item in learning.trajectories.values() if item.tenant_id == self.tenant_id]
        trajectory_ids = {item.id for item in trajectories}
        attributions = [item for item in learning.attributions.values() if item.trajectory_id in trajectory_ids]
        lessons = [item for item in learning.lessons.values() if item.tenant_id == self.tenant_id]
        procedures = [item for item in learning.procedures.values() if item.tenant_id == self.tenant_id]
        self._save_payload(
            "learning",
            {
                "trajectories": [item.to_dict() for item in trajectories],
                "attributions": [item.to_dict() for item in attributions],
                "lessons": [item.to_dict() for item in lessons],
                "procedures": [item.to_dict() for item in procedures],
            },
        )
        self._mirror_learning(trajectories, lessons, procedures)

    def load_queue(self) -> InProcessQueue:
        return InProcessQueue.from_dict(self._load_payload("queue", _DEFAULT_RUNTIME_PAYLOAD["queue"]))

    def save_queue(self, queue: InProcessQueue) -> None:
        self._save_payload("queue", queue.to_dict())

    def load_metrics(self) -> MetricsRegistry:
        return MetricsRegistry(self._load_payload("metrics", _DEFAULT_RUNTIME_PAYLOAD["metrics"]))

    def save_metrics(self, metrics: MetricsRegistry) -> None:
        self._save_payload("metrics", metrics.snapshot().to_dict())

    def load_gate_cases(self) -> list[RegressionCase]:
        payload = self._load_payload("gate_cases", None)
        if payload is not None:
            return [RegressionCase.from_dict(row) for row in payload]
        return self._load_gate_cases_from_tables()

    def save_gate_cases(self, cases: list[RegressionCase]) -> None:
        self._save_payload("gate_cases", [case.to_dict() for case in cases])
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur)
                cur.execute("DELETE FROM eval_cases WHERE tenant_id = %s AND origin = 'runtime_state'", (self.db_tenant_id,))
                for case in cases:
                    cur.execute(
                        """
                        INSERT INTO eval_cases(id, tenant_id, origin, signature, query, expected, tier, protected)
                        VALUES (%s, %s, 'runtime_state', %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                          signature = EXCLUDED.signature,
                          query = EXCLUDED.query,
                          expected = EXCLUDED.expected,
                          tier = EXCLUDED.tier,
                          protected = EXCLUDED.protected
                        """,
                        (
                            case.id,
                            self.db_tenant_id,
                            case.signature,
                            case.query,
                            self._jsonb({"expected_substring": case.expected_substring}),
                            case.tier,
                            case.protected,
                        ),
                    )

    def _load_user_model_from_tables(self) -> UserModel:
        model = UserModel()
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur)
                cur.execute(
                    """
                    SELECT id, user_id, statement, scope, confidence, explicit,
                      exceptions, source_evidence_cids, valid_from, valid_to, status
                    FROM preferences
                    WHERE tenant_id = %s
                    """,
                    (self.db_tenant_id,),
                )
                for row in cur.fetchall():
                    scope = dict(row["scope"] or {})
                    runtime = dict(scope.pop("_mnemosyne_runtime", {}) or {})
                    kind = runtime.get("kind") or (
                        UserMemoryKind.EXPLICIT_PREFERENCE.value if row["explicit"] else UserMemoryKind.INFERRED_PREFERENCE.value
                    )
                    model.add_entry(
                        UserModelEntry(
                            tenant_id=self.tenant_id,
                            user_id=str(runtime.get("user_id") or row["user_id"]),
                            kind=UserMemoryKind(kind),
                            statement=row["statement"],
                            scope=scope,
                            confidence=float(row["confidence"]),
                            exceptions=dict(row["exceptions"] or {}),
                            source_evidence_cids=_bytes_list_to_cids(row["source_evidence_cids"]),
                            valid_from=row["valid_from"],
                            valid_to=row["valid_to"],
                            status=row["status"],
                            id=str(runtime.get("id") or row["id"]),
                        )
                    )
        return model

    def _load_learning_from_tables(self, learning: LearningSystem) -> LearningSystem:
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur)
                cur.execute("SELECT * FROM trajectories WHERE tenant_id = %s", (self.db_tenant_id,))
                learning.trajectories = {
                    str(row["id"]): Trajectory(
                        id=str(row["id"]),
                        tenant_id=self.tenant_id,
                        user_id=str(row["user_id"]),
                        session_id=str(row["session_id"]),
                        task=row["task"],
                        steps=list(row["steps"] or []),
                        outcome=row["outcome"],
                        reward=float(row["reward"] or 0.0),
                        memory_version=bytes(row["memory_version"] or b"").decode("utf-8"),
                        created_at=row["created_at"],
                    )
                    for row in cur.fetchall()
                }
                cur.execute("SELECT * FROM lessons WHERE tenant_id = %s", (self.db_tenant_id,))
                learning.lessons = {
                    str(row["id"]): Lesson(
                        id=str(row["id"]),
                        tenant_id=self.tenant_id,
                        lesson_type=row["lesson_type"],
                        failure_signature=row["failure_signature"] or "",
                        content=row["content"],
                        votes=row["votes"],
                        status=row["status"],
                    )
                    for row in cur.fetchall()
                }
                cur.execute("SELECT * FROM procedures WHERE tenant_id = %s", (self.db_tenant_id,))
                learning.procedures = {
                    str(row["id"]): Procedure(
                        id=str(row["id"]),
                        tenant_id=self.tenant_id,
                        kind=row["kind"],
                        name=row["name"],
                        body=row["body"],
                        signature=dict(row["signature"] or {}),
                        status=row["status"],
                        success_rate=float(row["success_rate"]) if row["success_rate"] is not None else None,
                        n_trials=row["n_trials"],
                    )
                    for row in cur.fetchall()
                }
        return learning

    def _load_gate_cases_from_tables(self) -> list[RegressionCase]:
        with self.connect() as conn:
            with conn.cursor(row_factory=self._psycopg.rows.dict_row) as cur:
                self._set_tenant(cur)
                cur.execute(
                    "SELECT * FROM eval_cases WHERE tenant_id = %s AND origin = 'runtime_state'",
                    (self.db_tenant_id,),
                )
                return [
                    RegressionCase(
                        id=str(row["id"]),
                        signature=row["signature"],
                        query=row["query"],
                        expected_substring=dict(row["expected"] or {}).get("expected_substring", ""),
                        tier=row["tier"],
                        protected=row["protected"],
                    )
                    for row in cur.fetchall()
                ]

    def _mirror_user_model(self, entries: list[UserModelEntry], latent_profiles: list[LatentUserProfile]) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur)
                cur.execute(
                    "DELETE FROM preferences WHERE tenant_id = %s AND scope ? '_mnemosyne_runtime'",
                    (self.db_tenant_id,),
                )
                for entry in entries:
                    scope = dict(entry.scope)
                    scope["_mnemosyne_runtime"] = {
                        "id": entry.id,
                        "kind": entry.kind.value,
                        "user_id": entry.user_id,
                    }
                    cur.execute(
                        """
                        INSERT INTO preferences (
                          id, tenant_id, user_id, category, statement, scope,
                          confidence, explicit, exceptions, source_evidence_cids,
                          valid_from, valid_to, status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                          statement = EXCLUDED.statement,
                          scope = EXCLUDED.scope,
                          confidence = EXCLUDED.confidence,
                          explicit = EXCLUDED.explicit,
                          exceptions = EXCLUDED.exceptions,
                          source_evidence_cids = EXCLUDED.source_evidence_cids,
                          valid_from = EXCLUDED.valid_from,
                          valid_to = EXCLUDED.valid_to,
                          status = EXCLUDED.status
                        """,
                        (
                            entry.id,
                            self.db_tenant_id,
                            _stable_uuid("user", entry.user_id),
                            _preference_category(entry),
                            entry.statement,
                            self._jsonb(scope),
                            entry.confidence,
                            entry.kind != UserMemoryKind.INFERRED_PREFERENCE,
                            self._jsonb(entry.exceptions),
                            _cid_list_to_bytes(entry.source_evidence_cids),
                            entry.valid_from,
                            entry.valid_to,
                            entry.status,
                        ),
                    )
                cur.execute("DELETE FROM user_latent WHERE tenant_id = %s", (self.db_tenant_id,))
                for profile in latent_profiles:
                    embedding = _vector_literal(profile.embedding) if len(profile.embedding) == 1024 else None
                    cur.execute(
                        """
                        INSERT INTO user_latent(tenant_id, user_id, embedding, summary, updated_at)
                        VALUES (%s, %s, %s::vector, %s, %s)
                        ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                          embedding = EXCLUDED.embedding,
                          summary = EXCLUDED.summary,
                          updated_at = EXCLUDED.updated_at
                        """,
                        (
                            self.db_tenant_id,
                            _stable_uuid("user", profile.user_id),
                            embedding,
                            profile.summary,
                            profile.updated_at,
                        ),
                    )

    def _mirror_learning(
        self,
        trajectories: list[Trajectory],
        lessons: list[Lesson],
        procedures: list[Procedure],
    ) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur)
                cur.execute("DELETE FROM trajectories WHERE tenant_id = %s", (self.db_tenant_id,))
                for item in trajectories:
                    cur.execute(
                        """
                        INSERT INTO trajectories (
                          id, tenant_id, user_id, session_id, task, steps,
                          outcome, reward, memory_version, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            item.id,
                            self.db_tenant_id,
                            _stable_uuid("user", item.user_id),
                            _stable_uuid("session", item.session_id),
                            item.task,
                            self._jsonb(item.steps),
                            item.outcome,
                            item.reward,
                            item.memory_version.encode("utf-8"),
                            item.created_at,
                        ),
                    )
                cur.execute("DELETE FROM lessons WHERE tenant_id = %s", (self.db_tenant_id,))
                for item in lessons:
                    cur.execute(
                        """
                        INSERT INTO lessons (
                          id, tenant_id, lesson_type, failure_signature, content,
                          votes, status, embedding
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                        """,
                        (
                            item.id,
                            self.db_tenant_id,
                            item.lesson_type,
                            item.failure_signature,
                            item.content,
                            item.votes,
                            item.status,
                            _vector_literal(self.embedding.embed(item.content)),
                        ),
                    )
                cur.execute("DELETE FROM procedures WHERE tenant_id = %s", (self.db_tenant_id,))
                for item in procedures:
                    cur.execute(
                        """
                        INSERT INTO procedures (
                          id, tenant_id, kind, name, body, signature, embedding,
                          status, success_rate, n_trials
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
                        """,
                        (
                            item.id,
                            self.db_tenant_id,
                            item.kind,
                            item.name,
                            item.body,
                            self._jsonb(item.signature),
                            _vector_literal(self.embedding.embed(f"{item.name}\n{item.body}")),
                            item.status,
                            item.success_rate,
                            item.n_trials,
                        ),
                    )


def _preference_category(entry: UserModelEntry) -> str:
    scoped = str(entry.scope.get("category", "")).lower()
    if scoped in _PREFERENCE_CATEGORIES:
        return scoped
    if entry.kind == UserMemoryKind.HARD_INSTRUCTION:
        return "constraint"
    if entry.kind == UserMemoryKind.IDENTITY:
        return "domain"
    if entry.kind == UserMemoryKind.TEMPORARY_STATE:
        return "domain"
    return "workflow"
