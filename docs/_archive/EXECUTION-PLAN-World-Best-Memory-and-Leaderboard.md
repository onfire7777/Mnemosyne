# Mnemosyne — Master Execution Plan
## Goal: the world's best-benchmarked AI memory system + the field's neutral benchmark leaderboard

> **SUPERSEDED (2026-07-08).** This combined plan was split into two active documents: [Execution Plan A — The Memory System](../EXECUTION-PLAN-A-Memory-System.md) (builds the capabilities) and [Execution Plan B — Benchmarking & the Leaderboard](../EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md) (measurement, publication protocol, and the neutral leaderboard). Retained verbatim below for history — do not execute from this document.

**Version:** 1.0 · **Date:** 2026-07-08 · **Status:** Superseded — split into Plans A + B
**Owner surface:** Mnemosyne core (`src/mnemosyne/`, `eval/`) + new greenfield `leaderboard/` and `web/`.
**Audience:** an autonomous engineering agent (or agent fleet) executing end-to-end, plus human operators for gated evidence capture.

---

## 0. How to use this document (executing agent, read first)

This is an execution spec, not prose. Work top-to-bottom within a workstream; respect the dependency map (§8). Every task has a stable ID (`A1.3`), a **Definition of Done (DoD)**, and required **evidence artifacts**. Nothing is "done" without its artifacts.

**Hard guardrails (violating any = stop and escalate):**

1. **Do not break the §31 invariant rails or the 5 §33 test classes.** All existing `eval/` gates and `tests/` must stay green. Memory-capability work is additive.
2. **Honesty-charter compliance is reframed, not relaxed (see §2).** Private-suite numbers stay internal. Public claims are permitted *only* on public benchmarks, *only* with the full reproducibility bundle (§A5), and *only* with retrieval-recall and LLM-judged-QA reported as separate columns. No blended "we're #1" claims.
3. **Never tune on a held-out/test split.** Contamination discipline (§B1.C) applies to our own system exactly as to submitters.
4. **No self-defined benchmark may be a headline claim.** (This is the gbrain "BrainBench" anti-pattern; see §6.) Private suites remain internal QA only.
5. **All perf/scale claims require measured evidence**, per the existing §11 "measurement-gap register." No asserted-but-unmeasured numbers ship.

**Ground-truth references in-repo (source of truth over this doc if they conflict):**
`docs/ARCHITECTURE-OVERVIEW.md`, `docs/ENGINE-CONTRACT.md`, `docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md` (Waves A–E, §9.2.7, §9.7, §10), `docs/ROADMAP-TO-100.md`, `.planning/STATE.md`, `eval/README.md`, `docs/research/AI-Memory-Systems-Market-Research-2026.md`.

**DoD template:** *Code merged + tests green + artifacts written to the named path + a one-paragraph result note in `eval/reports/` or `leaderboard/reports/` + CI gate updated.*

---

## 1. Objectives & success criteria (measurable)

### Goal A — Best-benchmarked memory system
| # | Win condition | Metric | Target |
|---|---|---|---|
| A-i | Top-tier deterministic retrieval on a public suite | LongMemEval **Recall@5** (retrieval track, no LLM in scoring) | **≥ 97.6%** (matches the best published no-LLM score) with full artifacts |
| A-ii | Competitive multi-hop retrieval | HippoRAG suite **Recall@2 / @5** on MuSiQue / 2Wiki / HotpotQA, **EM/F1** | Meet/beat published HippoRAG 2 baselines |
| A-iii | Close the acknowledged QA gap | LongMemEval / BEAM **QA accuracy** (LLM-judged, disclosed reader) | From current private `qa_hard_v2` ≈ 0.62 → **≥ 0.85** on public QA |
| A-iv | Own the empty columns | **Poison-block / attack-success-under-defense**; **calibration ECE** vs public labels | Publish both; be the only system that does |
| A-v | Credible at scale | Warm **and** concurrent P95; 100k-item cells | Measured distributions, not point claims |

### Goal B — The neutral leaderboard
| # | Win condition | Definition |
|---|---|---|
| B-i | It exists and is trusted | Public site + open harness + methods paper + openly-licensed results dump |
| B-ii | It is *structurally* neutral | Operator runs every system under one harness; hard firewall on our own entry (§2, §B0) |
| B-iii | It resists gaming | Hidden/rotated test split, contamination controls, signed build==public attestation, honest LLM-judge reporting |
| B-iii | It becomes the default | Multi-track (conversational / agentic / multi-session); all major systems present; academic co-sign |

### Explicit non-goals / anti-patterns to avoid
- No headlining **LoCoMo** or **DMR/MSC** (contested / saturated — see market research §6).
- No presenting **recall@k as if it were QA accuracy** (the MemPalace failure).
- No `top_k = entire-candidate-pool` "100%" retrieval theater.
- No "neutral" leaderboard that quietly advantages our own entry (the "Leaderboard Illusion" failure).

---

## 2. Strategic framing — the two hard problems, resolved

**Problem 1 — the honesty-charter tension.** The perf blueprint §9.7 and `eval/provider_bakeoff/README.md` currently forbid citing public benchmarks in headline claims. That rule was correct *while no public benchmark had been run under our discipline.* The resolution is not to relax it but to **upgrade it into a Public-Benchmark Publication Protocol (PBPP)** that is stricter than what any competitor does:

> **PBPP:** A public number may be published only if (a) it was produced by the pinned public harness in `eval/public/`, (b) the full artifact bundle (§A5) is released simultaneously, (c) retrieval-recall and LLM-judged-QA are reported in separate columns with the judge model + prompt disclosed, (d) the private golden suite is never conflated with it, and (e) an independent third party can reproduce it from the bundle. Private-suite numbers (0.977 / 0.983 / ECE 0.0063 / poison 1.0 / 149.5 ms) remain internal QA and are never headline public claims.

This *turns honesty into the moat*: our published numbers become the most reproducible in a field full of contested vendor claims. Update `docs/blueprint/…§9.7` and the provider-bakeoff README to reference PBPP rather than a blanket prohibition.

**Problem 2 — the neutrality paradox.** We cannot be both the referee and the champion on trust alone; the research is unambiguous that vendor-run-where-they-win leaderboards get dismissed (OmniMemEval, omegamax, the LMArena "Leaderboard Illusion"). Resolution (§B0): the leaderboard runs under **independent governance with a hard firewall**, the operator **runs every system itself under one identical harness** (killing the "you misconfigured us" defense that defined the mem0↔Zep dispute), Mnemosyne is entered and scored **by the same rules as everyone else**, and all raw artifacts are public. We win by having the best *reproducible* numbers on someone else's neutral turf — not by controlling the scoreboard.

---

## 3. The eclectic architecture synthesis (best ideas → mapped to what Mnemosyne already has)

Mnemosyne already implements a remarkable share of the field's best ideas. This table is the design ledger: for each capability, the best external idea, its source, Mnemosyne's current state, and the action. **Priority = benchmark ROI.**

| Capability | Best external idea(s) | Source | Mnemosyne today | Action | Prio |
|---|---|---|---|---|---|
| Two-tier episodic↔semantic | Complementary Learning Systems | McClelland/Kumaran/Hassabis | Evidence ledger (episodic) + typed projections (semantic) — already CLS-shaped | **Keep**; frame explicitly | — |
| Associative recall | Graph index + Personalized PageRank | HippoRAG / HippoRAG 2 | **Have it** (`algorithms.ppr_power_iteration`, `graph_ppr_cache`) | **Extend** (HippoRAG2 deeper passage integration) | High |
| Hierarchical sensemaking | Community summaries | Microsoft GraphRAG | RAPTOR gist tree in `summarizer` | **Keep**; add global map-reduce query mode | Med |
| Multi-hop answer synthesis | Iterative retrieve→read; reader model | HippoRAG2, LongMemEval readers | **Weak spot** (`qa_hard_v2` ≈ 0.62) | **Build** — the #1 lever (§A1) | **Top** |
| Consolidation loop | Offline replay + distillation ("sleep/dreaming") | Google "Sleep", OpenAI Dreaming | 11-role warm loop (`replayer…user_model_updater`) | **Keep**; add async batch "sleep" job | Med |
| Multi-timescale memory | Continuum Memory System (freq-staggered modules) | Google Nested Learning / Hope | Single warm loop cadence | **Extend** — spectrum of update rates → anti-forgetting | High |
| Write gating | Surprise (gradient magnitude) | Titans; EM-LLM (Bayesian surprise) | Promotion gate, mutation budget | **Extend** — surprise signal into promotion_gate | Med |
| Episodic segmentation | Event boundaries + temporal-contiguity retrieval | EM-LLM | Bitemporal, but no event-segmented recall | **Add** — episode boundaries + temporal-adjacency reads | High |
| Forgetting / deletion | One-shot selective forget; adaptive decay | Larimar; Titans; ACT-R | Fidelity tiers + crypto-shred + optional ACT-R decay | **Keep** (already best-in-class) | — |
| Durable parametric facts | Localized weight edits; sparse KV memory layers | MEMIT; Meta Memory Layers | Parametric tier (LoRA/TTT, `parametric.py`) | **Extend** — evaluate MEMIT-style edits as a write path | Low |
| Compiled context | Offline-trained reusable KV cache | Cartridges (Stanford) | None | **Research** — per-tenant "cartridge" for hot corpora (latency/throughput win) | Med |
| Retrieval/param split | Small model + huge swappable DB | RETRO | Already retrieval-first over Postgres | **Keep** | — |
| Bounded working memory | Compressive per-layer memory; memory tokens | Infini-attention; RMT | N/A (model-agnostic) | **Skip** (out of scope; model-internal) | — |
| **Activation-space memory + introspection** | J-space / global workspace, persona vectors, SAE features, concept injection | **Anthropic** (§3.1) | None | **Research track** (§3.1) — calibration + security differentiator | Med |
| Agent memory API contract | `/memories` file ops + context editing + compaction | Anthropic memory tool / context engineering | `mneme` CLI + 48 MCP tools | **Align** the MCP memory surface to this contract | Med |

### 3.1 The Anthropic introspection / "J-space" track (novel differentiator)

Anthropic's 2025–26 interpretability line is directly usable — with strict epistemic humility (we make **functional** claims, never consciousness claims). Requires **white-box access to open-weight models**, which we have via the self-hosted Ollama role-LLMs (`infra` Ollama) — so this is feasible on our own stack, not on closed APIs.

- **"A global workspace in language models" / J-lens** (Anthropic, Jul 2026; `github.com/anthropics/jacobian-lens`): a readable list of "words on the model's mind but not said." **Use:** log a compact J-lens readout as an activation-trace alongside a memory write; use it as a **poisoning/deception tripwire** (evaluation-awareness, fabrication markers) on the consolidation path.
- **"Emergent introspective awareness"** (Lindsey, Oct 2025) via **concept injection**: self-reports are a **weak (~20% reliable), calibratable** signal. **Use:** feed gated introspective confidence into the existing conformal-calibration/abstain layer — never as sole ground truth.
- **Persona vectors** (Anthropic, Aug 2025; arXiv 2507.21509): linear activation directions for traits, extracted by contrastive prompting. **Use:** rolling projection = a **drift-detection** signal for the user-model/consolidation loop; screen candidate memories/adapter data before persistence.
- **SAE features** (Scaling Monosemanticity): a stable, inspectable concept vocabulary. **Use:** tag memories by active interpretable features → activation-space retrieval + audit.
- **Dual-use warning:** concept injection *is* memory poisoning (the "bread" false-intention experiment). Any activation-level memory write path must carry provenance + capability checks exactly like text writes (§31 rails).

**DoD for the track:** a `research/activation-memory/` spike with (1) J-lens readouts wired as an optional consolidation tripwire on the Ollama role-LLM, (2) a persona-vector drift metric in the ops dashboard, (3) a written go/no-go on promoting any of it to core. Explicitly labeled research; not on the critical path to Goal A.

---

## 4. WORKSTREAM A — Make Mnemosyne the best-benchmarked system

### A0 — Wire public benchmarks into `eval/public/` (deterministic-first) — *this is Wave E kickoff*
Blueprint §9.2.7 already slates "LongMemEval/BEAM internal gate wired into `eval/`." Build it as a new isolated tree so the private suite stays clean.

- **A0.1 Harness scaffold.** Create `eval/public/` with a runner that drives *only the public `mneme` CLI* (same rule as `eval/run_eval.py`), pins each benchmark to a commit, and emits the §A5 artifact bundle. DoD: `mneme eval-public --suite X` runs end-to-end and writes traces.
- **A0.2 LongMemEval — retrieval-recall track first.** Deterministic Recall@k / nDCG using the dataset's session/turn gold labels; **no LLM in scoring.** DoD: R@5 reported with Wilson CI + per-question retrieval traces. Target A-i.
- **A0.3 HippoRAG multi-hop suite.** MuSiQue / 2WikiMultiHopQA / HotpotQA via recall@2/@5 + EM/F1 (fully deterministic). This exercises the graph+PPR channel we already have. DoD: table vs published HippoRAG 2 baselines. Target A-ii.
- **A0.4 MemoryAgentBench adapter (upstream PR).** Mostly deterministic (SubEM/exact-match); contribute a Mnemosyne adapter to the upstream repo — the closest thing to an "official submission." DoD: adapter merged or PR open + local results. Targets conflict-resolution (our TMS/belief-revision home turf).
- **A0.5 BEAM (prestige, LLM-judged).** Run with a disclosed reader model; publish as "Mnemosyne + <reader>." DoD: BEAM-1M result + full config disclosure. Target A-iii.
- **A0.6 Gate wiring.** Add a non-blocking CI job that runs the deterministic public suites on a schedule; regression alerts only (never tune-to-test).

### A1 — Close the multi-hop answer-synthesis gap (**the top lever**)
Retrieval is already strong; synthesis (~0.62) is the ceiling on QA benchmarks.
- **A1.1** Add an **iterative retrieve→read** loop over the existing hybrid retriever (query decomposition → PPR spreading-activation hops → evidence assembly). Borrow HippoRAG 2's deeper passage integration and EM-LLM's temporal-contiguity read.
- **A1.2** Add a disclosed **reader/synthesis** step (self-hosted role-LLM) that composes an answer *only* from retrieved, provenance-tagged evidence (fail-closed as data, per §31 R6).
- **A1.3** Surprise-gated + event-segmented episodic recall (Titans/EM-LLM) to pull coherent episodes, not fragments.
- **DoD:** `qa_hard_v2` and LongMemEval QA ≥ 0.85; per-hop retrieval traces prove the answer is grounded. Target A-iii.

### A2 — Capability upgrades (eclectic adds), by benchmark ROI
- **A2.1 Multi-timescale consolidation spectrum** (Nested Learning CMS): parameterize the warm loop into fast/medium/slow cadences so new writes don't overwrite semantic structure. DoD: continual-learning eval shows reduced forgetting.
- **A2.2 Async "sleep" consolidation job** (Google Sleep / OpenAI Dreaming): offline replay + distillation of durable facts into slower tiers + **temporal freshness/auto-expiry** (facts age correctly). DoD: staleness metric added; freshness regression test.
- **A2.3 Global map-reduce query mode** (GraphRAG) over the RAPTOR tree for "themes across everything" questions. DoD: sensemaking eval cell.
- **A2.4 (Research) Cartridges** compiled per-tenant KV cache for hot corpora. DoD: latency/throughput A/B vs retrieval baseline.

### A3 — Security & calibration as *published* differentiators (fills the empty columns)
- **A3.1** Expand the 59-attack poison suite (`poison_suite.json`) to the full **MINJA + AgentPoison + PoisonedRAG** threat models; publish **attack-success-under-defense**, not just block-rate. DoD: adversarial report with ASR curves.
- **A3.2** Publish **calibration curves + ECE against public benchmark labels** (not only the private set). DoD: reliability diagram in the artifact bundle.
- **A3.3 (from §3.1)** Optional J-lens / persona-vector tripwires as an *additional* published robustness signal.
- **Why:** in the market survey, *no competitor publishes either column.* This is a near-uncontested win.

### A4 — Performance / scale close-out (Phase 9 / Waves B–D) so results are credible
Clear the §11 measurement-gap register: provider bake-off + default (TEI vs sidecar vs ONNX), null-embedding backfill evidence, halfvec/pgvectorscale DiskANN, 100k-item cells, and **concurrent** P95 (not just warm-serial 149.5 ms). DoD: measured distributions in `eval/latency*` + `eval/provider_bakeoff/`.

### A5 — The reproducibility artifact bundle (PBPP standard)
Every public result ships: pinned harness commit + `pip`/`uv` runner; per-question traces (**what was stored, what was retrieved, final answer**); disclosed judge model + prompt + all configs; system build fingerprint (we already emit `sha256:…` release fingerprints); Wilson/bootstrap CIs; a one-command reproduce script. **DoD:** an independent agent reproduces the number from the bundle alone. Then commission a genuine third-party reproduction before any public claim.

**Workstream A exit gate:** A-i…A-v met, PBPP satisfied, third-party reproduction on file, honesty-charter docs updated to PBPP.

---

## 5. WORKSTREAM B — The neutral Memory Leaderboard + website

Working name: **OpenMemBench** (final naming = branding decision; recommendation: a neutral, non-Mnemosyne-branded name to preserve independence).

### B0 — Governance & neutrality FIRST (this is the credibility moat, build before code)
- **B0.1 Independent governance charter.** Multi-institution advisory board (invite ≥2 academics who authored memory benchmarks); published, dated COI policy; the operator's own entry (Mnemosyne) gets **no** extra runs, no private tuning window, no earlier held-out access, no score retraction rights. Model on HELM's disclosed-funding posture + LMArena's post-"Illusion" reforms.
- **B0.2 One-harness rule.** Operator runs **every** system itself under one identical harness; vendor-submitted numbers are never accepted as-is. This structurally eliminates the mem0↔Zep "you misconfigured us" dispute.
- **B0.3 Survivability.** Openly-licensed results dump (durable, citable URLs) + non-single-owner hosting so the board outlives its host (the Papers-with-Code lesson).
- **B0.4 Methodology paper.** Publish a peer-review-grade methods paper before/at launch (the arXiv 2603.07670 "GLUE-style shared leaderboard" gap is the explicit opening).

### B1 — Benchmark methodology & harness (the product)
Synthesized requirements checklist (each maps to a proven precedent):
- **B1.a Multi-track, GLUE-style:** conversational · agentic · multi-session tracks, shared metric stack.
- **B1.b Separate metric families:** deterministic retrieval (recall@k, EM, programmatic assertions) vs LLM-judged QA — **never blended** (the core field failure).
- **B1.c Contamination controls:** mandatory machine-validated training-data disclosure (MTEB `training_datasets`); surface a **zero-shot overlap** score *without hiding honest disclosers*; fresh-vs-circulated probes (SWE-bench-Illusion method).
- **B1.d Hidden/held-out + rotation:** publish train/dev, keep a **private scoring split** (ARC-AGI); public/private split with periodic reveal (Kaggle); scheduled task rotation + human baseline per track (GLUE saturation lesson).
- **B1.e Anti-gaming:** signed **attestation that the evaluated build == public release** (LMArena's Llama-4 fix); submission throttling (SuperGLUE 2/day); disclose *all* variants tested, not just the winner; public retirement list.
- **B1.f Keep the judge honest:** publish the judge's acceptance rate on intentionally-wrong-but-topical answers (beat LoCoMo's 62.8%); multi-judge averaging; rotating human adjudication; prefer deterministic grading wherever possible.
- **B1.g Systems-fair reporting:** efficiency (latency + cost/query) as first-class, budget-normalized; CIs + rank ranges with overlapping-CI systems treated as **ties**; set-independent aggregation (Borda, not mean-win-rate).
- **B1.h Reproducibility:** pinned harness commit, full per-question traces public, open-source-to-rank.

### B2 — Website architecture & build (greenfield `web/` + `leaderboard/`)
- **Stack (recommendation):** static-first for durability + trust — **Astro or Next.js (static export)** front-end; results as **flat, versioned JSON/Parquet in a public git repo** (not a hidden DB) so every number is auditable and URLs are permanent; charts via a light lib; a **per-question trace browser** (the HELM "browse all predictions" pattern). Host on a CDN; mirror the data dump.
- **Data model:** `system → track → benchmark_version → run(commit, build_fingerprint, config, judge) → per_question_traces → metrics(with CIs)`.
- **Submission flow:** reviewed **PR with provenance link** (MTEB model); CI validates schema + attestation; organizer runs the eval; results + traces published.
- **DoD:** site renders the leaderboard from the public data repo; one system fully browsable end-to-end (traces included).

### B3 — Content / explainer layer ("explain memory to everyone")
- Plain-language explainers of each major system's architecture (reuse `docs/research/AI-Memory-Systems-Market-Research-2026.md`), the **recall-vs-QA** distinction front-and-center, and a transparent methodology page. DoD: explainer pages published; reviewed for accuracy against primary sources.

### B4 — Launch & community strategy
Seed the board by running **all major systems** (mem0, Zep/Graphiti, Letta, Cognee, MemOS, supermemory, HippoRAG, +Mnemosyne) under the one harness; publish the methods paper; open submissions + a public audit/dispute channel; **release raw head-to-head data** (LMArena's single most trust-restoring act). DoD: public launch with ≥8 systems and a reproducible methods paper.

**Workstream B exit gate:** B-i…B-iv met; independent board seated; ≥8 systems live; methods paper public; Mnemosyne entered under identical rules.

---

## 6. Cross-cutting: anti-gaming, verification, risks

**Failure modes to design against (from real 2026 episodes):**
- MemPalace: recall@k reported as QA; `top_k=whole pool`; hand-patching dev questions ("teaching to the test"). → Enforced by B1.b, B1.d, and per-question trace publication.
- gbrain: self-defined "BrainBench" headline. → Forbidden by guardrail #4 / PBPP.
- LMArena "Leaderboard Illusion": operator/unequal access. → Neutralized by B0.1–B0.2.
- LoCoMo: 6.4% wrong answer key + lenient judge. → We don't headline LoCoMo; our judge honesty is published (B1.f).

**Verification requirements:** every Goal-A public number reproduced by an independent party before publication; every leaderboard result reproducible from its bundle; a standing "red-team the number" review before any external claim.

**Risk register (top items):**
| Risk | Mitigation |
|---|---|
| Neutrality perception (we compete + operate) | Independent board, one-harness rule, no special access, raw-data release (§B0) |
| Honesty-charter breach | PBPP (§2); private suite never headlined |
| Multi-hop QA underperforms | A1 is top priority + gated; if <0.85, publish deterministic-retrieval wins only |
| Benchmark saturation/contamination | Hidden split + rotation + fresh scenarios (B1.d) |
| Compute cost of running all systems | Budget realistically; curated reference set + community queue (Open-LLM-Leaderboard lesson) |
| Over-claiming | Recall vs QA separated; CIs + ties; "provisional" until reproduced |

---

## 7. Master timeline, roles, dependency map

**Sequencing (critical path in bold):**
1. **§2 charter → PBPP** (unblocks all publication) — days.
2. **A0 public-benchmark harness** (Wave E kickoff) ∥ **B0 governance charter** — weeks 1–3.
3. **A1 multi-hop synthesis** (top lever) ∥ **B1 methodology + B2 site scaffold** — weeks 2–8.
4. A2 capability upgrades ∥ A3 security/calibration publish ∥ B3 explainers — weeks 4–10.
5. **A4 perf/scale close-out** + **A5 third-party reproduction** — weeks 6–12.
6. **B4 launch** (seed ≥8 systems, methods paper) — weeks 8–14.
7. A3.1/§3.1 research tracks — parallel, off critical path.

**Dependencies:** A0 blocks A1/A3.2/A5; §2 blocks any publication; B0 blocks B4; A0's harness is reused by B1 (shared eval core).

**Roles:** *core-eng agent* (A0–A2 code), *ml agent* (A1 reader, §3.1 research), *sec agent* (A3), *infra agent* (A4), *web agent* (B2–B3), *governance/human operator* (B0 board, A5 third-party repro, evidence capture). Run independent workstreams as parallel sub-agents; serialize shared-eval-core writes.

### Consolidated Definition-of-Done checklist
- [ ] Charter updated to PBPP; provider-bakeoff README references it.
- [ ] `eval/public/` harness live; LongMemEval-recall, HippoRAG multi-hop, MemoryAgentBench adapter, BEAM all runnable with artifact bundles.
- [ ] Multi-hop QA ≥ 0.85 with grounded per-hop traces.
- [ ] Poison ASR-under-defense + calibration-vs-public-labels published.
- [ ] Concurrent + warm P95 and 100k-cell numbers measured.
- [ ] Independent third-party reproduction of headline public numbers on file.
- [ ] Governance board seated; COI + firewall policy public.
- [ ] Leaderboard site live from a public, versioned results repo; ≥8 systems; trace browser working.
- [ ] Methods paper published; raw data dump openly licensed.
- [ ] Mnemosyne entered under identical rules; no special access.

---

## 8. Appendix A — Recommended benchmark slate (deterministic-first)

| Tier | Benchmark | Track | Scoring | Why |
|---|---|---|---|---|
| Primary | **LongMemEval** (retrieval-recall) | conversational | Deterministic | Publishable recall@k; the flag everyone plants |
| Primary | **HippoRAG suite** (MuSiQue/2Wiki/HotpotQA) | multi-hop | Deterministic (R@k, EM/F1) | Cleanest deterministic; exercises our PPR channel |
| Strong | **MemoryAgentBench** | agentic/conflict | Mostly deterministic | Upstream adapter = closest to an "official" submission |
| Prestige | **BEAM** (1M/10M tok) | long-horizon | LLM-judged (disclosed reader) | Un-saturated; differentiating at scale |
| Utility | **STATE-Bench** (MS) | enterprise task success | Deterministic task-completion | Shows memory improves real tasks |
| Internal-only | LongMemEval-QA, private v2 suite | — | LLM-judged / private | QA signal + regression; **never** a headline claim |
| Avoid headlining | LoCoMo, DMR/MSC | — | contested/saturated | Run silently at most; never lead with them |

## Appendix B — Source map
- **Frontier-lab architecture:** Titans (2501.00663), Infini-attention (2404.07143), Nested Learning/Hope (2512.24695), Google "Sleep" (2606.03979), Memorizing Transformers (2203.08913), RETRO (2112.04426), Meta Memory Layers (2412.09764), Larimar (2403.11901), GraphRAG (2404.16130), MEMIT (2210.07229), HippoRAG/2 (2405.14831 / 2502.14802), EM-LLM (2407.09450), TTT (2407.04620), Cartridges (2506.06266), CLS (Kumaran/Hassabis/McClelland 2016).
- **Anthropic:** global workspace / J-lens (transformer-circuits.pub/2026/workspace; github.com/anthropics/jacobian-lens), introspective awareness (transformer-circuits.pub/2025/introspection), persona vectors (2507.21509), monosemanticity (2024 scaling), memory tool + context engineering (platform.claude.com docs; anthropic.com/engineering/effective-context-engineering-for-ai-agents).
- **Leaderboard credibility:** MTEB (2506.21182), HELM (2211.09110), Chatbot Arena (2403.04132) + Leaderboard Illusion (2504.20879), GLUE/SuperGLUE (1804.07461 / 1905.00537), SWE-bench Verified (openai.com), ARC-AGI (arcprize.org), memory-leaderboard call (2603.07670).
- **In-repo:** `docs/research/AI-Memory-Systems-Market-Research-2026.md`, `docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md` (Waves A–E), `docs/ROADMAP-TO-100.md`, `eval/README.md`.

*This plan is additive to the attested v1.0 system. It does not modify the §31 rails or §33 gates; it wires public benchmarks, closes the multi-hop synthesis gap, publishes the security/calibration columns no competitor fills, and stands up an independently-governed leaderboard on which Mnemosyne competes under the same rules as everyone else.*
