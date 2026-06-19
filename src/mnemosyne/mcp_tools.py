"""MCP-compatible tool facade for agents."""

from __future__ import annotations

from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.gate import GateResult, RegressionCase
from mnemosyne.learning import LearningSystem, Trajectory
from mnemosyne.models import Assertion, Evidence, Preference, Relation
from mnemosyne.parametric import ParametricTier
from mnemosyne.prefetch import AnticipatoryPrefetcher, PrefetchCandidate
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.security import SecurityPolicy, TrustTier, WriteRole
from mnemosyne.user_model import UserMemoryKind, UserModel, UserModelEntry


TOOL_SPEC: list[dict[str, Any]] = [
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
        "name": "explain",
        "description": "Return retrieval stages, channels, provenance, confidence, and immutable rails.",
        "arguments": ["tenant_id", "query"],
    },
    {
        "name": "correct",
        "description": "Record an authoritative correction and upsert the superseding assertion.",
        "arguments": ["tenant_id", "user_id", "subject", "predicate", "object_value", "correction_text"],
    },
    {
        "name": "forget",
        "description": "Erase evidence content and propagate retraction or provenance trimming.",
        "arguments": ["tenant_id", "cid"],
    },
    {
        "name": "export",
        "description": "Export tenant-owned evidence, assertions, relations, preferences, and audit records.",
        "arguments": ["tenant_id"],
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
        "name": "trajectory_log",
        "description": "Persist a trajectory for procedural/corrective learning.",
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
        "name": "procedure_induce",
        "description": "Induce a procedure from a corrective lesson.",
        "arguments": ["lesson_id"],
    },
    {
        "name": "lesson_promote",
        "description": "Promote a lesson through protected regression cases.",
        "arguments": ["lesson_id", "cases"],
    },
    {
        "name": "procedure_validate",
        "description": "Mark an induced procedure as validated for the isolated parametric tier.",
        "arguments": ["procedure_id"],
    },
    {
        "name": "parametric_propose",
        "description": "Create an isolated shadow parametric artifact from active lessons/procedures.",
        "arguments": ["tenant_id"],
    },
    {
        "name": "parametric_evaluate",
        "description": "Evaluate a shadow parametric artifact against gate evidence.",
        "arguments": ["tenant_id"],
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
        self.parametric = ParametricTier()

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
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cid = self.engine.append_evidence(
            Evidence(
                tenant_id=tenant_id,
                user_id=user_id,
                actor=actor,  # type: ignore[arg-type]
                source_type=source_type,
                source_identity=source_identity,
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
    ) -> dict[str, Any]:
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
        return {"id": assertion_id, "branch": branch}

    def relation(
        self,
        tenant_id: str,
        source: str,
        predicate: str,
        target: str,
        branch: str = "main",
        confidence: float = 0.7,
        source_evidence_cids: list[str] | None = None,
    ) -> dict[str, Any]:
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
        return {"id": relation_id, "branch": branch}

    def preference(
        self,
        tenant_id: str,
        user_id: str,
        category: str,
        statement: str,
        explicit: bool = False,
        confidence: float = 0.7,
        source_evidence_cids: list[str] | None = None,
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
            )
        )
        return {"id": preference_id, "security": decision}

    def search(
        self,
        tenant_id: str,
        query: str,
        branch: str = "main",
        min_trust_tier: int | None = None,
        max_trust_tier: int | None = None,
        max_sensitivity: int | None = None,
    ) -> dict[str, Any]:
        filt: dict[str, Any] = {}
        if max_trust_tier is not None:
            filt["max_trust_tier"] = max_trust_tier
        elif min_trust_tier is not None:
            filt["min_trust_tier"] = min_trust_tier
        if max_sensitivity is not None:
            filt["max_sensitivity"] = max_sensitivity
        return self.engine.retrieve(query=query, tenant_id=tenant_id, branch=branch, filt=filt).to_dict()

    def deep_search(self, tenant_id: str, query: str, branch: str = "main") -> dict[str, Any]:
        return self.engine.deep_search(query=query, tenant_id=tenant_id, branch=branch).to_dict()

    def explain(self, tenant_id: str, query: str, branch: str = "main") -> dict[str, Any]:
        return self.engine.explain(query=query, tenant_id=tenant_id, branch=branch)

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
    ) -> dict[str, Any]:
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
        return {"id": assertion_id, "branch": branch}

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
        result = self.engine.forget(
            tenant_id=tenant_id,
            cid=cid,
            branch=branch,
            requested_by=requested_by,
            erasure_mode=erasure_mode,
        )
        result["security"] = decision
        return result

    def export(self, tenant_id: str) -> dict[str, Any]:
        return self.engine.export_tenant(tenant_id)

    def branch(self, name: str, from_branch: str = "main", kind: str = "scratch") -> dict[str, Any]:
        self.engine.branch(name=name, frm=from_branch, kind=kind)
        return {"branch": name, "from": from_branch, "kind": kind}

    def merge(self, from_branch: str, into: str = "main") -> dict[str, Any]:
        return self.engine.merge(frm=from_branch, into=into).to_dict()

    def discard(self, branch: str) -> dict[str, Any]:
        self.engine.discard(branch)
        return {"discarded": branch}

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

    def prefetch(self, tenant_id: str, candidates: list[dict[str, Any]], branch: str = "main") -> dict[str, Any]:
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

    def trajectory_attribute(self, trajectory_id: str) -> dict[str, Any]:
        attribution = self.learning.attribute_failure(trajectory_id)
        self._save_learning()
        return attribution.to_dict()

    def lesson_induce(self, trajectory_id: str) -> dict[str, Any]:
        attribution = self.learning.attributions.get(trajectory_id) or self.learning.attribute_failure(trajectory_id)
        lesson = self.learning.induce_lesson(attribution)
        self._save_learning()
        return lesson.to_dict()

    def procedure_induce(self, lesson_id: str) -> dict[str, Any]:
        lesson = self.learning.lessons[lesson_id]
        procedure = self.learning.induce_procedure(lesson)
        self._save_learning()
        return procedure.to_dict()

    def lesson_promote(self, lesson_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
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
        return result.to_dict()

    def procedure_validate(self, procedure_id: str) -> dict[str, Any]:
        procedure = self.learning.procedures[procedure_id]
        procedure.status = "validated"
        self._save_learning()
        return procedure.to_dict()

    def parametric_propose(self, tenant_id: str) -> dict[str, Any]:
        artifact = self.parametric.propose_from_lessons(
            tenant_id,
            list(self.learning.lessons.values()),
            list(self.learning.procedures.values()),
        )
        return artifact.to_dict()

    def parametric_evaluate(
        self,
        tenant_id: str,
        protected_case_count: int = 1,
        gate_promoted: bool = True,
        protected_regressions: list[str] | None = None,
    ) -> dict[str, Any]:
        artifact = self.parametric.propose_from_lessons(
            tenant_id,
            list(self.learning.lessons.values()),
            list(self.learning.procedures.values()),
        )
        cases = [
            RegressionCase(
                id=f"parametric-protected-{index}",
                signature="parametric protected",
                query="parametric protected",
                expected_substring="protected",
                protected=True,
            )
            for index in range(protected_case_count)
        ]
        gate = GateResult(
            candidate_id=artifact.id,
            promoted=gate_promoted,
            protected_regressions=protected_regressions or [],
            failed_cases=[],
            passed_cases=[case.id for case in cases],
            margin=1.0 if gate_promoted else 0.0,
            rollback_branch=None,
        )
        return self.parametric.evaluate(artifact, gate, cases).to_dict()

    def _save_user_model(self) -> None:
        if self.runtime_state:
            self.runtime_state.save_user_model(self.user_model)

    def _save_learning(self) -> None:
        if self.runtime_state:
            self.runtime_state.save_learning(self.learning)

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
        if not decision.allowed:
            raise PermissionError(f"{operation} denied: {decision.reason}")
        return decision.to_dict()
