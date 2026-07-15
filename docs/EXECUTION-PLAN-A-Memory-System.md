# Mnemosyne — Execution Plan A: The Memory System
## Goal: the world's best-performing AI memory system

**Version:** 1.3 · **Date:** 2026-07-13 · **Status:** In Progress (approved)
**Scope:** the Mnemosyne engine and its capabilities (`src/mnemosyne/`, plus engine-side `eval/` regression suites).
**Companion doc:** *Execution Plan B — Benchmarking & the Leaderboard* owns measurement, publication, and the public leaderboard. This plan builds the capabilities; Plan B proves and publishes them. Where this plan says "measured/published," the authority is Plan B.
**Audience:** an autonomous engineering agent (or fleet) executing end-to-end, plus human operators for gated evidence capture.

**Live execution routing:** Approval is recorded. Phase 12 owns S1
and is executing Plan 12-04; S2, S3, S4, and the non-gating S5 research track
are scheduled in Phase 15. `.planning/STATE.md`, `.planning/ROADMAP.md`, and
`.planning/REQUIREMENTS.md` are the authoritative live trackers. The aggregate
checklist in this document closes only when its named artifacts and measured
DoDs exist; implementation progress alone does not check a box.

---

## 0. How to use this document (executing agent, read first)

Execution spec, not prose. Work top-to-bottom within a phase; respect the dependency map (§6). Every task has a stable ID (`S1.2`), a **Definition of Done (DoD)**, and required **artifacts**. Nothing is done without its artifacts.

**Hard guardrails (violating any = stop and escalate):**

1. **Do not break the §31 invariant rails or the 5 §33 test classes.** All existing `eval/` gates and `tests/` stay green. This work is **additive** to the attested v1.0 system.
2. **Capability first, claims later.** This plan makes the system *better*; it does not publish numbers. All external claims flow through Plan B's Public-Benchmark Publication Protocol (PBPP). No headline claims originate here.
3. **All perf/scale numbers require measured evidence** per the existing §11 "measurement-gap register." No asserted-but-unmeasured values.
4. **Provenance & capability checks apply to every new write path** (text, media, activation-level). Retrieved content is treated as data, never executed (§31 R6). New memory modalities inherit the same rails.
5. **Model-agnostic core.** Keep the minimal-dependency philosophy (core requires only `cryptography`); new heavy deps go behind optional extras or the sidecar/`services/` layer, never into core.

**Ground-truth references (source of truth over this doc if they conflict):**
`docs/ARCHITECTURE-OVERVIEW.md`, `docs/ENGINE-CONTRACT.md`, `docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md` (Waves A–E, §9.2.7, §11), `docs/superpowers/specs/2026-07-13-8gb-full-capability-unblock-design.md`, `.planning/STATE.md`, `.planning/codebase/{ARCHITECTURE,STACK,STRUCTURE}.md`, `eval/README.md`.

**DoD template:** *Code merged + all existing gates green + new regression cell added + artifacts written to the named path + one-paragraph result note in `eval/reports/`.*

---

## 1. Objective & success criteria (capability targets)

The system is "best-performing" when it hits these **capability** targets. Their *measurement and publication* are Plan B's job (via `eval/public/` + PBPP); this plan is responsible for making them true.

| # | Capability | Signal (measured by Plan B) | Target |
|---|---|---|---|
| S-i | Elite retrieval | Deterministic Recall@k / nDCG on public suites | Top-tier (≥ best published no-LLM score) |
| S-ii | Multi-hop associative recall | Deterministic R@2/@5 + EM/F1 on multi-hop sets | Meet/beat HippoRAG 2 baselines |
| S-iii | **Multi-hop answer synthesis (the gap)** | LLM-judged QA (disclosed reader) | Current protected `qa_hard_v2` EM/F1 = 0.0833 → **≥ 0.85** |
| S-iv | Security under attack | Attack-success-under-defense on MINJA/AgentPoison/PoisonedRAG | Best-in-field; publishable |
| S-v | Calibration | ECE + abstention vs public labels | Best-in-field; publishable |
| S-vi | Credible at scale | Warm **and** concurrent P95; 100k-item cells | Measured distributions |

**What "best" does *not* mean here:** it does not mean winning a contested board like LoCoMo, and it does not mean any self-defined internal metric being presented as a public result. Those are Plan-B guardrails; this plan simply builds real capability.

---

## 2. The eclectic architecture synthesis (best ideas → mapped to what Mnemosyne already has)

Mnemosyne already implements a large share of the field's best ideas. This table is the design ledger; **priority = benchmark ROI**. Full source citations in Appendix A.

| Capability | Best external idea(s) | Source | Mnemosyne today | Action | Prio |
|---|---|---|---|---|---|
| Two-tier episodic↔semantic | Complementary Learning Systems | McClelland/Kumaran/Hassabis | Evidence ledger (episodic) + typed projections (semantic) — already CLS-shaped | **Keep**; frame explicitly | — |
| Associative recall | Graph index + Personalized PageRank | HippoRAG / HippoRAG 2 | **Have it** (`algorithms.ppr_power_iteration`, `graph_ppr_cache`) | **Extend** (HippoRAG2 deeper passage integration) | High |
| Hierarchical sensemaking | Community summaries | Microsoft GraphRAG | RAPTOR gist tree in `summarizer` | **Keep**; add global map-reduce query mode | Med |
| Multi-hop answer synthesis | Iterative retrieve→read; reader model | HippoRAG2, LongMemEval readers | **Weak spot** (v17/v18 protected `qa_hard_v2` EM/F1 = 0.0833) | **Build** — the #1 lever (§3, S1) | **Top** |
| Consolidation loop | Offline replay + distillation ("sleep/dreaming") | Google "Sleep", OpenAI Dreaming | 11-role warm loop (`replayer…user_model_updater`) | **Keep**; add async batch "sleep" job | Med |
| Multi-timescale memory | Continuum Memory System (freq-staggered modules) | Google Nested Learning / Hope | Single warm-loop cadence | **Extend** — spectrum of update rates → anti-forgetting | High |
| Write gating | Surprise (gradient magnitude) | Titans; EM-LLM (Bayesian surprise) | Promotion gate + mutation budget | **Extend** — surprise signal into `promotion_gate` | Med |
| Episodic segmentation | Event boundaries + temporal-contiguity retrieval | EM-LLM | Bitemporal, but no event-segmented recall | **Add** — episode boundaries + temporal-adjacency reads | High |
| Forgetting / deletion | One-shot selective forget; adaptive decay | Larimar; Titans; ACT-R | Fidelity tiers + crypto-shred + optional ACT-R decay | **Keep** (already best-in-class) | — |
| Durable parametric facts | Localized weight edits; sparse KV memory layers | MEMIT; Meta Memory Layers | Parametric tier (LoRA/TTT, `parametric.py`) | **Extend** — evaluate MEMIT-style edits as a write path | Low |
| Compiled context | Offline-trained reusable KV cache | Cartridges (Stanford) | None | **Research** — per-tenant "cartridge" for hot corpora | Med |
| Retrieval/param split | Small model + huge swappable DB | RETRO | Already retrieval-first over Postgres | **Keep** | — |
| Bounded working memory | Compressive per-layer memory; memory tokens | Infini-attention; RMT | N/A (model-agnostic) | **Skip** (model-internal, out of scope) | — |
| **Activation-space memory + introspection** | J-space / global workspace, persona vectors, SAE features | **Anthropic** (§3.5) | None | **Research track** — calibration + security differentiator | Med |
| Agent memory API contract | `/memories` file ops + context editing + compaction | Anthropic memory tool / context engineering | `mneme` CLI + 48 MCP tools | **Align** the MCP memory surface to this contract | Med |

---

## 3. Phased build

### S1 — Close the multi-hop answer-synthesis gap (**top priority, critical path**)
Retrieval is already strong, but the latest protected v17/v18 reader runs
answered only 2/24 and scored EM/F1 0.0833. The older ≈0.62 figure came from a
different pre-custody evaluator and is not the current Phase 12 baseline.
Grounded synthesis remains the single highest-ROI capability, while the
independent LongMemEval-QA, graph/PPR, retrieval, §31, and §33 gates remain
separate exit conditions.

- **S1.1 Iterative retrieve→read loop.** Query decomposition → PPR spreading-activation hops over the existing graph → evidence assembly, reusing the hybrid retriever (dense + BM25 + PPR + RRF/MMR). Borrow HippoRAG 2's deeper passage integration.
- **S1.2 Grounded reader/synthesis step.** A disclosed self-hosted reader answers *only* from retrieved, provenance-tagged evidence; fail-closed, retrieved text handled as data (§31 R6). The default implementation is an extractive span/no-answer reader whose output is reconstructed and revalidated by the host. A generative role-LLM is permitted only as a separately disclosed comparison track and may not replace the extractive rail. Every claim must trace to an evidence CID.
- **S1.3 Episode-aware recall.** Add EM-LLM-style event boundaries + temporal-contiguity reads so synthesis pulls coherent episodes, not fragments.
- **DoD:** `qa_hard_v2` and (via Plan B) the held-out LongMemEval-QA public-dataset/internal-only track ≥ 0.85; per-hop retrieval traces prove groundedness; no regression on deterministic recall. Targets S-iii.

### S2 — Capability upgrades (by benchmark ROI)
- **S2.1 Multi-timescale consolidation spectrum** (Nested Learning CMS): parameterize the warm loop into fast/medium/slow cadences so new writes never overwrite semantic structure at once. DoD: continual-learning regression shows reduced forgetting.
- **S2.2 Async "sleep" consolidation job** (Google Sleep / OpenAI Dreaming): offline replay + distillation of durable facts into slower tiers, plus **temporal freshness / auto-expiry** so facts age correctly ("going to X" → "went to X"). DoD: staleness metric + freshness regression test.
- **S2.3 Global map-reduce query mode** (GraphRAG) over the RAPTOR tree for "themes across everything" questions. DoD: sensemaking eval cell.
- **S2.4 Surprise-gated writes** (Titans/EM-LLM): route a surprise signal into `promotion_gate` so high-information events are preferentially consolidated. DoD: write-precision/recall cell.
- **S2.5 (Research) Cartridges** — offline-compiled per-tenant KV cache for hot corpora. DoD: latency/throughput A/B vs retrieval baseline; go/no-go note.

### S3 — Security & calibration capabilities (differentiators)
Build the capability here; **publish via Plan B** (these fill columns no competitor fills).
- **S3.1 Expand the adversarial corpus.** Grow the 59-attack `poison_suite.json` to full MINJA + AgentPoison + PoisonedRAG threat models; implement/verify defenses so the metric is **attack-success-under-defense**, not just block-rate. DoD: adversarial report + regression gate.
- **S3.2 Calibration hardening.** Ensure the conformal-calibration/abstain layer produces reliability diagrams + ECE that hold up against *public* benchmark labels (not only the private set). DoD: reliability artifacts consumable by Plan B's bundle.

### S4 — Performance / scale close-out (Phase 9 / Waves B–D)
Clear the §11 measurement-gap register so capability claims are credible at scale:
- **S4.1** Provider bake-off + default selection (TEI vs sidecar vs ONNX) — resolve `eval/provider_bakeoff/` (protocol exists, results don't).
- **S4.2** Null-embedding production backfill evidence.
- **S4.3** halfvec / pgvectorscale DiskANN; 100k-item benchmark cells.
- **S4.4** **Concurrent** P95 (not just warm-serial 149.5 ms) — resolve the known CPU-embed bottleneck.
- **S4.5** **Physical 8 GiB compact grounded-QA path.** Shadow-bake off the pinned extractive reader/reranker pairs behind the optional Rust/ONNX sidecar boundary. The extractive span/no-answer reader remains the mandatory default rail; only if preregistered evidence requires it may an additive compact synthesis rung be evaluated under the same quality, custody, and physical-resource gates. `qwen3:0.6b` is a hypothesis, not a selected component. DoD: `.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md` passes on physical 8 GiB x86-64 AVX2 Windows and Linux systems without lowering CAP-003, retrieval, §31, or §33 gates; no ML dependency enters Python core. Stronger profiles may add capacity, never weaker quality or custody.
- **DoD:** measured distributions in `eval/latency*` and `eval/provider_bakeoff/`; §11 register and S4.5 physical-floor acceptance closed. Targets S-vi.

### S5 — Research track: activation-space memory & introspection (off critical path)
See §3.5 (below). Requires white-box access to open-weight models — feasible via the self-hosted Ollama role-LLMs. Explicitly labeled research; not gating Goal-A capability targets.

### 3.5 The Anthropic introspection / "J-space" track (novel differentiator)
Anthropic's 2025–26 interpretability line is directly usable — with strict **epistemic humility**: we make *functional* claims, never consciousness claims.

- **J-lens / global workspace** (Anthropic, Jul 2026; `github.com/anthropics/jacobian-lens`): a readable list of "words on the model's mind but not said." **Use:** log a compact J-lens readout as an activation-trace on the consolidation path; use it as a **poisoning/deception tripwire** (evaluation-awareness, fabrication markers).
- **Introspective awareness** (Lindsey, Oct 2025) via concept injection: self-reports are a **weak (~20% reliable), calibratable** signal. **Use:** feed gated introspective confidence into the conformal-calibration/abstain layer — never as sole ground truth.
- **Persona vectors** (Anthropic, Aug 2025; arXiv 2507.21509): activation directions for traits via contrastive prompting. **Use:** rolling projection = drift-detection for the user-model/consolidation loop; screen candidate memories/adapter data before persistence.
- **SAE features** (Scaling Monosemanticity): stable inspectable concept vocabulary. **Use:** tag memories by active interpretable features → activation-space retrieval + audit.
- **Dual-use warning:** concept injection *is* memory poisoning (the false-intention "bread" experiment). Any activation-level write path carries provenance + capability checks exactly like text (guardrail #4).
- **DoD:** `research/activation-memory/` spike with (1) J-lens tripwire on the Ollama role-LLM, (2) a persona-vector drift metric in the ops dashboard, (3) a written go/no-go on promoting any of it to core.

---

## 4. Cross-cutting: verification & quality
- Every capability change adds a **regression cell** to `eval/` and keeps all §33 classes green.
- No capability is "done" on a single run — point estimates carry Wilson/bootstrap CIs (existing harness convention).
- Capability numbers stay **internal** until Plan B's PBPP + third-party reproduction clear them for any external claim.

## 5. Risk register (system-specific)
| Risk | Mitigation |
|---|---|
| Multi-hop synthesis underperforms 0.85 | S1 is critical path + gated; if short, ship deterministic-retrieval strength and iterate — never overclaim |
| New modality breaks a §31 rail | Additive-only; every write path re-runs the rail regression before merge |
| Heavy deps creep into core | Sidecar/optional-extra discipline (guardrail #5) |
| Activation track over-interpreted as "consciousness" | Functional-signal framing only; research-labeled; off critical path |
| Scale numbers asserted not measured | §11 register must be closed (S4) before any scale claim |

---

## 6. Timeline, roles, dependency map

**Critical path (bold):**
1. **S1 multi-hop synthesis** — weeks 1–6 (top lever).
2. S2 capability upgrades ∥ S3 security/calibration — weeks 3–9.
3. **S4 perf/scale close-out** — weeks 5–11.
4. S5 / §3.5 activation research — parallel, off critical path.

**Dependencies:** S1 unblocks S-iii; S3/S4 feed Plan B's artifact bundle; the public harness that *measures* all of this is **Plan B §3 (`eval/public/`)** — coordinate the shared eval core (serialize writes to it).

**Roles:** *core-eng agent* (S1–S2), *ml agent* (S1 reader, S5 research), *sec agent* (S3.1), *infra agent* (S4). Run independent phases as parallel sub-agents.

### Definition-of-Done checklist (Plan A)
- [ ] Multi-hop QA ≥ 0.85 with grounded per-hop traces (S1).
- [ ] Multi-timescale consolidation + async sleep job + freshness/expiry live (S2).
- [ ] Global map-reduce query mode + surprise-gated writes shipped (S2).
- [ ] Adversarial corpus expanded; attack-success-under-defense capability ready for publication (S3.1).
- [ ] Calibration reliability artifacts hold vs public labels (S3.2).
- [ ] §11 measurement-gap register closed: concurrent+warm P95, 100k cells, provider default (S4).
- [ ] Compact grounded-QA stack passes physical 8 GiB Windows/Linux acceptance with unchanged quality/custody gates (S4.5).
- [ ] Activation-memory research spike + go/no-go note (S5).
- [ ] All §31 rails and §33 classes green throughout.

---

## Appendix A — Frontier-lab source map (architecture ideas)
Titans (arXiv 2501.00663), Infini-attention (2404.07143), Nested Learning/Hope (2512.24695), Google "Sleep" (2606.03979), Memorizing Transformers (2203.08913), RETRO (2112.04426), Meta Memory Layers (2412.09764), Larimar/IBM (2403.11901), Microsoft GraphRAG (2404.16130), MEMIT (2210.07229), HippoRAG / HippoRAG 2 (2405.14831 / 2502.14802), EM-LLM (2407.09450), Test-Time Training (2407.04620), Cartridges (2506.06266), CLS theory (Kumaran/Hassabis/McClelland 2016).
**Anthropic:** global workspace / J-lens (transformer-circuits.pub/2026/workspace; github.com/anthropics/jacobian-lens), introspective awareness (transformer-circuits.pub/2025/introspection), persona vectors (2507.21509), scaling monosemanticity (2024), memory tool + context engineering (platform.claude.com docs; anthropic.com/engineering/effective-context-engineering-for-ai-agents).

## Appendix B — Dependency on Plan B
Plan B (*Benchmarking & the Leaderboard*) owns: the `eval/public/` harness that measures S-i…S-vi, the Public-Benchmark Publication Protocol (PBPP) that governs any external claim about this system, the reproducibility artifact bundle, third-party reproduction, and the neutral leaderboard on which Mnemosyne is entered. This plan produces capabilities; Plan B proves and publishes them.

*This plan is additive to the attested v1.0 system. It does not modify the §31 rails or §33 gates.*
