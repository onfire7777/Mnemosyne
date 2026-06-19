"""MCP-compatible tool facade for agents."""

from __future__ import annotations

from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.models import Assertion, Evidence, Preference, Relation
from mnemosyne.prefetch import AnticipatoryPrefetcher, PrefetchCandidate
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
        "arguments": ["tenant_id", "user_id", "actor", "source_type", "content"],
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
]


class MemoryTools:
    def __init__(
        self,
        engine: LocalMemoryEngine,
        ingestion: IngestionPipeline | None = None,
        prefetcher: AnticipatoryPrefetcher | None = None,
        user_model: UserModel | None = None,
    ):
        self.engine = engine
        self.ingestion = ingestion or IngestionPipeline(engine)
        self.prefetcher = prefetcher or AnticipatoryPrefetcher(engine)
        self.user_model = user_model or UserModel()

    def capture(
        self,
        tenant_id: str,
        user_id: str,
        actor: str,
        source_type: str,
        content: str,
        branch: str = "main",
        trust_tier: int = 1,
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
        content: str,
        branch: str = "main",
        trust_tier: int = 1,
        source_identity: str | None = None,
        metadata: dict[str, Any] | None = None,
        signed_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.ingestion.ingest(
            IngestRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                actor=actor,
                source_type=source_type,
                content=content,
                source_identity=source_identity,
                metadata=metadata or {},
                signed_provenance=signed_provenance,
                trust_tier=trust_tier,
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
        trust_tier: int = 1,
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
    ) -> dict[str, Any]:
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
        return {"id": preference_id}

    def search(
        self,
        tenant_id: str,
        query: str,
        branch: str = "main",
        min_trust_tier: int | None = None,
        max_sensitivity: int | None = None,
    ) -> dict[str, Any]:
        filt: dict[str, Any] = {}
        if min_trust_tier is not None:
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

    def forget(self, tenant_id: str, cid: str, branch: str = "main", requested_by: str = "user") -> dict[str, Any]:
        return self.engine.forget(tenant_id=tenant_id, cid=cid, branch=branch, requested_by=requested_by)

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
    ) -> dict[str, Any]:
        entry_id = self.user_model.add_entry(
            UserModelEntry(
                tenant_id=tenant_id,
                user_id=user_id,
                kind=UserMemoryKind(kind),
                statement=statement,
                scope=scope or {},
                confidence=confidence,
                exceptions=exceptions or {},
                source_evidence_cids=source_evidence_cids or [],
            )
        )
        return {"id": entry_id}

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
