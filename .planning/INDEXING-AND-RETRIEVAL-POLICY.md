# Mnemosyne — Indexing Strategy & Retrieval Policy (Retrieval Lane)

**Date:** 2026-06-23
**Lane:** Retrieval — owns the *indexing strategy* and the *retrieval / ranking / fallback policy* over the existing memory substrate.
**Type:** Policy + contract. **Not** a schema change, **not** a lifecycle/forgetting policy, **not** a guardrail redefinition.
**Status convention:** each area states the **policy** (blueprint-target intent) and, where they differ, a **Current:** note describing what the shipped engine actually does. The policy is the target; the `Current:` notes keep it honest and tell the schema/consolidation lanes what is not yet wired.
**Governs:** how keyed memory records across the stores are indexed, queried, fused, ranked, assembled, and degraded — realized by `src/mnemosyne/retrieval.py`, `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/engine.py`, `src/mnemosyne/policy.py`, `src/mnemosyne/calibration.py`, and the engine contract (blueprint §28).

**Imports (read, never redefine):**
- **Key schemas** — the **canonical runtime DDL** is `sql/schema.sql` (what the engine runs); blueprint §5/§29/Appendix A is the design and diverges in places — this policy cites the *canonical* column names. Field sets, keys, and bitemporal columns are owned by the **schema lane**; this lane adds no column and renames no key.
- **Lifecycle** — blueprint §10/§25, implemented in `src/mnemosyne/lifecycle.py`. This lane **consumes** lifecycle-maintained signals as ranking inputs; it never advances decay, demotes fidelity, rehearses, supersedes, evicts, or erases.
- **Guardrails** — blueprint §11/§27, implemented in `src/mnemosyne/security.py` (+ `parametric.py`). This lane **invokes** the guardrail primitives as hard filters; it never relaxes or restates the rules.

---

## 0. Lane boundary & scope (read first)

### 0.1 Scope framing — this is a runtime-engine lane
The project's `A–G` lane registry (`OPS-HANDOFF-AND-OWNERSHIP.md`) governs the **Bridgememory ops/docs hub** (`Desktop/Bridgememory/.bridgememory/…`): A = hub key-schema, B = entry templating, C = runbooks, D = env/secrets, E = observability, F = rollback, G = release validation. **There is no retrieval or indexing lane among A–G**, and Lane A explicitly disclaims the runtime engine. This document is therefore a **new runtime-engine concern** that does not collide with A–G ownership and is **not** bound by their "coding frozen for parity" rule. It is the policy behind parity row **#1 "Production Postgres retrieval"** and the retrieval side of row **#6 "Multimodal retrieval."**

### 0.2 What this lane owns
- **Index strategy** — which index *type* maps to which **existing** column, with what parameters and maintenance trigger.
- **Query planning** — fast vs deep routing; gated query expansion.
- **Channel orchestration** — which channels run, concurrency, per-channel budgets.
- **Fusion + activation re-scoring + rerank + dedup**.
- **Context-packet assembly & budget** (the per-turn working-memory output).
- **Fallback / abstention policy** — behavior on adapter failure, empty results, low confidence, gist-only support, budget exhaustion.

### 0.3 What this lane does NOT own
- Table/field/key/PK/bitemporal-column definitions → **schema lane** (`sql/schema.sql`). Physical index DDL is **co-owned**: this lane states the *requirement* (signal → column → index type + params); the schema lane lands the migration. No index implies a new logical key.
- Decay curve, salience update, importance-at-write, fidelity demotion, rehearsal, supersession, eviction, transitive erasure → **lifecycle lane** (`lifecycle.py`).
- Trust/sensitivity/quarantine/provenance/capability/isolation/data-as-data rules → **guardrail contract** (`security.py`).
- Write path (extract/upsert/dedup/quarantine), consolidation, belief revision, learning loop → **ingestion / consolidation / belief lanes** (§6, §8, §21).

**Direction of dependence:** retrieval *reads* schema, *consumes* lifecycle signals, and is *gated by* guardrails. None of those three depends on retrieval. This keeps ownership non-overlapping.

---

## 1. Substrate assumption (one unified store — I4 / §28)

Retrieval runs over a single Postgres substrate where rows carry embeddings *and* lexical terms *and* typed bitemporal edges (blueprint I4): **pgvector** (`embedding VECTOR(1024)` on `evidence`, `assertions`, `entities`, `procedures`, `lessons`), **Postgres FTS** (`assertions.lexeme TSVECTOR`; production lexical = **ParadeDB BM25**), **graph traversal** (`relations` via recursive CTE / **Apache AGE**), and b-tree/GIN metadata indexes. Co-location means **no cross-store sync drift** for this lane to manage.

Everything indexable is a **projection of the immutable evidence ledger** (`evidence`, append-only, content-addressed by `cid`). Indexes are therefore **droppable and rebuildable from the ledger** — the recovery property this lane relies on (§5.F) and which the schema/lifecycle lanes must preserve.

All physical backends sit behind the engine-contract adapters in `retrieval.py`: `EmbeddingProvider`, `MediaEmbeddingProvider`, `Reranker`, `LexicalRetriever`, `GraphRetriever`. Swapping a backend (local ↔ HTTP ↔ command ↔ ParadeDB/AGE/Neo4j at scale) is an adapter change, **not** a policy change. This lane targets the contract, not a vendor.

---

## 2. Indexing strategy (per store, over existing canonical columns)

Every index is built from columns the **schema lane already defines in `sql/schema.sql`** — no column is added here. Mapping is *signal → existing column → index type → maintenance*.

| Store (canonical table) | Mutability | Indexed signal(s) | Existing column(s) read | Index type | Maintenance trigger |
|---|---|---|---|---|---|
| **Evidence ledger** `evidence` (+ episodic index, §5.9) | append-only | dense, lexical, scope, time, modality | `embedding`, `content`/`metadata`-derived text, `session_id`/`user_id`/`actor`/`created_at`, `modality` | pgvector **HNSW** (`evidence_embedding_hnsw`, cosine) + FTS GIN + b-tree(time/session) | on append (incremental); full rebuild from ledger on demand |
| **Semantic** `assertions` | supersede-only | dense, lexical, temporal, scope, recency | `embedding`, `lexeme`, `valid_from`/`valid_to`/`transaction_time`, `scope`, `last_accessed`/`access_count` | pgvector HNSW + GIN(`lexeme`) + b-tree(bitemporal) + GIN(`scope`) | on upsert/supersede |
| **Entity graph** `entities` + `relations` + `entity_aliases` | edge-invalidation | graph proximity (PPR), alias lookup, entity vector | `relations.source`/`predicate`/`target`/`confidence`/`valid_*`; `entities.embedding`/`salience`; `entity_aliases.(tenant_id,alias)` | AGE / recursive-CTE traversal; pgvector(entities); b-tree(alias) | edges on write; PPR live in deep mode (blueprint: precompute during consolidation — *not yet wired*) |
| **Procedural** `procedures` | versioned + gated | task/skill similarity | `embedding`, `signature` | pgvector HNSW + GIN(`signature`) | on gated promotion |
| **Preference** `preferences` | scoped supersede | scope + category + statement match | `category`, `scope`, `statement` | GIN(`scope`) + b-tree(`category`) + FTS(`statement`) | on scoped supersede |
| **Corrective / lessons** `lessons` | versioned + gated | failure-signature + dense | `failure_signature`, `content`, `embedding` | b-tree(`failure_signature`) + pgvector | on validation/prune (`votes`) |
| **Resource** `resources` | versioned | reference + metadata | `uri`, `content_hash`, `metadata` | b-tree(uri/hash) + GIN(metadata) | on version/ingest |

**Store-count note (no gap):** the blueprint names **nine** logical stores. Store **#1 Working memory** is the *assembled per-turn output* (§3.5), not an index target. Store **#9 Meta-memory** is the common **envelope** whose fields (`trust_tier`, `sensitivity`, `valid_*`, `status`, `last_accessed`, `access_count`, `confidence`/`calibration`) are indexed **inline on every other store's rows**, not as a separate table. That is why the table above lists the seven indexable stores.

**Preference channel caveat (schema dependency):** canonical `preferences` has **no `embedding` column**. The preference channel is therefore **GIN(scope) + b-tree(category) + FTS(statement)** only. A dense preference channel is a **schema-lane migration this lane would request** (add `preferences.embedding VECTOR(1024)`), not something retrieval may assume today.

**Multimodal indexing (parity row #6):** media bytes live in an **encrypted external object store** (not inline). At **ingest** an extractor derives text into `evidence` fields/metadata (`derived_text`, `ocr_text`, `transcript`, `caption`, `alt_text`, `description`) with asset-CID + derived-CID hashes and graph lineage, and a `MediaEmbeddingProvider` may store a raw `media_embedding` in `evidence.metadata`. Retrieval indexes media through (a) the **derived text** (FTS + dense over the evidence row) and (b) the **stored media embedding** surfaced as evidence metadata. There is **no separate media-ANN channel** at query time today; the `MediaEmbeddingProvider`/`CommandMediaEmbeddingProvider` adapters are ingest-side. Production parity requires non-local extractor + embedder + encrypted store, validated by `multimodal-ops-check` (§7.2).

**Cross-cutting index rules (retrieval-owned, none redefining a key):**
1. **Tenant/branch isolation is structural, not a trailing filter.** Enforced by Postgres **RLS** (`_set_tenant` session GUC `mnemosyne_current_tenant()`) + an explicit `tenant_id = %s AND branch = %s` predicate on every retrieval path. No degraded path may cross a tenant or branch boundary (tested: tenant + deep-graph branch isolation). *(Framing note: this is RLS + predicate, not a per-tenant physical partition.)*
2. **Bitemporal as-of is index-native.** `valid_from`/`valid_to` (+ `transaction_time`, `expired_at`) are indexed so "current truth" and "as-of T" are the **same index path with a different bound**. `as_of` is a first-class planner parameter (§3, §7.1 "time/as-of"), realized as `WHERE valid_from <= T AND (valid_to IS NULL OR valid_to > T)` on assertions and relations.
3. **Candidate eligibility by `status`.** Retrieval admits only `status IN ('active','contested')`; `superseded`/`quarantined`/`retracted`/`candidate` are excluded in SQL (active/contested filter belongs to retrieval; the *status transitions* belong to belief/lifecycle).
4. **Dense index params** (HNSW `m`, `ef_construction`, `ef_search`, cosine metric) are retrieval-owned tunables; defaults favor recall, raised `ef_search` on the deep path.
5. **PPR is a graph traversal, gated by mode.** Live recursive PPR runs in deep mode; the blueprint's "precompute/cache PPR during consolidation, live only in deep" (I4 scaling guard) is the **target** — *Current:* no cached-PPR read path exists; deep mode simply runs the in-Python recursive PPR (damping 0.85, ~12 iterations) and fast mode omits the graph channel.
6. **Indexes are rebuildable.** Loss/corruption of any index is a `DROP` + rebuild-from-ledger, never data loss. This lane defines the rebuild trigger; it does not define the ledger.

---

## 3. Retrieval policy — the pipeline

Retrieval is a **planner, not a single embedding lookup** (§7), in two modes that share channels:

```
query
  │  ① PLAN (§7.1)        classify: task type · entities · time/as-of · scope · memory types · required accuracy · fast|deep
  │                       (deep) gated multi-query expansion, fused by RRF — gated on LOW retriever confidence (avoid drift)
  ▼
  ② GUARD PRE-FILTER       tenant/user/branch scope (RLS) · trust-tier floor · sensitivity ceiling · quarantine exclusion
  │                        fail-closed: a record failing a guard is never a candidate (security.py + RLS)
  ▼
  ③ MULTI-CHANNEL (§7.2)   run concurrently; each returns a ranked list. The 7 channels:
        exact / metadata ──┐
        BM25 / lexical ────┤   (postgres_fts → postgres_lexical_fallback)
        dense vector ──────┼─▶ (postgres_pgvector → evidence pgvector → postgres_dense_fallback)
        graph PPR ─────────┤   (postgres_graph_ppr; deep mode only)
        preference ────────┤
        procedure ─────────┤
        lesson / warning ──┘   (by failure_signature — "don't repeat this")
        (as-of is a temporal BOUND applied across channels, not a channel)
  ▼
  ④ FUSE (§7.4)            RRF: score(d) = Σ_r 1/(k + rank_r(d)), k = 60 (default tunable). Fused channels labelled "a+b".
  ▼
  ⑤ ACTIVATION RE-SCORE    memory score over fused hits — §4 (apply_activation_scores)
  ▼
  ⑥ RERANK + DEDUP         cross-encoder over the rerank window; MMR dedup (λ = 0.72)
  ▼
  ⑦ ASSEMBLE + BUDGET      U-curve ordering; fit token budget; k is budget-derived — §3.5
  ▼
  ⑧ GUARD POST-FILTER      security.sanitize_retrieved_text(...); rails retrieved_text_is_data_not_instruction,
  │                        source_trust_filter_required (invoke, do not restate)
  ▼
  ⑨ CONFIDENCE / ABSTAIN   aggregate confidence + conformal threshold → answer or abstain — §4.1
  ▼
  context packet (+ calibrated confidence, provenance, explain rail)
```

**Channel name literals (for explain-rail / ops correlation):** the default Postgres pipeline emits `postgres_pgvector`, `postgres_dense_fallback`, `postgres_fts`, `postgres_lexical_fallback`, `postgres_graph_ppr`, with RRF-fused hits joined by `+` (e.g. `postgres_fts+postgres_pgvector`). The local engine emits `dense_hash`/`dense_media`, `lexical`, `graph_ppr`, `candidate`. `command_lexical`/`command_graph_ppr` appear only as command-adapter defaults when an adapter returns no channel; `+rerank` is appended only by the standalone `LocalSimilarityReranker`/`HttpReranker`.

**Why these channels:** lexical + dense cover the paraphrase/exact-term split; the graph channel covers multi-hop associative recall; the **preference / procedure / lesson channels are what make this a memory engine rather than document RAG** (§7.2).

**Mode routing (§7.1; latency contract §15 + §22.5):**
- **Fast** (default): no LLM query-planner, no graph channel, distilled cross-encoder rerank, U-curve assembly. **Fast-mode memory overhead P95 ≤ ~300–400 ms** before the agent generates (NFR §15).
- **Deep** (investigative): adds the graph PPR channel and raises `top_k → deep_top_k`. Blueprint target additionally specifies LLM planning, query decomposition, and listwise (RankGPT) rerank. *Current:* deep mode = **graph channel on + higher k only**; LLM planner, multi-query expansion, and listwise rerank are blueprint-target, **not yet wired**.

`apply_activation_scores(...)`, `activation_explain(...)`, the `_rrf(...)` fuser, `_u_curve_order(...)`, and the conformal abstention check already implement ⑤–⑨; this policy fixes their semantics and tunables, not their existence.

### 3.5 Context-packet assembly & budget (working memory, store #1)

The pipeline output is the **per-turn context packet** — blueprint store #1, ephemeral, assembled fresh each turn. Assembly is **precision-first**, defending against three documented failures (§6: "Lost in the Middle," "Context Rot," "The Power of Noise"):

- **U-curve ordering** (`_u_curve_order`): place the strongest items at the **head and tail**, the single most-relevant item **adjacent to the query**; weaker/distractor-prone items never sit mid-context.
- **Tight token budget well below the model window** (`OperatingPolicy.token_budget`, default **4096**): context rot degrades quality with length even on trivial tasks, so the packet is deliberately small.
- **`k` is budget-derived, not fixed.** Final item count = `min(rerank output, fit(token_budget), top_k)`. The "3–5 survivors" figure is a typical cross-encoder *output cap*, **not** a hard assembly count; default `top_k = 8`, `deep_top_k = 24`.
- **Every slot carries a provenance tag**; the packet carries an **aggregate confidence + uncertainty note** (§4.1).
- **Quality bar:** the assembled packet targets **≥ +15% answer quality vs. full-context at ≤ 10% of the tokens** (§16).

### 3.6 Reconsolidation-on-read (§22.7)

Each retrieval updates the accessed records' `last_accessed` / `access_count` (the *testing effect*; feeds the base-level signal in §4) and **may enqueue an update-on-recall** when a retrieved memory is found stale or contradicted during the task. **Boundary:** the `last_accessed`/`access_count` write is a read-side telemetry side-effect this lane emits; the *decay/salience advancement* driven by it is **lifecycle-owned**, and the "update-on-recall" enqueue hands off to the **consolidation/belief** lane. Retrieval never rewrites the belief itself.

---

## 4. Ranking signals (explicit)

After RRF fusion, hits are re-scored by the **shipped activation scorer** `apply_activation_scores` (`retrieval.py`), a weighted, normalized blend:

```
base_level(m) = min(1.0, ln(1 + access_count) / ln(11))          # log of access frequency, capped
semantic(m,q) = max(score, 0) / max(max_relevance, 0.01)         # normalized fused (dense+lexical) relevance
recency(m)    = 1 / (1 + decay · age_days)                       # hyperbolic recency; decay = 0.5
importance(m) = confidence · trust_weight(trust_tier)            # belief strength × trust multiplier

activation(m) = ( w_base·base_level + w_sem·semantic + w_imp·importance + w_rec·recency ) / Σ w
out_score(m)  = hit.score · (0.5 + activation)                   # activation lifts/dampens the fused score
```

`activation_weights` (real keys + `policy.py` defaults): **`base_level = 0.35`, `semantic = 0.35`, `importance = 0.20`, `recency = 0.10`**.

| Signal | Reads (canonical column) | Owned by | Role here |
|---|---|---|---|
| **semantic** (relevance) | fused dense (`embedding`) + lexical (`lexeme`) score | **retrieval** | computed here (RRF then normalized) |
| **base_level** (frequency) | `assertions.access_count`; evidence `metadata.lifecycle.access_count` for forgetter input | retrieval reads/writes; **lifecycle** governs decay | computed from the column for assertion ranking; evidence access counts feed lifecycle demotion/rehearsal state |
| **recency** | `assertions.last_accessed` → age; evidence `metadata.lifecycle.last_accessed` for forgetter input | retrieval reads/writes | computed here (hyperbolic) for assertion ranking; evidence recency feeds lifecycle utility |
| **importance** | `assertions.confidence` × `trust_weight(trust_tier)` | belief sets `confidence`; **guardrail** owns `trust_weight`/tiers; **lifecycle** owns entity `salience` | consumed; folds trust as a *soft* multiplier (see note) |

**Trust appears in two places, deliberately:** as a **hard admit/deny floor** at the pre-filter (②), and as a **soft confidence multiplier** inside `importance` via `trust_weight`. These are not in conflict — a record below `max_trust_tier` is already excluded, so the score-level use only **down-weights among already-admitted records**. (This corrects an earlier draft claim that trust is "never folded into the score.")

**Importance source caveat:** canonical `assertions` has **no `salience` or `importance` column**. `salience` exists only on `entities` (used for graph-node importance); per-item importance for ranking is derived from `confidence × trust_weight`, and any decayed salience is consumed **only where lifecycle exposes it** (entity rows / lifecycle state), never recomputed in the ranker.

**Blueprint-target delta (Phase 5):** the blueprint's full ACT-R model (§7.4 / Appendix B.1) adds a **spreading-activation (PPR) term `w_s`**, an ACT-R **power-law base-level** `ln(Σ age⁻ᵈ)`, a noise term `ε`, and a **dynamic top-k stop** (`C > pG`). The shipped scorer omits all four (no spreading term, log-count base-level, fixed `top_k`). Weights `w_*` and `decay` are **constants in Phase 1** and **gated-learnable by the cold loop in Phase 5** (§8.4) under the promotion gate (`gate.py`, protected regression cases). The learnable scope is exactly the §6 tunables — never schemas or guardrails.

### 4.1 Confidence & abstention signals

The system **knows what it knows** (blueprint I8 / §26). The packet's confidence is **not a single scalar** — it aggregates **verbalized confidence + semantic entropy (`semantic_entropy`) over candidates + retrieval agreement + provenance strength + fidelity tier**. Two values travel with each item: `confidence` and **`calibrated_confidence`** (conformal, per memory-type).

**Shipped abstention rule** (`postgres_engine.retrieve` / `engine.retrieve`):
```
threshold = conformal_threshold(calibration_for(tenant_id, memory_type))   # calibration.py, alpha = 1 - target_coverage
            else policy.abstention_threshold                                # default 0.45 when no calibration set
confidence = trust- and per-hit-confidence-weighted mean of hit scores
if gist_only:  confidence = min(confidence, threshold · 0.95)               # gist support can never clear the bar alone
abstained = (confidence < threshold) OR gist_only
```
On abstain, the engine returns *"not confident — here is what I have and why,"* offers **`deep_search`** or a clarifying question, and surfaces **multiple hypotheses** when the belief core holds contested facts. Abstention also fires when the conformal **prediction set is empty or too large** (§26).

**Calibration data flow:** `conformal_calibration(tenant_id, memory_type, scores, target_coverage)` (default coverage 0.9). Scores are tuned from **labeled production eval rows** via `calibration-tune` (`--min-examples 100 --min-correct 50 --min-incorrect 50`), which **fails closed** on insufficient sample shape, low empirical coverage, or **high false-accept rate**. *(Boundary: the calibration dataset is eval/metacognition-fed; the per-type `target_coverage` choice is retrieval-policy-owned.)*

---

## 5. Fallback behavior (explicit)

Layered. **Fail closed on safety; fail soft on availability; degrade to abstention rather than confident error.** Default-on-uncertainty ordering: **safety > calibrated correctness > recall > latency.**

**A. Adapter / provider unavailable (availability → fail soft).**
- Provider down or returns malformed output → fall back to the deterministic local adapters in `retrieval.py`: `HashingEmbeddingProvider`, `LocalSimilarityReranker`. Malformed *provider* output is **rejected** (`HttpReranker` validates index range/uniqueness; `_extract_embedding`/`_normalize_vector` raise on bad shape / non-finite / zero vector) — then the local path is used. Quality drops; the request still returns.
- Selection is env-driven (`retrieval_adapters_from_env`): `MNEMOSYNE_EMBEDDING_PROVIDER ∈ {http, local|local-hashing|hashing}`, `MNEMOSYNE_RERANKER_PROVIDER ∈ {http, local|local-similarity}`, `MNEMOSYNE_LEXICAL_PROVIDER ∈ {command, postgres|native}` (default `postgres`), `MNEMOSYNE_GRAPH_PROVIDER ∈ {command, postgres|native}` (default `postgres`); plus `*_URL/_MODEL/_API_KEY`, `*_COMMAND`, `*_BACKEND`, `MNEMOSYNE_EMBEDDING_DIMS` (1024), `MNEMOSYNE_RETRIEVAL_TIMEOUT` (30). Production gates (`provider-check --forbid-local`, `retrieval-ops-check`) assert non-local backends — so local fallback is a **resilience path surfaced in the explain rail**, never a silent permanent downgrade.

**B. Dense-channel degradation (three stages, built-in).** `vector_search` tries (1) pgvector over `assertions` → (2) pgvector over `evidence` stored embeddings → (3) **deterministic Python cosine over null-embedding evidence** (`postgres_dense_fallback`). Dense recall degrades gracefully rather than vanishing when embeddings are absent.

**C. A channel fails or times out (availability → fail soft).** Continue with the remaining channels; RRF (④) operates on whatever ranked lists arrived. A dead graph channel degrades multi-hop recall but never blocks lexical/dense. Missing/fallback channels are recorded in the explain rail.

**D. Latency budget exceeded (fast path).** Return best-so-far from completed channels rather than block — the fast-mode P95 ceiling (§15/§22.5) is hard. Callers needing exhaustiveness request `deep_search` explicitly.

**E. Empty or low-confidence results (correctness → abstain, don't confabulate).** Per §4.1: (1) escalate fast → deep once if budget allows; (2) if still thin, **conformal abstention** with the candidate evidence; (3) surface **multiple hypotheses**; (4) signal the caller that **fresh external data** is needed (planning classified this at ①) — retrieval does not fetch the world itself.

**F. Gist-only support (correctness → abstain).** If the only support is an **abstractive-gist / statistical-trace** tier item (confabulation-risk), the abstention rule caps confidence below threshold (§4.1). `gist_support_report` / `_is_gist_hit` provide the signal (lifecycle tier ∈ {`abstractive_gist`, `statistical_trace`}, source ∈ {`consolidation-summary`, `statistical-trace`}, or any `confabulation_risk` flag); `is_retired_summary_metadata` drops `retired`/`superseded`/`stale` summaries. This lane fixes the *action* (abstain); the *tiering* stays **lifecycle-owned** (lifecycle's parallel helper is `sole_support_requires_abstention`).

**G. Guardrail trip (safety → fail closed, NO fallback).** Tenant/branch mismatch, trust below floor, over-sensitivity, or quarantine → the record is **excluded with no degraded path**. There is no best-effort that leaks across a namespace or promotes untrusted-derived content into the instruction layer. This is the one place fallback is **forbidden**.

---

## 6. Configuration surface (retrieval-owned tunables)

All live on `OperatingPolicy` (`policy.py`); **none** alters a schema, lifecycle curve, or guardrail rule. Real fields + defaults:

| Field | Default | Purpose |
|---|---|---|
| `top_k` | 8 | fast-mode final candidate count |
| `deep_top_k` | 24 | deep-mode final candidate count |
| `token_budget` | 4096 | context-packet token budget (§3.5) |
| `rrf_k` | 60 | RRF constant |
| `rerank_width` | 32 | cross-encoder rerank window |
| `mmr_lambda` | 0.72 | MMR relevance-vs-diversity |
| `abstention_threshold` | 0.45 | confidence floor when no calibration set |
| `max_trust_tier` | 4 | trust-tier admission floor (alias `min_trust_tier` accepted) |
| `max_sensitivity` | 3 | sensitivity ceiling |
| `decay` | 0.5 | recency decay coefficient (§4) |
| `activation_weights` | `{base_level:0.35, semantic:0.35, importance:0.20, recency:0.10}` | activation blend |
| `immutable_rails` | 8 flags | guard rails asserted, not editable here |

`conformal_calibration.target_coverage` (default 0.9) is per-type and tuned via `calibration-tune`. **Blueprint-target tunables not yet on `OperatingPolicy`** (would be added when wired): per-channel candidate caps, per-mode `ef_search`, mode-routing thresholds, multi-query expansion gate, ACT-R dynamic-stop cost params, PPR refresh cadence. Phase 5 cold-loop tuning scope = exactly these listed knobs, under `gate.py`.

---

## 7. Observability, acceptance metrics & the production gate

### 7.1 Explain rail
Every packet carries the `retrieve().explain` surface: `channels`, `rrf_k`, `mmr_lambda`, `activation` (`activation_explain`: weights + per-hit score/activation), `calibration`, `semantic_entropy`, `gist_support`, `read_marks`, `adapters`, `rails`. This is the audit surface the ops dashboards (§32) chart: **channel hit-rates + P95 latency, activation-score distributions, calibration error + abstention rate.**

### 7.2 Acceptance metrics & eval methodology (§14/§16/§33)
The policy's done-when gate is numeric:
- **Quality:** retrieval **recall@k** and **nDCG** on the *private* regression suite; **≥ +15% answer quality vs. full-context at ≤ 10% tokens**.
- **Latency:** fast-path memory-overhead **P95 ≤ ~300–400 ms** (deep mode best-effort/async).
- **Calibration:** **ECE ≤ 0.05**; **abstention precision** ("I don't know" correlates with unanswerable); **false-accept rate** bounded.
- **Safety:** **0 protected-fact regressions per release**; ≥ 95% poisoning-attempt block.
- **Methodology guardrails:** strict LLM-judge with **adversarial-answer screening**; report **confidence intervals** (most LoCoMo-style deltas are within noise); **corpus sizes exceeding the model window** (measure memory, not context management); **continuous regression on every change** to retrieval/prompts/procedures/policies.
- **Benchmark integrity:** public sets (LoCoMo, LongMemEval, PersonaMem, MemoryAgentBench) are **internal sanity gates only, never headline claims** (LoCoMo keys are ~6% wrong and fit in context).

### 7.3 Production retrieval evidence contract (`retrieval-ops-check`)
Production parity (parity row #1) is closed by gates over **real infra**, not by code (per the DO-NOT-REDERIVE rule). `retrieval-ops-check --bundle … --min-cases 3 --min-calibration-examples 50` requires a bundle proving:
- **`provider_check`** — `forbid_local=true`; non-local embedding/reranker providers and non-local lexical/graph backends; `lexical_probe`/`graph_probe` hit evidence.
- **`adapter_probes`** — lexical, vector, graph, reranker adapters with production validation, non-local names, **SHA-256 fingerprints** (command/source/query/tenant/result/top-id), hit counts, bounded latency.
- **`retrieval`** — hashed tenant/query cases proving **all five paths: lexical, vector, graph, reranked, calibrated**.
- **`calibration`** — production dataset fingerprint, sample-shape counts, empirical coverage, **false-accept rate**, threshold.
- **`redaction`** — omits raw queries, embeddings, documents, results, stdout/stderr, commands, env, credentials.

Production backends per the parity rows: **#1** = ParadeDB BM25 + Apache AGE + pgvector + non-local embedding/reranker; **#6** = non-local extractor + media-embedding + encrypted object store (`multimodal-ops-check`, modalities image/audio/video, async `media_extract` jobs with fail-closed dead-job handling).

---

## 8. Model recommendations (§28)

| Slot | Fast path | Deep path | Notes |
|---|---|---|---|
| **Reranker** | small / distilled cross-encoder (Qwen3-Reranker / Cohere Rerank), window ≤ 50 | **listwise LLM (RankGPT)** for **novel domains**, window up to 200 | *Current:* `rerank_width = 32`; listwise not yet wired |
| **Embedding** | Qwen3-Embedding (self-host) / Gemini-Embedding / Voyage-3.5 | same | **1024-dim Matryoshka**; track `embedding_version` |

All behind the §28 adapter contract — model choice is config, not policy.

---

## 9. Agent-facing retrieval surface (§13 / §30.7)

The read verbs this lane realizes (an agent uses them without knowing internals — FR-9):
- **`memory.search(q, scope, as_of, mode=fast)`** — default fast retrieval; `as_of` + `scope` are first-class.
- **`memory.deep_search(q, scope, budget)`** — investigative; explicit token `budget`.
- **`memory.get(id)`**, **`memory.explain(q)`** — direct fetch + the §7.1 explain rail.
- **`graph.query(seed, hops)`**, **`graph.timeline(entity)`**, **`graph.as_of(entity, t)`** — graph/temporal reads.
- **`lesson.search(signature)`**, **`procedure.search(...)`** — the memory-specific channels.

Two retrieval-owned defaults are encoded into the agent contract: **prefer `deep_search` for audits/ambiguity** (maps to deep-mode routing) and **abstain under threshold** (§4.1). Retrieved content is always tagged data, never instruction (§0.3, enforced at ⑧).

---

## 10. Boundaries with other lanes (explicit, non-overlapping)

| Concern | Owner | Code locus | This lane's relationship |
|---|---|---|---|
| Tables/columns/PKs/bitemporal columns | **Schema lane** | `sql/schema.sql` | reads canonical columns only; adds none |
| Physical index DDL / migrations | **Schema lane (co-owned)** | migrations | this lane specifies signal→column→type→params; schema lands DDL (e.g. the `preferences.embedding` ask) |
| Decay, salience-on-access, importance-at-write, fidelity demotion ladder, spaced rehearsal, supersession, transitive erasure | **Lifecycle lane** | `lifecycle.py` (`decayed_salience`, `FidelityTier`, `demotion_decision`, `next_rehearsal_days`, `sole_support_requires_abstention`); state in `runtime_state.payload` | consumes salience/recency/fidelity as inputs; triggers abstention on gist; never advances any of them |
| Trust tiers, sensitivity, quarantine, provenance/capability, isolation, data-as-data, write-gating | **Guardrail contract** | `security.py` (`TrustTier`, `meets_trust`, `trust_weight`, `sanitize_retrieved_text`, `SecurityPolicy.authorize_write`, RLS, `immutable_rails`) + `parametric.py` | invokes as hard pre/post filters and as the `trust_weight` input; never relaxes or restates |
| Write path, consolidation, belief revision, learning loop | **Ingestion / consolidation / belief lanes** | `ingestion.py`, `consolidation.py`, `belief.py`, `gate.py` | consumes their outputs (embeddings, validated lessons, statuses); authors none |
| Backend binaries (pgvector/AGE/ParadeDB/reranker), gate commands | **Frozen shared infra** | gate CLIs | targets the §28 adapter contract; never edits backend or gate behavior |

**Immutable rails this lane operates under (defined by the guardrail contract, not here):** `tenant_isolation_required`, `retrieved_text_is_data_not_instruction`, `source_trust_filter_required`, `branch_promotion_requires_gate`, `erasure_propagates_to_derived_indexes`.

---

## Appendix A — Implementation status (live vs blueprint-target)

| Area | Live in code | Blueprint-target / not yet wired |
|---|---|---|
| Channels | exact/metadata, lexical, dense (3-stage), graph PPR (deep), preference, procedure, lesson | cached-PPR fast path |
| Activation | `{base_level(log-count), semantic, importance(conf×trust), recency(hyperbolic)}` | ACT-R power-law base-level, **spreading/PPR term**, ε noise, **dynamic `C>pG` stop** |
| Modes | deep = graph-on + higher `top_k` | LLM planner, multi-query expansion, listwise RankGPT |
| Rerank | cross-encoder, `rerank_width=32` | window 50–200; listwise for novel domains |
| Assembly | U-curve ordering, `token_budget=4096`, budget-derived `k` | — |
| Abstention | conformal threshold (per `tenant_id`×`memory_type`) else `0.45`; gist cap; multi-signal confidence | empty/too-large prediction-set trigger fully wired |
| Multimodal | ingest-side extract + stored `media_embedding`; retrieval via derived-text + evidence dense | media-vector ANN channel; non-local extractor/embedder gated for prod |
| Preference channel | GIN(scope)+b-tree(category)+FTS(statement) | dense channel (needs `preferences.embedding` migration) |

## Appendix B — Shipped activation pseudocode (`apply_activation_scores`)

```
max_relevance = max(h.score for h in hits)
for m in hits:
    base_level = min(1.0, ln(1 + m.access_count) / ln(11))
    semantic   = max(m.score, 0) / max(max_relevance, 0.01)
    recency    = 1 / (1 + decay * age_days(m.last_accessed))        # decay = 0.5
    importance = m.confidence * trust_weight(m.trust_tier)          # trust_weight from security.py
    activation = ( w[base_level]*base_level + w[semantic]*semantic
                 + w[importance]*importance + w[recency]*recency ) / sum(w.values())
    m.activation = clamp(activation, 0, 1)
    m.score      = m.score * (0.5 + m.activation)
return sort_desc(hits, key=score)        # then rerank → MMR(λ=0.72) → U-curve → budget fit
```

**Done-when check:** (1) indexing strategy specified per store over real canonical columns, with ranking signals (§2, §4) and a layered fallback policy (§5) — ✅; (2) boundaries with the schema and lifecycle lanes (+ guardrail contract) stated explicitly, non-overlapping, and verified against `sql/schema.sql`/`lifecycle.py`/`security.py` (§0, §10) — ✅; no key schema or guardrail is redefined; every field/function/channel/config name cited exists in the canonical codebase.
