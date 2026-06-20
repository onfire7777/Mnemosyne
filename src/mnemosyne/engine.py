"""Local Mnemosyne engine implementation."""

from __future__ import annotations

import copy
import json
import os
import threading
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from mnemosyne.calibration import CalibrationSet, conformal_threshold
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
from mnemosyne.retrieval import activation_explain, apply_activation_scores, semantic_entropy
from mnemosyne.security import TrustTier, more_trusted, trust_weight
from mnemosyne.text import approx_tokens, cosine, hashing_embedding, lexical_score, tokenize


class MemoryEngine(Protocol):
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

    def branch(self, name: str, frm: str = "main", kind: str = "scratch") -> None:
        raise NotImplementedError

    def merge(self, frm: str, into: str = "main") -> MergeReport:
        raise NotImplementedError

    def discard(self, branch: str) -> None:
        raise NotImplementedError


class LocalMemoryEngine:
    """A deterministic local engine that implements the blueprint contract.

    It is intentionally dependency-light so the regression suite can run
    anywhere. Production storage is represented by sql/schema.sql; this local
    engine preserves the same invariants and API surface for development,
    counterfactual replay, and single-user operation.
    """

    def __init__(self, store_path: str | os.PathLike[str] | None = None, policy: OperatingPolicy | None = None):
        self.store_path = Path(store_path).expanduser() if store_path else None
        self.policy = policy or OperatingPolicy()
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

    def _audit(self, tenant_id: str, actor: str, op: str, target_id: str | None, diff: dict[str, Any]) -> None:
        self.audit_log.append(
            {
                "id": new_id(),
                "tenant_id": tenant_id,
                "actor": actor,
                "op": op,
                "target_id": target_id,
                "diff": diff,
                "at": utc_now().isoformat(),
            }
        )

    def _persist(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
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
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.store_path)

    def _load(self) -> None:
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.policy = OperatingPolicy.from_dict(data.get("policy"))
        self.branches = data.get("branches") or self.branches
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
            if existing and not existing.erased:
                self._audit(ev.tenant_id, ev.actor, "append_evidence.noop_dedup", cid, {"branch": branch})
                self._persist()
                return cid
            stored = copy.deepcopy(ev)
            stored.cid = cid
            stored.branch = branch
            self.evidence[key] = stored
            self._audit(ev.tenant_id, ev.actor, "append_evidence", cid, {"source_type": ev.source_type, "branch": branch})
            self._persist()
            return cid

    def get_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Evidence | None:
        with self._lock:
            ev = self.evidence.get(self._evidence_key(tenant_id, branch, cid))
            if ev and not ev.erased:
                return copy.deepcopy(ev)
            return None

    def upsert_assertion(self, assertion: Assertion, branch: str = "main") -> str:
        with self._lock:
            self._require_branch(branch)
            incoming = copy.deepcopy(assertion)
            incoming.branch = branch
            incoming.transaction_time = utc_now()
            incoming.status = "active" if incoming.status == "candidate" else incoming.status
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
                winner.confidence = max(winner.confidence, incoming.confidence)
                winner.source_evidence_cids = sorted(set(winner.source_evidence_cids + incoming.source_evidence_cids))
                winner.trust_tier = more_trusted(winner.trust_tier, incoming.trust_tier)
                winner.last_accessed = utc_now()
                self._audit(winner.tenant_id, "engine", "upsert_assertion.noop_or_reinforce", winner.id, {"before": before, "after": winner.to_dict()})
                self._persist()
                return winner.id

            conflicts = [item for item in peers if item.object != incoming.object]
            if conflicts:
                current = max(conflicts, key=lambda item: item.valid_from)
                if incoming.valid_from > current.valid_from:
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
                self._audit(incoming.tenant_id, "engine", op, incoming.id, {"conflict_with": current.id})

            key = self._branch_key(incoming.tenant_id, branch, incoming.id)
            self.assertions[key] = incoming
            self._audit(incoming.tenant_id, "engine", "upsert_assertion", incoming.id, {"statement": incoming.statement(), "status": incoming.status})
            self._persist()
            return incoming.id

    def _rebalance_contested(self, items: list[Assertion]) -> None:
        total = sum(max(item.confidence, 0.01) for item in items)
        for item in items:
            item.calibration["hypothesis_prob"] = max(item.confidence, 0.01) / total

    def add_relation(self, relation: Relation, branch: str = "main") -> str:
        with self._lock:
            self._require_branch(branch)
            item = copy.deepcopy(relation)
            item.branch = branch
            key = self._branch_key(item.tenant_id, branch, item.id)
            self.relations[key] = item
            self._audit(item.tenant_id, "engine", "add_relation", item.id, {"source": item.source, "target": item.target})
            self._persist()
            return item.id

    def add_justification(self, justification: Justification) -> str:
        with self._lock:
            item = copy.deepcopy(justification)
            self.justifications[item.id] = item
            self._audit(item.tenant_id, "engine", "add_justification", item.id, {"assertion_id": item.assertion_id, "dependencies": item.dependency_ids})
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
            self._audit(item.tenant_id, "engine", "add_contradiction", item.id, {"a": item.a, "b": item.b})
            self._persist()
            return item.id

    def add_preference(self, preference: Preference) -> str:
        with self._lock:
            pref = copy.deepcopy(preference)
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
            self._audit(pref.tenant_id, "engine", "add_preference", pref.id, {"category": pref.category, "explicit": pref.explicit})
            self._persist()
            return pref.id

    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        query_vec = hashing_embedding(query)
        hits: list[Hit] = []
        for hit in self._candidate_hits(filt):
            score = cosine(query_vec, hashing_embedding(hit.text))
            if score > 0:
                hit.score = score
                hit.channel = "dense_hash"
                hits.append(hit)
        return sorted(hits, key=lambda item: item.score, reverse=True)[:k]

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]:
        hits: list[Hit] = []
        for hit in self._candidate_hits(filt):
            score = lexical_score(query, hit.text)
            if score > 0:
                hit.score = score
                hit.channel = "lexical"
                hits.append(hit)
        return sorted(hits, key=lambda item: item.score, reverse=True)[:k]

    def graph_ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: datetime | None = None,
        tenant_id: str | None = None,
        branch: str | None = None,
    ) -> list[Hit]:
        seed_set = {seed.lower() for seed in seeds}
        if not seed_set:
            return []
        def matches_seed(node: str) -> bool:
            node_lower = node.lower()
            return node_lower in seed_set or bool(set(tokenize(node_lower)) & seed_set)

        adjacency: dict[str, set[str]] = defaultdict(set)
        relation_by_pair: dict[tuple[str, str], Relation] = {}
        for rel in self.relations.values():
            if tenant_id is not None and rel.tenant_id != tenant_id:
                continue
            if branch is not None and rel.branch != branch:
                continue
            if as_of and not self._valid_at(rel.valid_from, rel.valid_to, as_of):
                continue
            adjacency[rel.source.lower()].add(rel.target.lower())
            adjacency[rel.target.lower()].add(rel.source.lower())
            relation_by_pair[(rel.source.lower(), rel.target.lower())] = rel
            relation_by_pair[(rel.target.lower(), rel.source.lower())] = rel
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
        hits: list[Hit] = []
        for node, score in sorted(ranks.items(), key=lambda item: item[1], reverse=True):
            if matches_seed(node) or score <= 0:
                continue
            rel = next((relation_by_pair[pair] for pair in relation_by_pair if pair[0] == node or pair[1] == node), None)
            if rel:
                hits.append(
                    Hit(
                        id=rel.id,
                        kind="relation",
                        tenant_id=rel.tenant_id,
                        branch=rel.branch,
                        text=f"{rel.source} {rel.predicate} {rel.target}",
                        score=score,
                        channel="graph_ppr",
                        provenance=rel.source_evidence_cids,
                    )
                )
            if len(hits) >= k:
                break
        return hits

    def retrieve(self, query: str, tenant_id: str, branch: str = "main", deep: bool = False, filt: dict[str, Any] | None = None) -> RetrievalResult:
        effective_filter = dict(filt or {})
        effective_filter.update({"tenant_id": tenant_id, "branch": branch})
        k = self.policy.deep_top_k if deep else self.policy.top_k
        dense = self.vector_search(query, self.policy.rerank_width, effective_filter)
        lexical = self.lexical_search(query, self.policy.rerank_width, effective_filter)
        graph = self.graph_ppr(tokenize(query), max(4, k // 2), tenant_id=tenant_id, branch=branch) if deep else []
        fused = self._rrf([dense, lexical, graph], k=max(k * 2, self.policy.rerank_width))
        reranked = self._mmr(query, fused, k=max(k, 1))
        activated = apply_activation_scores(reranked, self.policy)
        ordered = self._u_curve_order(activated)
        budgeted, used = self._fit_budget(ordered, self.policy.token_budget)
        read_marks = self._record_retrieval_access(budgeted)
        confidence = self._confidence(budgeted)
        calibration = self._calibration_for(tenant_id, "fact")
        threshold = conformal_threshold(calibration) if calibration else self.policy.abstention_threshold
        entropy = semantic_entropy([hit.text for hit in budgeted])
        abstained = confidence < threshold
        note = None
        if abstained:
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
                "semantic_entropy": entropy,
                "read_marks": {"assertions": read_marks},
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
        source_cids = list(source_evidence_cids or [])
        aliases = {canonical}
        if alias and alias.strip():
            aliases.add(alias.strip())
        with self._lock:
            key = (tenant_id, canonical)
            row = self.entities.get(
                key,
                {
                    "id": new_id(),
                    "tenant_id": tenant_id,
                    "canonical": canonical,
                    "type": entity_type,
                    "summary": summary,
                    "salience": 0.5,
                    "aliases": [],
                    "source_evidence_cids": [],
                    "access_policy": access_policy or {"tenant": tenant_id},
                    "updated_at": utc_now().isoformat(),
                },
            )
            row["type"] = row.get("type") or entity_type
            if summary:
                row["summary"] = summary
            if access_policy:
                row["access_policy"] = dict(access_policy)
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

    def _record_retrieval_access(self, hits: list[Hit]) -> int:
        touched = 0
        now = utc_now()
        with self._lock:
            for hit in hits:
                if hit.kind != "assertion":
                    continue
                assertion = self.assertions.get(self._branch_key(hit.tenant_id, hit.branch, hit.id))
                if assertion is None:
                    continue
                assertion.last_accessed = now
                assertion.access_count += 1
                touched += 1
            if touched:
                self._persist()
        return touched

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
            derived_cids = [
                item.cid
                for item in self.evidence.values()
                if item.tenant_id == tenant_id
                and item.branch == branch
                and not item.erased
                and item.metadata.get("source_evidence_cid") == cid
                and item.cid != cid
            ]
            affected_cids = {cid, *derived_cids}
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
            }
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
            self._audit(tenant_id, requested_by, "forget", cid, {**propagated, "erasure_mode": mode.value})
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
        }

    def branch(self, name: str, frm: str = "main", kind: str = "scratch") -> None:
        with self._lock:
            if name in self.branches:
                return
            self._require_branch(frm)
            self.branches[name] = {"from": frm, "kind": kind, "created_at": utc_now().isoformat()}
            for ev in list(self.evidence.values()):
                if ev.branch == frm:
                    cloned = copy.deepcopy(ev)
                    cloned.branch = name
                    if cloned.cid:
                        self.evidence[self._evidence_key(cloned.tenant_id, name, cloned.cid)] = cloned
            for assertion in list(self.assertions.values()):
                if assertion.branch == frm:
                    cloned = copy.deepcopy(assertion)
                    cloned.branch = name
                    self.assertions[self._branch_key(cloned.tenant_id, name, cloned.id)] = cloned
            for rel in list(self.relations.values()):
                if rel.branch == frm:
                    cloned = copy.deepcopy(rel)
                    cloned.branch = name
                    self.relations[self._branch_key(cloned.tenant_id, name, cloned.id)] = cloned
            self._audit("*", "engine", "branch", name, {"from": frm, "kind": kind})
            self._persist()

    def merge(self, frm: str, into: str = "main") -> MergeReport:
        with self._lock:
            self._require_branch(frm)
            self._require_branch(into)
            report = MergeReport(frm, into, 0, 0, 0, 0, [])
            for ev in [item for item in self.evidence.values() if item.branch == frm and not item.erased]:
                if not ev.cid:
                    continue
                target_key = self._evidence_key(ev.tenant_id, into, ev.cid)
                if target_key not in self.evidence:
                    cloned = copy.deepcopy(ev)
                    cloned.branch = into
                    self.evidence[target_key] = cloned
                    report.evidence_added += 1
            for assertion in [item for item in self.assertions.values() if item.branch == frm]:
                before_count = len(self.assertions)
                cloned = copy.deepcopy(assertion)
                cloned.branch = into
                self.upsert_assertion(cloned, branch=into)
                if len(self.assertions) > before_count:
                    report.assertions_added += 1
                else:
                    report.assertions_merged += 1
            for rel in [item for item in self.relations.values() if item.branch == frm]:
                target_key = self._branch_key(rel.tenant_id, into, rel.id)
                if target_key not in self.relations:
                    cloned = copy.deepcopy(rel)
                    cloned.branch = into
                    self.relations[target_key] = cloned
                    report.relations_added += 1
            self.merge_log.append(report.to_dict())
            self._audit("*", "engine", "merge", frm, report.to_dict())
            self._persist()
            return report

    def discard(self, branch: str) -> None:
        if branch == "main":
            raise ValueError("main branch cannot be discarded")
        with self._lock:
            self._require_branch(branch)
            discarded_assertion_ids = {item.id for item in self.assertions.values() if item.branch == branch}
            self.evidence = {key: item for key, item in self.evidence.items() if item.branch != branch}
            self.assertions = {key: item for key, item in self.assertions.items() if item.branch != branch}
            self.relations = {key: item for key, item in self.relations.items() if item.branch != branch}
            surviving_assertion_ids = {item.id for item in self.assertions.values()}
            orphaned_assertion_ids = discarded_assertion_ids - surviving_assertion_ids
            if orphaned_assertion_ids:
                self.justifications = {
                    key: item
                    for key, item in self.justifications.items()
                    if item.assertion_id not in orphaned_assertion_ids
                    and not (set(item.dependency_ids) & orphaned_assertion_ids)
                }
                self.contradictions = {
                    key: item
                    for key, item in self.contradictions.items()
                    if item.a not in orphaned_assertion_ids and item.b not in orphaned_assertion_ids
                }
            self.branches.pop(branch, None)
            self._audit("*", "engine", "discard", branch, {})
            self._persist()

    def _candidate_hits(self, filt: dict[str, Any]) -> list[Hit]:
        tenant_id = filt.get("tenant_id")
        branch = filt.get("branch", "main")
        include_quarantined = bool(filt.get("include_quarantined", False))
        default_max_trust = int(TrustTier.UNTRUSTED_EXTERNAL) if include_quarantined else self.policy.max_trust_tier
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
        max_sensitivity = int(filt.get("max_sensitivity", self.policy.max_sensitivity))
        hits: list[Hit] = []
        for ev in self.evidence.values():
            if ev.erased or ev.tenant_id != tenant_id or ev.branch != branch:
                continue
            if ev.trust_tier > max_trust or ev.sensitivity > max_sensitivity:
                continue
            if not include_quarantined and ev.metadata.get("quarantine_reason"):
                continue
            hits.append(
                Hit(
                    id=ev.cid or "",
                    kind="evidence",
                    tenant_id=ev.tenant_id,
                    branch=ev.branch,
                    text=ev.content,
                    score=0.0,
                    channel="candidate",
                    provenance=[ev.cid] if ev.cid else [],
                    trust_tier=ev.trust_tier,
                    sensitivity=ev.sensitivity,
                    metadata={"actor": ev.actor, "source_type": ev.source_type},
                )
            )
        for assertion in self.assertions.values():
            if assertion.tenant_id != tenant_id or assertion.branch != branch:
                continue
            if assertion.status not in {"active", "contested"}:
                continue
            if assertion.trust_tier > max_trust or assertion.sensitivity > max_sensitivity:
                continue
            hits.append(
                Hit(
                    id=assertion.id,
                    kind="assertion",
                    tenant_id=assertion.tenant_id,
                    branch=assertion.branch,
                    text=assertion.statement(),
                    score=0.0,
                    channel="candidate",
                    provenance=list(assertion.source_evidence_cids),
                    trust_tier=assertion.trust_tier,
                    sensitivity=assertion.sensitivity,
                    metadata={
                        "status": assertion.status,
                        "confidence": assertion.confidence,
                        "last_accessed": assertion.last_accessed.isoformat() if assertion.last_accessed else None,
                        "access_count": assertion.access_count,
                    },
                )
            )
        for pref in self.preferences.values():
            if pref.tenant_id != tenant_id or pref.status != "active":
                continue
            hits.append(
                Hit(
                    id=pref.id,
                    kind="preference",
                    tenant_id=pref.tenant_id,
                    branch=branch,
                    text=pref.statement,
                    score=0.0,
                    channel="candidate",
                    provenance=list(pref.source_evidence_cids),
                    trust_tier=0 if pref.explicit else 3,
                    sensitivity=0,
                    metadata={"category": pref.category, "explicit": pref.explicit},
                )
            )
        return hits

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
        query_vec = hashing_embedding(query)
        while remaining and len(selected) < k:
            best: Hit | None = None
            best_score = float("-inf")
            for hit in remaining:
                relevance = cosine(query_vec, hashing_embedding(hit.text))
                diversity_penalty = 0.0
                if selected:
                    diversity_penalty = max(cosine(hashing_embedding(hit.text), hashing_embedding(item.text)) for item in selected)
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
    def _confidence(hits: list[Hit]) -> float:
        if not hits:
            return 0.0
        weighted = 0.0
        total = 0.0
        for hit in hits:
            trust = trust_weight(hit.trust_tier)
            base = float(hit.metadata.get("confidence", 0.7))
            weighted += max(hit.score, 0.01) * trust * base
            total += max(hit.score, 0.01)
        return max(0.0, min(1.0, weighted / max(total, 0.01)))

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

    def export_all(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_dict(),
            "branches": self.branches,
            "evidence": [item.to_dict() for item in self.evidence.values()],
            "assertions": [item.to_dict() for item in self.assertions.values()],
            "relations": [item.to_dict() for item in self.relations.values()],
            "preferences": [item.to_dict() for item in self.preferences.values()],
            "justifications": [item.to_dict() for item in self.justifications.values()],
            "contradictions": [item.to_dict() for item in self.contradictions.values()],
            "audit_log": self.audit_log,
            "deletion_log": self.deletion_log,
            "merge_log": self.merge_log,
        }
