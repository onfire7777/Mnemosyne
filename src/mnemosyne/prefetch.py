"""Anticipatory prefetch with a predictability gate, Markov trajectory tracking, and PassageGraph walk."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import RetrievalResult
from mnemosyne.passages import PassageGraph, PassageRecord
from mnemosyne.text import tokenize


@dataclass(frozen=True, slots=True)
class PrefetchCandidate:
    query: str
    probability: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PrefetchResult:
    candidate: PrefetchCandidate
    executed: bool
    reason: str
    retrieval: RetrievalResult | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["retrieval"] = self.retrieval.to_dict() if self.retrieval else None
        return data


class PredictabilityGate:
    """Blocks speculative retrieval unless confidence and safety allow it."""

    def __init__(self, min_probability: float = 0.65, max_candidates: int = 5):
        if not 0.0 <= min_probability <= 1.0:
            raise ValueError("min_probability must be between 0 and 1")
        self.min_probability = min_probability
        self.max_candidates = max_candidates

    def adaptive_threshold(
        self,
        context_uncertainty: float = 0.0,
        cache_hit_rate: float = 0.5,
    ) -> float:
        """Compute an adaptive predictability threshold based on trajectory uncertainty and cache hit rate.

        Higher context uncertainty increases the threshold to prevent noisy speculative fetches;
        higher cache hit rate lowers the threshold to reward accurate trajectory warming.
        At defaults (context_uncertainty=0.0, cache_hit_rate=0.5), returns self.min_probability.
        """
        u = max(0.0, min(1.0, float(context_uncertainty)))
        h = max(0.0, min(1.0, float(cache_hit_rate)))
        adjusted = self.min_probability + 0.15 * u - 0.15 * (h - 0.5)
        return round(max(0.05, min(0.95, adjusted)), 6)

    def allow(
        self,
        candidate: PrefetchCandidate,
        *,
        context_uncertainty: float | None = None,
        cache_hit_rate: float | None = None,
    ) -> tuple[bool, str]:
        threshold = (
            self.adaptive_threshold(
                0.0 if context_uncertainty is None else context_uncertainty,
                0.5 if cache_hit_rate is None else cache_hit_rate,
            )
            if (context_uncertainty is not None or cache_hit_rate is not None)
            else self.min_probability
        )
        if candidate.probability < threshold:
            return False, "candidate below predictability threshold"
        if not candidate.query.strip():
            return False, "empty query"
        if candidate.metadata.get("requires_network") is True:
            return False, "prefetch cannot perform network side effects"
        return True, "allowed"


_STOP_TOKENS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "why",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "does",
        "did",
        "about",
        "into",
    }
)


class AnticipatoryPrefetcher:
    """Warms retrieval contexts without writing durable memory."""

    def __init__(self, engine: LocalMemoryEngine, gate: PredictabilityGate | None = None):
        self.engine = engine
        self.gate = gate or PredictabilityGate()
        self.cache: dict[tuple[str, str, str], RetrievalResult] = {}
        self._transitions: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self._transitions_norm: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self._passage_graph = PassageGraph()
        self._indexed_passage_ids: set[str] = set()
        self._cache_hits: int = 0
        self._cache_lookups: int = 0

    def record_query_transition(self, tenant_id: str, prev_query: str, next_query: str) -> None:
        """Record an observed Markov query transition (prev_query -> next_query) for tenant_id."""
        prev_q = (prev_query or "").strip()
        next_q = (next_query or "").strip()
        if not prev_q or not next_q or prev_q.lower() == next_q.lower():
            return
        self._transitions[tenant_id][prev_q][next_q] += 1
        self._transitions_norm[tenant_id][prev_q.lower()][next_q] += 1

    def _active_passage_graph(self, tenant_id: str, branch: str = "main") -> PassageGraph:
        """Return a live PassageGraph synced with the engine's current evidence and assertions."""
        engine_pg = getattr(self.engine, "passage_graph", None)
        if engine_pg is None:
            adapters = getattr(self.engine, "adapters", None)
            adapter_pg = getattr(adapters, "passage_graph", None)
            if isinstance(adapter_pg, PassageGraph):
                engine_pg = adapter_pg
            elif adapter_pg is not None and isinstance(getattr(adapter_pg, "passage_graph", None), PassageGraph):
                engine_pg = adapter_pg.passage_graph

        pg = engine_pg if isinstance(engine_pg, PassageGraph) else self._passage_graph

        # Sync live evidence rows from engine into PassageGraph
        read_rows = getattr(self.engine, "evidence_rows_for_reading", None)
        rows_iter: list[Any] = []
        if callable(read_rows):
            store = read_rows()
            in_branch = getattr(store, "in_branch", None)
            if callable(in_branch):
                rows_iter = list(in_branch(tenant_id, branch).values())
            elif isinstance(store, dict):
                rows_iter = list(store.values())
        if not rows_iter:
            ev_map = getattr(self.engine, "evidence", None)
            if isinstance(ev_map, dict):
                rows_iter = list(ev_map.values())

        for ev in rows_iter:
            if getattr(ev, "tenant_id", None) != tenant_id:
                continue
            if getattr(ev, "erased", False) or getattr(ev, "retired_at", None) is not None:
                continue
            ev_branch = getattr(ev, "branch", "main") or "main"
            if ev_branch != branch:
                continue
            cid = str(getattr(ev, "cid", "") or "")
            content = str(getattr(ev, "content", "") or "").strip()
            if cid and content and cid not in pg._passage_records:
                pg.add_passage(
                    PassageRecord(
                        passage_id=cid,
                        tenant_id=tenant_id,
                        branch=branch,
                        text=content,
                    )
                )

        # Also sync active assertions as virtual passages so entity/predicate neighborhoods are in graph
        assertion_items_fn = getattr(self.engine, "_assertion_items", None)
        if callable(assertion_items_fn):
            try:
                for a in assertion_items_fn(tenant_id, branch):
                    if getattr(a, "status", "active") != "active":
                        continue
                    pid = f"assertion:{a.id}"
                    if pid not in pg._passage_records:
                        pg.add_passage(
                            PassageRecord(
                                passage_id=pid,
                                tenant_id=tenant_id,
                                branch=branch,
                                text=f"{a.subject} {a.predicate} {a.object}",
                            )
                        )
            except Exception:
                pass

        return pg

    def predict_candidates_from_context(
        self,
        tenant_id: str,
        current_query: str,
        branch: str = "main",
        top_k: int = 5,
    ) -> list[PrefetchCandidate]:
        """Synthesize high-probability follow-up PrefetchCandidates using Markov transitions and live PassageGraph."""
        limit = max(0, int(top_k))
        if limit == 0 or not (current_query or "").strip():
            return []

        q_clean = current_query.strip()
        q_lower = q_clean.lower()
        q_tokens = [t for t in tokenize(q_clean) if len(t) >= 3 and t not in _STOP_TOKENS]
        q_token_set = set(q_tokens)

        candidates_by_query: dict[str, PrefetchCandidate] = {}

        def _add_candidate(query_str: str, prob: float, reason: str, meta: dict[str, Any]) -> None:
            norm_q = query_str.strip()
            if not norm_q or norm_q.lower() == q_lower:
                return
            bounded_prob = round(max(0.05, min(0.98, prob)), 4)
            existing = candidates_by_query.get(norm_q.lower())
            if existing is None or bounded_prob > existing.probability:
                candidates_by_query[norm_q.lower()] = PrefetchCandidate(
                    query=norm_q,
                    probability=bounded_prob,
                    reason=reason,
                    metadata=meta,
                )

        # 1. Markov Trajectory Candidates (exact match + token-overlap transitions)
        exact_counts = self._transitions[tenant_id].get(q_clean) or self._transitions_norm[tenant_id].get(q_lower)
        if exact_counts:
            total = sum(exact_counts.values())
            for next_q, count in exact_counts.most_common(limit):
                ratio = count / max(total, 1)
                prob = min(0.96, max(ratio, 0.68 + 0.25 * ratio))
                _add_candidate(
                    next_q,
                    prob,
                    "markov_transition",
                    {
                        "source": "markov",
                        "from_query": q_clean,
                        "transition_count": count,
                        "total_transitions": total,
                        "empirical_probability": round(ratio, 4),
                    },
                )
        elif q_token_set and self._transitions_norm[tenant_id]:
            # Partial Markov match when a past query shares salient tokens with current_query
            for prev_norm, counter in self._transitions_norm[tenant_id].items():
                prev_toks = {t for t in tokenize(prev_norm) if len(t) >= 3 and t not in _STOP_TOKENS}
                if not prev_toks:
                    continue
                overlap = len(q_token_set & prev_toks) / max(len(q_token_set | prev_toks), 1)
                if overlap >= 0.4:
                    total = sum(counter.values())
                    for next_q, count in counter.most_common(limit):
                        ratio = count / max(total, 1)
                        prob = min(0.90, 0.66 + 0.20 * ratio * overlap)
                        _add_candidate(
                            next_q,
                            prob,
                            "markov_fuzzy_transition",
                            {
                                "source": "markov_fuzzy",
                                "matched_query": prev_norm,
                                "overlap": round(overlap, 4),
                            },
                        )

        # 2. Live PassageGraph Co-occurrence & Entity Neighborhood Walk
        pg = self._active_passage_graph(tenant_id, branch)

        # 2a. Entity & Relation neighborhood walk in engine
        relation_items_fn = getattr(self.engine, "_relation_items", None)
        if callable(relation_items_fn) and q_token_set:
            try:
                for rel in relation_items_fn(tenant_id, branch):
                    src_toks = set(tokenize(rel.source))
                    tgt_toks = set(tokenize(rel.target))
                    if q_token_set & src_toks and not (q_token_set >= tgt_toks):
                        _add_candidate(
                            f"{rel.target}",
                            0.76,
                            "entity_neighborhood",
                            {
                                "source": "passage_graph_entity_walk",
                                "seed_entity": rel.source,
                                "predicate": rel.predicate,
                                "neighbor_entity": rel.target,
                            },
                        )
                    elif q_token_set & tgt_toks and not (q_token_set >= src_toks):
                        _add_candidate(
                            f"{rel.source}",
                            0.74,
                            "entity_neighborhood",
                            {
                                "source": "passage_graph_entity_walk",
                                "seed_entity": rel.target,
                                "predicate": rel.predicate,
                                "neighbor_entity": rel.source,
                            },
                        )
            except Exception:
                pass

        # 2b. PassageGraph co-occurring terms and high-IDF bridge terms
        scored_co_terms: dict[str, float] = {}
        for qt in q_tokens:
            co_terms = pg.get_corpus_cooccurrences(qt, top_n=limit * 3)
            co_counter = pg._cooccurrences.get(qt.lower(), Counter())
            for rank_idx, co_term in enumerate(co_terms):
                if co_term in q_token_set or co_term in _STOP_TOKENS or len(co_term) < 3:
                    continue
                co_count = max(1, co_counter.get(co_term, 1))
                idf_val = max(0.3, pg.get_live_idf(co_term))
                score = co_count * idf_val / (1.0 + 0.15 * rank_idx)
                scored_co_terms[co_term] = max(scored_co_terms.get(co_term, 0.0), score)

        if scored_co_terms:
            ranked_co = sorted(scored_co_terms.items(), key=lambda kv: (-kv[1], kv[0]))
            max_score = max(ranked_co[0][1], 1.0)
            for idx, (co_term, raw_score) in enumerate(ranked_co[:limit]):
                norm_strength = min(1.0, raw_score / max_score)
                prob = max(0.66, min(0.88, 0.67 + 0.18 * norm_strength - 0.02 * idx))
                seed = q_tokens[0] if q_tokens else q_clean
                follow_up_query = f"{seed} {co_term}"
                _add_candidate(
                    follow_up_query,
                    prob,
                    "passage_graph_cooccurrence",
                    {
                        "source": "passage_graph",
                        "seed_query": q_clean,
                        "bridge_term": co_term,
                        "idf": round(pg.get_live_idf(co_term), 4),
                    },
                )

        ranked = sorted(
            candidates_by_query.values(),
            key=lambda c: (c.probability, c.query),
            reverse=True,
        )
        return ranked[:limit]

    def autonomous_prefetch(
        self,
        tenant_id: str,
        current_query: str,
        branch: str = "main",
        access_context: dict[str, Any] | None = None,
    ) -> list[PrefetchResult]:
        """Autonomously synthesize follow-up candidates from Markov + PassageGraph context and warm the cache."""
        candidates = self.predict_candidates_from_context(
            tenant_id,
            current_query,
            branch=branch,
            top_k=self.gate.max_candidates,
        )
        return self.prefetch(
            tenant_id,
            candidates,
            branch=branch,
            access_context=access_context,
        )

    def prefetch(
        self,
        tenant_id: str,
        candidates: list[PrefetchCandidate],
        branch: str = "main",
        access_context: dict[str, Any] | None = None,
    ) -> list[PrefetchResult]:
        selected = set(
            id(candidate)
            for candidate in sorted(candidates, key=lambda item: item.probability, reverse=True)[: self.gate.max_candidates]
        )
        results: list[PrefetchResult] = []
        for candidate in candidates:
            if id(candidate) not in selected:
                results.append(PrefetchResult(candidate, False, "candidate outside prefetch limit"))
                continue
            allowed, reason = self.gate.allow(candidate)
            if not allowed:
                results.append(PrefetchResult(candidate, False, reason))
                continue
            retrieval = self.engine.retrieve(candidate.query, tenant_id, branch=branch, filt=dict(access_context or {}))
            self.cache[(tenant_id, branch, candidate.query)] = retrieval
            results.append(PrefetchResult(candidate, True, reason, retrieval))
        return results

    def get_warmed(self, tenant_id: str, query: str, branch: str = "main") -> RetrievalResult | None:
        self._cache_lookups += 1
        hit = self.cache.get((tenant_id, branch, query))
        if hit is not None:
            self._cache_hits += 1
        return hit
