# Mnemosyne — A Recursive, Self-Improving Memory Architecture for AI Agents

**Comprehensive Design Specification — v1.0**

> *Codename "Mnemosyne" (after the Greek titaness of memory, mother of the Muses); short handle **Mneme**. The name is a placeholder you can rename.*

This document specifies the design of a unified agent-memory system that takes the best ideas from GBrain and MemPalace, the broader academic literature, and every credible production system, and combines them into a single architecture that is **self-improving, self-learning, self-adapting, and self-optimizing**, with **lossless recall** and **high-precision retrieval** at the same time. It is grounded in a deep research pass across cognitive science, the RAG/retrieval literature, the self-improving-agent literature, and ~20 real systems (open-source and commercial); the load-bearing claims are cited, and vendor marketing is flagged as such.

---

## Table of contents

0. [Executive summary](#0-executive-summary)
1. [Goals, definitions, and the central tension](#1-goals-definitions-and-the-central-tension)
2. [Research foundations (condensed)](#2-research-foundations-condensed)
3. [Core architectural principles](#3-core-architectural-principles)
4. [System overview and data flow](#4-system-overview-and-data-flow)
5. [The memory stores (the substrate)](#5-the-memory-stores-the-substrate)
6. [Ingestion and the write path](#6-ingestion-and-the-write-path)
7. [The retrieval engine](#7-the-retrieval-engine)
8. [The recursive self-improvement system](#8-the-recursive-self-improvement-system)
9. [The user model (personalization)](#9-the-user-model-personalization)
10. [Forgetting and the memory lifecycle](#10-forgetting-and-the-memory-lifecycle)
11. [Security and governance](#11-security-and-governance)
12. [Storage and infrastructure stack](#12-storage-and-infrastructure-stack)
13. [Agent-facing API and MCP tools](#13-agent-facing-api-and-mcp-tools)
14. [Evaluation and observability](#14-evaluation-and-observability)
15. [Phased build roadmap](#15-phased-build-roadmap)
16. [How Mnemosyne surpasses its predecessors](#16-how-mnemosyne-surpasses-its-predecessors)
17. [Hard parts, resolutions, and honest limitations](#17-hard-parts-resolutions-and-honest-limitations)
- [Appendix A — Reference SQL schema](#appendix-a--reference-sql-schema)
- [Appendix B — Key algorithms](#appendix-b--key-algorithms)
- [Appendix C — References](#appendix-c--references)
- [Appendix D — Glossary](#appendix-d--glossary)

---

## 0. Executive summary

**The thesis.** A great memory system is not one big vector database, and it is not a literal merger of two codebases. It is an **event-sourced, multi-store memory operating system** with two fundamental layers — an **immutable evidence layer** (everything that was actually said, done, or observed, stored verbatim and never *silently* destroyed — only superseded, decayed in salience, or, for explicit user/legal erasure, crypto-shredded; §17.3) and a set of **derived, rebuildable memory projections** (current facts, relationships, preferences, skills, and lessons compiled from that evidence). Over those layers run a **high-precision retrieval engine** and a **three-timescale recursive learning loop** that lets the system improve itself without corrupting what it knows.

This maps cleanly onto three independent bodies of knowledge that all point at the same shape:

- **Software architecture:** Command-Query Responsibility Segregation (CQRS) + Event Sourcing — an append-only event log plus read-optimized projections that can be rebuilt at any time.
- **Neuroscience:** Complementary Learning Systems theory — a fast, one-shot **hippocampal** store (episodes) plus a slow, generalizing **neocortical** store (semantics), linked by **replay-driven consolidation** (McClelland et al. 1995; Kumaran, Hassabis & McClelland 2016).
- **The two parents:** MemPalace contributes the **lossless, verbatim episodic layer**; GBrain contributes the **compiled current truth + hybrid retrieval + entity graph + "human always wins" source-of-truth** discipline.

**The five "self-*" properties, made concrete.** Each is a specific mechanism, not an aspiration:

| Property | Mechanism in Mnemosyne |
|---|---|
| **Self-learning** | Consolidation promotes recurring episodes into semantic facts, induces reusable workflows from successful trajectories (Agent Workflow Memory), and distills lessons from failures (Reflexion / ExpeL). |
| **Self-adapting** | A dedicated user model learns explicit + inferred preferences with scope, confidence, and validity; behavior adapts per-context and is always user-overridable. |
| **Self-improving** | Every important task is logged as a trajectory; failures are diagnosed; candidate lessons/skills are validated on a held-out regression suite before promotion, and are reversible. |
| **Self-optimizing** | A slow meta-loop learns the system's *own* policies — retrieval routing, ranking weights, write decisions (ADD/UPDATE/DELETE/NOOP), consolidation cadence — against measured outcomes (Memory-R1-style), gated and versioned. |
| **Recursive** | Memory operates on memory: reflections can be reflected upon, skills compose skills, and the policy that manages memory is *itself* stored as procedural memory and improved by the same loop — around an **immutable outer invariant** (the reward, verifier, and safety rules can never be self-edited). |

**Resolving "complete recall AND retrieval at the same time."** These pull in opposite directions, and the literature is decisive that stuffing everything into context *degrades* quality ("lost in the middle," "context rot," "the power of noise"). Mnemosyne resolves the tension by **separating the layer at which each guarantee lives**:

- **Completeness lives in storage.** The evidence ledger is append-only and lossless — nothing important is ever deleted, only superseded, decayed in salience, or compacted with a pointer back to the original. Total recall is a *storage* guarantee.
- **Precision lives in retrieval.** The retrieval engine assembles the *smallest, highest-signal* context for each task. A **deep investigative mode** can exhaustively traverse the evidence when completeness is actually required, so "I can always get the exact original back" holds without ever dumping it by default.

**Headline design decisions** (each defended later and traced to a source):

1. **Event sourcing + CQRS** over a single mutable store. Evidence is immutable; all derived memory is a rebuildable projection (§3, §5).
2. **Nine typed memory stores**, not one blob — working, episodic, semantic, temporal-graph, procedural, preference, corrective, resource, meta (CoALA taxonomy extended; §5).
3. **Bi-temporal facts and edges** — every fact carries *valid time* (true in the world) and *transaction time* (known to the system); change closes an interval and opens a new one; nothing is overwritten (Zep/Graphiti; §5–6).
4. **Activation-based retrieval scoring** — a principled `base-level + spreading + importance + recency` score (ACT-R; Generative Agents) over a **hybrid** dense+lexical+graph channel set, fused by RRF, cross-encoder-reranked, MMR-deduplicated, and ordered against the U-curve (§7).
5. **Three recursive learning loops** at three timescales (hot/intra-task, warm/sleep-time consolidation, cold/meta-optimization), each with a **validation gate and rollback**, around an **immutable outer invariant** (§8).
6. **Postgres-centric core with a pluggable engine contract** — one canonical battle-tested path (Postgres + pgvector + BM25 + graph + object storage), with adapters to swap in specialized stores (Qdrant/Neo4j/OpenSearch) per-component at scale (§12).
7. **Memory treated as a credential-grade control surface** — per-tenant/per-source isolation, provenance/trust tiers, data-never-executed-as-instruction, write-gating, and sanitization on retrieval (§11).

**What is genuinely novel** is not any single component (each is borrowed from the best available source) but the **integration**: a lossless evidence spine, multiple rebuildable projections, an activation-scored hybrid retriever, and a *recursive* learning system that improves both the content of memory and the policies that manage it — all under a safety invariant and a strict provenance/versioning discipline. §16 makes the "best of everything" mapping explicit.

---

## 1. Goals, definitions, and the central tension

### 1.1 What you asked for, stated precisely

Build the best possible memory system that:

- combines the strengths of GBrain (structured, compiled knowledge + hybrid retrieval + entity graph) and MemPalace (lossless verbatim episodic recall + hierarchical scoping);
- has **full, complete memory** (nothing important is ever lost) **and** excellent **recall/retrieval** (the right thing surfaces at the right time);
- is **self-improving, self-learning, self-adapting, self-optimizing**, and **recursive**;
- learns from **its own mistakes** and **the user's mistakes**, and improves over time;
- adapts to the **user's preferences and context**, cleanly and reversibly;
- updates its memory over time **without corrupting** what it already knows;
- is **eclectic** — takes the best features of every kind of memory system, with no compromises;
- works both **local-first for a single user** and **scaled to multi-tenant production**.

### 1.2 Definitions (so the "self-*" words mean something)

- **Memory** = any information the system persists beyond the current model call. Subdivided into nine typed stores (§5).
- **Recall** (completeness) = the guarantee that information, once ingested, can always be retrieved exactly — a property of the **storage** layer.
- **Retrieval** (precision) = selecting and ordering the minimal high-signal subset for a given task — a property of the **query** layer.
- **Self-learning** = acquiring new durable knowledge/skills from experience with no human authoring.
- **Self-adapting** = changing behavior to fit the user/context, reversibly and with provenance.
- **Self-improving** = measurably increasing task performance over time via validated changes to memory.
- **Self-optimizing** = improving the system's *own* internal policies (retrieval, ranking, write/forget decisions, cadence) against measured outcomes.
- **Recursive** = the system's improvement machinery applies to itself: memory about memory, skills that build skills, and a self-editable management policy — bounded by an **immutable outer invariant**.

### 1.3 The central tension and its resolution

"Complete memory + complete retrieval" is internally contradictory if read as "always retrieve everything." Three robust findings forbid it:

- **Lost in the Middle** (Liu et al. 2023): accuracy is U-shaped in the position of the needed fact and *degrades as total context grows*.
- **Context Rot** (Chroma 2025): across 18 frontier models, performance declines with input length *even on trivial tasks*, well before the window is full.
- **The Power of Noise** (Cuconasu et al., SIGIR 2024): related-but-wrong passages — exactly what a high-recall retriever surfaces — are the *most damaging* distractors.

**Resolution (the architecture's hinge):** put **completeness in storage** and **precision in retrieval**.

```
                COMPLETENESS                          PRECISION
        (storage-layer guarantee)            (query-layer guarantee)
   ┌────────────────────────────────┐   ┌────────────────────────────────┐
   │ Append-only evidence ledger.    │   │ Per task: assemble the smallest │
   │ Nothing important deleted —     │──▶│ ordered, deduplicated, high-    │
   │ only superseded / decayed /     │   │ signal context. Deep mode can   │
   │ compacted with a pointer back.  │   │ exhaustively traverse evidence  │
   │ "Total recall" = always         │   │ when completeness is required.  │
   │ reconstructable.                │   │ "Precision" = right thing, now. │
   └────────────────────────────────┘   └────────────────────────────────┘
```

This is exactly how human memory works: experience is encoded richly, but recall is reconstructive, cue-driven, and selective (Tulving & Thomson 1973). It is also how the two parents already split the world — MemPalace keeps verbatim drawers; GBrain compiles current truth — and Mnemosyne keeps **both**, with a bridge between them.

### 1.4 Non-goals

- **Not** a new foundation model. Mnemosyne is the memory/retrieval/learning substrate *around* whatever model(s) you use; it deliberately makes a mid-tier model behave like a much stronger one on knowledge-, context-, and personalization-heavy tasks (the original transcript's premise, which the literature supports).
- **Not** weight-level fine-tuning by default. Learning lives in memory, prompts, and skills (the CoALA "procedural memory" surface). Weight-level options (LoRA fast-weights, test-time training) are an optional advanced tier (§8.6), never the default path.
- **Not** dependent on any single vendor benchmark score for its design (the benchmark layer is demonstrably unreliable — §2.5, §14).

---

## 2. Research foundations (condensed)

This section distills the research that drives the design. Citations use author/year; full URLs are in Appendix C. Claims from vendor papers are marked **[vendor]**; figures not independently reproduced are marked **[unverified]**.

### 2.1 Cognitive science — the blueprint nature gave us

- **Memory is plural, not monolithic.** Humans have working, episodic, semantic, and procedural memory (Tulving 1972; Squire 2004). Each has different write rules, retention, and retrieval. **Design implication:** typed stores (§5), not one undifferentiated index.
- **Complementary Learning Systems (CLS)** (McClelland, McNaughton & O'Reilly 1995; updated for AI by Kumaran, Hassabis & McClelland 2016). The brain needs *two* systems because fast learning and stable generalization conflict (catastrophic interference). The hippocampus encodes episodes in one shot; the neocortex slowly extracts structure by **replaying** episodes offline and **interleaving** them with old knowledge. Replay is **prioritized** by reward/novelty/surprise. **Design implication:** a fast episodic store + a slow semantic store + an **offline consolidation job with prioritized replay** (§8.2) — the single most important pattern in the system.
- **Forgetting is a feature.** The Ebbinghaus curve is an exponential/power-law decay modulated by strength; modern work treats adaptive forgetting as essential for handling non-stationary worlds and reducing interference (Wang et al. 2024). **Design implication:** a decay/salience score on every memory; scheduled pruning; supersession over deletion (§10).
- **Retrieval is reconstructive and cue-dependent.** Spreading activation through an associative network (Collins & Loftus 1975), encoding specificity (Tulving & Thomson 1973), and **reconsolidation** — recall returns a memory to an editable state and re-stores it. **Design implication:** store rich encoding context; retrieve by similarity **+ graph activation + recency + importance**; make recall a **read-write** operation that can boost or correct a memory (§7.4, §8.1).
- **ACT-R's activation math** (Anderson & Schooler 1991) gives a *principled, tunable* retrieval score: `activation = base-level (frequency + power-law-decayed recency) + spreading activation (relevance via associative links) + noise`, with the rational interpretation that activation tracks the **need probability** — how likely this item is useful *right now*. **Design implication:** a real scoring function (§7.4), not bare cosine similarity, with a justified decay parameter and an expected-gain stopping rule for top-k.
- **CoALA — Cognitive Architectures for Language Agents** (Sumers, Yao, Narasimhan & Griffiths 2023). The canonical mapping of cognitive architecture onto LLM agents: four memory modules (working/episodic/semantic/procedural), an action space split into **internal** (retrieve, reason, learn) and **external** (grounding) actions, and a **propose→evaluate→select** decision cycle where **planning is read-only and execution is the only mutating phase**. Its sharpest claim: **the agent's own prompts/policy are procedural memory**, so self-editing prompts *is* procedural learning. **Design implication:** CoALA is the skeleton of the whole system (§4, §8).

### 2.2 Retrieval — what actually works

- **Hybrid beats either half.** Dense vector search (semantics) + lexical BM25/SPLADE (exact terms, names, IDs) fused by **Reciprocal Rank Fusion** (`score(d) = Σ 1/(k + rank_r(d))`, k≈60; Cormack et al. 2009), which is robust precisely because it ignores incomparable score scales. **Tuned convex fusion** can beat RRF if you can tune per-domain (Bruch et al. 2022).
- **Rerank narrow, retrieve wide.** A cross-encoder over the top 50–200 candidates → keep top 3–5. First-stage recall sets the ceiling; reranking recovers more when the retriever is weak. LLM listwise reranking (RankGPT) is best for zero-shot/novel domains.
- **Graph retrieval for multi-hop and themes.** HippoRAG/HippoRAG2 (Personalized PageRank over a knowledge graph — single-step multi-hop, cheap to update) and GraphRAG (community summaries for global sensemaking, but expensive to update). **For mutable memory, HippoRAG's "just add edges" and LightRAG's "union-merge" updates are the right primitives; GraphRAG's re-summarization is the wrong one.**
- **Bi-temporal knowledge-graph memory** (Zep/Graphiti **[vendor]**): model *valid time* vs *transaction time*; on contradiction, close the old edge's validity interval and add a new edge — never overwrite. This is the most durable single decision for handling change; its LongMemEval gains on temporal/cross-session reasoning are the credible part of its numbers.
- **Chunking: restraint wins.** Tuned recursive (~200 tokens, minimal overlap) is a strong default; **late chunking** (embed the whole doc, then pool per chunk) is the best low-cost upgrade; proposition/semantic/LLM chunking rarely justify their cost (Chroma 2024; Jina 2024).
- **Hierarchical synthesis:** RAPTOR (recursive summary tree, "collapsed-tree" retrieval) for multi-hop/thematic recall; **small-to-big** (match on small chunks, return the parent) is the cheapest high-leverage upgrade over naive RAG.
- **Context engineering** (Anthropic 2025): the retriever's job is to assemble the *smallest* high-signal context — compaction, structured note-taking, just-in-time hydration, sub-agent isolation.

### 2.3 Self-improvement — how agents get better without retraining

- **External validation is the gate to memory.** Reflexion (verbal self-reflection stored and replayed), Self-Refine (intra-task iteration), and especially **CRITIC** (Gou et al. 2023) — whose ablation shows self-critique *without tools* barely helps — converge on one rule: **never let the model self-certify what enters durable memory; validate with tools/ground truth.**
- **Typed experiential memory.** ExpeL (cross-task insights + retrieved success trajectories, with **vote-count decay** as a cheap validation primitive), Generative Agents (importance-scored memory stream + accumulation-triggered **reflection** that cites sources), and **Agent Workflow Memory** (induce reusable, abstracted **workflows** from successful trajectories — +51% on WebArena, gains *widen* out-of-distribution). **Design implication:** store rules, reflections, and workflows as *separate* typed memories, each validated differently (§8).
- **Skills as composable code.** Voyager's growing **skill library** (executable code keyed by description embeddings, each gated by self-verification) is the procedural-memory backbone; new skills compose old ones; the library only grows (its antidote to forgetting).
- **Recursive self-improvement, safely.** STOP, Gödel Agent, and Promptbreeder show a system can improve its own scaffolding/prompts (even *self-referentially*). But STOP also empirically showed models writing code to **disable their own sandbox** (0.42% of GPT-4 runs), and Anthropic's reward-tampering work showed models generalizing to **edit their own reward and the tests that would catch it**. **Design implication:** make the meta-level editable for ceiling, but **freeze an outer invariant** (reward, verifier, safety rules, the substrate you can't validate) and enforce it *structurally*, not by instruction (§8.5, §11).
- **Explicit write operations + learned policies.** Mem0's `{ADD, UPDATE, DELETE, NOOP}` is the most reusable write-path vocabulary (auditable, enables dedup + contradiction handling). Memory-R1 learns *which* edits help via RL on downstream correctness. **Design implication:** an explicit, typed, auditable write decision (§6.3), later made a learned policy (§8.4).
- **Sleep-time compute** (Letta 2025): do expensive memory work **offline during idle time**, on a **separate consolidator** that owns memory-write authority while the user-facing agent does not. **Design implication:** the warm loop (§8.2) — and a clean safety split.
- **The dominant failure modes** are reward hacking, **model collapse** from training on one's own outputs (Shumailov et al., Nature 2024 — tails vanish first), and unsafe self-modification. Mitigations: anchor with real/edge-case data, monitor diversity, never auto-promote procedures, keep reward/verifier outside the editable surface, make rollback **transitive** (Layered Mutability shows shallow reverts "ratchet" — derived effects persist).

### 2.4 What to steal from real systems (and what to resist)

**Steal:** bi-temporal validity + verbatim provenance (Zep, MemPalace); explicit write ops, but **ingest both user and assistant turns** (Mem0 drops assistant turns by default — a documented problem); tiered context with token budgets + deterministic priority eviction (LlamaIndex, MemoryOS); a single "heat" signal driving both eviction and promotion (MemoryOS); hot-path vs background consolidation / sleep-time (Letta); **retroactive memory evolution** but with bounded write cost (A-MEM's Zettelkasten notes — its O(N²) write blow-up is the cautionary tale); verbatim content layer + compressed symbolic pointer layer (MemPalace's AAAK); markdown/git as human-editable source of truth with the DB as a derived index, plus **zero-LLM entity extraction** for the graph (GBrain's "human always wins"); hybrid retrieval + per-result **evidence/provenance tags** and `search --explain` (GBrain); the semantic/episodic/procedural taxonomy and **procedural-memory-as-self-rewriting-prompt** (LangMem/CoALA).

**Resist:** brain/OS analogies as *algorithmic* claims (they're mostly metaphor over LLM-orchestrated RAG + bookkeeping); "open source" that hides a closed engine; abandoned projects; and **any architecture decision justified by a vendor LoCoMo number**.

### 2.5 The benchmark-integrity warning (informs §14)

Independent audits found LoCoMo's answer key ~6.4% wrong, the standard LLM judge accepting ~63% of intentionally-wrong vague answers, and both LoCoMo and LongMemEval_S small enough to fit in a modern context window — so a plain full-context baseline (or even *filesystem + grep*, per Letta) can beat "specialized" memory systems. **Design implication:** Mnemosyne is validated against a **private regression suite built from real corrections**, with a strict judge and confidence intervals, measuring the **write path** and **forgetting**, not just retrieval latency (§14).

### 2.6 Security — memory is an attack surface

Persistent memory makes prompt injection *durable*: a single poisoned interaction can re-fire across sessions (now codified as OWASP **ASI06: Memory & Context Poisoning**). **MINJA** (NeurIPS 2025) is the load-bearing result — an *ordinary user* with only a shared memory bank can implant poisoned reasoning (98.2% injection success) with near-zero utility drop. AgentPoison, PoisonedRAG, and demonstrated attacks on production assistants (SpAIware, MemoryTrap) round out the picture. The credible defenses are **architectural, not detection-based**: per-user/source **isolation** (directly nullifies MINJA's only assumption), **provenance/trust tiers + capability tracking** (CaMeL-style), **data-never-executed-as-instruction** + sanitization on retrieval, **write-gating**, and **never injecting untrusted-derived memory into the system prompt** (the MemoryTrap fix). See §11.

---

## 3. Core architectural principles

Ten load-bearing principles. Every later section is an application of these.

1. **Evidence is sacred; everything else is derived.** An append-only, immutable **evidence ledger** records what actually happened (verbatim). Facts, summaries, preferences, graph edges, skills, and lessons are **projections** that must be *rebuildable* from evidence. The one sanctioned exception to immutability is **explicit user/legal erasure**, which is a first-class, audited operation, not a silent delete (§17.3). (Event Sourcing + CQRS; MemPalace verbatim; GBrain raw_data/provenance.)

2. **Two speeds, by design (CLS).** A fast, cheap, one-shot **episodic write** path and a slow, deliberate **semantic consolidation** path. Never make the user wait for consolidation; never let the reactive path do destructive edits.

3. **Typed memory, not a blob.** Nine stores (§5), each with its own representation, write rule, retrieval method, and lifecycle. A raw user statement is *not* automatically a fact, a preference, or part of the user profile — it is evidence until promoted.

4. **Time is first-class and bi-temporal.** Every fact/edge carries **valid time** (true-in-world) and **transaction time** (known-to-system). Change closes an interval and opens a new one. Contradictions are retained until resolved, never silently overwritten.

5. **Completeness in storage, precision in retrieval.** (§1.3.) Lossless evidence; minimal, ordered, deduplicated context; a deep mode that can reconstruct anything on demand.

6. **Retrieval is activation-scored and multi-channel.** Hybrid dense + lexical + graph, fused by RRF, reranked, deduplicated, ordered against the U-curve, and scored by an ACT-R-style `base-level + spreading + importance + recency` function — not cosine similarity alone.

7. **Learning is loop-shaped and validation-gated.** Log trajectory → diagnose → propose candidate (fact/preference/workflow/skill/lesson) → **validate on a held-out regression suite** → promote only if non-inferior with no regression → **versioned and reversible**. No candidate self-certifies.

8. **Recursive, around an immutable invariant.** Memory operates on memory; the management *policy* is itself improvable procedural memory. But the **reward signal, the validator, and the safety/identity rules live outside the self-editable surface** and are enforced structurally.

9. **Memory is a credential-grade control surface.** Per-tenant/per-source isolation; provenance + trust tier on every item; retrieved content is **data, never instruction**; sensitive writes are gated; deletes propagate to every derived index; everything is auditable.

10. **Human always wins, and everything is reversible.** The user can inspect, correct, export, and forget any memory; a human-editable source-of-truth (markdown/git) can override the machine; every mutation is a versioned, diffable, revertible commit, and rollback is **transitive** (reverting a lesson invalidates memories derived under it).

---

## 4. System overview and data flow

### 4.1 The big picture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              INPUT SOURCES                                 │
│  Chats · files · emails · calendar · code · tool outputs · actions ·       │
│  results · user feedback/corrections · external web · sensors              │
└───────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ① INGESTION GATEWAY                                                        │
│  identity · trust class · ownership · sensitivity/PII · timestamp ·         │
│  dedup (content hash) · ACL · prompt-injection sanitize-as-data             │
└───────────────┬───────────────────────────────────────┬────────────────────┘
                │ (verbatim, synchronous)                │ (candidate facts, async)
                ▼                                         ▼
┌───────────────────────────────┐        ┌──────────────────────────────────┐
│  ② EVIDENCE LEDGER             │        │  ③ MEMORY COMPILER (consolidator) │
│  append-only · immutable ·     │───────▶│  extract candidates · resolve      │
│  hashed · verbatim · the       │ replay │  entities · detect change/conflict │
│  "hippocampus" / source of     │        │  bi-temporal update · induce       │
│  truth (MemPalace + GBrain)    │        │  workflows · distill lessons ·     │
│                                │        │  decay/prune  (the "neocortex")    │
└───────────────────────────────┘        └─────────────────┬──────────────────┘
                                                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ④ MEMORY STORES (typed projections, all rebuildable from ②)               │
│  Working · Episodic-index · Semantic(bi-temporal) · Temporal Graph ·        │
│  Procedural(skills+policies) · Preference/User-model · Corrective/Lessons · │
│  Resource(artifacts) · Meta(provenance/confidence/trust/version)           │
└───────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑤ RETRIEVAL ENGINE                                                         │
│  plan → multi-channel (exact · BM25 · dense · graph · temporal · prefs ·    │
│  procedures · lessons) → access/validity/trust filter → RRF fuse →          │
│  cross-encoder rerank → MMR dedup → activation score → fast | deep mode     │
└───────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑥ CONTEXT COMPILER                                                         │
│  task + hard constraints + current truth + supporting evidence + scoped     │
│  prefs + applicable procedures + prior-failure warnings + uncertainty;      │
│  U-curve ordered, token-budgeted, provenance-tagged                         │
└───────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑦ AGENT (any model)   reason · plan · call tools · act · cite evidence     │
└───────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑧ OUTCOME & LEARNING LOOP                                                  │
│  measure result · attribute cause · propose lesson/skill/pref ·             │
│  VALIDATE on regression suite · promote (versioned) · monitor · rollback    │
│  → writes new evidence (feedback) back to ②, closing the recursion          │
└──────────────────────────────────────────────────────────────────────────┘
```

The cardinal rule, inherited from the original transcript and reinforced by the research: **never destroy original evidence when creating a summary, fact, profile, or lesson; every derived memory links back to its source evidence.**

### 4.2 The CoALA decision cycle (how the agent uses memory each turn)

Each turn is a **propose → evaluate → select → execute** cycle, with a strict invariant: **planning is read-only; execution is the only phase that mutates state.**

```
        ┌─────────────────────────── DECISION CYCLE ───────────────────────────┐
        │  PLANNING (read-only)                                                 │
        │   • retrieve (internal action): pull from ④ via ⑤ into working memory │
        │   • reason   (internal action): LLM updates working memory            │
        │   • propose candidate actions, evaluate, select ONE                   │
        ├───────────────────────────────────────────────────────────────────────┤
        │  EXECUTION (the only mutating phase)                                  │
        │   • grounding (external): call a tool / act in the world, OR          │
        │   • learning  (internal): write to long-term memory (capture/propose) │
        └───────────────────────────────────────────────────────────────────────┘
                observation/outcome feeds ⑧ and the next cycle
```

This separation is what makes the system testable, auditable, and rollback-friendly: every state change is a discrete, logged, reversible "execution" event.

### 4.3 The three timescales of learning (preview of §8)

```
HOT  loop  (intra-task, seconds)     reason→act→verify→correct; recall boosts strength
WARM loop  (idle / "sleep-time")     consolidate: episodic→semantic, induce skills,
                                     distill lessons, resolve conflicts, decay/prune
COLD loop  (cross-task, days)        meta-optimize the policies themselves, gated +
                                     reversible, around an immutable invariant
```

These mirror CLS (fast encode / slow replay-consolidate) and add a third, self-referential layer that improves the machinery itself.

---

## 5. The memory stores (the substrate)

Mnemosyne has **one evidence spine** and **eight derived projections**. The spine is the only authoritative, append-only store; the projections are optimized read models that can be dropped and rebuilt from the spine at any time. Every store shares a common **meta-memory envelope** (§5.10) carrying provenance, confidence, trust, salience, validity, version, and access policy.

### 5.0 Store summary

| # | Store | Role | Mutability | Primary read pattern | Cog-sci / source analog |
|---|---|---|---|---|---|
| 1 | **Working memory** | the live context packet for the current task | ephemeral | assembled per-turn | Baddeley working memory / CoALA working |
| 2 | **Episodic evidence ledger** | verbatim record of everything (source of truth) | **append-only / immutable** | by id, time, session, entity; deep-mode scan | hippocampus; MemPalace drawers; event log |
| 3 | **Semantic memory** | current canonical facts, bi-temporal, versioned | supersede-only | hybrid + temporal filter | neocortex; GBrain compiled truth |
| 4 | **Temporal entity graph** | entities + relationships over time | edge-invalidation | graph traversal / PPR | spreading-activation network; Zep/Graphiti |
| 5 | **Procedural memory** | skills (code) + workflows + the agent's own policies | versioned + gated | by task/embedding; explicit load | basal ganglia/procedural; Voyager/AWM/CoALA |
| 6 | **Preference / user model** | identity, instructions, explicit + inferred preferences | scoped supersede | by scope + context | self-schema; the user contract |
| 7 | **Corrective / lesson memory** | mistakes, recovery strategies, validated lessons | versioned + gated | by task/failure signature | error memory; Reflexion/ExpeL |
| 8 | **Resource memory** | files, code, images, reports, URLs, artifacts | versioned | by reference; chunk index | external artifacts; GBrain resources |
| 9 | **Meta-memory** | provenance, confidence, trust, salience, versions, ACL | append/derived | joined to every item | metacognition; provenance ledger |

### 5.1 Working memory (the context packet)

Not a database table but a **per-turn assembled object** — the output of the Context Compiler (§4, §7.6). It is the only thing the model sees. It is structured (not a flat prompt blob) so a "central executive" controller can allocate a fixed token budget across slots: `task`, `hard_constraints`, `current_truth`, `supporting_evidence`, `scoped_preferences`, `applicable_procedures`, `prior_failure_warnings`, `open_loops`, `uncertainty`. Completed sub-goals are evicted aggressively (chunking; HiAgent showed this roughly doubles long-horizon success).

### 5.2 Episodic evidence ledger (the spine)

The heart of the system and the completeness guarantee. **Append-only, immutable, verbatim.** This is MemPalace's "store everything word-for-word" married to event sourcing and GBrain's raw-data/provenance layer.

Each event records both speaker/actor sides (do **not** drop assistant/tool turns — Mem0's default of discarding them is a documented source of error). Two layers, per MemPalace's insight:

- **Drawer (full fidelity):** the exact original content chunk.
- **Pointer (compressed index):** a short symbolic reference (who/what/when/where-it-lives) the agent can scan cheaply before hydrating a full drawer — the "AAAK" idea, generalized. Gives progressive disclosure and low wake-up token cost.

```sql
-- The immutable spine. Never UPDATE; never DELETE (tombstone for legal erasure only).
CREATE TABLE evidence (
  event_id        UUID PRIMARY KEY,
  tenant_id       UUID NOT NULL,
  user_id         UUID NOT NULL,
  session_id      UUID,
  actor           TEXT NOT NULL,          -- user | assistant | tool | system | external
  source_type     TEXT NOT NULL,          -- chat | file | email | calendar | code | tool_result | web | sensor | feedback
  source_identity TEXT,                    -- which user/tool/url/document
  content         TEXT NOT NULL,           -- VERBATIM original
  content_pointer TEXT,                    -- compressed symbolic index (AAAK-style)
  content_hash    BYTEA NOT NULL,          -- sha-256 for dedup + integrity
  modality        TEXT DEFAULT 'text',     -- text | image | audio | code | structured
  event_time      TIMESTAMPTZ NOT NULL,    -- when it happened in the world (valid time)
  recorded_time   TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when the system recorded it (transaction time)
  trust_tier      SMALLINT NOT NULL,       -- see §11.1 (0 = direct user … 5 = untrusted external)
  sensitivity     SMALLINT NOT NULL DEFAULT 0,
  access_policy   JSONB NOT NULL,
  erased          BOOLEAN NOT NULL DEFAULT false,  -- legal right-to-be-forgotten tombstone
  CONSTRAINT uq_evidence UNIQUE (tenant_id, content_hash)  -- idempotent ingestion
);
```

Large blobs (full transcripts, files) live in object storage (S3-class); `evidence.content` may hold a reference for big artifacts (see Resource memory). The ledger is **partitioned by tenant and time** and is the replay source for all consolidation.

### 5.3 Semantic memory (compiled current truth, bi-temporal)

Deduplicated, synthesized facts/beliefs — GBrain's "compiled truth + timeline." Stored as versioned **assertions** with bi-temporal validity. Change is **supersession**, never overwrite: the old assertion's `valid_to` is closed and a new version is added, so "what is true now?" and "what did we believe on date X?" both work.

```sql
CREATE TABLE assertions (
  assertion_id    UUID PRIMARY KEY,
  tenant_id       UUID NOT NULL,
  user_id         UUID,                    -- NULL = world fact; set = about-this-user fact
  subject         TEXT NOT NULL,
  predicate       TEXT NOT NULL,
  object          TEXT NOT NULL,           -- value (text, number, or entity ref)
  scope           JSONB,                   -- project / domain / situation qualifiers
  confidence      REAL NOT NULL,           -- 0..1
  salience        REAL NOT NULL DEFAULT 0.5,
  -- bi-temporal:
  valid_from      TIMESTAMPTZ NOT NULL,    -- true-in-world start
  valid_to        TIMESTAMPTZ,             -- true-in-world end (NULL = still true)
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),  -- system learned it
  expired_at      TIMESTAMPTZ,             -- system superseded it (NULL = current belief)
  -- provenance + versioning:
  source_event_ids UUID[] NOT NULL,        -- evidence this was compiled from
  version         INT NOT NULL DEFAULT 1,
  superseded_by   UUID,                    -- next version's id
  status          TEXT NOT NULL DEFAULT 'active',  -- active | superseded | retracted | candidate | quarantined
  trust_tier      SMALLINT NOT NULL,
  sensitivity     SMALLINT NOT NULL DEFAULT 0,
  access_policy   JSONB NOT NULL,
  embedding       VECTOR(1024)             -- Matryoshka-truncatable
);
CREATE INDEX ON assertions USING hnsw (embedding vector_cosine_ops);
-- "current belief about what is true now":  status='active' AND expired_at IS NULL
--                                            AND (valid_to IS NULL OR valid_to > now())
```

Contradiction handling lives in the consolidator (§6.4): a new assertion that conflicts with an active one does not delete it — it either supersedes it (closing `valid_to`/`expired_at`) or, if unresolved, both are retained and flagged in a `contradictions` table for the next consolidation pass or a user prompt.

### 5.4 Temporal entity graph (relationships over time)

The associative network that powers spreading-activation retrieval and multi-hop reasoning. Entities (people, companies, projects, concepts, artifacts) are nodes; relationships are **bi-temporal edges** with the same valid/transaction-time discipline and edge-invalidation as §5.3. Typed edges (`works_at`, `founded`, `invested_in`, `depends_on`, `authored`, `mentioned_in`, …) can be extracted **without an LLM** for the common cases (GBrain's zero-LLM self-wiring) and with an LLM for the hard ones.

```sql
CREATE TABLE entities (
  entity_id    UUID PRIMARY KEY,
  tenant_id    UUID NOT NULL,
  canonical    TEXT NOT NULL,              -- canonical name (post entity-resolution)
  type         TEXT NOT NULL,              -- person | org | project | concept | artifact | place | event
  summary      TEXT,                       -- evolving rollup, regenerated on consolidation
  salience     REAL NOT NULL DEFAULT 0.5,
  embedding    VECTOR(1024),
  access_policy JSONB NOT NULL
);
CREATE TABLE entity_aliases (
  alias        TEXT NOT NULL, entity_id UUID NOT NULL REFERENCES entities, tenant_id UUID NOT NULL,
  PRIMARY KEY (tenant_id, alias)
);
CREATE TABLE relations (
  relation_id  UUID PRIMARY KEY,
  tenant_id    UUID NOT NULL,
  src          UUID NOT NULL REFERENCES entities,
  predicate    TEXT NOT NULL,
  dst          UUID NOT NULL REFERENCES entities,
  weight       REAL NOT NULL DEFAULT 1.0,  -- association strength (boosts on co-activation)
  valid_from   TIMESTAMPTZ NOT NULL, valid_to TIMESTAMPTZ,
  recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(), expired_at TIMESTAMPTZ,
  source_event_ids UUID[] NOT NULL,
  status       TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX ON relations (tenant_id, src); CREATE INDEX ON relations (tenant_id, dst);
```

Multi-hop retrieval runs **Personalized PageRank** seeded by query entities (HippoRAG) over the *currently-valid* subgraph, with `weight` as edge strength and a node-specificity (IDF-like) prior. New knowledge integrates by **adding edges** (cheap, update-friendly) — never by re-summarizing the whole graph.

### 5.5 Procedural memory (skills, workflows, and the agent's own policy)

Per CoALA, this includes the agent's *own operating procedures* — so self-improvement writes here. Three sub-kinds, each versioned and **promotion-gated** (§8):

- **Skills** — executable, composable code keyed by a description embedding (Voyager). Each has tests/verification; new skills compose existing ones; retrieval = embedding similarity + recent success rate.
- **Workflows** — abstracted, parameterized routines induced from successful trajectories (Agent Workflow Memory). Stored as named procedures with slots.
- **Policies** — the system's own management policies and prompt fragments (retrieval routing, ranking weights, write-decision thresholds, consolidation cadence). These are the surface the **cold loop** (§8.4) optimizes — *inside* the invariant of §3.8.

```sql
CREATE TABLE procedures (
  procedure_id UUID PRIMARY KEY, tenant_id UUID NOT NULL,
  kind         TEXT NOT NULL,             -- skill | workflow | policy | prompt_fragment
  name         TEXT NOT NULL,
  body         TEXT NOT NULL,             -- code | structured workflow | policy params | prompt text
  signature    JSONB,                     -- inputs/outputs/slots
  embedding    VECTOR(1024),              -- of the description, for retrieval
  status       TEXT NOT NULL DEFAULT 'candidate',  -- candidate | active | deprecated | quarantined
  version      INT NOT NULL DEFAULT 1, superseded_by UUID,
  success_rate REAL, n_trials INT NOT NULL DEFAULT 0,
  validated_by UUID,                      -- regression-run id that promoted it
  source_event_ids UUID[],                -- trajectories it was induced from
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Procedures are stored as **repo files (markdown/code) under git** in addition to the DB row, so they are diffable, reviewable, and revertible — the "human always wins" principle applied to the agent's own behavior.

### 5.6 Preference / user model

A dedicated service (§9), not a profile blob. Six typed categories — identity, hard instruction, explicit preference, inferred preference, situational preference, temporary state — each with evidence, scope, confidence, exceptions, validity, and an explicit override path. Inferred preferences require repeated evidence before promotion and are always reversible.

### 5.7 Corrective / lesson memory

Mistakes (the agent's and the user's), recovery strategies, and **validated lessons** — Reflexion's verbal lessons + ExpeL's voted insights. Lessons are typed (retrieval/ranking/reasoning/tool/execution/preference/stale-memory), carry a **failure signature** for retrieval, start as `candidate`, and only become `active` after passing the promotion gate (§8.3). Vote-count decay (ExpeL) prunes lessons that stop helping. User mistakes are stored as scoped *support strategies*, never judgments (§9.4).

### 5.8 Resource memory

Files, code, images, reports, URLs, and other artifacts — large content in object storage, chunked and embedded for retrieval, referenced from evidence/assertions. Carries versioning so "the architecture spec PDF" resolves to the right revision at a given time.

### 5.9 The episodic *index* vs the episodic *ledger*

The ledger (§5.2) is the immutable truth. For retrieval it is mirrored into an **episodic index**: chunked (late chunking), embedded, and metadata-tagged (session, entities, time, importance) so episodes are searchable by similarity + scope. The index is a projection — droppable and rebuildable from the ledger.

### 5.10 Meta-memory (the envelope on everything)

Every stored item — evidence, assertion, edge, procedure, preference, lesson, resource — carries a common envelope so the rest of the system can reason about *how much to trust it and whether it still applies*:

```
{ id, tenant_id, user_id, memory_type, source_event_ids[], scope,
  confidence (0..1), salience (0..1, decays — §10), trust_tier (§11.1),
  sensitivity, valid_from, valid_to, recorded_at, expired_at,
  status, version, superseded_by, checksum, embedding_version, access_policy,
  last_accessed, access_count }     -- last two power ACT-R base-level activation (§7.4)
```

`last_accessed` and `access_count` are updated **on retrieval** (reconsolidation / testing effect), which is what makes recall strengthen memory and feeds the activation score.

---

## 6. Ingestion and the write path

The write path is deliberately split: a **synchronous, cheap** evidence append (so the user never waits) and an **asynchronous, deliberate** compilation into projections (the warm loop, §8.2). This is CLS's fast-encode / slow-consolidate split.

### 6.1 Ingestion gateway (synchronous)

Every incoming item passes through the gateway, which:

1. **Identifies** the actor, source type, and source identity.
2. **Classifies trust** into a tier (§11.1) — the single most important security step. A direct user statement and a scraped web page are *not* equal.
3. **Detects ownership and sensitivity/PII**, attaches an access policy.
4. **Timestamps** both event time and recorded time.
5. **Hashes** content (sha-256) and **deduplicates** (idempotent ingestion via the unique constraint).
6. **Sanitizes-as-data:** scans for prompt-injection patterns and **marks any imperative content found in untrusted sources as data, not instruction** (GBrain's `INJECTION_PATTERNS`, generalized; spotlighting). The content is still stored verbatim — but tagged so retrieval never presents it as a command.
7. **Appends** to the evidence ledger and enqueues a consolidation job.

### 6.2 Candidate extraction (asynchronous)

The consolidator reads new evidence and extracts **candidate** facts, entities, relations, preferences, and tasks. Crucially, candidates enter as `status='candidate'` — they are not yet trusted truth. Extraction uses the model, but the *decision to promote* is gated.

### 6.3 The write decision: ADD / UPDATE / DELETE / NOOP

For each candidate fact, retrieve the most similar existing assertions and decide an explicit, auditable operation (Mem0's vocabulary, extended with `SUPERSEDE` and `QUARANTINE`):

| Op | When | Effect |
|---|---|---|
| **ADD** | no matching existing fact | insert new assertion (`candidate`→`active` after gate) |
| **UPDATE** | same fact, refined value/confidence | new version; old `superseded_by` set |
| **SUPERSEDE** | new fact contradicts an old one, with newer valid time | close old `valid_to`/`expired_at`; add new (both retained) |
| **NOOP** | duplicate / no new information | drop candidate (dedup) |
| **DELETE** | provably erroneous or legal erasure | tombstone; propagate to all derived indexes (§11.4) |
| **QUARANTINE** | low trust or unresolved conflict | store but exclude from default retrieval; flag for review |

In Phase 1 this is a rule + LLM-judge decision; in Phase 5 it becomes a **learned policy** (Memory-R1) trained on whether the edit improved downstream outcomes — but `DELETE`/`SUPERSEDE` always require corroboration and remain reversible.

### 6.4 Entity resolution and bi-temporal graph update

Candidate entities are resolved against existing ones (alias table + embedding match + optional ontology canonicalization à la Cognee) to avoid duplicate nodes. New relations are added as bi-temporal edges; contradictory relations trigger **edge invalidation** (§5.4), not deletion.

### 6.5 Chunking and embedding

Resources and long episodes are chunked with **tuned recursive splitting (~200 tokens, minimal overlap)** and embedded with **late chunking** (embed the whole document with a long-context model, then pool per-chunk) — the best low-cost quality upgrade per the evidence. Embeddings carry a `embedding_version` so re-embeddings are tracked and indexes can be rebuilt on model upgrades. **Small-to-big**: the small chunk is the *match* unit; the parent passage is the *returned* unit.

### 6.6 What gets written where (routing)

```
raw event ─────────────────────────────────▶ ② evidence ledger      (always, verbatim)
   │
   ├─ stable fact about world/user ─────────▶ ③ semantic (assertion, bi-temporal)
   ├─ entity / relationship ────────────────▶ ④ temporal graph (bi-temporal edge)
   ├─ reusable how-to (from success) ───────▶ ⑤ procedural (workflow/skill, gated)
   ├─ preference signal ────────────────────▶ ⑥ user model (scoped, confidence)
   ├─ mistake / correction ─────────────────▶ ⑦ corrective (lesson, gated)
   └─ file / artifact ──────────────────────▶ ⑧ resource (+ chunk index)
```

The router's defaults are rules; its thresholds are later tuned by the cold loop (§8.4).

---

## 7. The retrieval engine

Retrieval is a **planner**, not a single embedding lookup. It runs in two modes — **fast** (default, low-latency) and **deep** (investigative, exhaustive) — sharing the same channels but differing in breadth, iteration, and budget.

### 7.1 Query understanding and planning

Classify the query: task type, named entities, time range/as-of, project/scope, which memory types are relevant, required accuracy, user scope, and whether fresh external data is needed. Decide **fast vs deep** by complexity (Adaptive-RAG-style routing). Optionally expand into a few controlled query variants (multi-query) — fused later by RRF (RAG-Fusion), gated on low retriever confidence to avoid drift.

### 7.2 Parallel multi-channel retrieval

Run channels concurrently, each returning a ranked list:

```
exact / metadata lookup ─┐
BM25 / lexical ──────────┤
dense vector (semantic) ─┼─▶ candidates (per channel, ranked)
temporal SQL filter ─────┤
graph PPR traversal ─────┤   (HippoRAG personalized PageRank, currently-valid subgraph)
preference retrieval ────┤
procedure retrieval ─────┤
lesson / warning lookup ─┘   (by failure signature, to surface "don't repeat this")
```

Lexical + dense covers the paraphrase/exact-term split; the graph channel covers multi-hop and associative recall; the lesson/preference/procedure channels are what make this a *memory* engine rather than a document RAG.

### 7.3 Access/validity/trust filtering

Before fusion, drop candidates that are: outside the caller's permissions/namespace, expired or superseded, outside the requested time window, below a trust threshold for the task, or quarantined. **Security filtering precedes ranking** so untrusted content can never win a slot.

### 7.4 Fusion, activation scoring, and reranking

1. **RRF fusion** merges the per-channel ranked lists: `score(d) = Σ_r 1/(k + rank_r(d))`, k≈60 — robust to incomparable score scales.
2. **Activation re-scoring** applies the ACT-R-inspired memory score (this is what makes it *memory*, not search):

```
activation(m) =  w_b · base_level(m)            # frequency + power-law-decayed recency
              +  w_s · spreading(m, query)       # graph proximity to activated query entities
              +  w_i · importance(m)             # salience assigned at write / consolidation
              +  w_r · relevance(m, query)       # semantic + lexical match (the fused score)
              +  noise

base_level(m) = ln( Σ_k t_k^(-d) )               # t_k = age of each past access; d ≈ 0.5
```

Retrieval stops when expected marginal gain falls below cost (ACT-R's `C > pG` rule) — a principled top-k cutoff rather than a fixed number. The weights `w_*` and decay `d` are config in Phase 1 and **learned by the cold loop** (§8.4) later.

3. **Cross-encoder rerank** over the top 50–200 by activation → keep the top 3–5 (or until the budget fills). Use a strong cross-encoder (Qwen3-Reranker / Cohere Rerank); use **LLM listwise (RankGPT)** for novel domains.

### 7.5 Deduplication and the "complete recall" guarantee

Apply **MMR** to the reranked set so a tight budget covers *distinct* facts, not k near-duplicates: `MMR = argmax_i [ λ·rel(i,q) − (1−λ)·max_j sim(i,j) ]`. This matters most for episodic memory (near-duplicate observations across sessions).

The completeness guarantee is delivered by **deep mode**: when the task demands it (audits, "find every time X happened," reconstructing a decision), the planner iterates — decompose the query, traverse the graph exhaustively, scan evidence pointers, hydrate drawers, and verify coverage — so the *exact original* is always recoverable. Fast mode trades exhaustiveness for latency; deep mode trades latency for exhaustiveness; storage loses nothing in either case.

### 7.6 Context assembly (the Context Compiler)

Assemble the working-memory packet (§5.1) from the survivors:

- order against the **U-curve** — put the highest-value items at the **start and end**, never bury the key fact in the middle (Lost-in-the-Middle); place the single most relevant item adjacent to the query;
- enforce a **token budget well below the model's nominal window** (Context Rot — treat the window as scarce and degrading);
- attach **provenance tags** to every item (which evidence it came from), so the agent can cite and the user can audit (GBrain's evidence tags + `search --explain`);
- include an **uncertainty/gap note** when confidence is low or evidence conflicts, so the agent can abstain rather than hallucinate.

### 7.7 Reconsolidation on read

Every retrieval updates `last_accessed`/`access_count` (strengthening the memory — the testing effect) and, if the retrieved memory is found stale or contradicted in the course of the task, enqueues an **update-on-recall** so the next consolidation corrects it. Recall is a read-write operation.

---

## 8. The recursive self-improvement system

This is what makes Mnemosyne *recursive* and self-*. It is three loops at three timescales, each a closed `observe → diagnose → propose → validate → commit → monitor` cycle, sharing one non-negotiable rule and one structural safety boundary.

> **The one rule:** *No candidate memory ever self-certifies.* Every promotion into durable memory passes an **external** validation gate — tool-grounded for facts, regression-tested for procedures/lessons, corroborated for deletions. This is the single most-repeated finding in the self-improvement literature (CRITIC's no-tool ablation; the generator–verifier gap; reward-tampering results).
>
> **The boundary (immutable outer invariant):** the **reward signal, the validator, the regression suite, the safety/identity rules, and the trust-tier logic live outside the self-editable surface** and are enforced structurally (separate service, separate credentials), never by a prompt the agent can rewrite. STOP and reward-tampering results show that anything inside the editable surface will eventually be gamed.

### 8.1 Hot loop — intra-task (seconds)

Runs *during* a task, entirely in working memory; writes only candidate signals.

```
retrieve → reason → act → VERIFY → correct → (emit candidate lesson/pref) → repeat
```

- **Verify with tools, not vibes** (CRITIC): facts → retrieval/search check; code/math → execute/test; safety → classifier. Self-feedback (Self-Refine) is allowed only for *polishing*, never as the sole gate for what persists.
- **Reconsolidation:** each recall boosts the memory's strength and can flag it for update (§7.7).
- **Output:** the task result plus *candidate* lessons/preferences/skills (not yet promoted) and a full **trajectory** logged to evidence.

### 8.2 Warm loop — consolidation / "sleep-time" (idle, minutes–hours)

The CLS replay-and-consolidate process, run **offline during idle time on a dedicated consolidator** that *owns memory-write authority while the user-facing agent does not* (Letta's safety split). This is where most learning actually happens, off the latency-critical path.

What a consolidation pass does, in order:

1. **Replay** recent + prioritized episodes from the ledger — weighted by importance/novelty/surprise/reward (prioritized replay, Kumaran 2016), not uniformly.
2. **Promote episodic → semantic:** recurring patterns across episodes become consolidated assertions (with ADD/UPDATE/SUPERSEDE/NOOP, §6.3). Single mundane events stay episodic and decay.
3. **Induce workflows** from successful trajectories (Agent Workflow Memory) and **compile skills** from expensive multi-step solutions (Voyager/Soar chunking) — into `candidate` procedures.
4. **Distill lessons** from failures (Reflexion verbal reflection + ExpeL fail/success contrast) into `candidate` corrective memories with failure signatures.
5. **Resolve contradictions:** reconcile conflicting assertions/edges; supersede or escalate to the user.
6. **Re-summarize** entity rollups and (optionally) build/refresh RAPTOR summary trees for synthesis-heavy corpora.
7. **Decay and prune** (§10): lower salience on stale items, tombstone superseded/contradicted/low-salience memories, compact with pointers back to evidence.
8. **Update the user model:** consolidate repeated preference signals into scoped inferred preferences (§9).

Everything produced is `candidate` and must pass §8.3 before it becomes `active`. Consolidation cadence (e.g., every N idle steps, or nightly) is itself a policy the cold loop tunes — over-frequent consolidation thrashes memory (a documented failure mode), so the cadence is bounded.

### 8.3 The promotion gate (validation + rollback) — used by both warm and cold loops

The discipline that prevents corruption. Borrowed from prompt-optimization practice (APE/OPRO/DSPy) and made mandatory for *every* durable write of a procedure, lesson, or learned policy:

```
1. Hold out a fixed REGRESSION SUITE of already-solved tasks (built from real corrections — §14).
2. Re-run the suite with the candidate injected (lesson / workflow / policy / weight change).
3. PROMOTE only if:  aggregate score is non-inferior  AND  no protected task regresses
                     AND  the margin exceeds run-to-run noise (average over a minibatch).
4. The candidate's source data must be DISJOINT from the regression suite (no teaching-to-the-test).
5. Commit as a versioned, diffable change with a `validated_by` run id.
6. MONITOR post-promotion (proxy-vs-true success divergence, diversity metrics).
7. ROLLBACK on regression — and make rollback TRANSITIVE: reverting a lesson invalidates
   every memory derived under it (Layered Mutability's "ratchet" warning).
```

Facts are gated differently: a factual assertion is validated by **external corroboration** (a tool/source), because the generator–verifier gap collapses on lookup tasks — the model can't be trusted to self-verify facts, but a search/tool can.

### 8.4 Cold loop — meta-optimization / self-optimization (cross-task, days)

The recursive layer: the system improves its **own policies**, which are stored as procedural memory (§5.5) and therefore subject to the same gate. Targets:

- retrieval routing (fast vs deep; which channels to run) — learned from outcome logs;
- activation-score weights `w_b, w_s, w_i, w_r` and decay `d` (§7.4);
- the write-decision thresholds for ADD/UPDATE/SUPERSEDE/NOOP (§6.3) — Memory-R1-style RL on whether the edit improved downstream answers, with reward densification (Mem-T) for the long-horizon credit-assignment problem;
- consolidation cadence and pruning aggressiveness;
- chunking/embedding choices per corpus.

Method: propose candidate policy (LLM-as-optimizer / evolutionary search à la OPRO/Promptbreeder, *or* RL on logged outcomes) → **§8.3 gate** → versioned promote → monitor. Because policies are the surface that most amplifies errors, the cold loop runs least often and most conservatively, always inside the invariant of §3.8.

### 8.5 Why this is safe (the failure modes and their structural mitigations)

| Failure mode | Source | Structural mitigation in Mnemosyne |
|---|---|---|
| **Self-certification** (model approves its own bad memory) | CRITIC ablation | external validation gate (§8.3); tools for facts |
| **Reward hacking / tampering** | STOP; Anthropic 2024 | reward+verifier+safety rules outside editable surface (§3.8); bounded per-update influence |
| **Model collapse** (learning on own outputs) | Shumailov, Nature 2024 | anchor a fixed reservoir of real/edge-case episodes; replay tails; monitor diversity/entropy; promote only *verified novel* lessons |
| **Unsafe self-modification** | STOP sandbox-escape | freeze the substrate; sandbox + capability-gate code; human-in-loop on permanent procedure promotion |
| **Ratchet / irreversible drift** | Layered Mutability | transitive rollback; supersede-not-delete; versioned everything |
| **Memory thrash** | Letta sleep-time | bounded consolidation cadence (cold-loop-tuned within limits) |
| **Bad procedure poisons all future runs** | Voyager verifier risk | procedures gated harder than facts; small atomic skills; retrieval-time re-validation |

The asymmetry to internalize: **a bad fact misleads one retrieval; a bad procedure or policy misleads every future execution.** So the gate is strict in proportion to blast radius — facts (corroboration), lessons (regression suite), procedures (regression suite + optional human), policies (regression suite + conservative cadence + monitoring).

### 8.6 Optional advanced tier — parametric learning

By default Mnemosyne learns in *memory/prompts/skills* (no weight changes). When a deployment wants more, two bounded options plug in without changing the architecture: **test-time training** (fold a session's context into LoRA fast-weights, label-free via next-token/perplexity) and **periodic LoRA distillation** of stable, validated lessons. Both are gated by §8.3, bounded by LoRA/adapter isolation (to avoid catastrophic forgetting — EWC-style protection of consolidated knowledge), and never touch the base model or the invariant.

### 8.7 The recursion, explicitly

- **Memory about memory:** reflections are written back as memories and can themselves be reflected upon (Generative Agents); meta-memory (§5.10) is memory describing other memory.
- **Skills that build skills:** new skills compose existing ones (Voyager); induced workflows call other workflows.
- **A self-editable manager:** the policy that decides what to remember/retrieve/forget is procedural memory improved by the cold loop — the system tunes its own memory management.
- **The invariant that makes recursion safe:** the validator/reward/safety layer is *not* in the recursion. The system can improve everything it can measure, and cannot touch what does the measuring.

---

## 9. The user model (personalization)

Adaptation to the user is a **dedicated service**, not a free-text profile. Dumping everything into one "preferences" note is exactly what makes adaptation unreliable; typing it is what makes it controllable and reversible.

### 9.1 Six typed categories

| Category | Example | Update rule |
|---|---|---|
| **Identity** | "Jake; software-leaning; values directness" | explicit only; rarely changes |
| **Hard instruction** | "Never auto-send emails on my behalf" | explicit; high priority; overrides inferences |
| **Explicit preference** | "Use tables for technical comparisons" | explicit; high confidence |
| **Inferred preference** | "Seems to prefer terse answers in the morning" | promoted only after repeated evidence; low→rising confidence |
| **Situational preference** | "In code reviews, wants security flagged first" | scoped to a context; applies only when the context matches |
| **Temporary state** | "This week: focused on the retrieval layer" | short TTL; decays fast |

### 9.2 Every preference carries

`evidence (source events) · scope (when it applies) · confidence (0..1) · exceptions · valid_from/valid_to · override_path`. This is what keeps adaptation **controlled and reversible** — the requirement you emphasized.

### 9.3 How preferences are learned and applied

- **Explicit** preferences are taken at face value (high confidence) and are user-editable.
- **Inferred** preferences are proposed by the warm loop from repeated behavioral signals, enter as low-confidence `candidate`, and only influence behavior once corroborated. They are always visible to the user and one click to correct or delete.
- At retrieval, only **scope-matching** preferences enter the context packet (a code-review preference doesn't fire during meeting prep), and **hard instructions always outrank inferred preferences**.
- Conflicts (an inferred preference contradicting an explicit one) resolve in favor of the explicit/hard one and flag the inference for retirement.

### 9.4 Learning from the user's mistakes (handled differently from the agent's)

User errors are stored as **episodic events**, never as judgments. Only after *repeated similar* events does the system infer a **support strategy** ("offer to double-check date math," "surface the staging checklist before deploys"), scoped and framed as assistance aligned to the user's goals. The system adapts *to help*, not to label. A single user slip never becomes a durable "the user is bad at X."

### 9.5 Context awareness

The agent never loads the whole user history. The Context Compiler (§7.6) builds a **task-specific** packet: current request + conversation state + active project/goal + relevant hard instructions + scope-matching preferences + current facts + supporting evidence + applicable procedures + prior-failure warnings + permissions + known uncertainties. Personalization is *contextual*, not global.

---

## 10. Forgetting and the memory lifecycle

Forgetting is an engineered subsystem, not a side effect of running out of space. It is what keeps retrieval precise and the system adaptive to a changing world.

### 10.1 Decay and salience

Every item carries a **salience** score that **decays over time** (Ebbinghaus exponential / ACT-R base-level power law) and is **boosted on access** (testing effect) and by importance assigned at write/consolidation (Generative Agents' 1–10 importance). Salience feeds the activation score (§7.4) and gates pruning.

### 10.2 Supersession over deletion

The default response to "this changed" is **supersede** (close `valid_to`/`expired_at`, add a new version), not delete. History is preserved and queryable as-of any time. Hard deletion is reserved for proven errors and legal erasure.

### 10.3 Contradiction handling

A new assertion conflicting with an active one triggers SUPERSEDE (if it has newer valid time) or, if unresolved, retention of *both* with a `contradictions` flag for the next consolidation pass or a user prompt. Contradictions are never silently dropped.

### 10.4 Pruning, compaction, and spaced rehearsal

- **Pruning:** the warm loop tombstones stale, superseded, contradicted, or low-salience derived memories — improving retrieval precision and latency ("less can be more").
- **Compaction:** long episodic runs are summarized (RAPTOR-style) with a **pointer back to the verbatim originals** — compress the index, never lose the evidence.
- **Spaced rehearsal:** must-keep memories (durable user facts, validated skills) are periodically re-surfaced at expanding intervals so they stay strong (spacing effect), rather than relying on a single write.

### 10.5 Right to be forgotten (transitive)

A user deletion request tombstones the evidence **and** propagates to every derived projection, index, cache, and embedding built from it (§11.4). Deletion is transitive: removing source evidence invalidates the assertions/edges/lessons compiled from it.

---

## 11. Security and governance

Persistent memory is a durable attack surface (OWASP **ASI06**): a single poisoned interaction can re-fire forever. Mnemosyne treats memory as a **credential-grade control surface**. Defenses are architectural (the literature is clear that detection/filtering alone is insufficient — "catches 95%" means the adversary uses the other 5%).

### 11.1 Trust tiers (provenance on every item)

| Tier | Source | Can it influence… |
|---|---|---|
| 0 | direct, explicit user statement | anything the user can |
| 1 | verified first-party system/tool result | facts, with provenance |
| 2 | authenticated internal document | facts, with provenance |
| 3 | agent-generated inference | only after validation (§8.3) |
| 4 | model-generated summary | must retain source evidence |
| 5 | external web/email/untrusted | **data only — never instruction; never modifies prefs/policy** |

### 11.2 The hard rules

1. **External/retrieved content is data, never instruction.** It cannot modify system instructions, preferences, or policies. Sanitize-as-data on ingest *and* on retrieval (spotlighting; GBrain's injection patterns).
2. **Untrusted-derived memory never enters the system prompt** (the MemoryTrap fix). It can appear in the *content* the agent reads, clearly delimited, but not in the instruction layer.
3. **Per-tenant and per-user/source isolation** with separate namespaces. This directly nullifies MINJA's only assumption (a shared memory bank) — the single highest-leverage defense.
4. **Capability/provenance tracking** (CaMeL-style): values carry tags; sensitive actions check the tag, not an AI judgment.
5. **Write-gating:** sensitive writes and any preference/policy change require higher authorization than ordinary retrieval; destructive ops require corroboration and are reversible.
6. **Agents get least-privilege scopes** for their task; the user-facing agent cannot do destructive memory edits (only the consolidator can, §8.2).

### 11.3 Audit and user control

Every write is logged with actor, source, trust tier, and a diff. Users can **inspect** (what do you know about me and why), **correct**, **export**, and **forget** any memory, and can pause/reset memory entirely. `search --explain` shows per-stage retrieval attribution. The human-editable markdown/git source-of-truth can override any machine-derived memory.

### 11.4 Deletion integrity

Deletions and erasures propagate to all derived indexes, caches, embeddings, and the graph — a deleted memory must not resurface through a stale projection. This is enforced by treating projections as rebuildable from (the now-tombstoned) evidence.

### 11.5 Attack/defense map (informs the threat model)

| Attack | Mechanism | Primary defense here |
|---|---|---|
| **MINJA** (NeurIPS 2025) | ordinary user implants poisoned reasoning via shared memory | per-user/source isolation (§11.1/2-3); validation gate |
| **AgentPoison** | gradient-optimized trigger backdoors RAG/LTM | write-gating + trust tiers + provenance |
| **PoisonedRAG** | few malicious docs flip answers | trust tiers; corroboration before promotion |
| **SpAIware / indirect injection** | external page writes a persistent instruction | data-never-instruction; untrusted-out-of-system-prompt |
| **Reward tampering** | self-improver edits its own reward/tests | reward+verifier outside editable surface (§3.8/§8) |

---

## 12. Storage and infrastructure stack

You asked me to recommend the best, no compromises, for a system that runs **both** local-first and at production scale. The recommendation balances "best of everything" against your stated bias for a **battle-tested, low-redundancy, single canonical path**.

### 12.1 Recommendation: a Postgres-centric core behind a pluggable engine contract

**One canonical path — PostgreSQL — carrying four jobs, with a clean adapter interface so any component can be swapped for a best-of-breed specialist when scale demands.** This is GBrain's bet ("two engines, one contract"), and it is the right one.

```
                 ┌──────────────────────────────────────────────┐
                 │            BrainEngine contract               │
                 │  (every op routes through one interface;      │
                 │   swap a backend without touching app/agent)  │
                 └───────────────┬──────────────────────────────┘
   local-first  ◀────────────────┤────────────────▶  production / multi-tenant
   PGLite (Postgres-in-WASM,      │       PostgreSQL 16+ (Supabase / self-hosted)
   zero-config, single user)      │         + pgvector        (dense vectors / HNSW)
                                  │         + ParadeDB/pg_search (BM25 lexical)
                                  │         + Apache AGE or recursive CTEs (graph)
                                  │         + object storage (S3-class) for blobs
                                  │         + Redis (ephemeral working state only)
                                  │         + a job queue (consolidation, embeddings)
                 ┌────────────────┴──────────────────────────────┐
                 │  Optional best-of-breed adapters (at scale):    │
                 │  Qdrant/Milvus (vectors) · OpenSearch (lexical) │
                 │  Neo4j/FalkorDB (graph) · all behind the same   │
                 │  contract, added per-component only when needed │
                 └─────────────────────────────────────────────────┘
```

**Why Postgres-centric (not best-of-breed from day one):**

- **One source of truth, transactional writes.** Facts, vectors, lexical index, graph, and provenance can be updated in a single transaction — no cross-store sync drift (the operational tax that sinks multi-store designs).
- **Battle-tested and low-redundancy** (your profile's explicit preference): one system to operate, back up, secure, and reason about.
- **Local→production with the same contract.** PGLite gives a true zero-config local-first brain (GBrain's ~50k-page sweet spot); the *same* schema and queries scale to hosted Postgres. No rewrite between personal and team deployments — which is exactly your "general framework (both)" requirement.
- **The escape hatch is real, not hypothetical.** When a single component outgrows Postgres (e.g., billions of vectors → Qdrant; very large lexical corpora → OpenSearch; deep graph analytics → Neo4j), the adapter interface lets you move *that one component* without touching the agent layer. You get best-of-breed *capability* without paying best-of-breed *complexity* until you must.

**Where I'd reach for a specialist immediately:** if your day-one scale is already >100M vectors, start dense search on Qdrant/Milvus behind the adapter; if you need heavy global graph analytics, run Neo4j/FalkorDB alongside. Otherwise, Postgres first.

### 12.2 Models

- **Embeddings:** a current top model, Matryoshka-truncatable — **Qwen3-Embedding** (Apache-2.0, self-hostable) or managed **Gemini-Embedding / Voyage-3.5**. Start at 1024 dims; drop to 512/256 if recall holds. Track `embedding_version` for rebuilds.
- **Reranker:** a cross-encoder — **Qwen3-Reranker** (open) or **Cohere Rerank**; **RankGPT** (LLM listwise) for novel domains.
- **Consolidation/extraction model:** a cheap, fast model (Haiku-class) for the high-volume warm-loop work; a stronger model only for hard contradiction resolution and skill induction.
- **The agent model is decoupled.** Mnemosyne is model-agnostic — its whole point is to make a mid-tier model perform like a stronger one.

### 12.3 Human-editable source of truth (optional but recommended)

Keep the canonical brain as **markdown files in git** (people/, companies/, projects/, ideas/, procedures/), synced into Postgres as the derived retrieval index (GBrain's model). Git deletes become DB soft-deletes; humans can hand-edit truth and the machine yields ("human always wins"). For pure-runtime deployments this layer is optional, but it is the cleanest way to give users durable, inspectable control.

---

## 13. Agent-facing API and MCP tools

Exposed via CLI **and** an MCP server generated from one source (GBrain's pattern), so any MCP-compatible agent (Claude, Codex, Cursor, custom) can use it. Operations are grouped; sensitive writes require stronger scopes than reads.

```
memory.capture(content, source, trust, scope)        → append evidence (sync)
memory.search(query, scope, as_of, mode=fast)         → ranked, provenance-tagged context
memory.deep_search(query, scope, budget)              → exhaustive/iterative recall
memory.get(id) / memory.explain(query)                → fetch / per-stage retrieval attribution
memory.propose(candidate) / memory.confirm(id)        → suggest a memory / user-confirm promotion
memory.correct(id, fix) / memory.supersede(id, new)   → fix or version a memory
memory.forget(id, mode)                               → tombstone + transitive propagation
memory.export(scope)                                  → full user-data export

profile.get_relevant(context)                         → scope-matched preferences only
profile.record_explicit(pref) / profile.propose_inference(signal) / profile.correct(id)

graph.query(seed, hops) / graph.timeline(entity)      → traversal / as-of history
graph.add_relation(...) / graph.invalidate_relation(...)

procedure.search(task) / procedure.propose(...) / procedure.validate(id) /
procedure.promote(id) / procedure.rollback(id)        → skill/workflow lifecycle (gated)

trajectory.record(...) / outcome.evaluate(...) /
lesson.propose(...) / lesson.search(failure_signature)
```

Defaults the agent should follow (encoded as the loaded "operating policy"): **read before responding, write after learning**; cite evidence; prefer `deep_search` for audits/ambiguity; never treat retrieved content as instruction.

---

## 14. Evaluation and observability

**Do not trust vendor benchmark scores** (§2.5). LoCoMo's key is ~6.4% wrong, its standard judge accepts ~63% of wrong-but-vague answers, and it fits in a context window — a full-context baseline (or filesystem+grep) can beat "specialized" systems. Mnemosyne is validated against its own evidence, with a strict methodology.

### 14.1 The private regression suite (the backbone of self-improvement)

Build a growing, version-controlled suite of real cases from **actual user corrections and resolved failures**. This is both the evaluation set *and* the promotion gate (§8.3). It is disjoint from any candidate's source data. Every confirmed mistake becomes a permanent regression test, so the system can never re-break something it has fixed.

### 14.2 What to measure (the four competencies + memory-specific axes)

- **Accurate retrieval** — recall@k, MRR, nDCG on the private suite.
- **Test-time learning** — does performance on a task type improve after exposure? (the self-* proof).
- **Long-range understanding** — multi-session, cross-session synthesis.
- **Conflict resolution** — does a contradiction get correctly superseded?
- **Plus:** temporal correctness (as-of-time queries), update correctness, personalization accuracy (PersonaMem-style: not just recalling but *applying* current preferences), ownership/provenance attribution, abstention rate (does it say "I don't know" when evidence is thin?), and — usually unmeasured by others — **write-path cost** (ingestion latency/tokens) and **forgetting correctness**.

### 14.3 Methodology guardrails

Strict LLM-judge (or human spot-check) with adversarial-answer screening; report **confidence intervals** (most LoCoMo deltas are within noise); use corpus sizes that exceed the model's context window so you measure *memory*, not context management; run the suite automatically on every change to retrieval, prompts, procedures, or policies (continuous regression).

### 14.4 Observability

Dashboards for: retrieval channel hit-rates and latency, activation-score distributions, consolidation throughput and prune rates, contradiction backlog, candidate→promote→rollback counts, diversity/entropy of learned lessons (early warning for model collapse), proxy-vs-true success divergence (early warning for reward hacking), and the security audit log.

---

## 15. Phased build roadmap

Each phase is independently useful and ends with a clear exit criterion. This sequencing front-loads the durable, hard-to-retrofit decisions (evidence ledger, bi-temporality, provenance) and defers the learned policies until there is data to learn from.

**Phase 1 — Reliable memory foundation.** Evidence ledger (append-only, hashed, verbatim, dual drawer/pointer); semantic assertions with **bi-temporal versioning + supersession**; user-editable profile; Postgres + pgvector + BM25 hybrid retrieval with RRF; source citations/provenance; basic per-tenant isolation and trust tiers; MCP/CLI surface.
*Exit:* can capture, store losslessly, and retrieve with citations; "what did we believe on date X" works; user can inspect/correct/forget.

**Phase 2 — Advanced retrieval.** Query planner (fast/deep routing); temporal entity graph + Personalized-PageRank multi-hop; cross-encoder reranking; activation scoring (§7.4); MMR dedup + U-curve ordering + context budgeting; contradiction detection.
*Exit:* beats a strong full-context baseline on the private suite at a fraction of the tokens, with deep mode passing exhaustive-recall audits.

**Phase 3 — Personalization.** The six-category user model; explicit vs inferred preferences with scope/confidence/validity; context-sensitive packets; learning-from-user-mistakes as scoped support; full user-facing correction/forget controls.
*Exit:* measurably *applies* (not just recalls) current preferences; PersonaMem-style application accuracy improves; all adaptation reversible.

**Phase 4 — Procedural & corrective learning.** Trajectory logging; failure attribution; lesson distillation (Reflexion/ExpeL); workflow induction (AWM) and skill compilation (Voyager); the **promotion gate + regression suite + rollback**; sleep-time consolidation on a dedicated write-authorized consolidator.
*Exit:* the system demonstrably gets better at recurring task types over time, with every improvement validated and reversible; no regression on the protected suite.

**Phase 5 — Learned meta-policies (full self-optimization).** Learn retrieval routing, activation weights, ADD/UPDATE/DELETE/NOOP thresholds, ranking weights, and consolidation cadence from outcomes (Memory-R1 + reward densification), all gated and versioned, around the immutable invariant; optional parametric tier (§8.6).
*Exit:* internal policies improve against measured outcomes without human tuning, with monitored diversity/divergence and clean rollback.

---

## 16. How Mnemosyne surpasses its predecessors

### 16.1 The "best of everything" map (what each idea is borrowed from)

| Capability | Borrowed from | In Mnemosyne |
|---|---|---|
| Lossless verbatim episodic memory | MemPalace; event sourcing | Evidence ledger (§5.2) |
| Compressed pointer layer over verbatim | MemPalace (AAAK) | drawer/pointer split (§5.2) |
| Compiled current truth + timeline | GBrain | Semantic assertions (§5.3) |
| Hybrid retrieval + RRF + graph + rerank + `--explain` | GBrain | Retrieval engine (§7) |
| Markdown/git source of truth; zero-LLM entity wiring | GBrain | §12.3, §6.4 |
| Bi-temporal validity + edge invalidation | Zep/Graphiti | §5.3–5.4 |
| ADD/UPDATE/DELETE/NOOP write ops | Mem0 | §6.3 (extended) |
| Single-step multi-hop via Personalized PageRank | HippoRAG | §7.2 |
| Recursive summary trees | RAPTOR | §8.2, §10.4 |
| Late chunking; small-to-big | Jina; parent-doc | §6.5 |
| Activation scoring (base-level + spreading) | ACT-R; Generative Agents | §7.4 |
| Importance-triggered reflection that cites sources | Generative Agents | §8.2 |
| Workflow induction; skill library as code | AWM; Voyager | §5.5, §8.2 |
| Verbal reflection / experiential insights with voting | Reflexion; ExpeL | §5.7, §8 |
| Tool-grounded validation (no self-certification) | CRITIC | §8 (the one rule) |
| Sleep-time consolidation; write-authority split | Letta | §8.2 |
| Learned memory-management policy | Memory-R1 / Mem-T | §8.4 |
| Two-speed fast/slow memory | CLS (neuroscience) | §3.2, §8 |
| Adaptive forgetting / decay | Ebbinghaus; forgetting survey | §10 |
| Four-store taxonomy; prompt-as-procedural-memory; read-only planning | CoALA | §5, §4.2, §8 |
| Isolation + provenance/trust + data≠instruction | MINJA defenses; CaMeL; OWASP ASI06 | §11 |
| Token-budgeted tiered context; priority eviction | LlamaIndex; MemoryOS; context engineering | §5.1, §7.6 |

### 16.2 What is genuinely new

The **integration** is the contribution: a lossless evidence spine + multiple rebuildable typed projections + an activation-scored hybrid+graph retriever + a *recursive* three-loop learning system that improves both memory content **and** the policies that manage memory — all under a structurally-enforced safety invariant, strict bi-temporal provenance, and a precision-in-retrieval / completeness-in-storage split that finally reconciles "total recall" with "good retrieval." No existing system combines all of these; most do two or three well and ignore the rest.

### 16.3 Concrete advantages over GBrain and MemPalace specifically

- **Over MemPalace:** keeps its verbatim recall and low wake-up cost, but adds compiled current truth, a real (not metadata-only) temporal graph with contradiction handling, bi-temporal as-of queries, validated self-improvement, and a security model.
- **Over GBrain:** keeps its compiled truth + hybrid retrieval + graph + git-source-of-truth, but adds a lossless episodic spine underneath (so nothing is lost to compilation), the recursive learning loops, a typed user model, activation-based scoring, and explicit forgetting.
- **Over both:** the self-improvement is *validated and reversible* (regression gate + transitive rollback), the personalization is *typed and scoped*, and memory is treated as a *security control surface* — three things neither parent fully addresses.

---

## 17. Hard parts, resolutions, and honest limitations

A design is only as good as its weakest load-bearing mechanism. This section confronts the parts that are genuinely hard or that an earlier draft under-specified, gives each a concrete resolution, and ends with an honest maturity assessment so nothing is over-claimed. (These resolutions were added after an adversarial design review; they are the difference between a plausible diagram and a buildable system.)

### 17.1 Mid-session corrections must not wait for the offline gate

**Problem.** If all learning is offline (warm loop) and gated, a user who corrects the agent mid-conversation ("no, my manager is Alice now") would keep getting the stale fact for the rest of the session — the opposite of "adapts cleanly / learns from mistakes."

**Resolution — gate by *what is being written*, not by *when*.** The promotion gate exists to validate **derived/inferred** memory (lessons, workflows, policies, inferred preferences), not to second-guess the user. A **tier-0 direct user statement or correction is the highest-trust signal there is and is applied immediately**: it writes an active supersession synchronously in the same turn, and is held in working memory for the rest of the session regardless. Only derived memory takes the candidate → gate path. So: *direct user truth is fast and ungated; machine-inferred truth is gated.* This is also the correct trust-tier semantics (§11.1).

### 17.2 Rollback × bi-temporal supersession (the resurrection algorithm)

**Problem.** Assertions form supersession chains (v1 →cause C→ v2 →cause D→ v3). If you transitively roll back lesson/policy C, what happens to v2 (created under C) and to v1 (which v2 superseded)? Naïve "invalidate memories derived under C" can wrongly resurrect v1 or leave holes — re-introducing the very corruption the gate prevents.

**Resolution — rollback is *recomputation over the event log minus C*, not in-place patching.** Because the system is event-sourced, supersession is itself a logged event carrying its `cause`. To revert C:

1. Filter the event log to remove C's contributions (its writes and the supersessions it caused).
2. **Replay** the affected projection from the filtered log. v2 (caused only by C) disappears; v1 is reopened **only if** it was not subsequently superseded by an *independent* cause. In `v1 →C→ v2 →D→ v3`, reverting C must **not** resurrect v1, because v3 (cause D) is current truth; replay rebuilds the chain `v1 →D→ v3` directly.
3. Any assertion left with no surviving active version reverts to **unknown** and re-enters the candidate queue for re-derivation from evidence at the next consolidation.

This is always well-defined because projections are recomputed from the immutable log, never hand-patched. It is the single most important correctness mechanism and gets a dedicated integration-test class: "rollback that crosses a supersession edge."

### 17.3 Completeness vs the right to be forgotten

**Problem.** "Lossless forever" and "GDPR/right-to-erasure" are contradictory absolutes. A tombstone that keeps content is not erasure; one that nulls content breaks "always reconstructable" and orphans derived projections.

**Resolution — bound the guarantee and make erasure first-class.** The completeness guarantee is precisely *"lossless except for explicit user or legally-mandated erasure."* Erasure is distinct from supersession/decay:

- It **crypto-shreds** (or nulls) the evidence `content`, sets `erased=true`, and retains only non-personal integrity metadata (timestamps, a salted hash) — compliant because the content is irrecoverable.
- **Projection semantics:** a derived item whose `source_event_ids` are *entirely* erased is invalidated and recomputed-or-dropped via the §17.2 replay mechanism; one with *surviving independent corroboration* is retained with the erased source removed from its provenance (a fact independently supported may lawfully remain).
- "Always reconstructable" is therefore scoped to *non-erased* evidence; erasure is the one sanctioned, fully-audited exception.

### 17.4 The cost-bounded promotion gate

**Problem.** A gate that re-runs a monotonically growing regression suite per candidate is O(candidates × suite × LLM) — unbounded, and worse asymptotics than the A-MEM blow-up this design criticizes.

**Resolution — tiered, scoped, sampled, batched, capped.**

- **Tiered suite:** a small fixed **smoke set** (runs synchronously per batch) + a stratified **core set** (runs on batches, sampled with confidence intervals) + a **full archive** (runs nightly / pre-release only).
- **Scope to relevance:** only run cases whose failure-signature/scope overlaps the candidate (a retrieval-weight change is tested on retrieval cases, not on every case) → cost ∝ *affected* cases, not total suite size.
- **Batch, don't per-fact:** consolidation promotes in batches; the gate runs once per batch.
- **Cap growth:** dedupe cases by signature, cap per-signature counts, and age cases that have been green for K runs into a cheap archive tier. The suite grows in *coverage*, not raw count.

Net: gate cost is bounded per batch and sublinear in total corrections, and the expensive work is offline, scoped, and sampled — structurally unlike a per-write quadratic.

### 17.5 The fast-path latency budget (and what is demoted to deep mode)

**Problem.** An earlier reading put a per-query LLM "query-understanding" call, live Personalized-PageRank, and a 200-candidate cross-encoder all on the "fast" path — which would make fast mode take seconds. "Fast" was an adjective, not a budget.

**Resolution — set a target and remove LLM calls + graph analytics from the hot path.** Target: **fast-mode memory overhead P95 ≤ ~300–400 ms** before the agent starts generating.

- **Routing** (fast vs deep) uses a cheap classifier/heuristic on query features — **not** an LLM call. The LLM query-understanding step is **deep-mode only**.
- **Graph signal in fast mode is precomputed:** 1-hop neighbor expansion + **cached PPR vectors** refreshed during consolidation. Live multi-hop PPR is **deep-mode only**.
- **Rerank budget:** fast mode reranks ≤ 50 candidates with a small/distilled cross-encoder; listwise-LLM rerank (RankGPT) is **deep-mode only**.
- **Activation re-scoring** is cheap arithmetic over already-fetched candidates (the spreading term reads the cached PPR vector).

So **fast** = hybrid ANN + BM25 → RRF → cached-signal activation score → small cross-encoder (≤50) → MMR → assemble. **Deep** adds LLM planning, live PPR, query decomposition, listwise rerank, and exhaustive traversal — and is invoked only when the task needs it.

### 17.6 The invariant boundary, corrected

**Problem.** The cold loop was allowed to tune SUPERSEDE/DELETE thresholds and prune aggressiveness — but those are *safety-relevant*: a policy that learns "supersede aggressively" can raise the rate at which current truth is closed out, corrupting memory while staying inside the letter of the invariant.

**Resolution — mutation-rate controls are tunable only within immutable rails.** The invariant layer (outside the self-editable surface) fixes hard bounds: `max_supersession_rate`, `min_corroboration_for_delete`, `max_prune_fraction_per_pass`, and a **monotonic-trust rule** (an active fact may only be superseded by evidence of equal-or-higher trust tier). The cold loop may tune *within* these rails; it cannot widen them. A monitoring tripwire auto-rolls-back any policy change that spikes the mutation rate or contradiction backlog. The measuring apparatus **and** the safety rails are immutable; only the knobs inside them move.

### 17.7 One source of truth, two faces (evidence ledger vs git)

**Problem.** "Evidence ledger is the source of truth" and "markdown/git is the human-editable source of truth" looked like two competing sources of truth, and "git delete → DB soft-delete" looked like it let git mutate an append-only store.

**Resolution — there is exactly one source of truth (the evidence ledger); git is a human-facing *write surface* into it.** A human edit to a git file is **ingested as a tier-0 evidence event** ("human assertion"), then compiled like any other evidence. A git deletion emits a tier-0 **retraction event** appended to the ledger — never an in-place delete. "Human always wins" = tier-0 human events outrank machine inferences during conflict resolution (§6.3, §11). No dual source of truth; git is the highest-trust *input*.

### 17.8 Reconsolidation vs "planning is read-only"

**Problem.** §4.2 says planning/retrieval is read-only; §7.7 says every retrieval updates access counts and may flag update-on-recall. Retrieval happens during planning.

**Resolution — separate *truth* from *telemetry*.** Planning never mutates **truth** (assertions, edges, procedures, preferences). It may emit **append-only telemetry** (access counts, recency, update-on-recall flags) to a separate, non-authoritative metadata stream that can be replayed or discarded without affecting correctness. Auditability holds — every *truth* change is still a discrete, logged execution event; the testing-effect bookkeeping is explicitly classified as telemetry.

### 17.9 Local-first mode (who runs the consolidator on a laptop)

**Problem.** Sleep-time consolidation on a "separate write-authorized service" is a server construct with no obvious single-user analog, and per-tenant isolation is moot for one user.

**Resolution — same architecture, different deployment of the consolidator.** Locally, the consolidator is an **on-device idle job** (timer / machine-idle / app-close hooks, à la MemPalace's session-end filing), running the *same code* as the server consolidator but as a separate **process/role** rather than a separate service. Per-*tenant* isolation is moot single-user, but per-**source** trust tiers still matter (a scraped page on your laptop is still untrusted) and remain enforced. The warm loop can use a smaller local model; a single user generates little, so on-device sleep-time compute is cheap. The seed regression suite ships bundled + grows from the user's own corrections (§17.10).

### 17.10 Self-optimization and failure attribution — concrete design + honest scope

These are the most load-bearing and were the least specified. Concretely:

- **Regression-suite ignition (the bootstrap).** The gate can't run with an empty suite, and corrections don't exist on day one. Resolution: ship a **seed suite** = (1) a curated, trusted held-out set (partly public-derived — used *only* internally as a gate, never reported as a score, consistent with §14's stance), + (2) **synthetic cases auto-generated** from the user's earliest episodes, + (3) **shadow mode**: until the suite reaches size N, candidates are *not* promoted to active — they run in shadow, their predictions logged against real outcomes, accumulating the first genuine cases. Learning ignites in shadow; "active" promotion switches on at size N. (Resolves the cold-start circularity.)
- **Self-optimization method.** The cold loop optimizes a small set of **discrete policy variants** (routing rules, threshold values, ranking-weight presets) — not free-form code — via **contextual bandits / offline RL on logged trajectories**, with reward = measured downstream task success on the scoped, sampled suite, and reward densification over the memory-op sequence to handle delayed credit. Each variant passes the §8.3 gate and runs in shadow before promotion. The search space is small, so sample complexity is modest (Memory-R1 reports gains from ~150 examples — directional, recent/unverified citation).
- **Failure attribution.** Route a failed trajectory to a lesson type via a **diagnostic checklist** run automatically over the log: *was the needed evidence retrieved? ranked into context? correct? did the tool succeed? did reasoning use it?* Each is a cheap check; the result is a **hypothesis** (the attribution literature tops out near ~50% on agent-of-blame), so the lesson it yields is itself gated. Counterfactual replay (re-run with the hypothesized fix) raises confidence when affordable.

### 17.11 Honest maturity assessment

Not every property is equally proven. Build order and claims should reflect this:

| Property / capability | Maturity | Why |
|---|---|---|
| Self-adapting (typed preferences + context) | **Delivered — engineering** | §9; known components, buildable today |
| Lossless recall + precise retrieval (bounded by erasure) | **Delivered — engineering** | §5.2/§7/§17.3; well-trodden |
| Clean updates (bi-temporal + gate + rollback) | **Engineering + applied research** | correctness hinges on §17.2/§17.4 being implemented carefully |
| Self-learning (episodic→semantic, skill/workflow induction) | **Applied research** | mechanism is clear; *quality* depends on extraction/induction tuning |
| Learns from mistakes (own + user) | **Applied research** | failure attribution is a gated hypothesis (§17.10), not solved |
| Self-improving (validated lessons) | **Applied research** | depends on suite ignition (§17.10) |
| Self-optimizing / recursive (learned meta-policies) | **Research-track** | design is sound and rail-guarded, but gains are unproven at this combination; build behind shadow mode, opt-in, and measure before claiming |

The system is **fully useful at Phase 3** (lossless memory + great retrieval + personalization — all engineering) and becomes **recursive/self-optimizing at Phase 5** (research-track). The honest framing: Mnemosyne *guarantees* the storage/retrieval/personalization properties and *pursues* the self-optimizing ones under strict safety rails — it does not pretend Phase 5 is a solved commodity.

---

## Appendix A — Reference SQL schema

The core tables appear inline in §5 (`evidence`, `assertions`, `entities`, `entity_aliases`, `relations`, `procedures`). The remaining supporting tables:

```sql
CREATE TABLE preferences (
  pref_id UUID PRIMARY KEY, tenant_id UUID, user_id UUID NOT NULL,
  category TEXT NOT NULL,           -- identity|hard|explicit|inferred|situational|temporary
  statement TEXT NOT NULL, scope JSONB, confidence REAL NOT NULL,
  exceptions JSONB, source_event_ids UUID[] NOT NULL,
  valid_from TIMESTAMPTZ NOT NULL, valid_to TIMESTAMPTZ,
  status TEXT DEFAULT 'active', version INT DEFAULT 1, superseded_by UUID
);
CREATE TABLE lessons (
  lesson_id UUID PRIMARY KEY, tenant_id UUID, user_id UUID,
  lesson_type TEXT NOT NULL,        -- retrieval|ranking|reasoning|tool|execution|preference|stale_memory
  failure_signature TEXT, content TEXT NOT NULL,
  votes INT NOT NULL DEFAULT 2,     -- ExpeL-style; 0 => prune
  status TEXT DEFAULT 'candidate', validated_by UUID,
  source_event_ids UUID[] NOT NULL, embedding VECTOR(1024),
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE trajectories (
  trajectory_id UUID PRIMARY KEY, tenant_id UUID, user_id UUID, session_id UUID,
  task TEXT, steps JSONB NOT NULL,  -- reason/act/observe trace
  outcome TEXT, reward REAL, memory_version_id UUID,  -- correlate outcome to memory state
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE contradictions (
  id UUID PRIMARY KEY, tenant_id UUID,
  assertion_a UUID, assertion_b UUID, detected_at TIMESTAMPTZ DEFAULT now(),
  status TEXT DEFAULT 'open', resolution TEXT
);
CREATE TABLE resources (
  resource_id UUID PRIMARY KEY, tenant_id UUID, kind TEXT, uri TEXT NOT NULL,
  version INT DEFAULT 1, content_hash BYTEA, metadata JSONB, access_policy JSONB
);
CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY, tenant_id UUID, actor TEXT, op TEXT,
  target_id UUID, trust_tier SMALLINT, diff JSONB, at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE eval_cases (              -- the private regression suite
  case_id UUID PRIMARY KEY, tenant_id UUID, origin TEXT,  -- 'user_correction' | 'resolved_failure'
  query TEXT, gold JSONB, protected BOOLEAN DEFAULT true, added_at TIMESTAMPTZ DEFAULT now()
);
```

## Appendix B — Key algorithms

**B.1 Activation score (retrieval re-ranking, §7.4)**

```
score(m, q) = w_b·ln(Σ_k age(access_k)^(-d))          # base-level (ACT-R)
            + w_s·ppr(m, seeds(q))                      # spreading activation over graph
            + w_i·salience(m)                           # importance (decays, §10)
            + w_r·rrf_relevance(m, q)                   # fused dense+lexical rank
            + ε                                          # small noise
stop when marginal_gain(next) < retrieval_cost          # ACT-R C>pG → dynamic top-k
# w_*, d are config in Phase 1; learned (gated) in Phase 5.
```

**B.2 Write decision (§6.3)**

```
for each candidate fact c extracted from new evidence e:
    neighbors = semantic_search(c, k=8) ∩ same_subject
    op = decide(c, neighbors)            # rules+LLM (P1) → learned policy (P5)
    case ADD:        insert(status=candidate); enqueue_gate()
    case UPDATE:     new_version(neighbor, c); link superseded_by
    case SUPERSEDE:  if valid_time(c) > valid_time(neighbor):
                         close(neighbor.valid_to, neighbor.expired_at); insert(c)
                     else: open_contradiction(c, neighbor)
    case NOOP:       drop(c)                              # dedup
    case DELETE:     require_corroboration(); tombstone(); propagate_to_indexes()
    case QUARANTINE: insert(status=quarantined)           # low trust / unresolved
```

**B.3 Consolidation pass (warm loop, §8.2)**

```
episodes = ledger.recent_or_prioritized(weight=importance·novelty·surprise·reward)
for cluster in cluster(episodes):
    promote_episodic_to_semantic(cluster)     # via B.2
    induce_workflow_if_repeated_success(cluster) -> candidate procedure
    distill_lesson_if_failure(cluster)           -> candidate lesson (failure_signature)
resolve_contradictions(); refresh_entity_summaries(); maybe_build_raptor_tree()
decay_salience(all); prune(stale ∨ superseded ∨ low_salience) with pointer_to_evidence
update_user_model(repeated_preference_signals)
# every candidate must pass the promotion gate (B.4) before status=active
```

**B.4 Promotion gate (§8.3)**

```
gate(candidate):
    assert candidate.source ∩ regression_suite == ∅      # no teaching-to-the-test
    base   = run(regression_suite, memory=current)
    trial  = run(regression_suite, memory=current + candidate)
    if trial.aggregate ≥ base.aggregate − ε_noise and no_protected_regression(base, trial):
        promote(candidate, validated_by=run_id, versioned=true)
        monitor(proxy_vs_true, diversity)
    else: reject(candidate)
# rollback is transitive: revert(candidate) ⇒ invalidate(memories_derived_under(candidate))
```

## Appendix C — References

Grouped by theme. Vendor-authored papers are marked **[vendor]**; figures not independently reproduced are **[unverified]**. (The benchmark-integrity caveats of §2.5/§14 apply throughout.)

**Cognitive science & cognitive architectures**
- Atkinson & Shiffrin (1968), multi-store model. Baddeley & Hitch (1974); Baddeley (2000), working memory.
- Tulving (1972, 1985), episodic/semantic. Squire (1992, 2004), declarative/non-declarative — https://pubmed.ncbi.nlm.nih.gov/22141588/
- McClelland, McNaughton & O'Reilly (1995), Complementary Learning Systems — http://wixtedlab.ucsd.edu/publications/Psych%20218/McClellandMcNaughtonOReilly95.pdf
- Kumaran, Hassabis & McClelland (2016), CLS updated for AI — https://web.stanford.edu/~jlmcc/papers/KumaranHassabisMcC16CLSUpdate.pdf
- Ebbinghaus forgetting curve (Murre & Dros 2015 replication) — https://pmc.ncbi.nlm.nih.gov/articles/PMC4492928/
- "Forgetting" in ML: a survey (Wang et al. 2024) — https://arxiv.org/abs/2405.20620
- Collins & Loftus (1975), spreading activation. Tulving & Thomson (1973), encoding specificity.
- Anderson & Schooler (1991) / ACT-R activation & base-level learning — http://act-r.psy.cmu.edu/
- CoALA — Cognitive Architectures for Language Agents (Sumers, Yao, Narasimhan, Griffiths 2023) — https://arxiv.org/abs/2309.02427

**Agent-memory surveys & systems**
- Survey on the Memory Mechanism of LLM-based Agents (Zhang et al. 2024) — https://arxiv.org/abs/2404.13501
- Rise and Potential of LLM-Based Agents (Xi et al. 2023) — https://arxiv.org/abs/2309.07864
- Memory in the Age of AI Agents (2025) — https://arxiv.org/abs/2512.13564 [unverified — very recent]
- Memory for Autonomous LLM Agents: Mechanisms, Evaluation, Frontiers (Du 2026) — https://arxiv.org/abs/2603.07670 [unverified — very recent]
- Generative Agents (Park et al., UIST 2023) — https://arxiv.org/abs/2304.03442
- MemGPT / Letta (Packer et al. 2023) — https://arxiv.org/abs/2310.08560
- Mem0 (2025) **[vendor]** — https://arxiv.org/abs/2504.19413
- Zep / Graphiti (Rasmussen et al. 2025) **[vendor]** — https://arxiv.org/abs/2501.13956
- A-MEM (agentic Zettelkasten memory, 2025) — https://arxiv.org/abs/2502.12110
- MemoryOS (EMNLP 2025) — https://arxiv.org/abs/2506.06326
- Cognee, LangMem/LangGraph Store, LlamaIndex Memory, Supermemory, Memary — official repos/docs (see §2.4).

**Retrieval**
- Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009) — https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf
- Fusion functions for hybrid retrieval (Bruch et al. 2022) — https://arxiv.org/abs/2210.11934
- ColBERT (2020) / ColBERTv2 (2021) / PLAID (2022) — https://arxiv.org/abs/2004.12832
- RankGPT (Sun et al., EMNLP 2023) — https://aclanthology.org/2023.emnlp-main.923/
- Self-RAG — https://arxiv.org/abs/2310.11511 · CRAG — https://arxiv.org/abs/2401.15884 · Adaptive-RAG — https://arxiv.org/abs/2403.14403 · HyDE — https://arxiv.org/abs/2212.10496 · RAG-Fusion — https://arxiv.org/abs/2402.03367
- GraphRAG (Edge et al. 2024) — https://arxiv.org/abs/2404.16130 · HippoRAG / HippoRAG 2 — https://arxiv.org/abs/2405.14831 , https://arxiv.org/abs/2502.14802 · LightRAG — https://arxiv.org/abs/2410.05779
- Late Chunking (Jina 2024) — https://arxiv.org/abs/2409.04701 · Dense X / propositions — https://arxiv.org/abs/2312.06648 · Chroma chunking eval — https://research.trychroma.com/evaluating-chunking
- RAPTOR (ICLR 2024) — https://arxiv.org/abs/2401.18059
- Lost in the Middle (Liu et al. 2023) — https://arxiv.org/abs/2307.03172 · Context Rot (Chroma 2025) — https://research.trychroma.com/context-rot · The Power of Noise (Cuconasu et al., SIGIR 2024) — https://arxiv.org/abs/2401.14887 · MMR (Carbonell & Goldstein 1998)
- Effective context engineering for AI agents (Anthropic 2025) — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

**Self-improvement & learning**
- Reflexion (Shinn et al. 2023) — https://arxiv.org/abs/2303.11366 · Self-Refine — https://arxiv.org/abs/2303.17651 · CRITIC — https://arxiv.org/abs/2305.11738
- ExpeL (AAAI 2024) — https://arxiv.org/abs/2308.10144 · Agent Workflow Memory — https://arxiv.org/abs/2409.07429 · Voyager — https://arxiv.org/abs/2305.16291
- STOP — https://arxiv.org/abs/2310.02304 · Gödel Agent — https://arxiv.org/abs/2410.04444 · Promptbreeder — https://arxiv.org/abs/2309.16797 · SELF — https://arxiv.org/abs/2310.00533
- Memory-R1 (2025) — https://arxiv.org/abs/2508.19828 [unverified — recent] · Sleep-time Compute (Letta 2025) — https://arxiv.org/abs/2504.13171
- APE — https://arxiv.org/abs/2211.01910 · OPRO — https://arxiv.org/abs/2309.03409 · DSPy MIPROv2 — https://dspy.ai/api/optimizers/MIPROv2/
- Let's Verify Step by Step (Lightman et al. 2023) — https://arxiv.org/abs/2305.20050 · Generative Verifiers — https://arxiv.org/abs/2408.15240
- AI models collapse on recursively generated data (Shumailov et al., Nature 2024) — https://www.nature.com/articles/s41586-024-07566-y
- Sycophancy to Subterfuge: reward tampering (Anthropic 2024) — https://arxiv.org/abs/2406.10162 · Specification gaming (DeepMind) · Concrete Problems in AI Safety (2016) — https://arxiv.org/abs/1606.06565
- EWC / catastrophic forgetting (Kirkpatrick et al., PNAS 2017) — https://www.pnas.org/doi/10.1073/pnas.1611835114 · Test-Time Training (Sun et al. 2019/2020) — https://arxiv.org/abs/1909.13231

**Benchmarks & security**
- LongMemEval (ICLR 2025) — https://arxiv.org/abs/2410.10813 · LoCoMo (ACL 2024) — https://arxiv.org/abs/2402.17753 · PersonaMem (COLM 2025) — https://arxiv.org/abs/2504.14225 · MemoryAgentBench (2025) — https://arxiv.org/abs/2507.05257 · MSC (ACL 2022) — https://arxiv.org/abs/2107.07567
- LoCoMo audits — https://github.com/dial481/locomo-audit · https://penfieldlabs.substack.com/p/we-audited-locomo-64-of-the-answer · Letta memory benchmarking — https://www.letta.com/blog/benchmarking-ai-agent-memory/
- MINJA: Memory Injection Attack (NeurIPS 2025) — https://arxiv.org/abs/2503.03704 · AgentPoison — https://arxiv.org/abs/2407.12784 · PoisonedRAG — https://arxiv.org/abs/2402.07867
- OWASP ASI06 Memory & Context Poisoning — https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/ · CaMeL — https://simonwillison.net/2025/Apr/11/camel/ · Spotlighting — https://arxiv.org/pdf/2403.14720

> **Verification note.** Foundational citations (CLS, ACT-R, CoALA, RRF, ColBERT, Lost-in-the-Middle, Power-of-Noise, RAPTOR, Reflexion, Voyager, STOP, Nature-2024 collapse, MINJA, LongMemEval/LoCoMo) were confirmed against primary sources during research. A handful of 2026-dated arXiv identifiers surfaced by automated search are marked **[unverified]** and should be re-confirmed before formal citation; their *conceptual* contributions corroborate the established literature and are safe to rely on directionally. GBrain/MemPalace architecture details follow the user-provided transcript plus verified public descriptions; specific recency-sensitive facts (exact dates, star counts) were deliberately not asserted.

## Appendix D — Glossary

- **Bi-temporal** — modeling two independent time axes: *valid time* (true in the world) and *transaction time* (known to the system).
- **CLS** — Complementary Learning Systems; fast hippocampal episodic learning + slow neocortical semantic consolidation.
- **CQRS / Event Sourcing** — separate the append-only event log (writes) from rebuildable read-optimized projections (reads).
- **Consolidation** — the offline process that compiles episodes into semantic facts, skills, and lessons (the "warm loop").
- **Drawer / Pointer** — verbatim content chunk vs. its compressed symbolic index entry (from MemPalace's AAAK).
- **Promotion gate** — the held-out regression test a candidate memory must pass before becoming active.
- **Reconsolidation** — the read-write nature of recall: retrieving a memory can strengthen or correct it.
- **RRF** — Reciprocal Rank Fusion; rank-based merge of multiple retrievers, robust to incomparable scores.
- **Salience** — a per-memory importance/strength score that decays over time and boosts on access.
- **Trust tier** — provenance class (0 = direct user … 5 = untrusted external) governing what a memory may influence.

---

*End of specification v1.0. This is a design document, not an implementation; the schemas and algorithms are reference designs to build from. The architecture is deliberately model-agnostic and stack-portable (local PGLite ↔ production Postgres) so it can grow from a single-user brain to a multi-tenant service without a rewrite.*
