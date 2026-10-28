"""Sandboxed generative replay primitives.

The dreamer is deliberately shadow-only: it recombines already-retained
evidence into low-trust candidates for later gates, but never writes to the
ledger, never changes active beliefs, and never participates in answer
retrieval.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .models import Evidence
from .text import tokenize


@dataclass(frozen=True, slots=True)
class DreamCandidate:
    """Low-trust replay hypothesis produced from existing evidence."""

    id: str
    tenant_id: str
    branch: str
    content: str
    source_evidence_cids: tuple[str, ...]
    reality_class: str = "self_generated"
    trust_tier: int = 5
    shadow_only: bool = True
    promotion_required: bool = True
    critical_path: bool = False
    surprise_score: float = 0.0
    candidate_kind: str = "hypothesis"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def hypothesis(self) -> str:
        return self.content

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_evidence_cids"] = list(self.source_evidence_cids)
        return data


@dataclass(frozen=True, slots=True)
class DreamReport:
    """Replay output contract for G3 shadow generativity."""

    tenant_id: str
    branch: str
    candidates: tuple[DreamCandidate, ...]
    source_count: int
    shadow_only: bool = True
    production_mutation: bool = False
    critical_path: bool = False
    promotion_gate_required: bool = True

    def __iter__(self):
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)

    def __getitem__(self, index: int) -> DreamCandidate:
        return self.candidates[index]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data


_NEGATION_TOKENS = frozenset(
    {
        "not",
        "never",
        "no",
        "none",
        "cannot",
        "cant",
        "wont",
        "doesnt",
        "didnt",
        "isnt",
        "arent",
        "wasnt",
        "werent",
        "without",
        "disabled",
        "disable",
        "off",
        "false",
        "failed",
        "rejected",
        "deprecated",
        "removed",
        "dropped",
        "prohibited",
        "forbidden",
        "dislike",
        "dislikes",
        "hate",
        "hates",
        "inactive",
        "offline",
        "unencrypted",
        "unsupported",
    }
)

_OPPOSING_STATE_PAIRS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (frozenset({"enabled", "enable", "on", "true", "active"}), frozenset({"disabled", "disable", "off", "false", "inactive", "deprecated"})),
    (frozenset({"online", "up", "healthy", "reachable"}), frozenset({"offline", "down", "unhealthy", "unreachable"})),
    (frozenset({"allowed", "permitted", "required", "mandatory", "supported"}), frozenset({"prohibited", "forbidden", "banned", "unsupported", "rejected"})),
    (frozenset({"passed", "succeeded", "approved", "accepted"}), frozenset({"failed", "errored", "rejected", "denied"})),
    (frozenset({"likes", "like", "loves", "love", "prefers", "prefer", "enjoys"}), frozenset({"dislikes", "dislike", "hates", "hate", "avoids", "avoid"})),
    (frozenset({"encrypted", "public", "synchronous", "sync", "dark"}), frozenset({"unencrypted", "private", "asynchronous", "async", "light"})),
)


@dataclass(frozen=True, slots=True)
class SandboxedDreamer:
    """Deterministic low-trust generative replay specialist."""

    max_candidates: int = 3
    min_sources: int = 2
    max_sources: int = 64
    max_source_chars: int = 4096

    def dream(
        self,
        evidence: str | Sequence[Evidence | Mapping[str, Any]],
        maybe_evidence: Sequence[Evidence | Mapping[str, Any]] | None = None,
        *,
        tenant_id: str | None = None,
        branch: str = "dream-shadow",
        max_candidates: int | None = None,
    ) -> DreamReport:
        if isinstance(evidence, str) and maybe_evidence is not None:
            tenant_id = evidence
            ev_seq: Sequence[Evidence | Mapping[str, Any]] = maybe_evidence
        else:
            ev_seq = evidence if not isinstance(evidence, str) else ()

        usable = [
            _coerce_source(item, max_chars=self.max_source_chars, index=idx)
            for idx, item in enumerate(list(ev_seq)[: self.max_sources])
        ]
        if tenant_id is None:
            tenant_id = next((item["tenant_id"] for item in usable if item["tenant_id"]), "default")
        usable = [
            item
            for item in usable
            if item["cid"]
            and item["content"]
            and item["tenant_id"] == tenant_id
            and item["access_tenant"] == tenant_id
        ]
        if len(usable) < self.min_sources:
            return DreamReport(tenant_id=tenant_id, branch=branch, candidates=(), source_count=len(usable))

        limit = max(0, int(max_candidates if max_candidates is not None else self.max_candidates))
        if limit == 0:
            return DreamReport(tenant_id=tenant_id, branch=branch, candidates=(), source_count=len(usable))

        idf_map = _compute_corpus_idf(usable)

        # 1. Discover latent cross-evidence contradictions
        contradiction_candidates = self._find_contradiction_candidates(
            usable,
            idf_map=idf_map,
            tenant_id=tenant_id,
            branch=branch,
        )

        # 2. Discover structural holes (non-adjacent / cross-session high-IDF bridges & 2-hop connections)
        structural_hole_candidates = self._find_structural_hole_candidates(
            usable,
            idf_map=idf_map,
            tenant_id=tenant_id,
            branch=branch,
        )

        # 3. Adjacent replay hypotheses (baseline coverage)
        adjacent_candidates: list[DreamCandidate] = []
        for left, right in zip(usable, usable[1:], strict=False):
            left_terms = _salient_terms(left["content"])
            right_terms = _salient_terms(right["content"])
            if not left_terms or not right_terms:
                continue
            source_cids = (str(left["cid"]), str(right["cid"]))
            surprise = _pair_surprise_score(left, right, idf_map=idf_map, is_non_adjacent=False)
            content = (
                "Sandbox replay hypothesis: "
                f"{left_terms[0]} may relate to {right_terms[0]} across retained evidence."
            )
            adjacent_candidates.append(
                DreamCandidate(
                    id=_candidate_id(tenant_id, branch, content, source_cids),
                    tenant_id=tenant_id,
                    branch=branch,
                    content=content,
                    source_evidence_cids=source_cids,
                    surprise_score=surprise,
                    candidate_kind="hypothesis",
                    metadata={"kind": "hypothesis", "surprise_score": surprise},
                )
            )

        # Combine and deduplicate by source CID pair, prioritizing high-surprise contradictions and structural holes
        prioritized_pool = sorted(
            [*contradiction_candidates, *structural_hole_candidates],
            key=lambda c: (c.candidate_kind == "contradiction", c.surprise_score, c.id),
            reverse=True,
        )

        selected: list[DreamCandidate] = []
        seen_cid_pairs: set[frozenset[str]] = set()

        for cand in [*prioritized_pool, *adjacent_candidates]:
            if len(selected) >= limit:
                break
            pair_key = frozenset(cand.source_evidence_cids)
            if pair_key in seen_cid_pairs:
                continue
            seen_cid_pairs.add(pair_key)
            selected.append(cand)

        return DreamReport(
            tenant_id=tenant_id,
            branch=branch,
            candidates=tuple(selected),
            source_count=len(usable),
        )

    def discover_structural_holes(
        self,
        evidence: Sequence[Evidence | Mapping[str, Any]],
        *,
        tenant_id: str,
        branch: str = "dream-shadow",
    ) -> list[DreamCandidate]:
        usable = [
            _coerce_source(item, max_chars=self.max_source_chars, index=idx)
            for idx, item in enumerate(evidence[: self.max_sources])
        ]
        usable = [
            item
            for item in usable
            if item["cid"]
            and item["content"]
            and item["tenant_id"] == tenant_id
            and item["access_tenant"] == tenant_id
        ]
        if len(usable) < self.min_sources:
            return []
        idf_map = _compute_corpus_idf(usable)
        return self._find_structural_hole_candidates(usable, idf_map=idf_map, tenant_id=tenant_id, branch=branch)

    def detect_contradictions(
        self,
        evidence: Sequence[Evidence | Mapping[str, Any]],
        *,
        tenant_id: str,
        branch: str = "dream-shadow",
    ) -> list[DreamCandidate]:
        usable = [
            _coerce_source(item, max_chars=self.max_source_chars, index=idx)
            for idx, item in enumerate(evidence[: self.max_sources])
        ]
        usable = [
            item
            for item in usable
            if item["cid"]
            and item["content"]
            and item["tenant_id"] == tenant_id
            and item["access_tenant"] == tenant_id
        ]
        if len(usable) < self.min_sources:
            return []
        idf_map = _compute_corpus_idf(usable)
        return self._find_contradiction_candidates(usable, idf_map=idf_map, tenant_id=tenant_id, branch=branch)

    def _find_contradiction_candidates(
        self,
        usable: list[dict[str, str]],
        *,
        idf_map: dict[str, float],
        tenant_id: str,
        branch: str,
    ) -> list[DreamCandidate]:
        found: list[DreamCandidate] = []
        n = len(usable)
        for i in range(n):
            for j in range(i + 1, n):
                left, right = usable[i], usable[j]
                conflict = _detect_pair_contradiction(left["content"], right["content"], idf_map=idf_map)
                if conflict is None:
                    continue
                shared_subj, conflict_desc, score = conflict
                source_cids = (str(left["cid"]), str(right["cid"]))
                content = (
                    f"Sandbox replay hypothesis (contradiction on {shared_subj}): "
                    f"{shared_subj} has conflicting evidence ({conflict_desc}) across retained evidence."
                )
                found.append(
                    DreamCandidate(
                        id=_candidate_id(tenant_id, branch, content, source_cids),
                        tenant_id=tenant_id,
                        branch=branch,
                        content=content,
                        source_evidence_cids=source_cids,
                        surprise_score=score,
                        candidate_kind="contradiction",
                        metadata={
                            "kind": "contradiction",
                            "subject": shared_subj,
                            "conflict": conflict_desc,
                            "surprise_score": score,
                        },
                    )
                )
        found.sort(key=lambda c: (c.surprise_score, c.id), reverse=True)
        return found

    def _find_structural_hole_candidates(
        self,
        usable: list[dict[str, str]],
        *,
        idf_map: dict[str, float],
        tenant_id: str,
        branch: str,
    ) -> list[DreamCandidate]:
        found: list[DreamCandidate] = []
        n = len(usable)
        terms_by_idx = [set(_salient_terms(item["content"], limit=10)) for item in usable]

        for i in range(n):
            for j in range(i + 1, n):
                left, right = usable[i], usable[j]
                is_non_adjacent = (j - i > 1) or (left["session_id"] != right["session_id"])
                if not is_non_adjacent:
                    continue
                ti, tj = terms_by_idx[i], terms_by_idx[j]
                if not ti or not tj:
                    continue

                shared = ti & tj
                only_i = sorted(ti - tj, key=lambda t: (-idf_map.get(t, 1.0), t))
                only_j = sorted(tj - ti, key=lambda t: (-idf_map.get(t, 1.0), t))

                if shared and only_i and only_j:
                    # Direct high-IDF bridge across non-adjacent / cross-session evidence
                    bridge = max(shared, key=lambda t: (idf_map.get(t, 1.0), len(t), t))
                    surprise = _pair_surprise_score(left, right, idf_map=idf_map, is_non_adjacent=True)
                    source_cids = (str(left["cid"]), str(right["cid"]))
                    content = (
                        f"Sandbox replay hypothesis (structural hole via {bridge}): "
                        f"{only_i[0]} may relate to {only_j[0]} across retained evidence."
                    )
                    found.append(
                        DreamCandidate(
                            id=_candidate_id(tenant_id, branch, content, source_cids),
                            tenant_id=tenant_id,
                            branch=branch,
                            content=content,
                            source_evidence_cids=source_cids,
                            surprise_score=surprise,
                            candidate_kind="structural_hole",
                            metadata={
                                "kind": "structural_hole",
                                "bridge_term": bridge,
                                "hop_count": 1,
                                "surprise_score": surprise,
                            },
                        )
                    )
                elif not shared:
                    # Check 2-hop connection via a third evidence item k
                    best_k: int | None = None
                    best_bridges: tuple[str, str] | None = None
                    best_bridge_score = 0.0
                    for k in range(n):
                        if k == i or k == j:
                            continue
                        tk = terms_by_idx[k]
                        b_ik = ti & tk
                        b_kj = tk & tj
                        if b_ik and b_kj:
                            b1 = max(b_ik, key=lambda t: (idf_map.get(t, 1.0), t))
                            b2 = max(b_kj, key=lambda t: (idf_map.get(t, 1.0), t))
                            score_k = idf_map.get(b1, 1.0) + idf_map.get(b2, 1.0)
                            if score_k > best_bridge_score:
                                best_bridge_score = score_k
                                best_k = k
                                best_bridges = (b1, b2)
                    if best_k is not None and best_bridges is not None and only_i and only_j:
                        b1, b2 = best_bridges
                        surprise = round(min(0.97, max(0.45, 0.35 + 0.15 * best_bridge_score)), 4)
                        source_cids = (str(left["cid"]), str(right["cid"]))
                        bridge_label = b1 if b1 == b2 else f"{b1}/{b2}"
                        content = (
                            f"Sandbox replay hypothesis (structural hole via {bridge_label}): "
                            f"{only_i[0]} may relate to {only_j[0]} across retained evidence."
                        )
                        found.append(
                            DreamCandidate(
                                id=_candidate_id(tenant_id, branch, content, source_cids),
                                tenant_id=tenant_id,
                                branch=branch,
                                content=content,
                                source_evidence_cids=source_cids,
                                surprise_score=surprise,
                                candidate_kind="structural_hole",
                                metadata={
                                    "kind": "structural_hole",
                                    "bridge_term": bridge_label,
                                    "bridge_cid": str(usable[best_k]["cid"]),
                                    "hop_count": 2,
                                    "surprise_score": surprise,
                                },
                            )
                        )

        found.sort(key=lambda c: (c.surprise_score, c.id), reverse=True)
        return found


def _coerce_source(
    item: Evidence | Mapping[str, Any],
    *,
    max_chars: int,
    index: int = 0,
) -> dict[str, str]:
    if isinstance(item, Evidence):
        access_tenant = item.access_policy.get("tenant")
        meta = item.metadata if isinstance(item.metadata, Mapping) else {}
        session_id = str(
            meta.get("session_id")
            or item.source_identity
            or item.source_type
            or f"session-{index}"
        )
        return {
            "cid": str(item.cid or ""),
            "content": item.content[:max_chars],
            "tenant_id": item.tenant_id,
            "access_tenant": str(access_tenant or ""),
            "session_id": session_id,
        }
    access_policy = item.get("access_policy") if isinstance(item.get("access_policy"), Mapping) else {}
    access_tenant = access_policy.get("tenant") if isinstance(access_policy, Mapping) else None
    meta = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    session_id = str(
        item.get("session_id")
        or (meta.get("session_id") if isinstance(meta, Mapping) else None)
        or item.get("source_identity")
        or item.get("source_type")
        or f"session-{index}"
    )
    return {
        "cid": str(item.get("cid") or ""),
        "content": str(item.get("content") or "")[:max_chars],
        "tenant_id": str(item.get("tenant_id") or ""),
        "access_tenant": str(access_tenant or ""),
        "session_id": session_id,
    }


def _salient_terms(text: str, *, limit: int = 3) -> list[str]:
    stop = {
        "about",
        "across",
        "after",
        "before",
        "evidence",
        "from",
        "into",
        "that",
        "their",
        "there",
        "this",
        "with",
        "have",
        "were",
        "been",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
    }
    terms = [term for term in tokenize(text) if len(term) >= 4 and term not in stop]
    ranked = sorted(set(terms), key=lambda term: (-terms.count(term), term))
    return ranked[:limit]


def _compute_corpus_idf(usable: Sequence[Mapping[str, str]]) -> dict[str, float]:
    n = max(len(usable), 1)
    df: dict[str, int] = {}
    for item in usable:
        for term in set(_salient_terms(item["content"], limit=24)):
            df[term] = df.get(term, 0) + 1
    return {term: round(math.log((n + 1.0) / (count + 0.5)) + 1.0, 4) for term, count in df.items()}


def _pair_surprise_score(
    left: Mapping[str, str],
    right: Mapping[str, str],
    *,
    idf_map: Mapping[str, float],
    is_non_adjacent: bool,
) -> float:
    ti = set(_salient_terms(left["content"], limit=12))
    tj = set(_salient_terms(right["content"], limit=12))
    if not ti or not tj:
        return 0.1
    union = ti | tj
    inter = ti & tj
    novelty = 1.0 - (len(inter) / max(len(union), 1))
    bridge_idf = max((idf_map.get(t, 1.0) for t in inter), default=1.0)
    cross_session = 1.2 if (is_non_adjacent or left.get("session_id") != right.get("session_id")) else 1.0
    raw = (bridge_idf / (bridge_idf + 1.2)) * (0.4 + 0.6 * novelty) * cross_session
    return round(min(0.98, max(0.15, raw)), 4)


def _detect_pair_contradiction(
    left_text: str,
    right_text: str,
    *,
    idf_map: Mapping[str, float],
) -> tuple[str, str, float] | None:
    left_salient = set(_salient_terms(left_text, limit=12))
    right_salient = set(_salient_terms(right_text, limit=12))
    shared = left_salient & right_salient
    if not shared:
        return None

    left_toks = set(tokenize(left_text))
    right_toks = set(tokenize(right_text))

    # Pick highest-IDF shared subject/entity token
    subject = max(shared, key=lambda t: (idf_map.get(t, 1.0), len(t), t))
    subj_idf = idf_map.get(subject, 1.0)

    # 1. Check opposing state pairs (e.g., enabled vs disabled, active vs deprecated, dark vs light)
    for pos_set, neg_set in _OPPOSING_STATE_PAIRS:
        l_pos, l_neg = left_toks & pos_set, left_toks & neg_set
        r_pos, r_neg = right_toks & pos_set, right_toks & neg_set
        if (l_pos and r_neg) or (l_neg and r_pos):
            v1 = sorted(l_pos or l_neg)[0]
            v2 = sorted(r_neg if l_pos else r_pos)[0]
            score = round(min(0.99, 0.78 + 0.08 * min(subj_idf, 2.5)), 4)
            return subject, f"{v1} vs {v2}", score

    # 2. Check negation polarity inversion on shared subject + predicate/object overlap
    left_neg = bool(left_toks & _NEGATION_TOKENS) or bool(re.search(r"(?i)\b(?:n't|not|never|no\s+longer)\b", left_text))
    right_neg = bool(right_toks & _NEGATION_TOKENS) or bool(re.search(r"(?i)\b(?:n't|not|never|no\s+longer)\b", right_text))
    if left_neg != right_neg and len(shared) >= 2:
        score = round(min(0.98, 0.76 + 0.08 * min(subj_idf, 2.5)), 4)
        return subject, "affirmative vs negated claim", score

    # 3. Check conflicting numeric values when sharing >= 2 salient context tokens
    left_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", left_text))
    right_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", right_text))
    if left_nums and right_nums and left_nums != right_nums and len(shared) >= 2:
        n1 = sorted(left_nums)[0]
        n2 = sorted(right_nums)[0]
        score = round(min(0.97, 0.75 + 0.08 * min(subj_idf, 2.5)), 4)
        return subject, f"numeric value {n1} vs {n2}", score

    return None


def _candidate_id(tenant_id: str, branch: str, content: str, source_cids: tuple[str, ...]) -> str:
    payload = "\n".join([tenant_id, branch, content, *source_cids]).encode("utf-8")
    return "dream:" + hashlib.sha256(payload).hexdigest()[:24]
