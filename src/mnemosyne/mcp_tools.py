"""MCP-compatible tool facade for agents."""

from __future__ import annotations

from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence


TOOL_SPEC: list[dict[str, Any]] = [
    {
        "name": "capture",
        "description": "Append verbatim evidence to the content-addressed ledger.",
        "arguments": ["tenant_id", "user_id", "actor", "source_type", "content"],
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
]


class MemoryTools:
    def __init__(self, engine: LocalMemoryEngine):
        self.engine = engine

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

