# Mnemosyne — World-Best Memory Platform: Full-Capability, No-Trade-Off Design

**Date:** 2026-07-15
**Status:** Approved master/program design — decomposes into per-workstream specs
**Author scope:** Synthesis of this program's research and the objective current
state of the Mnemosyne codebase into a single governing design for becoming the
best-measured memory system in the world, per benchmark category, at full
capability and quality on physical 8 GiB hardware, with no quality or capability
trade-off relative to any larger deployment.

**Relationship to existing documents.** This document *extends and does not
replace*: `docs/superpowers/specs/2026-07-13-8gb-full-capability-unblock-design.md`,
`docs/research/Compact-Reader-Reranker-8GB-Design.md`,
`.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`,
`.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`,
`docs/EXECUTION-PLAN-A-Memory-System.md`,
`docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`,
`docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md`, the Phase 12
candidate protocol, PBPP, and the §31 invariant rails / §33 test classes. It
changes no frozen protocol, threshold, custody rule, publication gate, or
human-owned governance boundary. Approval authorizes implementation planning; it
does not create a benchmark result or a public claim.

**Evidence terms (strict, inherited from the 8 GB spec).** *Verified* = an
immutable artifact or exact-SHA check exists. *Pending* = the gate has not
passed. *Hypothesis* = a proposed design or claim. *Human-owned* = an agent may
prepare materials but may not perform the decision or external act. Every
performance number in this document is a **measured target to be pursued**, never
an assumed constant and never a promised outcome.

---

## 0. How to read this document

This is a **master/program design**, deliberately larger than one implementation
plan. §11 decomposes it into five sub-projects; each gets its own
spec → plan → build cycle. Work top-down within a workstream and respect the
dependency order in §11. Nothing in this document authorizes bypassing the
hardware-admission runbook, the custody protocol, PBPP, or the §31/§33 rails.

---

## 1. Goal and the meaning of "no trade-off"

**Goal.** Mnemosyne becomes the best-measured memory system in the world,
demonstrated **per benchmark category** under a **single neutral, reproducible
harness**, with **full capability and full answer quality on physical 8 GiB
hardware** and **no quality or capability loss** relative to any larger
deployment.

"No trade-off" is a precise engineering claim, not a slogan. It is decomposed
into four guarantees, each with a concrete mechanism:

1. **No quality trade-off — by construction.** The 8 GiB profile and the
   multi-tenant server run the **identical frozen model artifacts, identical
   quantization, identical preprocessing, and identical retrieval / consolidation
   / answering code path**. Identical inputs therefore produce the identical
   decoded answer. This is enforced as a **byte-parity gate** (§7.5, §10), not
   asserted. Stronger hardware may improve latency, throughput, corpus capacity,
   and concurrency; it may **not** unlock a higher-scoring configuration. A
   larger or hosted reader may exist **only** as a separately disclosed
   research / teacher / comparison track (Plan A principle 2; carried unchanged).

2. **No capability trade-off — the full platform fits the envelope.** Every
   memory plane (episodic, semantic, temporal-graph, procedural, working,
   prospective), every retrieval channel, every security rail, and the complete
   answering plane fit the preregistered floor envelope (§9). No capability is
   removed, disabled, or degraded to fit 8 GiB.

3. **No scale trade-off — corpus lives on disk.** The 8 GiB bound is on the
   *working set*, not the corpus. SqliteEngine (per-tenant WAL, FTS5, on-disk
   vectors, on-disk graph tables) streams retrieval from disk, so extreme-scale
   corpora (e.g. BEAM at 10M tokens) are processable on 8 GiB. Larger hardware
   reduces wall-clock; it does not change the answer. Latency, not quality, is
   what scale costs on a small host.

4. **No integrity trade-off — honesty is a hard rail.** Every headline-eligible
   number is produced under a frozen, published protocol on the real system,
   disclosed to match execution byte-for-byte, reported per category with **no
   average that hides a weak column**, and independently reproducible before any
   external claim (PBPP; §8, §10). We do not fake, round, blend, or headline an
   unestablished number to appear complete.

**The reconciliation.** "Best in the world" and "8 GiB" are not in tension once
the compact stack is made *the product* and parity is proven: the 8 GiB profile
*is* the quality ceiling, and the server is the same system running faster and
wider. This dissolves the trade-off rather than negotiating it.

---

## 2. Objective current state (evidence-grounded, unbiased)

This section is deliberately even-handed: it credits what exists and states what
does not, from the codebase, not from aspiration.

### 2.1 What Mnemosyne already is (verified in `src/mnemosyne/`)

Mnemosyne is **already substantially the full production memory platform**, not a
retrieval-and-QA stack. The independent architectural pattern that current
research converges on maps onto the existing blueprint nearly one-to-one:

| Required plane | Mnemosyne implementation | Status |
|---|---|---|
| Immutable episodic event log | Evidence ledger: content-addressed (`evidence.cid` = SHA-256 over canonical JSON), append-only; the single source of truth | ✅ built |
| Temporal semantic memory | Bitemporal subject–predicate–object beliefs; `valid_from` / `valid_until`; `as_of()` time-travel; supersession and contradiction links (~1,066 references to these primitives across the core) | ✅ built |
| Extraction / consolidation | 11-role ordered warm loop (replayer → extractor → resolver → belief_reviser → skill_inducer → lesson_distiller → summarizer → forgetter → embedder → promotion_gate → user_model_updater); protected regression gate on every promotion | ✅ built |
| Procedural memory | `Procedure` / `ProcedureInducer` (skill induction) with utility/outcome statistics; `Lesson` / `LessonDistiller` for corrective learning | ✅ built |
| Forgetting and deletion | Graduated fidelity tiers VERBATIM → EXTRACTIVE_SUMMARY → ABSTRACTIVE_GIST → STATISTICAL_TRACE; optional ACT-R decay + demotion/rehearsal lifecycle; crypto-shred erasure via Vault | ✅ built |
| Hybrid retrieval | Dense (pgvector HNSW) + lexical BM25/FTS + graph Personalized PageRank; fused via RRF + MMR + U-curve + budget fit; cross-encoder rerank | ✅ built |
| Conflict / validity resolution | Belief revision core; supersession/contradiction resolution over bitemporal beliefs | ✅ built |
| Grounded answering + abstention | Evidence-grounded reader; conformal calibration → abstain-or-answer; retrieved text handled as data, never executed | ✅ built |
| Security / tenancy / provenance | Capability-secured fail-closed writes; TrustTier 0–5; Postgres Row-Level Security; hash-chained audit log; honeytokens; SSRF-guarded egress; C2PA provenance | ✅ built |
| Multi-engine parity | Three engines behind one `MemoryEngine` Protocol (Local / Postgres / Sqlite); cross-engine parity enforced by tests; 7 §31 invariant rails + 5 §33 test classes regression-tested | ✅ built |

v1.0 is attested (2026-07-07). The suite is large (thousands of tests). The
architectural distance to "complete memory platform" is therefore **small**, not
large — the common critique that "a QA stack is not a memory system" is correct
in general but does not describe this codebase.

### 2.2 Genuine gaps (verified absent in the core)

Three capability gaps are real and confirmed by direct search of
`src/mnemosyne/`:

- **G1 — Prospective memory absent.** No intention / reminder / deferred-trigger /
  `due_at` / scheduling engine exists for *user-facing deferred intentions*. The
  only scheduling in the code is the internal forgetting-rehearsal cadence. This
  is a real capability gap versus PM-Bench, TriggerBench, reminders, and
  autonomous-goal execution.
- **G2 — Working memory absent.** No explicit current-task / active-goal /
  active-constraint / working-set plane. This is a real gap versus action-oriented
  evaluation (MemoryArena, STATE-Bench, and the workflow / premise-awareness
  categories of LongMemEval-V2).
- **G3 — Benchmark coverage narrow.** `eval/public/adapters/` contains
  LongMemEval and HippoRAG only. Absent: LongMemEval-V2, MemoryAgentBench,
  Memora/FAMA, BEAM, LoCoMo, PM-Bench, MemoryArena, STATE-Bench, AFTER. This is
  the single largest distance to "best on every benchmark."

### 2.3 The current substrate blocker (from this program's investigation)

An independent root-cause investigation (retained at
`~/mnemosyne-tier-b-custody/GRAPH-PPR-ROOTCAUSE-2026-07-15.md`; summarized in the
active GOAL) established, with file:line evidence, that the `graph_ppr` retrieval
channel is **inert (0 hits / 1000 questions, channel sum 0)** on the HippoRAG
track, and that multi-hop QA reproduces an EM/F1 ≈ 0.083 floor. Root cause:
(A) the eval ingests via `capture_batch` and **never runs consolidation**, so
`engine.relations` is empty at query time; (B) the deterministic extractor
matches only whole-sentence copular clauses, so it emits no edges from prose or
even from the dev fixture. **Nothing leads any benchmark until this substrate is
fixed** (Workstream 1). The fix (run consolidation before search; broaden the
deterministic extractor) is in flight in the autonomous loop.

### 2.4 Unmeasured strengths (opportunity, not gap)

Two existing capabilities are architecturally aligned with benchmarks Mnemosyne
does not yet run, and are plausible leadership positions:

- **Bitemporal supersession → Memora/FAMA.** FAMA penalizes using stale
  memories even when the final answer is plausible; Mnemosyne's `valid_from`/
  `valid_until` + supersession is built precisely to select the currently-valid
  state. This is a place the design can plausibly lead — but there is no adapter
  measuring it today.
- **Crypto-shred forgetting → deletion-residue tests.** Recent research finds
  raw-only deletion can leave derived-summary residue recoverable in ~20% of
  cases; Mnemosyne's graduated forgetting + Vault crypto-shred targets exactly
  the derived tiers. Again, aligned but unmeasured.

### 2.5 Honest verdict

Mnemosyne today has an unusually complete platform **and currently leads no
benchmark**, for three reasons: the retrieval substrate is broken (§2.3), only
two benchmark families are wired (§2.2 G3), and existing numbers are internal and
unreproduced. The distance to world-best is therefore **not primarily an
architecture gap** — it is a substrate fix + measurement + two capability planes +
reproducibility program. This is a favorable position: the hard, slow part
(the platform) is largely done.

---

## 3. Governing principles

Additive to the 8 GB spec's four principles (full capability at the floor
envelope; quality parity everywhere; the compact stack is the product path; no
custody compromise), which are carried unchanged. This design adds:

5. **Parity by construction is the no-trade-off mechanism.** Quality parity is
   achieved by running identical frozen artifacts and code paths on every
   profile and proving byte-parity, not by tuning two configurations to agree.
6. **Per-category truth over aggregate scores.** Every benchmark is reported by
   competency. No averaged or blended score may hide a weak category. A single
   weak column is a finding, not something to average away.
7. **Protocol-frozen, reproduced targets.** Each benchmark target is stated
   against a specific, frozen dataset version and evaluation protocol, and gated
   at "reproduce the best comparable published baseline" before any stretch
   number is pursued. Numbers are measured, never assumed (this explicitly
   includes quantization loss; §7.4).
8. **Append-only evidence with logical supersession.** Information is never
   destructively overwritten; corrections end a validity interval and add a
   superseding assertion. This preserves auditability and reconstruction while
   the retrieval layer selects the currently-valid state. (Already Mnemosyne's
   model; restated as a program invariant.)
9. **The answering plane is a subsystem, not the system.** The compact ONNX
   reader/reranker/embedder is the final retrieval-and-answering plane. It is
   evaluated by the static multi-hop QA suite (MuSiQue/HotpotQA/2Wiki). Those
   sets do **not** define whether Mnemosyne is a complete memory system.

---

## 4. Target architecture (full platform)

The complete platform. Legend: ✅ exists, ➕ new in this program, ◆ upgraded.

```
Applications / Agents / MCP / Tools
            │
       Memory Gateway ✅   identity · tenancy · trust · policy · idempotency · audit
            │
   Immutable Evidence Ledger ✅   episodes: messages · actions · results · corrections
            │
   Extraction & Consolidation ✅   ADD · REINFORCE · SUPERSEDE · CONTRADICT · RETRACT · MERGE · NO_OP · QUARANTINE
            │
 ┌───────────────────── memory taxonomy ─────────────────────┐
 │ semantic ✅   temporal-graph ✅   procedural ✅            │
 │ working ➕     prospective ➕      episodic ✅              │
 └────────────────────────────────────────────────────────────┘
            │
   Hybrid Index & Retrieval ◆   lexical · dense · graph-PPR · temporal · metadata · procedural · prospective
            │
   Conflict & Validity Resolver ✅
            │
   Grounded Context Builder ✅   evidence-budget optimization · provenance tagging
            │
   Answering Plane ➕   compact ONNX Rust sidecar: embedder · reranker · extractive reader ·
                        deterministic arithmetic/date synthesis · optional constrained generator
            │
   Answer · Action · Reminder · or calibrated Abstention

Cross-cutting: deletion & correction ✅ · security & privacy ✅ ·
observability & evaluation ◆ · backup/recovery/replication ✅
```

**What is genuinely new** is small and bounded: the working-memory plane (§5),
the prospective-memory trigger engine (§6), and the compact answering plane (§7).
The retrieval fusion is *upgraded* (◆) to (a) actually populate and use the graph
channel — Workstream 1 — and (b) add procedural and prospective retrieval routes.
Observability is *upgraded* (◆) to emit the per-request trace and per-category
metrics the benchmark program requires (§8.4).

**Data flow (write path), unchanged in shape, made complete:** raw episode →
candidate extraction → memory-type classification → entity resolution → duplicate
detection → contradiction/update analysis → evidence-span verification →
policy/sensitivity checks → commit mutations (one explicit operation per
candidate) → update indexes → record audit event. A user correction takes the
fast synchronous path: preserve the prior assertion historically, end its
validity interval, add the new fact with a `supersedes` link, invalidate affected
summaries/caches, and make the correction visible to the next request.

**Data flow (read path):** query → intent/memory-type classification → query
decomposition → authorization & tenant filters (applied *before* candidate
retrieval and graph expansion) → parallel candidate retrieval across all routes →
fusion → cross-encoder rerank → temporal/conflict resolution → evidence-budget
optimization → grounded context package → answering plane → answer / action /
reminder / abstention, every factual claim carrying an evidence CID.

---

## 5. Working memory plane (➕ G2)

**Purpose.** Hold transient state for the current task without it silently
becoming permanent: active goal, current plan, active constraints, unresolved
questions, recent tool results, intermediate conclusions.

**Design.** A tenant/session-scoped, short-TTL store behind the existing gateway
and engine Protocol (added to all three engines to preserve parity). Working
items are **not** auto-promoted to durable semantic memory; promotion is an
explicit consolidation decision through the existing promotion_gate with its
regression check. Working memory participates in retrieval as a distinct route
(recency- and task-relevance-weighted) and is included in the evidence-budget
optimizer.

**Rails.** Same capability/tenancy/trust/audit rails as every other write path;
retrieved working-memory content is data, never executed (§31 R6); TTL expiry is
deterministic and audited. No new heavy dependency; small tables + in-process
cache. Cross-engine parity tests (L0–L2) extended to cover it.

---

## 6. Prospective memory / deterministic trigger engine (➕ G1)

**Purpose.** Remember to execute an intention when a future condition occurs —
reminders, deadlines, conditional actions, deferred intentions, follow-up
obligations, recurring checks, dependency-completion triggers — without relying on
a language model to spontaneously remember.

**Design.** A deterministic scheduler, not an LLM behavior. An `Intention`
record: `intention_id`, `tenant_id`/`user_id`/`agent_id`, `trigger_type`
(exact_time · time_window · event · condition · dependency_completion),
`trigger_expression`, `action`, `status`, `priority`, `due_at`, `dependencies[]`,
`reschedule_history[]`, `cancellation_state`, plus provenance to the originating
episode. A deterministic evaluator fires triggers when their condition is
satisfied and infrastructure is available; firing is idempotent and audited.

**Precision/recall discipline.** PM-Bench evidence shows the strongest evaluated
configuration reaches ~65.1 F1 and that systems face a real precision–recall
trade-off (missed intentions vs. acting unnecessarily). The engine therefore
exposes an explicit, tunable, and **measured** precision/recall operating point;
it does not silently prefer one failure mode. Deterministic time-trigger execution
when infrastructure is available is a **hard correctness gate** (§10).

**Rails.** Same gateway/tenancy/trust/audit rails; no heavy dependency; a small
table + a deterministic evaluator; parity across engines; retrieved intention
content is data, never executed.

---

## 7. Compact answering plane (➕ §9 answering plane)

The final retrieval-and-answering plane, exported to ONNX and served from a Rust
`ort` sidecar, within the floor envelope (§9). Every component below is a
2026-current best-at-size candidate; **none is accepted on paper** — each is
selected by a controlled, protocol-frozen bakeoff and must pass the parity
contract (§7.5). Rankings in this section are inputs to the bakeoff, not
conclusions.

### 7.1 Extractive reader (the core)

**Role.** Answer multi-hop questions **only** from retrieved provenance-tagged
evidence; emit exact spans or abstain; resolve yes/no and comparison answers via
an explicit answer-type head; cite source episodes.

**Selection = bakeoff-and-promote between two families:**
- **Maximum published quality:** DeBERTa-v3-large (435M) — best documented
  no-answer calibration and span-extraction quality, and the reader family behind
  the strongest published multi-hop results (Beam Retrieval). Costs: a
  gather-heavy ONNX graph with documented dynamic-INT8 pathologies (a community
  port found ~50% of MatMuls improperly quantized by naive `quantize_dynamic`) —
  mitigated with `per_channel=True` + `reduce_range=True` and a verified export;
  and a 512-token window that forces passage striding.
- **Clean-export long-context:** ModernBERT-large / Ettin-encoder-400M — native
  8k context (all assembled passages in one pass), standard attention + RoPE that
  quantizes and exports cleanly, GLUE lineage comparable to DeBERTa-large. Cost:
  no public SQuAD2 / multi-hop fine-tune with reported numbers exists, so the
  fine-tune must be produced and validated in-house, and ModernBERT has a
  documented QA fine-tuning instability (LR sensitivity, occasional NaN loss) to
  control with an LR sweep, multiple seeds, and FP32 fine-tuning.

**Multi-task heads (both families):** span start/end **+ a 3-way answer-type head
(yes / no / span)** — required for comparison questions that have no extractable
span — **+ a per-sentence supporting-fact classifier**. Structure markers before
passage titles and sentences; passages concatenated in retrieved-hop order;
answer aggregation as a global argmax over the concatenated context; SQuAD2-style
null-score margin (thresholded on dev) for abstention.

**Feasibility, stated honestly.** With near-oracle retrieval, purely extractive
DeBERTa-class readers reach **2Wiki 88.5 EM / 90.9 F1** and **HotpotQA 72.7 EM /
85.0 F1** (published). MuSiQue-Ans is harder: the best comparable extractive
result is ~69.2 F1 (2024), a 2026 method reports ~71.2 F1 with a 32B reasoner and
a different configuration, human average is ~78 F1, and the estimated human upper
bound is ~88.6 F1. MuSiQue ≥0.85 is therefore **not an established result** and is
treated as a pursued research stretch, not a pass/fail gate (§8.1). This is a
statement about the current state of the field, not a limit we accept for the
architecture.

### 7.2 Cross-encoder reranker (≤150M)

Bakeoff anchored on **Ettin-reranker-68M** (beats the 568M bge-reranker-v2-m3 at
~1/8 the size; clean ONNX INT8 ~70 MB), with -150M as the quality rung and -32M
as the latency rung. All are ModernBERT-architecture → clean INT8 export.

### 7.3 Embedding model (≤150M)

Bakeoff anchored on **IBM granite-embedding-english-r2** (149M, 768-dim; beats
same-size BGE/E5/Arctic and some larger models), with gte-modernbert-base and
snowflake-arctic-embed-m-v1.5 (Matryoshka) as comparators, and
potion-retrieval-32M (static) as an optional ultra-cheap pre-filter tier. This
component replaces the current PyTorch+torch embedding service (a ~1–2 GB
consumer) in **every** deployment, so it is a shared win, not an 8 GiB-only
change.

**Dimension decision (explicit, resolved in the sub-spec, not assumed here).** No
≤150M model emits native 1024-dim; the schema is currently 1024-dim. Options, to
be decided by measured retrieval quality and migration cost: (a) re-embed the
corpus at 768-dim (cleanest; preferred pending a quality check), (b) adopt a
335M/1024-dim model and spend more of the artifact budget, or (c) zero-pad 768→1024
(cosine-preserving but wastes 25% of the vector store). Matryoshka slices *down*,
not up, so it does not reach 1024 from 768.

### 7.4 Quantization — measured, never assumed

INT8 dynamic quantization loss is model-, layer-, and calibration-dependent and is
**not accepted as a universal constant.** BERT/RoBERTa-class span models typically
lose ~0.5–1.5 F1, but on AVX2-only CPUs (no VNNI) the u8s8 kernel can saturate and
drop sharply unless `reduce_range=True` (7-bit weights) or U8U8 is used. No public
study isolates INT8 impact on **no-answer calibration** specifically, so the
null-vs-span margin shift under quantization is **measured directly** on our dev
set. Reference FP32 → ONNX FP32 → promoted ONNX INT8 must pass the exact
span/abstention parity contract (§7.5) before promotion; the "≤1 F1 loss" figure
is a target to verify, not a premise.

### 7.5 Serving runtime and the parity contract

**Runtime.** ONNX Runtime via Rust `ort` (pykeio/ort): identical MLAS INT8 kernels
to Python onnxruntime (same quality/latency) but ~100 MB baseline instead of a
~2 GB Python framework baseline — decisive under the process-tree cap. One shared
`Arc<Session>` across threads (never one-session-per-worker). Memory discipline:
**disable the CPU memory arena** (it grows greedily and never returns memory — the
single biggest lever) or configure a shared allocator across the three sessions;
export weights as aligned external data and **mmap** them (shared across
processes, evictable, not counted as private commit); spawn, do not fork, workers;
`intra_op_num_threads` = physical cores, inter_op = 1, spinning disabled for a
sidecar; INT8 tuned for AVX2 (`per_channel` + `reduce_range`), benchmarked on the
oldest target SKU.

**Parity contract (the no-trade-off enforcement).** The 8 GiB profile and the
server load the same frozen artifacts and run the same code path; the acceptance
gate requires **exact decoded spans and identical abstention decisions** across
the reference implementation, ONNX FP32, and promoted ONNX INT8, and across every
supported execution provider. Byte-level tensor identity is recorded **only where
measured**; it is not claimed as a prerequisite without evidence.

### 7.6 Synthesis — deterministic first, constrained generation only if required

First preference is **no model at all**: composition over extracted spans
("how many years between X and Y") is deterministic arithmetic / date
normalization computed in the sidecar. Only if a real free-text composition gap
remains after the extractive rail and the deterministic step does an additive,
preregistered compact generator rung (candidate: LFM2-350M, ~230 MB Q4; Qwen3-0.6B
as the safe-ecosystem alternative) enter under the *same* quality, custody, and
physical-resource gates, with **constrained decoding + mandatory span-alignment
validation**: every output token must align to provided spans or the system falls
back to extractive output. The generator never becomes the default rail.

### 7.7 Distillation recipe (for the in-house reader fine-tune)

The strongest 2025–2026 template is pointwise MSE regression on raw teacher
logits (the recipe that recovered ~99.6% of teacher quality for a 400M reranker
student). For the span reader: (1) soft-label span KD (temperature-scaled KL / MSE
on start/end logits) + hard gold spans; (2) a custody-approved LLM teacher answers
multi-hop questions over **TRAIN-only decontaminated** corpora, aligned back to
evidence to produce hard span labels + confidence for filtering; (3) no-answer
calibration transfer via teacher-labeled unanswerable examples at ~1:1 with
answerable, then a post-hoc null-margin threshold on dev (post-hoc calibration and
split-conformal risk control give distribution-free abstention guarantees);
(4) data scale ~130k–250k real pairs augmented with teacher-generated multi-hop
pairs. Off-host training still requires a digest-pinned environment,
secrets/cost/timeout controls, retained manifests, and explicit spend authority
(carried from the 8 GB spec B3); it is not authorized by this document.

---

## 8. Benchmark program (the path to per-category world-best)

No single averaged score defines success. Each benchmark family is wired as a
neutral-harness adapter (Plan B), run under a frozen protocol with the exact
dataset version pinned, and reported per competency.

### 8.1 Static multi-hop QA (evaluates the answering plane, §7)

| Benchmark (frozen version) | Parity gate (reproduce) | Stretch (pursued, not gated) |
|---|---|---|
| 2WikiMultihopQA | ≥88.47 EM / ≥90.87 F1 | improve while preserving support-fact accuracy |
| HotpotQA (distractor) | ≥72.69 EM / ≥85.04 F1 | push EM toward human ≈83; do not lower support-fact accuracy |
| MuSiQue-Ans | ≥69.2 answer F1 (reproduce comparable baseline) | ~0.72–0.75 under a frozen comparable protocol; pursue toward human upper bound ≈88.6 — **not a pass/fail gate** |

### 8.2 Memory-system benchmarks (evaluate the platform)

| Capability | Benchmark | Gate |
|---|---|---|
| Personal conversational recall | LongMemEval-S (cleaned; version pinned) | ≥86% initial · 90% strong · 94% frontier — engineering tiers, not SOTA declarations |
| Agent-experience memory | LongMemEval-V2 | ≥72.5% at lower latency than the strongest baseline |
| General memory competencies | MemoryAgentBench | beat the best reproduced baseline in **each** of the 4 competencies (retrieval, test-time learning, long-range understanding, conflict resolution); report separately — conflict resolution is ~6–14% field-wide and is a target to lead |
| Updates / invalidation / forgetting | Memora / FAMA | beat released baselines at weekly / monthly / quarterly horizons (**aligned with Mnemosyne's supersession strength**) |
| Extreme scale | BEAM-1M / BEAM-10M | ~≥75% / ~≥65% under a fixed answerer + judge; demonstrate no quality collapse as history grows |
| Deferred intentions | PM-Bench (+ TriggerBench) | ≥65.1 F1 (requires the §6 engine) |
| Action-oriented / experience improvement | MemoryArena · STATE-Bench · AFTER | demonstrate positive memory-driven improvement; procedural transfer without over-specialization |
| Multi-user / permissions | GroupMemBench · GateMem | preserve utility + access control + deletion simultaneously |

### 8.3 Cross-cutting correctness (reported separately, never averaged in)

- Stale-memory usage: reported separately; target < 5%.
- Deletion compliance: 100% on deterministic deletion/cascade tests, with a
  signed deletion manifest enumerating every affected object and verifying removal
  across raw + derived + index + summary + cache + procedure + retention-bound
  backup tiers (raw-only deletion is insufficient).
- Evidence provenance: 100% of durable factual answers linked to stored evidence.
- Abstention: measure precision **and** recall; never reward guessing.

### 8.4 Harness, disclosure, and reproducibility (PBPP, unchanged)

Every public number is produced by the pinned `eval/public/` neutral harness on
the **full production stack**, ships the complete artifact bundle, reports
retrieval-recall and LLM-judged QA in **separate columns** with judge model +
prompt disclosed and the judge's acceptance rate on intentionally-wrong-but-topical
answers reported, is never conflated with the private suite, discloses the
executed engine/model/custody **byte-for-byte** (the current
`postgres-recursive-ppr`-vs-local disclosure mismatch is audited and corrected),
and is genuinely reproduced by an independent third party through the human-owned
M3 process before any external claim. The self-reported 92–96% figures from some
commercial systems are treated as unreproduced until independently reproduced
under this harness; reproducibility is the axis on which the neutral leaderboard
wins.

---

## 9. The 8 GiB no-trade-off budget (concrete, no corner cut)

The floor envelope (carried from the 8 GB spec): ≤1 GiB model/tokenizer artifacts,
≤3 GiB compact-sidecar peak, ≤6.5 GiB whole process tree, ≥1.5 GiB system-available
throughout. The **full platform** fits it:

| Component | Peak RAM (target, measured at acceptance) | Notes |
|---|---|---|
| ONNX artifacts (reader + reranker + embedder, INT8) | ≤1.0 GiB | reader ~400 MB + reranker ~70 MB + embedder ~150 MB + tokenizers; mmap'd, shared, evictable |
| Rust `ort` sidecar peak (arena disabled) | ≤2.0 GiB | batch-1; long reader passes serialized |
| SqliteEngine store + FTS5 + vector/graph working set | ~1.0–1.5 GiB | corpus on disk, not RAM |
| Memory core (gateway · consolidation · retrieval · full taxonomy incl. working + prospective) | ~1.0 GiB | deterministic Python/Rust; small tables + evaluator |
| Optional constrained generator rung | ~0.3 GiB | only when composition truly required |
| System-available floor | ≥1.5 GiB | held throughout the exact-scale workload |
| **Total on an 8 GiB machine** | **≤7 GiB** | full platform, every plane, every rail |

The two new planes (§5, §6) add near-zero footprint. Extreme-scale corpora are
disk-backed, so 8 GiB bounds the working set, not the corpus. A 2–2.5 GiB process
target is an optimization goal, not accepted evidence — actual residency, memory
pressure, GPU placement (none required), context, and swap delta at exact scale
decide viability (COMPACT-MODEL-8GB-ACCEPTANCE, unchanged).

**Efficiency gates for the 8 GiB product:** total peak resident ≤7 GiB;
memory/QA sidecar peak ≤2 GiB; retrieved answer context ≤~1,500 tokens median;
retrieval p95 ≤2 s; end-to-end p95 ≤5 s; accuracy loss vs. full-precision
reference ≤1 F1 (measured, per §7.4); exact evidence-recall parity vs. the server;
identical frozen artifacts on compact and server when claiming parity.

---

## 10. Deployment profiles and acceptance criteria

### 10.1 Two profiles, one system

- **8 GiB single-node product (C1, the floor):** no-VM deployment on SqliteEngine
  + compact ONNX sidecar + local encrypted key management + loopback/unix-socket
  defaults + unchanged audit/provenance/security semantics. This is the product
  for end users and the profile on which "runs on 8 GiB" is proven.
- **Multi-tenant server:** the existing self-hosted stack (Postgres + pgvector,
  Keycloak, Vault, SeaweedFS, Caddy, step-ca, observability), providing
  replication, horizontal workers, larger indexes, higher concurrency, distributed
  object storage. Same schemas, same memory policies, **same frozen model
  artifacts**, same retrieval and conflict-resolution algorithms.

**Parity claim (exact wording):** given the same memory state, model versions, and
retrieval configuration, the compact and server deployments produce equivalent
ranked evidence and equivalent answers. Server hardware increases throughput,
corpus scale, and concurrency — not answer quality.

### 10.2 Acceptance criteria

**Hard correctness gates (all must hold):**
- 100% tenant and user isolation under adversarial tests.
- 100% evidence provenance for durable factual memories.
- 100% deterministic time-trigger execution when infrastructure is available.
- 100% verified cascade deletion in controlled tests (signed deletion manifest).
- User corrections affect the next retrieval; no obsolete fact is presented as
  current when a newer authoritative fact exists.
- Full memory reconstruction from canonical episodes; indexes deletable and
  rebuildable without data loss.
- Procedures support versioning and rollback; no promotion to trusted skill on a
  single successful trajectory.
- Every durable memory has a source and a creation reason; inferred facts are
  visibly distinguished from user-stated facts; untrusted content is never
  silently promoted to authoritative.

**Quality gates (per §8; per-category, no hidden average):** reproduce or exceed
the frozen published baseline on each static QA set; ≥86% LongMemEval-S initial;
≥72.5% LongMemEval-V2; beat reproduced baselines in **every** MemoryAgentBench
competency; beat Memora/FAMA baselines at all three horizons; positive memory-driven
improvement on MemoryArena/STATE-Bench; ≥65.1 PM-Bench; every category reported
independently.

**Operational gates:** crash-safe idempotent ingestion; point-in-time recovery;
versioned schemas and models; rolling index rebuilds; bounded queue backlogs;
auditable corrections and deletions; defined latency and memory SLOs; chaos testing
for worker/database/index failures.

**8 GiB efficiency + parity gates (§9):** the floor envelope held at exact scale;
byte-parity of decoded spans and abstention decisions across reference/FP32/INT8
and all providers; identical frozen artifacts across profiles.

**Integrity gates (PBPP, §8.4):** neutral-harness production-stack numbers only;
disclosure equals execution byte-for-byte; separate recall/QA columns with judge
diagnostics; independent third-party reproduction before any external claim.

---

## 11. Workstream decomposition (dependency-ordered; each → its own spec)

This master design decomposes into five sub-projects. Each gets its own
spec → plan → build cycle; none may weaken a §31/§33 rail, the custody protocol,
or PBPP.

1. **W1 — Substrate fix (in flight).** Populate and use the graph channel
   (run consolidation before search; broaden the deterministic extractor); prove
   positive graph participation and lifted Recall@5 on the dev fixture + 16-case
   matrix; correct the disclosed-vs-actual engine mismatch. *Owner: the running
   autonomous loop. Blocks everything.*
2. **W2 — Harvest unmeasured strengths.** Wire Memora/FAMA (supersession),
   deletion-residue/leakage tests (crypto-shred), and AFTER/STATE-Bench
   (procedural) adapters; report the aligned strengths. *Fast capability wins.*
3. **W3 — Complete the taxonomy.** Build the working-memory plane (§5) and the
   deterministic prospective-memory trigger engine (§6), with cross-engine parity
   and PM-Bench/TriggerBench + action-oriented coverage.
4. **W4 — Full neutral adapter suite.** LongMemEval-V2, MemoryAgentBench, BEAM,
   LoCoMo, PM-Bench, MemoryArena, STATE-Bench, GroupMemBench/GateMem under one
   harness with per-competency reporting and reproducible bundles (Plan B M/L).
5. **W5 — Compact answering plane at parity.** The ONNX Rust sidecar (§7): the
   reader bakeoff, the embedder replacement (server + compact), quantization
   measured, distillation, and the byte-parity contract — delivering the 8 GiB
   product profile and the multi-hop QA numbers.

**Mapping to the existing GSD roadmap and requirements (so this is not a parallel
track).** These workstreams overlay the live `.planning/` roadmap rather than
replacing it: W1 completes Phase 12 (Plan 12-04; CAP-001/002/003, BENCH-005). W2
and W3 land in Phase 15 (CAP-007..010 for consolidation/sensemaking/procedural,
and two additive requirements this design introduces — *prospective memory* and
*working memory* — to be added to `.planning/REQUIREMENTS.md` as CAP-012/CAP-013
when their sub-specs are authored). W4 is Phase 13 (BENCH-006/007) plus the new
adapter families, feeding Phase 14 reproducibility (REPRO-001/002) and Phase 16
leaderboard (LEAD/GOV). W5 is Plan A S1.2 / S4.5 and CAP-011 (the compact 8 GiB
path). No new requirement silently changes a frozen threshold; each is added to
the ledger through the normal GSD flow with its own traceability test.

W1 blocks all measurement. W2 and W3 can proceed in parallel after W1. W4 depends
on the adapters each capability needs (W2/W3 supply some). W5 delivers the
answering plane and 8 GiB profile and can proceed in parallel once W1 lands, but
its headline numbers depend on W1's retrieval fix. Human-owned governance,
independent reproduction, and public wording remain gates on any external claim
throughout.

---

## 12. Risks and honest unknowns (unbiased)

- **MuSiQue ≥0.85 is not established** by any comparable published result and may
  not be reachable under a frozen comparable protocol; it is pursued as a stretch,
  never gated. Treating it as a pass/fail gate would make Phase 12 uncloseable and
  would read externally as an impossible claim. (This corrects an earlier
  overstatement in program discussion that framed it as physically impossible; the
  accurate statement is "not established," with human upper bound ≈88.6.)
- **The reader fine-tune must be produced in-house** for the long-context family
  (no public ModernBERT-large/Ettin-400M SQuAD2/multi-hop fine-tune with reported
  numbers exists), and ModernBERT has a documented QA fine-tuning instability to
  control. The bakeoff exists precisely to de-risk this.
- **Quantization loss and no-answer-calibration shift under INT8 must be measured**
  (no public study isolates the calibration effect); the ≤1 F1 target is to verify.
- **Component-level SOTA-at-size does not prove the *combination* is SOTA** on
  memory or multi-hop QA; only the controlled end-to-end bakeoff establishes it.
- **Benchmark protocols and dataset versions vary** (LongMemEval was re-cleaned;
  MuSiQue-Ans vs MuSiQue-Full differ); every target is pinned to an exact version
  and protocol, and competitor numbers are treated as unreproduced until run under
  our harness.
- **Some benchmarks may be in genuine tension** (isolated-retrieval vs holistic
  understanding); the full taxonomy is designed to answer from different planes to
  avoid forcing a single-configuration compromise, but this must be demonstrated,
  not assumed.
- **Extreme-scale (BEAM-10M) on 8 GiB is latency-bound, not quality-bound** — this
  is the intended behavior (hardware buys wall-clock, not answers), but end-to-end
  runs must confirm no working-set overflow or quality collapse.
- **Dependency and footprint discipline:** the Python core stays minimal (only
  required dep `cryptography`); the compact stack lives behind optional
  extras / `services/` / Rust sidecars; no ML dependency enters the core.

---

## 13. What this document does not change

The §31 invariant rails and §33 test classes; the hardware-admission runbook and
its work-class tiers; the Phase 12 candidate protocol; preregistration,
one-attempt-per-protected-split, once-ever held-out runs, TRAIN-only decontaminated
corpora, and digest pinning; PBPP; the human-owned governance / independent-
reproduction / public-wording / publication boundaries. This design authorizes
implementation planning of the workstreams in §11, not a benchmark result, an
8 GiB-compatibility claim, or any public claim.

---

## 14. Definition of done for this specification

This spec is complete when: the full-platform architecture (§4) with the two new
planes (§5, §6) and the compact answering plane (§7) is specified; the no-trade-off
guarantees (§1) each have a concrete enforcement mechanism (parity contract §7.5,
budget §9, disk-backed scale §1.3, integrity rails §8.4); the per-benchmark
protocol-frozen target contract (§8) is stated with parity gates and pursued
stretches; the acceptance criteria (§10.2) are per-category with no hidden average;
the workstream decomposition (§11) is dependency-ordered with each sub-project
scoped to its own spec; and the risks/unknowns (§12) are stated without bias. It
does not require any benchmark to have been run. Sub-project specs are authored
next, beginning with the first unblocked workstream.
