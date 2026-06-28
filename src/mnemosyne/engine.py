"""Local Mnemosyne engine implementation."""

from __future__ import annotations

import copy
import json
import math
import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from mnemosyne.access_policy import (
    apply_relation_redactions,
    apply_statement_redactions,
    apply_text_redactions,
    effective_max_sensitivity,
    may_read_item,
    merge_access_policies,
    validate_access_policy,
)
from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.consciousness import RealityMonitor
from mnemosyne.ids import content_cid, new_id
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
from mnemosyne.policy import OperatingPolicy
from mnemosyne.privacy import ErasureMode
from mnemosyne.retrieval import (
    HashingEmbeddingProvider,
    LocalSimilarityReranker,
    QUERY_SUPPORT_THRESHOLD,
    RetrievalAdapters,
    activation_explain,
    answer_grounding_floor_report,
    apply_workspace_retrieval_advisory,
    apply_activation_scores,
    gist_support_report,
    is_retired_summary_metadata,
    query_support,
    schema_fast_path_rerank,
    semantic_entropy,
    strip_workspace_broadcast_filter,
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
from mnemosyne.standing import (
    standing,
    standing_abstention_report,
    standing_erasure_cascade_report,
    standing_observability_record,
)
from mnemosyne.text import approx_tokens, cosine, lexical_score, tokenize
from mnemosyne.workspace import self_generation_budget_report


def _bounded_float(value: object, *, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


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

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        raise NotImplementedError

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
        raise NotImplementedError

    def add_preference(self, preference: Preference) -> str:
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

    def retrieve(self, query: str, tenant_id: str, branch: str = "main", deep: bool = False, filt: dict[str, Any] | None = None) -> RetrievalResult:
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

    def export_tenant(self, tenant_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def branch(self, name: str, frm: str = "main", kind: str = "scratch", tenant_id: str | None = None) -> None:
        raise NotImplementedError

    def merge(self, frm: str, into: str = "main", tenant_id: str | None = None) -> MergeReport:
        raise NotImplementedError

    def discard(self, branch: str, tenant_id: str | None = None) -> None:
        raise NotImplementedError


class LocalMemoryEngine:
    """A deterministic local engine that implements the blueprint contract.

    It is intentionally dependency-light so the regression suite can run
    anywhere. Production storage is represented by sql/schema.sql; this local
    engine preserves the same invariants and API surface for development,
    counterfactual replay, and single-user operation.
    """

    def __init__(
        self,
        store_path: str | os.PathLike[str] | None = None,
        policy: OperatingPolicy | None = None,
        adapters: RetrievalAdapters | None = None,
    ):
        self.store_path = Path(store_path).expanduser() if store_path else None
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
        self.audit_log: list[dict[str, Any]] = []
        self.deletion_log: list[dict[str, Any]] = []
        self.merge_log: list[dict[str, Any]] = []
        if self.store_path and self.store_path.exists():
            self._load()

    @staticmethod
    def _evidence_key(tenant_id: str, branch: str, cid: str) -> str:
        return f"{tenant_id}:{branch}:{cid}"

    @staticmethod
    def _branch_key(tenant_id: str, branch: str, item_id: str) -> str:
        return f"{tenant_id}:{branch}:{item_id}"

    def _audit(
        self,
        tenant_id: str,
        actor: str,
        op: str,
        target_id: str | None,
        diff: dict[str, Any],
        *,
        source: str | None = None,
        trust_tier: int | None = None,
        capability_tags: list[str] | None = None,
    ) -> None:
        normalized_tags = sorted(set(capability_tags or []))
        audit_diff = dict(diff)
        audit_diff.setdefault("source", source or actor)
        if trust_tier is not None:
            audit_diff.setdefault("trust_tier", trust_tier)
        if normalized_tags:
            audit_diff.setdefault("capability_tags", normalized_tags)
        self.audit_log.append(
            {
                "id": new_id(),
                "tenant_id": tenant_id,
                "actor": actor,
                "op": op,
                "target_id": target_id,
                "source": source or actor,
                "trust_tier": trust_tier,
                "capability_tags": normalized_tags,
                "diff": audit_diff,
                "at": utc_now().isoformat(),
            }
        )

    def _persist(self) -> None:
        if not self.store_path:
            return
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
        self.store_path.chmod(0o600)

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
        self.audit_log = list(data.get("audit_log", []))
        self.deletion_log = list(data.get("deletion_log", []))
        self.merge_log = list(data.get("merge_log", []))

    def append_evidence(self, ev: Evidence, branch: str = "main") -> str:
        access_policy = validate_access_policy(ev.access_policy, tenant_id=ev.tenant_id, location="evidence.access_policy")
        with self._lock:
            self._require_branch(branch)
            cid = content_cid(
                ev.content,
                {
                    "tenant_id": ev.tenant_id,
                    "source_type": ev.source_type,
                    "content_pointer": ev.content_pointer,
                    "modality": ev.modality,
                },
            )
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
            stored.metadata = dict(stored.metadata)
            stored.metadata.setdefault("reality_class", reality_class)
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
            ev.embedding = list(embedding)
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
        query_vec = self._embed_text(query)
        hits: list[Hit] = []
        for hit in self._candidate_hits(filt):
            score = cosine(query_vec, self._embedding_for_hit(hit))
            if score > 0:
                hit.score = score
                hit.channel = "dense_media" if hit.metadata.get("stored_media_embedding") else "dense_hash"
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
        ranks = {node: (1.0 if matches_seed(node) else 0.0) for node in adjacency}
        for seed in seed_set:
            ranks.setdefault(seed, 1.0)
        for _ in range(12):
            next_ranks = {node: 0.15 * (1.0 if matches_seed(node) else 0.0) for node in ranks}
            for node, neighbors in adjacency.items():
                if not neighbors:
                    continue
                share = 0.85 * ranks.get(node, 0.0) / len(neighbors)
                for neighbor in neighbors:
                    next_ranks[neighbor] = next_ranks.get(neighbor, 0.0) + share
            ranks = next_ranks
        for node, score in sorted(ranks.items(), key=lambda item: item[1], reverse=True):
            if matches_seed(node) or score <= 0:
                continue
            relation_row = next((relation_by_pair[pair] for pair in relation_by_pair if pair[0] == node or pair[1] == node), None)
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

    def retrieve(self, query: str, tenant_id: str, branch: str = "main", deep: bool = False, filt: dict[str, Any] | None = None) -> RetrievalResult:
        workspace_broadcast = workspace_broadcast_from_context(filt)
        effective_filter = strip_workspace_broadcast_filter(filt)
        effective_filter.update({"tenant_id": tenant_id, "branch": branch})
        k = self.policy.deep_top_k if deep else self.policy.top_k
        dense = self.vector_search(query, self.policy.rerank_width, effective_filter)
        lexical = self.lexical_search(query, self.policy.rerank_width, effective_filter)
        graph = (
            self.graph_ppr(tokenize(query), max(4, k // 2), tenant_id=tenant_id, branch=branch, filt=effective_filter)
            if deep
            else []
        )
        fused = self._rrf([dense, lexical, graph], k=max(k * 2, self.policy.rerank_width))
        reranked = self.adapters.reranker.rerank(query, fused, k=max(k * 2, k))
        reranked, schema_fast_path = schema_fast_path_rerank(query, reranked, self.policy)
        diversified = self._mmr(query, reranked, k=max(k, 1))
        activated = self._apply_standing_scores(apply_activation_scores(diversified, self.policy))
        ordered = self._u_curve_order(activated)
        ordered, schema_fast_path_final = schema_fast_path_rerank(query, ordered, self.policy)
        schema_fast_path = self._merge_schema_fast_path_reports(schema_fast_path, schema_fast_path_final)
        ordered, workspace_retrieval_advisory = apply_workspace_retrieval_advisory(
            ordered,
            filt,
            tenant_id=tenant_id,
            branch=branch,
            policy=self.policy,
        )
        budgeted, used = self._fit_budget(ordered, self.policy.token_budget)
        budgeted = self._mark_retrieved_text_as_data(budgeted)
        read_marks = self._record_retrieval_access(budgeted)
        calibration = self._calibration_for(tenant_id, "fact")
        threshold = conformal_threshold(calibration) if calibration else self.policy.abstention_threshold
        support_report = query_support(query, budgeted)
        insufficient_support = support_report["score"] < QUERY_SUPPORT_THRESHOLD
        confidence = self._confidence(query, budgeted, support_score=support_report["score"])
        prediction_set_size = self._prediction_set_size(budgeted, threshold)
        entropy = semantic_entropy([hit.text for hit in budgeted])
        gist_support = gist_support_report(budgeted)
        gist_only = bool(gist_support["applied"])
        reality_monitoring = self._reality_monitoring_report(budgeted)
        standing_report = reality_monitoring["standing"]
        ungrounded_reality_only = bool(standing_report["abstention_gate"]["active"])
        if ungrounded_reality_only != bool(reality_monitoring["ungrounded_only"]):
            raise AssertionError("Standing P1 mirror diverged from reality-monitoring abstention gate")
        answer_grounding_floor = answer_grounding_floor_report(budgeted, self.policy)
        answer_grounding_floor_active = bool(answer_grounding_floor["active"])
        if gist_only:
            confidence = min(confidence, threshold * 0.95)
        if ungrounded_reality_only:
            confidence = min(confidence, threshold * 0.95)
        if answer_grounding_floor_active:
            confidence = min(confidence, threshold * 0.95)
        if calibration:
            abstained = (
                should_abstain(confidence, calibration, prediction_set_size=prediction_set_size)
                or insufficient_support
                or gist_only
                or ungrounded_reality_only
                or answer_grounding_floor_active
            )
        else:
            abstained = (
                confidence < threshold
                or prediction_set_size == 0
                or insufficient_support
                or gist_only
                or ungrounded_reality_only
                or answer_grounding_floor_active
            )
        note = None
        if gist_only:
            note = "Only gist-tier memory support was retrieved; inspect source evidence before answering."
        elif ungrounded_reality_only:
            note = (
                "Retrieved support has low groundedness or insufficient independent "
                "external support; abstaining until grounded evidence is available."
            )
        elif answer_grounding_floor_active:
            note = (
                "Retrieved support is dominated by low-grounded self-generated content; "
                "flagging as hypothesis and abstaining until grounded support is available."
            )
        elif insufficient_support:
            note = "Retrieved evidence did not cover enough query terms; abstaining until stronger support is available."
        elif abstained:
            note = "Evidence is too thin, low-trust, or conflicting for a confident answer."
        return RetrievalResult(
            query=query,
            hits=budgeted,
            confidence=confidence,
            abstained=abstained,
            uncertainty_note=note,
            token_budget=self.policy.token_budget,
            used_tokens=used,
            explain={
                "channels": {
                    "dense_hash": len(dense),
                    "lexical": len(lexical),
                    "graph_ppr": len(graph),
                },
                "rrf_k": self.policy.rrf_k,
                "mmr_lambda": self.policy.mmr_lambda,
                "activation": activation_explain(budgeted, self.policy),
                "calibration": self._calibration_explain(calibration, threshold),
                "confidence": {
                    "score": confidence,
                    "answer_score": confidence,
                    "prediction_set_size": prediction_set_size,
                    "threshold": threshold,
                    "source": "conformal" if calibration else "evidence_quality",
                    "query_support": support_report,
                },
                "semantic_entropy": entropy,
                "gist_support": gist_support,
                "reality_monitoring": reality_monitoring,
                "standing": standing_report,
                "answer_grounding_floor": answer_grounding_floor,
                "schema_fast_path": schema_fast_path,
                "workspace_broadcast": workspace_broadcast,
                "workspace_retrieval_advisory": workspace_retrieval_advisory,
                "read_marks": read_marks,
                "adapters": {
                    "embedding": self.adapters.embedding.name,
                    "embedding_dims": self.adapters.embedding.dims,
                    "reranker": self.adapters.reranker.name,
                    "lexical_backend": self.adapters.lexical_backend,
                    "graph_backend": self.adapters.graph_backend,
                },
                "rails": self.policy.immutable_rails,
            },
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
        touched_assertions = 0
        touched_evidence = 0
        now = utc_now()
        with self._lock:
            evidence_cids: set[tuple[str, str, str]] = set()
            for hit in hits:
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
            propagated: dict[str, Any] = {
                "retracted_assertions": [],
                "trimmed_assertions": [],
                "retracted_preferences": [],
                "trimmed_preferences": [],
                "expired_relations": [],
                "trimmed_relations": [],
                "removed_entities": [],
                "trimmed_entities": [],
                "erased_derived_evidence": derived_cids,
                "retained_derived_evidence": sorted(retained_derived),
                "trimmed_derived_evidence": sorted(retained_derived),
            }
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
            entry = {
                "id": new_id(),
                "tenant_id": tenant_id,
                "evidence_cid": cid,
                "requested_by": requested_by,
                "erasure_mode": mode.value,
                "propagated": propagated,
                "at": utc_now().isoformat(),
            }
            self.deletion_log.append(entry)
            self._audit(
                tenant_id,
                requested_by,
                "forget",
                cid,
                {**propagated, "erasure_mode": mode.value, "source_type": ev.source_type},
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
                target_key = self._branch_key(rel.tenant_id, into, rel.id)
                if target_key not in self.relations:
                    cloned = copy.deepcopy(rel)
                    cloned.branch = into
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

    def _embedding_for_hit(self, hit: Hit) -> list[float]:
        if hit.kind == "evidence":
            ev = self.evidence.get(self._evidence_key(hit.tenant_id, hit.branch, hit.id))
            if ev and ev.embedding:
                return ev.embedding
        return self._embed_text(hit.text)

    def _embed_text(self, text: str) -> list[float]:
        return self.adapters.embedding.embed(text)

    def _rrf(self, ranked_lists: list[list[Hit]], k: int) -> list[Hit]:
        by_id: dict[tuple[str, str], Hit] = {}
        scores: dict[tuple[str, str], float] = defaultdict(float)
        channels: dict[tuple[str, str], list[str]] = defaultdict(list)
        for ranked in ranked_lists:
            for rank, hit in enumerate(ranked, start=1):
                key = (hit.kind, hit.id)
                by_id[key] = hit
                scores[key] += 1.0 / (self.policy.rrf_k + rank)
                channels[key].append(hit.channel)
        fused = []
        for key, hit in by_id.items():
            item = copy.deepcopy(hit)
            item.score = scores[key]
            item.channel = "+".join(sorted(set(channels[key])))
            fused.append(item)
        return sorted(fused, key=lambda item: item.score, reverse=True)[:k]

    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        selected: list[Hit] = []
        remaining = list(hits)
        query_vec = self._embed_text(query)
        while remaining and len(selected) < k:
            best: Hit | None = None
            best_score = float("-inf")
            for hit in remaining:
                hit_vec = self._embedding_for_hit(hit)
                relevance = cosine(query_vec, hit_vec)
                diversity_penalty = 0.0
                if selected:
                    diversity_penalty = max(cosine(hit_vec, self._embedding_for_hit(item)) for item in selected)
                score = self.policy.mmr_lambda * relevance - (1.0 - self.policy.mmr_lambda) * diversity_penalty
                score += hit.score
                if score > best_score:
                    best = hit
                    best_score = score
            if best is None:
                break
            selected.append(best)
            remaining.remove(best)
        return selected

    @staticmethod
    def _u_curve_order(hits: list[Hit]) -> list[Hit]:
        front: list[Hit] = []
        back: list[Hit] = []
        for idx, hit in enumerate(hits):
            if idx % 2 == 0:
                front.append(hit)
            else:
                back.insert(0, hit)
        return front + back

    @staticmethod
    def _fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]:
        kept: list[Hit] = []
        used = 0
        for hit in hits:
            cost = approx_tokens(hit.text)
            if used + cost > budget:
                continue
            kept.append(hit)
            used += cost
        return kept, used

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
        }
