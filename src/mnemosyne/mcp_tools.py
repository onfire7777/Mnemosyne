"""MCP-compatible tool facade for agents."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from mnemosyne.engine import (
    Intention,
    LocalMemoryEngine,
    ProspectiveOperatingPoint,
    TriggerEvaluationContext,
    WorkingMemoryItem,
)
from mnemosyne.ids import new_id
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.gate import Candidate, GATING_CASE_ORIGINS, GateResult, PromotionGate, RegressionCase
from mnemosyne.learning import LearningSystem, Trajectory, counterfactual_replay_score
from mnemosyne.media_limits import DEFAULT_MAX_INGEST_BYTES, enforce_byte_limit
from mnemosyne.models import Assertion, Evidence, Preference, Relation, parse_dt
from mnemosyne.observability import MetricsRegistry
from mnemosyne.parametric import ParametricTier, protected_suite_is_gating, protected_suite_report
from mnemosyne.postgres_engine import _stable_uuid as _postgres_stable_uuid
from mnemosyne.prefetch import AnticipatoryPrefetcher, PrefetchCandidate
from mnemosyne.privacy import ErasureMode
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.security import SecurityPolicy, SessionIdentity, TrustTier, WriteRole
from mnemosyne.source_truth import apply_markdown_git_source
from mnemosyne.user_model import UserMemoryKind, UserMistakeEvent, UserModel, UserModelEntry


def _parse_prospective_datetime(value: str, *, field: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


TOOL_SPEC: list[dict[str, Any]] = [
    {
        "name": "working_seed",
        "description": "Seed tenant/session-scoped working memory with bounded TTL and evidence provenance.",
        "arguments": ["tenant_id", "session_id", "user_id", "agent_id", "task_id", "branch", "kind", "content", "evidence_ids", "ttl_seconds", "created_at", "role", "source_trust_tier"],
    },
    {
        "name": "working_query",
        "description": "List live working-memory items in an explicit authenticated subject scope.",
        "arguments": ["tenant_id", "session_id", "user_id", "agent_id", "task_id", "branch", "as_of"],
    },
    {
        "name": "working_promote",
        "description": "Promote one working item through the regression-backed promotion gate.",
        "arguments": ["tenant_id", "session_id", "user_id", "agent_id", "task_id", "branch", "item_id", "as_of", "cases", "role", "source_trust_tier"],
    },
    {
        "name": "working_expire",
        "description": "Expire due working-memory items in an explicit authenticated subject scope.",
        "arguments": ["tenant_id", "session_id", "user_id", "agent_id", "task_id", "branch", "expired_at", "role", "source_trust_tier"],
    },
    {
        "name": "capture",
        "description": "Append verbatim evidence to the content-addressed ledger.",
        "arguments": ["tenant_id", "user_id", "actor", "source_type", "content"],
    },
    {
        "name": "ingest",
        "description": "Run the ingestion pipeline with provenance verification and optional object externalization.",
        "arguments": [
            "tenant_id",
            "user_id",
            "actor",
            "source_type",
            "content",
            "data",
            "media_type",
            "modality",
            "signed_provenance",
            "capability_tags",
        ],
    },
    {
        "name": "assert_fact",
        "description": "Upsert a typed assertion with evidence provenance.",
        "arguments": ["tenant_id", "subject", "predicate", "object_value", "source_evidence_cids"],
    },
    {
        "name": "source_sync",
        "description": "Compile committed Markdown/git source-of-truth assertion blocks into evidence-backed memory.",
        "arguments": ["tenant_id", "user_id", "root"],
    },
    {
        "name": "relation",
        "description": "Add a temporal relation edge for graph retrieval.",
        "arguments": ["tenant_id", "source", "predicate", "target"],
    },
    {
        "name": "preference",
        "description": "Record an explicit or inferred preference with precedence rules.",
        "arguments": ["tenant_id", "user_id", "category", "statement"],
    },
    {
        "name": "schedule_intention",
        "description": "Schedule a data-only prospective-memory intention backed by originating evidence.",
        "arguments": [
            "tenant_id",
            "user_id",
            "agent_id",
            "trigger_type",
            "trigger_expression",
            "action",
            "due_at",
            "evidence_ids",
            "priority",
            "dependencies",
            "reschedule_history",
            "recurrence_policy",
        ],
    },
    {
        "name": "update_intention",
        "description": "Reschedule or replace the data-only action for an authenticated subject intention.",
        "arguments": [
            "tenant_id", "intention_id", "user_id", "agent_id", "due_at",
            "action", "recurrence_policy",
        ],
    },
    {
        "name": "cancel_intention",
        "description": "Cancel a scheduled prospective-memory intention as its owning user or agent.",
        "arguments": [
            "tenant_id",
            "intention_id",
            "cancelled_by",
        ],
    },
    {
        "name": "evaluate_intentions",
        "description": "Evaluate due prospective-memory intentions from an authenticated scheduler context.",
        "arguments": ["tenant_id", "evaluated_at", "trigger_context", "operating_point"],
    },
    {
        "name": "list_intentions",
        "description": "List prospective-memory intentions owned by the authenticated subject.",
        "arguments": ["tenant_id"],
    },
    {
        "name": "search",
        "description": "Fast hybrid retrieval with trust filtering, provenance, confidence, and abstention.",
        "arguments": ["tenant_id", "query"],
    },
    {
        "name": "deep_search",
        "description": "Expanded retrieval path with graph channel enabled when graph data exists.",
        "arguments": ["tenant_id", "query"],
    },
    {
        "name": "get",
        "description": "Fetch one memory record by id or cid from the tenant export surface.",
        "arguments": ["tenant_id", "id"],
    },
    {
        "name": "explain",
        "description": "Return retrieval stages, channels, provenance, confidence, and immutable rails.",
        "arguments": ["tenant_id", "query"],
    },
    {
        "name": "propose",
        "description": "Write a candidate fact into an isolated proposal branch for later confirmation.",
        "arguments": ["tenant_id", "user_id", "subject", "predicate", "object_value"],
    },
    {
        "name": "confirm",
        "description": "Confirm a proposed branch or candidate id by merging it into main.",
        "arguments": ["id"],
    },
    {
        "name": "correct",
        "description": "Record an authoritative correction and upsert the superseding assertion.",
        "arguments": ["tenant_id", "user_id", "subject", "predicate", "object_value", "correction_text"],
    },
    {
        "name": "supersede",
        "description": "Supersede an existing assertion with a newer assertion value.",
        "arguments": ["tenant_id", "user_id", "id", "new"],
    },
    {
        "name": "forget",
        "description": "Erase evidence content and propagate retraction or provenance trimming.",
        "arguments": ["tenant_id", "cid"],
    },
    {
        "name": "export",
        "description": "Export a caller-scoped tenant disclosure view with omissions and redactions reported.",
        "arguments": ["tenant_id", "role", "user_id", "max_sensitivity", "capability_tags", "purpose"],
    },
    {
        "name": "residency_policy",
        "description": "Inspect configured data/runtime residency enforcement and transfer allowlists.",
        "arguments": [],
    },
    {
        "name": "branch",
        "description": "Create a branch from an existing branch.",
        "arguments": ["name"],
    },
    {
        "name": "merge",
        "description": "Merge a branch into another branch through the engine contract.",
        "arguments": ["from_branch"],
    },
    {
        "name": "discard",
        "description": "Discard a non-main branch and its candidate memories.",
        "arguments": ["branch"],
    },
    {
        "name": "profile_add",
        "description": "Add a typed user-model entry.",
        "arguments": ["tenant_id", "user_id", "kind", "statement"],
    },
    {
        "name": "profile_context",
        "description": "Return scope-matched user-model context.",
        "arguments": ["tenant_id", "user_id"],
    },
    {
        "name": "profile_get_relevant",
        "description": "Blueprint alias for returning relevant user-profile context.",
        "arguments": ["tenant_id", "user_id"],
    },
    {
        "name": "profile_record_explicit",
        "description": "Blueprint alias for recording an explicit user preference.",
        "arguments": ["tenant_id", "user_id", "statement"],
    },
    {
        "name": "profile_propose_inference",
        "description": "Blueprint alias for proposing an inferred user preference.",
        "arguments": ["tenant_id", "user_id", "statement"],
    },
    {
        "name": "profile_correct",
        "description": "Record an explicit profile correction that supersedes weaker entries.",
        "arguments": ["tenant_id", "user_id", "id", "statement"],
    },
    {
        "name": "profile_record_mistake",
        "description": "Record a neutral user-slip episode and promote scoped support only after repeated similar events.",
        "arguments": ["tenant_id", "user_id", "pattern", "description"],
    },
    {
        "name": "profile_retire_support_strategy",
        "description": "Retire a scoped support strategy so it no longer appears in profile context.",
        "arguments": ["tenant_id", "user_id", "strategy_id", "role", "source_trust_tier"],
    },
    {
        "name": "prefetch",
        "description": "Warm retrieval contexts through the anticipatory predictability gate.",
        "arguments": ["tenant_id", "candidates"],
    },
    {
        "name": "graph_neighbors",
        "description": "Run tenant- and branch-scoped graph PPR over relation seeds.",
        "arguments": ["tenant_id", "seeds"],
    },
    {
        "name": "graph_query",
        "description": "Blueprint alias for graph neighbor query over relation seeds.",
        "arguments": ["tenant_id", "seeds"],
    },
    {
        "name": "graph_timeline",
        "description": "Return assertion and relation events involving an entity.",
        "arguments": ["tenant_id", "entity"],
    },
    {
        "name": "graph_as_of",
        "description": "Return bitemporal assertions for a subject/predicate at a timestamp.",
        "arguments": ["tenant_id", "subject", "predicate", "time"],
    },
    {
        "name": "trajectory_log",
        "description": "Persist a trajectory for procedural/corrective learning.",
        "arguments": ["tenant_id", "user_id", "session_id", "task", "steps", "outcome", "reward", "memory_version"],
    },
    {
        "name": "trajectory_record",
        "description": "Blueprint alias for persisting a trajectory.",
        "arguments": ["tenant_id", "user_id", "session_id", "task", "steps", "outcome", "reward", "memory_version"],
    },
    {
        "name": "trajectory_attribute",
        "description": "Attribute a logged failure trajectory.",
        "arguments": ["trajectory_id"],
    },
    {
        "name": "lesson_induce",
        "description": "Induce a corrective lesson from a failure attribution.",
        "arguments": ["trajectory_id"],
    },
    {
        "name": "lesson_propose",
        "description": "Blueprint alias for proposing a lesson from a trajectory.",
        "arguments": ["trajectory_id"],
    },
    {
        "name": "procedure_induce",
        "description": "Induce a procedure from a corrective lesson.",
        "arguments": ["lesson_id"],
    },
    {
        "name": "procedure_propose",
        "description": "Blueprint alias for proposing a procedure from a lesson.",
        "arguments": ["lesson_id"],
    },
    {
        "name": "lesson_promote",
        "description": "Promote a lesson through protected regression cases.",
        "arguments": ["lesson_id", "cases", "role", "source_trust_tier"],
    },
    {
        "name": "procedure_validate",
        "description": "Mark an induced procedure as validated for the isolated parametric tier.",
        "arguments": ["procedure_id", "role", "source_trust_tier"],
    },
    {
        "name": "procedure_promote",
        "description": "Promote a validated procedure into the active procedural tier.",
        "arguments": ["procedure_id", "role", "source_trust_tier"],
    },
    {
        "name": "procedure_search",
        "description": "Search procedures by name, body, signature, tenant, and status.",
        "arguments": ["query"],
    },
    {
        "name": "procedure_rollback",
        "description": "Mark a procedure as rolled back without deleting history.",
        "arguments": ["procedure_id", "role", "source_trust_tier"],
    },
    {
        "name": "lesson_search",
        "description": "Search lessons by failure signature, content, tenant, and status.",
        "arguments": ["signature"],
    },
    {
        "name": "outcome_evaluate",
        "description": "Evaluate a logged trajectory outcome or counterfactual before/after counts.",
        "arguments": ["trajectory_id"],
    },
    {
        "name": "parametric_propose",
        "description": "Create an isolated shadow parametric artifact from active lessons/procedures.",
        "arguments": ["tenant_id", "role", "source_trust_tier"],
    },
    {
        "name": "parametric_evaluate",
        "description": "Evaluate a shadow parametric artifact against persisted protected gate evidence.",
        "arguments": ["artifact_uri", "role", "source_trust_tier", "protected_case_count"],
    },
    {
        "name": "parametric_rollback",
        "description": "Roll back a persisted isolated parametric artifact with protected-suite evidence.",
        "arguments": ["artifact_uri", "reason", "role", "source_trust_tier", "protected_case_count"],
    },
]


class MemoryTools:
    def __init__(
        self,
        engine: LocalMemoryEngine,
        ingestion: IngestionPipeline | None = None,
        prefetcher: AnticipatoryPrefetcher | None = None,
        user_model: UserModel | None = None,
        learning: LearningSystem | None = None,
        runtime_state: RuntimeState | None = None,
        security: SecurityPolicy | None = None,
        parametric: ParametricTier | None = None,
        metrics: MetricsRegistry | None = None,
    ):
        self.engine = engine
        self.ingestion = ingestion or IngestionPipeline(engine)
        self.prefetcher = prefetcher or AnticipatoryPrefetcher(engine)
        self.runtime_state = runtime_state
        self.security = security or SecurityPolicy()
        self.user_model = user_model or (runtime_state.load_user_model() if runtime_state else UserModel())
        self.learning = learning or LearningSystem(engine)
        if runtime_state:
            self.learning = runtime_state.load_learning(self.learning)
        self.parametric = parametric or ParametricTier()
        self.metrics = metrics or (runtime_state.load_metrics() if runtime_state else MetricsRegistry())

    @staticmethod
    def _working_time(value: str | datetime, name: str) -> datetime:
        parsed = parse_dt(value)
        if parsed is None or parsed.tzinfo is None:
            raise ValueError(f"{name} must be an ISO 8601 timestamp with timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _working_matches(
        item: WorkingMemoryItem, *, user_id: str, agent_id: str, task_id: str, branch: str
    ) -> bool:
        return (
            item.user_id == user_id
            and item.agent_id == agent_id
            and item.task_id == task_id
            and item.metadata.get("branch") == branch
        )

    def _authorize_working(
        self,
        identity: SessionIdentity | None,
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        agent_id: str,
    ) -> SessionIdentity:
        authorization = self._authorize_prospective(
            "read",
            identity,
            tenant_id=tenant_id,
            owner_id=user_id,
        )
        if not isinstance(identity, SessionIdentity):
            raise PermissionError("working memory requires verified session identity")
        if not identity.agent_id or identity.agent_id != agent_id:
            raise PermissionError("working memory agent mismatch")
        if not identity.session_id or identity.session_id != session_id:
            raise PermissionError("working memory session mismatch")
        if authorization.tenant_id != tenant_id or authorization.owner_id != user_id:
            raise PermissionError("working memory subject mismatch")
        return identity

    def working_seed(
        self, tenant_id: str, session_id: str, user_id: str, agent_id: str,
        task_id: str, branch: str, kind: str, content: str, evidence_ids: list[str],
        ttl_seconds: int, created_at: str | datetime, role: WriteRole = "agent",
        source_trust_tier: int = int(TrustTier.NORMAL), item_id: str | None = None,
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        identity = self._authorize_working(
            session_identity, tenant_id=tenant_id, session_id=session_id,
            user_id=user_id, agent_id=agent_id,
        )
        role = identity.role
        source_trust_tier = identity.source_trust_tier
        if type(ttl_seconds) is not int or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        if ttl_seconds > 24 * 60 * 60:
            raise ValueError("ttl_seconds must not exceed 86400")
        security = self._authorize(
            "working_seed", role=role, source_trust_tier=source_trust_tier, target_sink="belief"
        )
        created = self._working_time(created_at, "created_at")
        item = WorkingMemoryItem(
            item_id=item_id or new_id(), tenant_id=tenant_id, session_id=session_id,
            user_id=user_id, agent_id=agent_id, kind=kind, task_id=task_id,
            content=content, created_at=created, expires_at=created + timedelta(seconds=ttl_seconds),
            evidence_ids=evidence_ids, trust_tier=source_trust_tier,
            access_policy={"tenant": tenant_id}, metadata={"branch": branch},
        )
        self.engine.put_working(item)
        return {"item": item.to_dict(), "security": security}

    def working_query(
        self, tenant_id: str, session_id: str, user_id: str, agent_id: str,
        task_id: str, branch: str, as_of: str | datetime,
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        self._authorize_working(
            session_identity, tenant_id=tenant_id, session_id=session_id,
            user_id=user_id, agent_id=agent_id,
        )
        clock = self._working_time(as_of, "as_of")
        items = [
            item for item in self.engine.list_working(tenant_id, session_id, as_of=clock)
            if self._working_matches(item, user_id=user_id, agent_id=agent_id, task_id=task_id, branch=branch)
        ]
        return {"as_of": clock.isoformat(), "items": [item.to_dict() for item in items]}

    def working_promote(
        self, tenant_id: str, session_id: str, user_id: str, agent_id: str,
        task_id: str, branch: str, item_id: str, as_of: str | datetime,
        cases: list[dict[str, Any]], role: WriteRole, source_trust_tier: int,
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        identity = self._authorize_working(
            session_identity, tenant_id=tenant_id, session_id=session_id,
            user_id=user_id, agent_id=agent_id,
        )
        role = identity.role
        source_trust_tier = identity.source_trust_tier
        security = self._authorize(
            "working_promote", role=role, source_trust_tier=source_trust_tier,
            target_sink="branch_promotion",
        )
        if not cases:
            raise ValueError("working promotion requires explicit regression cases")
        clock = self._working_time(as_of, "as_of")
        item = self.engine.get_working(tenant_id, session_id, item_id, as_of=clock)
        if item is None or not self._working_matches(
            item, user_id=user_id, agent_id=agent_id, task_id=task_id, branch=branch
        ):
            raise KeyError("live working item not found in authenticated scope")
        regression_cases = [RegressionCase.from_dict(case) for case in cases]
        candidate = Candidate(
            id=item.item_id, kind="fact", signature=f"{item.kind} {item.task_id}",
            description=item.content, branch=f"working-promote-{new_id()}",
            source_evidence_cids=list(item.evidence_ids),
        )

        def apply_candidate(engine: LocalMemoryEngine, candidate_branch: str) -> None:
            engine.upsert_assertion(
                Assertion(
                    tenant_id=tenant_id, user_id=user_id, subject=item.task_id,
                    predicate=item.kind, object=item.content,
                    source_evidence_cids=list(item.evidence_ids), trust_tier=item.trust_tier,
                    access_policy=dict(item.access_policy),
                ),
                branch=candidate_branch,
            )

        gate = PromotionGate(self.engine, regression_cases).evaluate(tenant_id, candidate, apply_candidate)
        return {"item_id": item.item_id, "gate": gate.to_dict(), "security": security}

    def working_expire(
        self, tenant_id: str, session_id: str, user_id: str, agent_id: str,
        task_id: str, branch: str, expired_at: str | datetime, role: WriteRole,
        source_trust_tier: int, session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        identity = self._authorize_working(
            session_identity, tenant_id=tenant_id, session_id=session_id,
            user_id=user_id, agent_id=agent_id,
        )
        role = identity.role
        source_trust_tier = identity.source_trust_tier
        security = self._authorize(
            "working_expire", role=role, source_trust_tier=source_trust_tier,
            destructive=True, target_sink="belief",
        )
        clock = self._working_time(expired_at, "expired_at")
        expired = self.engine.expire_working(
            tenant_id,
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            task_id=task_id,
            branch=branch,
            expired_at=clock,
        )
        return {"expired_at": clock.isoformat(), "items": [item.to_dict() for item in expired], "security": security}

    def capture(
        self,
        tenant_id: str,
        user_id: str,
        actor: str,
        source_type: str,
        content: str,
        branch: str = "main",
        trust_tier: int = int(TrustTier.DIRECT_USER),
        source_identity: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enforce_byte_limit(
            content.encode("utf-8"),
            limit=getattr(self.ingestion, "max_ingest_bytes", DEFAULT_MAX_INGEST_BYTES),
            label="capture content",
        )
        cid = self.engine.append_evidence(
            Evidence(
                tenant_id=tenant_id,
                user_id=user_id,
                actor=actor,  # type: ignore[arg-type]
                source_type=source_type,
                source_identity=source_identity,
                session_id=session_id,
                content=content,
                metadata=metadata or {},
                trust_tier=trust_tier,
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )
        return {"cid": cid, "branch": branch, "idempotent": True}

    def ingest(
        self,
        tenant_id: str,
        user_id: str,
        actor: str,
        source_type: str,
        content: str | None = None,
        data: bytes | None = None,
        branch: str = "main",
        trust_tier: int | None = None,
        source_identity: str | None = None,
        media_type: str = "text/plain",
        modality: str = "text",
        metadata: dict[str, Any] | None = None,
        signed_provenance: dict[str, Any] | None = None,
        capability_tags: list[str] | None = None,
        sensitivity: int = 0,
    ) -> dict[str, Any]:
        if isinstance(data, str):
            max_bytes = getattr(self.ingestion, "max_ingest_bytes", DEFAULT_MAX_INGEST_BYTES)
            try:
                encoded = data.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError("ingest data must be base64-encoded when sent as a string") from exc
            max_encoded = ((max_bytes + 2) // 3) * 4
            if len(encoded) > max_encoded:
                raise ValueError(f"ingest data exceeds byte limit ({len(encoded)} base64 bytes > {max_encoded})")
            try:
                data = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise ValueError("ingest data must be base64-encoded when sent as a string") from exc
            enforce_byte_limit(data, limit=max_bytes, label="ingest data")
        elif data is not None:
            enforce_byte_limit(
                data,
                limit=getattr(self.ingestion, "max_ingest_bytes", DEFAULT_MAX_INGEST_BYTES),
                label="ingest data",
            )
        if content is None and data is None:
            raise ValueError("ingest requires content or data")
        return self.ingestion.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                actor=actor,
                source_type=source_type,
                content=content,
                data=data,
                source_identity=source_identity,
                media_type=media_type,
                modality=modality,  # type: ignore[arg-type]
                metadata=metadata or {},
                signed_provenance=signed_provenance,
                trust_tier=trust_tier,
                capability_tags=capability_tags or [],
                sensitivity=sensitivity,
            ),
            branch=branch,
        ).to_dict()

    def residency_policy(self) -> dict[str, object]:
        return self.ingestion.residency_policy()

    def assert_fact(
        self,
        tenant_id: str,
        subject: str,
        predicate: str,
        object_value: str,
        source_evidence_cids: list[str],
        user_id: str | None = None,
        branch: str = "main",
        confidence: float = 0.7,
        trust_tier: int = int(TrustTier.DIRECT_USER),
        role: WriteRole = "agent",
        source_trust_tier: int | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize(
            "assert_fact",
            role=role,
            source_trust_tier=source_trust_tier if source_trust_tier is not None else trust_tier,
            target_sink="belief",
        )
        assertion_id = self.engine.upsert_assertion(
            Assertion(
                tenant_id=tenant_id,
                user_id=user_id,
                subject=subject,
                predicate=predicate,
                object=object_value,
                source_evidence_cids=source_evidence_cids,
                confidence=confidence,
                status="active",
                trust_tier=trust_tier,
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )
        return {"id": assertion_id, "branch": branch, "security": decision}

    def source_sync(
        self,
        tenant_id: str,
        user_id: str,
        root: str,
        branch: str = "main",
        apply: bool = False,
        role: WriteRole = "operator",
        source_trust_tier: int = int(TrustTier.USER_AUTHORED),
        allow_dirty: bool = False,
    ) -> dict[str, Any]:
        decision = self._authorize(
            "source_sync",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="belief_correction",
        )
        result = apply_markdown_git_source(
            self.engine,
            tenant_id=tenant_id,
            user_id=user_id,
            root=root,
            branch=branch,
            apply=apply,
            source_trust_tier=source_trust_tier,
            require_clean_git=not allow_dirty,
        ).to_dict()
        result["security"] = decision
        return result

    def relation(
        self,
        tenant_id: str,
        source: str,
        predicate: str,
        target: str,
        branch: str = "main",
        confidence: float = 0.7,
        source_evidence_cids: list[str] | None = None,
        role: WriteRole = "agent",
        source_trust_tier: int = int(TrustTier.NORMAL),
    ) -> dict[str, Any]:
        decision = self._authorize(
            "relation",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="belief",
        )
        relation_id = self.engine.add_relation(
            Relation(
                tenant_id=tenant_id,
                source=source,
                predicate=predicate,
                target=target,
                confidence=confidence,
                source_evidence_cids=source_evidence_cids or [],
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )
        return {"id": relation_id, "branch": branch, "security": decision}

    def preference(
        self,
        tenant_id: str,
        user_id: str,
        category: str,
        statement: str,
        explicit: bool = False,
        confidence: float = 0.7,
        source_evidence_cids: list[str] | None = None,
        access_policy: dict[str, Any] | None = None,
        role: WriteRole = "agent",
        source_trust_tier: int | None = None,
    ) -> dict[str, Any]:
        trust = source_trust_tier if source_trust_tier is not None else (int(TrustTier.USER_AUTHORED) if explicit else int(TrustTier.UNTRUSTED_EXTERNAL))
        decision = self._authorize(
            "preference",
            role=role,
            source_trust_tier=trust,
            target_sink="preference",
        )
        preference_id = self.engine.add_preference(
            Preference(
                tenant_id=tenant_id,
                user_id=user_id,
                category=category,  # type: ignore[arg-type]
                statement=statement,
                explicit=explicit,
                confidence=confidence,
                source_evidence_cids=source_evidence_cids or [],
                access_policy=access_policy or {},
            )
        )
        return {"id": preference_id, "security": decision}

    def schedule_intention(
        self,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        trigger_type: str,
        trigger_expression: dict[str, Any],
        action: dict[str, Any],
        due_at: str,
        evidence_ids: list[str],
        priority: str = "normal",
        dependencies: list[str] | None = None,
        reschedule_history: list[dict[str, Any]] | None = None,
        recurrence_policy: dict[str, Any] | None = None,
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        authorization = self._authorize_prospective(
            "schedule",
            session_identity,
            tenant_id=tenant_id,
            actor_id=user_id,
            owner_id=user_id,
            agent_id=agent_id,
        )
        assert isinstance(session_identity, SessionIdentity)
        if not session_identity.session_id:
            raise PermissionError(
                "schedule intention denied: authenticated session identifier is required"
            )
        intention = Intention(
            intention_id=new_id(),
            tenant_id=authorization.tenant_id or tenant_id,
            user_id=authorization.owner_id or user_id,
            agent_id=authorization.agent_id or agent_id,
            trigger_type=trigger_type,
            trigger_expression=trigger_expression,
            action=action,
            due_at=_parse_prospective_datetime(due_at, field="due_at"),
            priority=priority,
            dependencies=dependencies or [],
            reschedule_history=reschedule_history or [],
            evidence_ids=evidence_ids,
            session_id=session_identity.session_id,
            recurrence_policy=recurrence_policy or {"type": "none"},
        )
        self.engine.schedule_intention(intention)
        return intention.to_dict()

    def update_intention(
        self,
        tenant_id: str,
        intention_id: str,
        user_id: str,
        agent_id: str,
        due_at: str | None = None,
        action: dict[str, Any] | None = None,
        recurrence_policy: dict[str, Any] | None = None,
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        authorization = self._authorize_prospective(
            "update", session_identity, tenant_id=tenant_id, actor_id=user_id,
            owner_id=user_id, agent_id=agent_id,
        )
        assert isinstance(session_identity, SessionIdentity)
        if not session_identity.session_id:
            raise PermissionError("update intention denied: authenticated session identifier is required")
        updated = self.engine.update_intention(
            authorization.tenant_id or tenant_id, intention_id,
            user_id=authorization.owner_id or user_id,
            agent_id=authorization.agent_id or agent_id,
            session_id=session_identity.session_id,
            due_at=(_parse_prospective_datetime(due_at, field="due_at") if due_at is not None else None),
            action=action, recurrence_policy=recurrence_policy,
        )
        return updated.to_dict()

    def cancel_intention(
        self,
        tenant_id: str,
        intention_id: str,
        cancelled_by: str,
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        authorization = self._authorize_prospective(
            "cancel",
            session_identity,
            tenant_id=tenant_id,
            actor_id=session_identity.user_id if isinstance(session_identity, SessionIdentity) else None,
            owner_id=session_identity.user_id if isinstance(session_identity, SessionIdentity) else None,
        )
        assert isinstance(session_identity, SessionIdentity)
        allowed_principals = {session_identity.user_id}
        if session_identity.agent_id:
            allowed_principals.add(session_identity.agent_id)
        if cancelled_by not in allowed_principals:
            raise PermissionError("cancel intention denied: cancellation principal is not authenticated")
        if not session_identity.session_id:
            raise PermissionError(
                "cancel intention denied: authenticated session identifier is required"
            )
        authorized_tenant = authorization.tenant_id or tenant_id
        current = next(
            (
                intention
                for intention in self.engine.list_intentions(authorized_tenant)
                if intention.intention_id == intention_id
            ),
            None,
        )
        if (
            current is not None
            and current.session_id is not None
            and current.session_id != session_identity.session_id
        ):
            raise PermissionError(
                "cancel intention denied: intention session does not match authenticated session"
            )
        if (
            current is not None
            and cancelled_by != session_identity.user_id
            and current.user_id != session_identity.user_id
            and current.user_id != _postgres_stable_uuid("user", session_identity.user_id)
        ):
            # A shared agent identity must not reach across users: the agent
            # principal only cancels intentions the authenticated user owns.
            # Pre-backfill Postgres rows expose the internal user UUID as
            # their external user id, so the authenticated user must also be
            # matched through the same stable-UUID mapping the engine applies.
            raise PermissionError(
                "cancel intention denied: agent principal may only cancel the authenticated user's intentions"
            )
        self.engine.cancel_intention(
            authorized_tenant,
            intention_id,
            cancelled_by=cancelled_by,
            session_id=session_identity.session_id,
        )
        return next(
            intention.to_dict()
            for intention in self.engine.list_intentions(authorized_tenant)
            if intention.intention_id == intention_id
        )

    def evaluate_intentions(
        self,
        tenant_id: str,
        evaluated_at: str,
        trigger_context: dict[str, Any],
        operating_point: dict[str, Any],
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        authorization = self._authorize_prospective(
            "evaluate",
            session_identity,
            tenant_id=tenant_id,
        )
        evaluated = _parse_prospective_datetime(
            evaluated_at,
            field="evaluated_at",
        )
        if type(trigger_context) is not dict:
            raise ValueError("trigger_context must be a JSON object")
        if type(operating_point) is not dict:
            raise ValueError("operating_point must be a JSON object")
        context_tenant_id = trigger_context.get("tenant_id", authorization.tenant_id or tenant_id)
        if context_tenant_id != (authorization.tenant_id or tenant_id):
            raise ValueError("trigger_context tenant_id must match authenticated tenant")
        context_arguments = dict(trigger_context)
        context_arguments["tenant_id"] = authorization.tenant_id or tenant_id
        context = TriggerEvaluationContext(**context_arguments)
        point = ProspectiveOperatingPoint(**operating_point)
        intentions = self.engine.evaluate_due_intentions(
            authorization.tenant_id or tenant_id,
            evaluated_at=evaluated,
            trigger_context=context,
            operating_point=point,
        )
        return {"intentions": [intention.to_dict() for intention in intentions]}

    def list_intentions(
        self,
        tenant_id: str,
        session_identity: SessionIdentity | None = None,
    ) -> dict[str, Any]:
        authorization = self._authorize_prospective(
            "read",
            session_identity,
            tenant_id=tenant_id,
            owner_id=session_identity.user_id if isinstance(session_identity, SessionIdentity) else None,
        )
        intentions = [
            intention
            for intention in self.engine.list_intentions(authorization.tenant_id or tenant_id)
            if intention.user_id == authorization.owner_id
        ]
        return {"intentions": [intention.to_dict() for intention in intentions]}

    def _authorize_prospective(
        self,
        operation: str,
        identity: SessionIdentity | None,
        *,
        tenant_id: str,
        actor_id: str | None = None,
        owner_id: str | None = None,
        agent_id: str | None = None,
    ) -> Any:
        # Updates are policy-equivalent to schedule: the Task 5 lease forbids
        # broadening SecurityPolicy, while the denial message below keeps the
        # real operation name.
        policy_operation = "schedule" if operation == "update" else operation
        decision = self.security.authorize_prospective_memory(
            policy_operation,
            identity,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            actor_id=actor_id,
            owner_id=owner_id,
            agent_id=agent_id,
        )
        if not decision.allowed:
            raise PermissionError(f"{operation} intention denied: {decision.reason}")
        return decision

    def search(
        self,
        tenant_id: str,
        query: str,
        branch: str = "main",
        min_trust_tier: int | None = None,
        max_trust_tier: int | None = None,
        max_sensitivity: int | None = None,
        role: WriteRole = "reader",
        user_id: str | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
        residency: str | None = None,
        region: str | None = None,
        break_glass: bool = False,
        lawful_basis: str | list[str] | None = None,
    ) -> dict[str, Any]:
        filt = self._read_context(
            tenant_id,
            role=role,
            user_id=user_id,
            max_sensitivity=max_sensitivity,
            capability_tags=capability_tags,
            purpose=purpose,
            residency=residency,
            region=region,
            break_glass=break_glass,
            lawful_basis=lawful_basis,
        )
        if max_trust_tier is not None:
            filt["max_trust_tier"] = max_trust_tier
        elif min_trust_tier is not None:
            filt["min_trust_tier"] = min_trust_tier
        start = perf_counter()
        result = self.engine.retrieve(query=query, tenant_id=tenant_id, branch=branch, filt=filt)
        self._record_retrieval(result.to_dict(), start)
        return result.to_dict()

    def deep_search(
        self,
        tenant_id: str,
        query: str,
        branch: str = "main",
        role: WriteRole = "reader",
        user_id: str | None = None,
        max_sensitivity: int | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
        residency: str | None = None,
        region: str | None = None,
        break_glass: bool = False,
        lawful_basis: str | list[str] | None = None,
    ) -> dict[str, Any]:
        start = perf_counter()
        filt = self._read_context(
            tenant_id,
            role=role,
            user_id=user_id,
            max_sensitivity=max_sensitivity,
            capability_tags=capability_tags,
            purpose=purpose,
            residency=residency,
            region=region,
            break_glass=break_glass,
            lawful_basis=lawful_basis,
        )
        result = self.engine.deep_search(query=query, tenant_id=tenant_id, branch=branch, filt=filt)
        self._record_retrieval(result.to_dict(), start)
        return result.to_dict()

    def explain(
        self,
        tenant_id: str,
        query: str,
        branch: str = "main",
        role: WriteRole = "reader",
        user_id: str | None = None,
        max_sensitivity: int | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
        residency: str | None = None,
        region: str | None = None,
        break_glass: bool = False,
        lawful_basis: str | list[str] | None = None,
    ) -> dict[str, Any]:
        start = perf_counter()
        filt = self._read_context(
            tenant_id,
            role=role,
            user_id=user_id,
            max_sensitivity=max_sensitivity,
            capability_tags=capability_tags,
            purpose=purpose,
            residency=residency,
            region=region,
            break_glass=break_glass,
            lawful_basis=lawful_basis,
        )
        result = self.engine.deep_search(query=query, tenant_id=tenant_id, branch=branch, filt=filt)
        self._record_retrieval(result.to_dict(), start)
        return result.to_dict()

    @staticmethod
    def _read_context(
        tenant_id: str,
        *,
        role: WriteRole = "reader",
        user_id: str | None = None,
        max_sensitivity: int | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
        residency: str | None = None,
        region: str | None = None,
        break_glass: bool = False,
        lawful_basis: str | list[str] | None = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {"tenant_id": tenant_id, "tenant": tenant_id, "role": role}
        if user_id:
            context["user_id"] = user_id
        if max_sensitivity is not None:
            context["max_sensitivity"] = max_sensitivity
        if capability_tags:
            context["capability_tags"] = list(capability_tags)
        if purpose is not None:
            context["purpose"] = purpose
        if residency:
            context["residency"] = residency
        if region:
            context["region"] = region
        if break_glass:
            context["break_glass"] = True
        if lawful_basis is not None:
            context["lawful_basis"] = lawful_basis
        return context

    def get(
        self,
        tenant_id: str,
        id: str,
        branch: str | None = None,
        role: WriteRole = "reader",
        user_id: str | None = None,
        max_sensitivity: int | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
        residency: str | None = None,
        region: str | None = None,
        break_glass: bool = False,
        lawful_basis: str | list[str] | None = None,
    ) -> dict[str, Any]:
        exported = self.export(
            tenant_id,
            role=role,
            user_id=user_id,
            max_sensitivity=max_sensitivity,
            capability_tags=capability_tags,
            purpose=purpose,
            residency=residency,
            region=region,
            break_glass=break_glass,
            lawful_basis=lawful_basis,
        )
        for collection in ("evidence", "assertions", "relations", "preferences", "justifications", "contradictions"):
            for item in exported.get(collection, []):
                item_id = item.get("cid") or item.get("id")
                if item_id != id:
                    continue
                if branch and item.get("branch") and item.get("branch") != branch:
                    continue
                return {"kind": collection.rstrip("s"), "record": item}
        for collection, rows in (("lesson", self.learning.lessons.values()), ("procedure", self.learning.procedures.values())):
            for item in rows:
                if item.tenant_id == tenant_id and item.id == id:
                    return {"kind": collection, "record": item.to_dict()}
        raise KeyError(f"memory record not found: {id}")

    def propose(
        self,
        tenant_id: str,
        user_id: str,
        subject: str,
        predicate: str,
        object_value: str,
        source_evidence_cids: list[str] | None = None,
        confidence: float = 0.7,
        trust_tier: int = int(TrustTier.NORMAL),
        branch: str | None = None,
        role: WriteRole = "agent",
        source_trust_tier: int | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize(
            "propose",
            role=role,
            source_trust_tier=source_trust_tier if source_trust_tier is not None else trust_tier,
            target_sink="belief",
        )
        proposal_branch = branch or f"proposal-{new_id()}"
        self._engine_branch(proposal_branch, "main", "proposal", tenant_id=tenant_id)
        assertion_id = self.engine.upsert_assertion(
            Assertion(
                tenant_id=tenant_id,
                subject=subject,
                predicate=predicate,
                object=object_value,
                confidence=confidence,
                source_evidence_cids=source_evidence_cids or [],
                status="active",
                trust_tier=trust_tier,
                access_policy={"tenant": tenant_id},
            ),
            branch=proposal_branch,
        )
        return {
            "id": assertion_id,
            "proposal_id": proposal_branch,
            "branch": proposal_branch,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "status": "proposed",
            "security": decision,
        }

    def confirm(
        self,
        id: str,
        role: WriteRole,
        source_trust_tier: int,
        tenant_id: str | None = None,
        branch: str | None = None,
        into: str = "main",
    ) -> dict[str, Any]:
        decision = self._authorize(
            "confirm",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="branch_promotion",
        )
        proposal_branch = branch or self._find_candidate_branch(id, tenant_id)
        report = self._engine_merge(proposal_branch, into, tenant_id=tenant_id)
        confirmed_id = self._resolve_confirmed_id(id, report)
        return {
            # Preserve the submitted id for backward compatibility, and ADD the
            # explicit source/confirmed identity resolved from the merge's
            # assertion_id_map (never a forced physical-id equality).
            "id": id,
            "source_id": id,
            "confirmed_id": confirmed_id,
            "branch": proposal_branch,
            "into": into,
            "merge": report.to_dict(),
            "security": decision,
        }

    @staticmethod
    def _resolve_confirmed_id(source_id: str, report: Any) -> str:
        """Resolve the authoritative destination id for ``source_id``.

        Fails closed when the merge produced no unique, non-blank string mapping
        for the requested source rather than fabricating an identity id.
        """
        id_map = getattr(report, "assertion_id_map", None) or {}
        confirmed_id = id_map.get(source_id)
        if not isinstance(confirmed_id, str) or not confirmed_id:
            raise KeyError(
                f"confirm: no authoritative destination mapping for source assertion {source_id!r}"
            )
        return confirmed_id

    def supersede(
        self,
        tenant_id: str,
        user_id: str,
        id: str,
        new: dict[str, Any],
        branch: str = "main",
        confidence: float = 0.95,
        role: WriteRole = "agent",
        source_trust_tier: int = int(TrustTier.USER_AUTHORED),
    ) -> dict[str, Any]:
        decision = self._authorize(
            "supersede",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="belief_correction",
        )
        existing = self.get(tenant_id, id, branch=branch)
        if existing["kind"] != "assertion":
            raise ValueError("supersede currently supports assertion records")
        record = existing["record"]
        new_object = new.get("object_value", new.get("object"))
        if new_object is None:
            raise ValueError("supersede requires new.object_value or new.object")
        assertion_id = self.engine.upsert_assertion(
            Assertion(
                tenant_id=tenant_id,
                subject=str(new.get("subject", record["subject"])),
                predicate=str(new.get("predicate", record["predicate"])),
                object=str(new_object),
                confidence=float(new.get("confidence", confidence)),
                scope=dict(new.get("scope", record.get("scope") or {})),
                source_evidence_cids=list(new.get("source_evidence_cids", record.get("source_evidence_cids") or [])),
                trust_tier=int(new.get("trust_tier", record.get("trust_tier", int(TrustTier.USER_AUTHORED)))),
                sensitivity=int(new.get("sensitivity", record.get("sensitivity", 1))),
                access_policy=dict(new.get("access_policy", record.get("access_policy") or {"tenant": tenant_id})),
            ),
            branch=branch,
        )
        return {
            "id": assertion_id,
            "supersedes": id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "branch": branch,
            "security": decision,
        }

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
        role: WriteRole = "agent",
        source_trust_tier: int = int(TrustTier.USER_AUTHORED),
    ) -> dict[str, Any]:
        decision = self._authorize(
            "correct",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="belief_correction",
        )
        assertion_id = self.engine.correct(
            tenant_id=tenant_id,
            user_id=user_id,
            subject=subject,
            predicate=predicate,
            object_value=object_value,
            correction_text=correction_text,
            branch=branch,
            confidence=confidence,
        )
        return {"id": assertion_id, "branch": branch, "security": decision}

    def forget(
        self,
        tenant_id: str,
        cid: str,
        branch: str = "main",
        requested_by: str = "user",
        role: WriteRole = "operator",
        source_trust_tier: int = int(TrustTier.USER_AUTHORED),
        erasure_mode: str = "tombstone_recompute",
    ) -> dict[str, Any]:
        decision = self._authorize(
            "forget",
            role=role,
            source_trust_tier=source_trust_tier,
            destructive=True,
        )
        mode = ErasureMode(erasure_mode)
        evidence = self.engine.get_evidence(tenant_id, cid, branch)
        content_pointer = evidence.content_pointer if evidence else None
        result = self.engine.forget(
            tenant_id=tenant_id,
            cid=cid,
            branch=branch,
            requested_by=requested_by,
            erasure_mode=mode,
        )
        if result.get("erased") and mode is ErasureMode.HARD_DELETE_LEGAL and content_pointer:
            result["object_shred"] = self.ingestion.object_store.shred(content_pointer, tenant_id=tenant_id)
        result["security"] = decision
        return result

    def export(
        self,
        tenant_id: str,
        role: WriteRole = "reader",
        user_id: str | None = None,
        max_sensitivity: int | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
        residency: str | None = None,
        region: str | None = None,
        break_glass: bool = False,
        lawful_basis: str | list[str] | None = None,
    ) -> dict[str, Any]:
        context = self._read_context(
            tenant_id,
            role=role,
            user_id=user_id,
            max_sensitivity=max_sensitivity,
            capability_tags=capability_tags,
            purpose=purpose,
            residency=residency,
            region=region,
            break_glass=break_glass,
            lawful_basis=lawful_basis,
        )
        if not hasattr(self.engine, "export_tenant_filtered"):
            raise NotImplementedError("public export requires engine.export_tenant_filtered")
        return self.engine.export_tenant_filtered(tenant_id, context)

    def _engine_branch(self, name: str, from_branch: str = "main", kind: str = "scratch", tenant_id: str | None = None) -> None:
        try:
            self.engine.branch(name=name, frm=from_branch, kind=kind, tenant_id=tenant_id)
        except TypeError:
            self.engine.branch(name=name, frm=from_branch, kind=kind)

    def _engine_merge(self, from_branch: str, into: str = "main", tenant_id: str | None = None) -> Any:
        try:
            return self.engine.merge(frm=from_branch, into=into, tenant_id=tenant_id)
        except TypeError:
            return self.engine.merge(frm=from_branch, into=into)

    def _engine_discard(self, branch: str, tenant_id: str | None = None) -> None:
        try:
            self.engine.discard(branch, tenant_id=tenant_id)
        except TypeError:
            self.engine.discard(branch)

    def _find_candidate_branch(self, id: str, tenant_id: str | None) -> str:
        branches = getattr(self.engine, "branches", {})
        if isinstance(branches, dict) and id in branches:
            return id
        if tenant_id:
            exported = self.engine.export_tenant(tenant_id)
            candidates = sorted(
                {
                    str(item["branch"])
                    for item in exported.get("assertions", [])
                    if item.get("id") == id and item.get("branch") != "main"
                }
            )
            if len(candidates) > 1:
                # Fail closed: auto-discovery is ambiguous. Refuse to silently
                # promote whichever branch happens to be enumerated first; the
                # caller must pass an explicit branch to disambiguate.
                raise KeyError(
                    f"confirm: ambiguous candidate branches {candidates!r} for {id!r}; "
                    "pass an explicit branch to disambiguate"
                )
            if candidates:
                return candidates[0]
        if id.startswith("proposal-"):
            return id
        raise KeyError(f"proposal branch not found for {id}")

    def branch(
        self,
        name: str,
        role: WriteRole,
        source_trust_tier: int,
        from_branch: str = "main",
        kind: str = "scratch",
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize(
            "branch",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="branch",
        )
        self._engine_branch(name, from_branch, kind, tenant_id=tenant_id)
        return {
            "branch": name,
            "from": from_branch,
            "kind": kind,
            "tenant_id": tenant_id,
            "security": decision,
        }

    def merge(
        self,
        from_branch: str,
        role: WriteRole,
        source_trust_tier: int,
        into: str = "main",
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize(
            "merge",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="branch_promotion",
        )
        report = self._engine_merge(from_branch, into, tenant_id=tenant_id).to_dict()
        report["security"] = decision
        return report

    def discard(
        self,
        branch: str,
        role: WriteRole,
        source_trust_tier: int,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        decision = self._authorize(
            "discard",
            role=role,
            source_trust_tier=source_trust_tier,
            destructive=True,
            target_sink="branch_promotion",
        )
        self._engine_discard(branch, tenant_id=tenant_id)
        return {"discarded": branch, "tenant_id": tenant_id, "security": decision}

    def profile_add(
        self,
        tenant_id: str,
        user_id: str,
        kind: str,
        statement: str,
        scope: dict[str, Any] | None = None,
        confidence: float = 0.7,
        exceptions: dict[str, Any] | None = None,
        source_evidence_cids: list[str] | None = None,
        role: WriteRole = "agent",
        source_trust_tier: int | None = None,
    ) -> dict[str, Any]:
        memory_kind = UserMemoryKind(kind)
        if memory_kind is UserMemoryKind.HARD_INSTRUCTION:
            trust = source_trust_tier if source_trust_tier is not None else int(TrustTier.USER_AUTHORED)
            decision = self._authorize(
                "profile_add",
                role=role,
                source_trust_tier=trust,
                target_sink="policy",
            )
        elif memory_kind in {UserMemoryKind.EXPLICIT_PREFERENCE, UserMemoryKind.INFERRED_PREFERENCE, UserMemoryKind.SITUATIONAL_PREFERENCE}:
            trust = source_trust_tier if source_trust_tier is not None else (
                int(TrustTier.USER_AUTHORED) if memory_kind is UserMemoryKind.EXPLICIT_PREFERENCE else int(TrustTier.UNTRUSTED_EXTERNAL)
            )
            decision = self._authorize(
                "profile_add",
                role=role,
                source_trust_tier=trust,
                target_sink="preference",
            )
        else:
            decision = self._authorize(
                "profile_add",
                role=role,
                source_trust_tier=source_trust_tier if source_trust_tier is not None else int(TrustTier.NORMAL),
            )
        entry_id = self.user_model.add_entry(
            UserModelEntry(
                tenant_id=tenant_id,
                user_id=user_id,
                kind=memory_kind,
                statement=statement,
                scope=scope or {},
                confidence=confidence,
                exceptions=exceptions or {},
                source_evidence_cids=source_evidence_cids or [],
            )
        )
        self._save_user_model()
        return {"id": entry_id, "security": decision}

    def profile_context(self, tenant_id: str, user_id: str, scope: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.user_model.context_packet(tenant_id, user_id, scope or {})

    def profile_get_relevant(self, tenant_id: str, user_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.profile_context(tenant_id, user_id, scope=context)

    def profile_record_explicit(
        self,
        tenant_id: str,
        user_id: str,
        statement: str,
        scope: dict[str, Any] | None = None,
        confidence: float = 0.9,
        source_evidence_cids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.profile_add(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=UserMemoryKind.EXPLICIT_PREFERENCE.value,
            statement=statement,
            scope=scope,
            confidence=confidence,
            source_evidence_cids=source_evidence_cids,
            role="agent",
            source_trust_tier=int(TrustTier.USER_AUTHORED),
        )

    def profile_propose_inference(
        self,
        tenant_id: str,
        user_id: str,
        statement: str,
        context: dict[str, Any] | None = None,
        confidence: float = 0.55,
        source_evidence_cids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.profile_add(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=UserMemoryKind.INFERRED_PREFERENCE.value,
            statement=statement,
            scope=context,
            confidence=confidence,
            source_evidence_cids=source_evidence_cids,
            role="agent",
            source_trust_tier=int(TrustTier.USER_AUTHORED),
        )

    def profile_correct(
        self,
        tenant_id: str,
        user_id: str,
        id: str,
        statement: str,
        context: dict[str, Any] | None = None,
        confidence: float = 0.95,
    ) -> dict[str, Any]:
        result = self.profile_record_explicit(
            tenant_id=tenant_id,
            user_id=user_id,
            statement=statement,
            scope=context,
            confidence=confidence,
            source_evidence_cids=[id],
        )
        result["corrects"] = id
        return result

    def profile_record_mistake(
        self,
        tenant_id: str,
        user_id: str,
        pattern: str,
        description: str,
        scope: dict[str, Any] | None = None,
        suggestion: str | None = None,
        occurred_at: str | None = None,
        role: WriteRole = "agent",
        source_trust_tier: int | None = None,
    ) -> dict[str, Any]:
        trust = source_trust_tier if source_trust_tier is not None else int(TrustTier.USER_AUTHORED)
        decision = self._authorize(
            "profile_record_mistake",
            role=role,
            source_trust_tier=trust,
            target_sink="preference",
        )
        event_kwargs: dict[str, Any] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "pattern": pattern,
            "description": description,
            "scope": scope or {},
        }
        if occurred_at is not None:
            parsed = parse_dt(occurred_at)
            if parsed is None:
                raise ValueError("occurred_at must be an ISO-8601 datetime")
            event_kwargs["occurred_at"] = parsed
        result = self.user_model.record_user_mistake(
            UserMistakeEvent(**event_kwargs),
            suggestion=suggestion,
        )
        self._save_user_model()
        return {
            **result,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "pattern": pattern,
            "scope": scope or {},
            "security": decision,
        }

    def profile_retire_support_strategy(
        self,
        tenant_id: str,
        user_id: str,
        strategy_id: str,
        role: WriteRole = "operator",
        source_trust_tier: int = int(TrustTier.USER_AUTHORED),
    ) -> dict[str, Any]:
        decision = self._authorize(
            "profile_retire_support_strategy",
            role=role,
            source_trust_tier=source_trust_tier,
            destructive=True,
            target_sink="preference",
        )
        strategy = self.user_model.support_strategies.get(strategy_id)
        if strategy is not None and (strategy.tenant_id != tenant_id or strategy.user_id != user_id):
            raise PermissionError("support strategy is outside the requested tenant/user scope")
        retired = self.user_model.retire_support_strategy(strategy_id)
        if retired:
            self._save_user_model()
        return {
            "strategy_id": strategy_id,
            "retired": retired,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "security": decision,
        }

    def prefetch(
        self,
        tenant_id: str,
        candidates: list[dict[str, Any]],
        branch: str = "main",
        role: WriteRole = "agent",
        user_id: str | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
    ) -> dict[str, Any]:
        access_context: dict[str, Any] = {"role": role}
        if user_id:
            access_context["user_id"] = user_id
        if capability_tags:
            access_context["capability_tags"] = list(capability_tags)
        if purpose is not None:
            access_context["purpose"] = purpose
        results = self.prefetcher.prefetch(
            tenant_id,
            [
                PrefetchCandidate(
                    query=str(candidate["query"]),
                    probability=float(candidate["probability"]),
                    reason=str(candidate.get("reason", "agent supplied")),
                    metadata=dict(candidate.get("metadata") or {}),
                )
                for candidate in candidates
            ],
            branch=branch,
            access_context=access_context,
        )
        return {"results": [item.to_dict() for item in results]}

    def graph_neighbors(
        self,
        tenant_id: str,
        seeds: list[str],
        branch: str = "main",
        k: int = 8,
    ) -> dict[str, Any]:
        hits = self.engine.graph_ppr(seeds, k, tenant_id=tenant_id, branch=branch)
        return {"hits": [hit.to_dict() for hit in hits]}

    def graph_query(self, tenant_id: str, seeds: list[str], branch: str = "main", hops: int = 1, k: int = 8) -> dict[str, Any]:
        result = self.graph_neighbors(tenant_id, seeds, branch=branch, k=k)
        result["hops"] = hops
        return result

    def graph_timeline(
        self,
        tenant_id: str,
        entity: str,
        branch: str = "main",
        role: WriteRole = "reader",
        user_id: str | None = None,
        max_sensitivity: int | None = None,
        capability_tags: list[str] | None = None,
        purpose: str | list[str] | None = None,
        residency: str | None = None,
        region: str | None = None,
        break_glass: bool = False,
        lawful_basis: str | list[str] | None = None,
    ) -> dict[str, Any]:
        exported = self.export(
            tenant_id,
            role=role,
            user_id=user_id,
            max_sensitivity=max_sensitivity,
            capability_tags=capability_tags,
            purpose=purpose,
            residency=residency,
            region=region,
            break_glass=break_glass,
            lawful_basis=lawful_basis,
        )
        events: list[dict[str, Any]] = []
        entity_l = entity.lower()
        for assertion in exported.get("assertions", []):
            if assertion.get("branch", "main") != branch:
                continue
            if entity_l not in {str(assertion.get("subject", "")).lower(), str(assertion.get("object", "")).lower()}:
                continue
            events.append({"kind": "assertion", "at": assertion.get("valid_from"), "record": assertion})
        for relation in exported.get("relations", []):
            if relation.get("branch", "main") != branch:
                continue
            if entity_l not in {str(relation.get("source", "")).lower(), str(relation.get("target", "")).lower()}:
                continue
            events.append({"kind": "relation", "at": relation.get("valid_from"), "record": relation})
        events.sort(key=lambda item: str(item.get("at") or ""))
        return {"entity": entity, "branch": branch, "events": events}

    def graph_as_of(self, tenant_id: str, subject: str, predicate: str, time: str, branch: str = "main") -> dict[str, Any]:
        moment = parse_dt(time)
        if moment is None:
            raise ValueError("graph_as_of requires an ISO timestamp")
        assertions = self.engine.as_of(subject, predicate, moment, tenant_id=tenant_id, branch=branch)
        return {"subject": subject, "predicate": predicate, "time": time, "assertions": [item.to_dict() for item in assertions]}

    def trajectory_log(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        task: str,
        steps: list[dict[str, Any]],
        outcome: str,
        reward: float,
        memory_version: str,
    ) -> dict[str, Any]:
        trajectory_id = self.learning.log_trajectory(
            Trajectory(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                task=task,
                steps=steps,
                outcome=outcome,  # type: ignore[arg-type]
                reward=reward,
                memory_version=memory_version,
            )
        )
        self._save_learning()
        return {"id": trajectory_id}

    def trajectory_record(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        task: str,
        steps: list[dict[str, Any]],
        outcome: str,
        reward: float,
        memory_version: str,
    ) -> dict[str, Any]:
        return self.trajectory_log(tenant_id, user_id, session_id, task, steps, outcome, reward, memory_version)

    def trajectory_attribute(self, trajectory_id: str) -> dict[str, Any]:
        attribution = self.learning.attribute_failure(trajectory_id)
        self._save_learning()
        return attribution.to_dict()

    def lesson_induce(self, trajectory_id: str) -> dict[str, Any]:
        attribution = self.learning.attributions.get(trajectory_id) or self.learning.attribute_failure(trajectory_id)
        lesson = self.learning.induce_lesson(attribution)
        self._save_learning()
        return lesson.to_dict()

    def lesson_propose(self, trajectory_id: str) -> dict[str, Any]:
        return self.lesson_induce(trajectory_id)

    def procedure_induce(self, lesson_id: str) -> dict[str, Any]:
        lesson = self.learning.lessons[lesson_id]
        procedure = self.learning.induce_procedure(lesson)
        self._save_learning()
        return procedure.to_dict()

    def procedure_propose(self, lesson_id: str) -> dict[str, Any]:
        return self.procedure_induce(lesson_id)

    def lesson_promote(
        self,
        lesson_id: str,
        cases: list[dict[str, Any]],
        role: WriteRole,
        source_trust_tier: int,
    ) -> dict[str, Any]:
        decision = self._authorize(
            "lesson_promote",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="branch_promotion",
        )
        lesson = self.learning.lessons[lesson_id]
        regression_cases = [
            RegressionCase(
                id=str(case["id"]),
                signature=str(case["signature"]),
                query=str(case["query"]),
                expected_substring=str(case["expected_substring"]),
                tier=str(case.get("tier", "smoke")),  # type: ignore[arg-type]
                protected=bool(case.get("protected", True)),
            )
            for case in cases
        ]
        result = self.learning.promote_lesson(lesson, regression_cases)
        self._save_learning()
        self.metrics.record_gate(promoted=result.promoted, rolled_back=bool(result.rollback_branch))
        self._save_metrics()
        payload = result.to_dict()
        payload["security"] = decision
        return payload

    def procedure_validate(self, procedure_id: str, role: WriteRole, source_trust_tier: int) -> dict[str, Any]:
        decision = self._authorize(
            "procedure_validate",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="branch_promotion",
        )
        procedure = self.learning.procedures[procedure_id]
        procedure.status = "validated"
        self._save_learning()
        payload = procedure.to_dict()
        payload["security"] = decision
        return payload

    def procedure_promote(self, procedure_id: str, role: WriteRole, source_trust_tier: int) -> dict[str, Any]:
        decision = self._authorize(
            "procedure_promote",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="branch_promotion",
        )
        procedure = self.learning.procedures[procedure_id]
        procedure.status = "promoted"
        self._save_learning()
        self.metrics.record_gate(promoted=True, rolled_back=False)
        self._save_metrics()
        payload = procedure.to_dict()
        payload["security"] = decision
        return payload

    def lesson_search(self, signature: str, tenant_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        query = signature.lower()
        lessons = []
        for lesson in self.learning.lessons.values():
            if tenant_id and lesson.tenant_id != tenant_id:
                continue
            if status and lesson.status != status:
                continue
            haystack = f"{lesson.failure_signature} {lesson.content}".lower()
            if query in haystack:
                lessons.append(lesson.to_dict())
        return {"lessons": lessons}

    def procedure_search(self, query: str, tenant_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        needle = query.lower()
        procedures = []
        for procedure in self.learning.procedures.values():
            if tenant_id and procedure.tenant_id != tenant_id:
                continue
            if status and procedure.status != status:
                continue
            haystack = f"{procedure.name} {procedure.body} {procedure.signature}".lower()
            if needle in haystack:
                procedures.append(procedure.to_dict())
        return {"procedures": procedures}

    def procedure_rollback(self, procedure_id: str, role: WriteRole, source_trust_tier: int) -> dict[str, Any]:
        decision = self._authorize(
            "procedure_rollback",
            role=role,
            source_trust_tier=source_trust_tier,
            destructive=True,
            target_sink="branch_promotion",
        )
        procedure = self.learning.procedures[procedure_id]
        procedure.status = "rolled_back"
        self._save_learning()
        self.metrics.record_gate(promoted=False, rolled_back=True)
        self._save_metrics()
        payload = procedure.to_dict()
        payload["security"] = decision
        return payload

    def outcome_evaluate(
        self,
        trajectory_id: str | None = None,
        before_successes: int | None = None,
        after_successes: int | None = None,
        total_cases: int | None = None,
    ) -> dict[str, Any]:
        if trajectory_id:
            trajectory = self.learning.trajectories[trajectory_id]
            return {
                "trajectory_id": trajectory.id,
                "outcome": trajectory.outcome,
                "reward": trajectory.reward,
                "passed": trajectory.outcome == "success" and trajectory.reward > 0,
                "memory_version": trajectory.memory_version,
            }
        if before_successes is None or after_successes is None or total_cases is None:
            raise ValueError("outcome_evaluate requires trajectory_id or before/after/total counts")
        return {
            "counterfactual_replay_score": counterfactual_replay_score(before_successes, after_successes, total_cases),
            "before_successes": before_successes,
            "after_successes": after_successes,
            "total_cases": total_cases,
        }

    def parametric_propose(self, tenant_id: str, role: WriteRole, source_trust_tier: int) -> dict[str, Any]:
        security = self._authorize(
            "parametric_propose",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="safety_rail",
        )
        artifact = self.parametric.propose_from_lessons(
            tenant_id,
            list(self.learning.lessons.values()),
            list(self.learning.procedures.values()),
        )
        result = artifact.to_dict()
        result["security"] = security
        return result

    def _parametric_protected_cases(self, protected_case_count: int) -> tuple[list[RegressionCase], str]:
        if protected_case_count < 0:
            raise ValueError("protected_case_count must be non-negative")
        if self.runtime_state:
            persisted = [
                case
                for case in self.runtime_state.load_gate_cases()
                if case.protected and case.origin in GATING_CASE_ORIGINS and case.mode == "active"
            ]
            if persisted:
                return persisted[:protected_case_count], "runtime_state"
        return (
            [
                RegressionCase(
                    id=f"parametric-protected-{index}",
                    signature="parametric protected",
                    query="parametric protected",
                    expected_substring="protected",
                    protected=True,
                    origin="synthetic",
                    mode="shadow",
                )
                for index in range(protected_case_count)
            ],
            "synthetic",
        )

    def parametric_evaluate(
        self,
        artifact_uri: str,
        role: WriteRole,
        source_trust_tier: int,
        protected_case_count: int = 1,
        gate_promoted: bool = True,
        protected_regressions: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.parametric.artifact_store:
            raise ValueError("parametric evaluation requires an artifact store")
        security = self._authorize(
            "parametric_evaluate",
            role=role,
            source_trust_tier=source_trust_tier,
            target_sink="safety_rail",
        )
        artifact = self.parametric.artifact_store.load_artifact(artifact_uri)
        cases, suite_source = self._parametric_protected_cases(protected_case_count)
        protected_count = len([case for case in cases if case.protected])
        suite_gating = (
            suite_source == "runtime_state"
            and protected_suite_is_gating(cases)
            and protected_case_count > 0
            and protected_count >= protected_case_count
        )
        effective_promoted = gate_promoted and suite_gating
        regressions = list(protected_regressions or [])
        if gate_promoted and not suite_gating:
            regressions.append("protected-suite-non-gating")
        gate = GateResult(
            candidate_id=artifact.id,
            promoted=effective_promoted,
            protected_regressions=regressions,
            failed_cases=[],
            passed_cases=[case.id for case in cases] if suite_gating else [],
            margin=1.0 if effective_promoted else 0.0,
            rollback_branch=None,
        )
        decision = self.parametric.evaluate(artifact, gate, cases)
        self.metrics.record_gate(promoted=decision.promoted, rolled_back=not decision.promoted)
        self._save_metrics()
        result = decision.to_dict()
        result["security"] = security
        result["protected_suite"] = {
            "source": suite_source,
            "gating": suite_gating,
            "required_protected_case_count": protected_case_count,
            **protected_suite_report(cases),
        }
        return result

    def parametric_rollback(
        self,
        artifact_uri: str,
        reason: str,
        role: WriteRole,
        source_trust_tier: int,
        protected_case_count: int = 1,
    ) -> dict[str, Any]:
        if not self.parametric.artifact_store:
            raise ValueError("parametric rollback requires an artifact store")
        security = self._authorize(
            "parametric_rollback",
            role=role,
            source_trust_tier=source_trust_tier,
            destructive=True,
            target_sink="safety_rail",
        )
        artifact = self.parametric.artifact_store.load_artifact(artifact_uri)
        cases, suite_source = self._parametric_protected_cases(protected_case_count)
        protected_count = len([case for case in cases if case.protected])
        suite_gating = (
            suite_source == "runtime_state"
            and protected_suite_is_gating(cases)
            and protected_case_count > 0
            and protected_count >= protected_case_count
        )
        rolled_back = self.parametric.rollback(artifact, reason, protected_cases=cases)
        self.metrics.record_gate(promoted=False, rolled_back=True)
        self._save_metrics()
        result = rolled_back.to_dict()
        result["security"] = security
        result["protected_suite"] = {
            "source": suite_source,
            "gating": suite_gating,
            "required_protected_case_count": protected_case_count,
            **protected_suite_report(cases),
        }
        rollback_record = dict(result.get("rail_report", {}).get("rollback") or {})
        if rollback_record:
            rollback_record["rollback_provider_authorized"] = security.get("allowed") is True
            result["rollback"] = rollback_record
        return result

    def _save_user_model(self) -> None:
        if self.runtime_state:
            self.runtime_state.save_user_model(self.user_model)

    def _save_learning(self) -> None:
        if self.runtime_state:
            self.runtime_state.save_learning(self.learning)

    def _save_metrics(self) -> None:
        if self.runtime_state:
            self.runtime_state.save_metrics(self.metrics)

    def _record_retrieval(self, result: dict[str, Any], start: float) -> None:
        latency_ms = (perf_counter() - start) * 1000
        channels = result.get("explain", {}).get("channels", {})
        self.metrics.record_retrieval(
            {str(channel): int(count) for channel, count in channels.items()},
            latency_ms,
            bool(result.get("abstained")),
        )
        self._save_metrics()

    def _authorize(
        self,
        operation: str,
        role: WriteRole,
        source_trust_tier: int,
        destructive: bool = False,
        target_sink: str | None = None,
    ) -> dict[str, Any]:
        decision = self.security.authorize_write(
            operation=operation,
            role=role,
            source_trust_tier=source_trust_tier,
            destructive=destructive,
            target_sink=target_sink,
        )
        self.engine.record_audit_event(
            None,
            str(role),
            "authorize_write",
            None,
            {
                "operation": operation,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "source_trust_tier": source_trust_tier,
                "destructive": destructive,
                "target_sink": target_sink,
            },
            source="mcp_tools",
            trust_tier=source_trust_tier,
            capability_tags=["authz", "allowed" if decision.allowed else "denied"],
        )
        if not decision.allowed:
            raise PermissionError(f"{operation} denied: {decision.reason}")
        return decision.to_dict()
