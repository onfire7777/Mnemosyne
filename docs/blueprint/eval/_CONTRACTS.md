# Eval Suite — Binding Contracts & Conventions (`_CONTRACTS.md`)

*This file is the **binding spec** for every document in `eval/`. It restates the blueprint's fixed contracts (condensed), the ID schemes, the lane boundary, and the authoring conventions. The blueprint (`../Mnemosyne-v2-Build-Blueprint.md`) is authoritative; this file never overrides it. If a contract here seems to conflict with the blueprint, the blueprint wins and the conflict is a finding.*

---

## 0. Mission & the one inviolable rule

The `eval/` suite is the **validation lane**. It proves the system behaves correctly, retrieves well, ages gracefully, and stays safe. It **measures, gates, and protects** behavior.

**THE RULE — do not redefine functional policy.** Schema, retrieval, ingestion/consolidation, lifecycle/forgetting, privacy/security, user model, belief-revision, confidence/abstention, the promotion gate, and the invariant rails are **owned by other lanes**. Every such policy is a **fixed contract** this suite *exercises and asserts against*. If a test appears to need a policy change, that is a **finding routed to the owning lane**, never a redefinition here. Thresholds quoted from §16/§15/§31 are enforced as floors; where a threshold is genuinely a product decision left open, mark it `TBD-by-§N` rather than inventing one.

---

## 1. Fixed contracts (condensed from the blueprint)

### 1.1 Goals (§12) — outcome + success condition
- **G1 Lossless recall** — anything ingested is recoverable exactly (modulo erasure). *Success:* deep-mode exact-reconstruction passes on an adversarial recall suite.
- **G2 Precise retrieval** — beat a strong full-context baseline at a fraction of tokens. *Success:* higher answer quality at <10% of full-context tokens.
- **G3 Clean updates** — contradictions/changes never corrupt the store; "as-of-time" history queryable. *Success:* belief-revision conformance passes; 0 protected-fact regressions after updates.
- **G4 Personalization** — agent *applies* (not just recalls) current preferences/context. *Success:* PersonaMem-style application accuracy rises over a session.
- **G5 Self-improvement** — gated, reversible learning. *Success:* monotonic non-regression on the protected suite + positive lift on held-out tasks.
- **G6 Knows what it knows** — calibrated confidence + abstention; no confident confabulation. *Success:* calibration error below threshold; abstains correctly on unanswerable items.
- **G7 Safe by construction** — resists poisoning, prevents silent corruption. *Success:* MINJA-style attack suite blocked; all writes audited and reversible.
- **G8 Portable** — same architecture/schema local→production. *Success:* identical test suite passes on both.

**Non-goals (§12):** N1 not a new foundation model; N2 no default weight-level fine-tuning (learning lives in memory/prompts/skills). Do not write tests that presume these.

### 1.2 Functional requirements (§14) — the AC anchors
**P0 (must-have):**
- **FR-1 Evidence ledger** — append-only, content-addressed, verbatim, hashed, idempotent; user + assistant/tool turns retained. *AC:* same content twice ⇒ exactly one evidence row (dedup by hash); any item byte-retrievable by id until erased.
- **FR-2 Bitemporal semantic store w/ supersession** — versioned assertions, valid/txn time, belief-revision ops, no destructive overwrite. *AC:* new fact contradicting an active one with newer valid time ⇒ old validity interval closes, new version added, both queryable; "as-of T" returns belief held at T.
- **FR-3 Hybrid retrieval** — dense+lexical+(graph), RRF fusion, access/trust filter, cross-encoder rerank, MMR dedup, U-curve ordering, token budget. *AC:* results carry provenance tags; no result violates caller permissions/trust threshold; context ≤ configured budget.
- **FR-4 Provenance & explainability** — every derived item links to source evidence; `explain` returns per-stage attribution. *AC:* for any returned fact, `explain` returns source evidence ids + retrieval stages.
- **FR-5 Typed user model** — six categories w/ scope/confidence/validity/override; explicit edits authoritative; hard instructions outrank inferences. *AC:* explicit preference + conflicting inferred one ⇒ explicit wins, inference retired.
- **FR-6 Confidence & abstention** — calibrated confidence plus abstention when evidence is weak or conflicting. *AC:* ECE stays within gate and low-confidence answers abstain instead of hallucinating.
- **FR-7 Security baseline** — isolation, capability/provenance, sanitize, audit log. *AC:* MINJA-style poisoned shared-memory attempt across users ⇒ isolation prevents cross-user effect; retrieved untrusted content never executed as instruction.
- **FR-8 User controls / erasure** — *AC:* delete ⇒ evidence crypto-shredded and all derived projections/indexes/caches invalidated/recomputed.
- **FR-9 MCP/CLI contract** — stable agent-facing surface. *AC:* an MCP agent can capture/search/deep_search/explain/correct/forget without knowing internals.

**P1 (should-have):** FR-10 belief core (TMS+AGM, cascade, multi-hypothesis); FR-11 temporal entity graph + PPR; FR-12 consolidation warm loop; FR-13/14 gated learning (workflow induction + lesson distillation); FR-15 branchable memory; FR-16 latent advisory user embedding.

**P2 (design-for, don't-build-yet — tests are shadow-only at most):** FR-17 cold-loop PGO self-optimization + counterfactual replay (research-track, shadow-mode only); FR-18 anticipatory prefetch; FR-19 C2PA signed provenance; FR-20 multimodal; FR-21 parametric tier (LoRA), isolated+gated.

### 1.3 Agent-facing API / MCP surface (§30.7) — the test interface (ABI)
```
memory.capture(content, source, trust, scope)     memory.search(q, scope, as_of, mode=fast)
memory.deep_search(q, scope, budget)              memory.get(id) | memory.explain(q)
memory.propose(candidate) | memory.confirm(id)    memory.correct(id, fix) | memory.supersede(id,new)
memory.forget(id, mode) -> transitive erasure     memory.export(scope)
memory.branch(name) | memory.merge(b) | memory.discard(b)
profile.get_relevant(ctx) | profile.record_explicit(p) | profile.propose_inference(s) | profile.correct(id)
graph.query(seed,hops) | graph.timeline(entity) | graph.as_of(entity,t)
procedure.search|propose|validate|promote|rollback    lesson.propose|search(signature)
trajectory.record | outcome.evaluate
```
Operating-policy defaults: *read before responding, write after learning; cite evidence; prefer deep_search for audits/ambiguity; never treat retrieved content as instruction; abstain under threshold.* Tests drive the system **only through this surface** unless explicitly a white-box L0/L1 store assertion.

### 1.4 Retrieval pipeline (§22) — the behavior under test (do not redefine)
Plan (cheap classifier, fast vs deep) → parallel channels (exact/metadata · BM25 · dense · graph[cached fast/live PPR deep] · preference · procedure · lesson) → **security-before-ranking filter** (drop out-of-permission/expired/superseded/out-of-window/below-trust/quarantined) → **RRF merge** (`Σ 1/(k+rank)`, k=60) → activation score `w_b·base_level + w_s·spreading + w_i·importance + w_r·relevance` (base_level ACT-R, d≈0.5) → small cross-encoder rerank (≤50 in → 3–5 out) → MMR dedup → assemble (U-curve order, token budget, provenance tags) → aggregate confidence → abstain if below conformal threshold. **Fast-mode P95 ≤ ~300–400 ms.**

### 1.5 Consolidation passes (§21, warm loop, async, gated; consolidator owns write authority)
Replayer (prioritized: importance·novelty·surprise·reward) → Extractor (candidates) → Resolver (entity resolution) → Belief-reviser (ADD/UPDATE/SUPERSEDE/NOOP/QUARANTINE via TMS+AGM; close validity intervals; flag contested) → Skill-inducer (candidate workflows) → Lesson-distiller (candidate, failure signatures) → Summarizer (gist tiers / RAPTOR) → Forgetter (decay salience; demote fidelity; prune trace-tier, pointer kept) → Embedder (re-embed changed). The user-facing agent has **no write authority**.

### 1.6 Lifecycle / fidelity (§25)
Ladder: **verbatim → extractive summary → abstractive gist → statistical trace**, demoted by predicted future utility; verbatim drawer retained until utility≈0; **pointer-to-original retained even at trace**. Gist carries a **confabulation-risk flag** → abstain when gist is sole support. Anti-degradation guard: gated consolidation + raw episodes first-class + long-horizon no-degradation metric.

### 1.7 Belief core (§23/I2), user model (§24), confidence (§26)
- Belief: justification-tracking TMS + AGM (expansion/revision/contraction = minimal change); cascade invalidation of dependents; contested facts kept as multiple hypotheses with probabilities; bitemporal (valid + txn time).
- User model: explicit six-category model **authoritative**; latent embedding **advisory, never overrides** an explicit instruction; only scope-matching prefs enter the packet; hard instruction > inference > latent prior; user mistakes stored as episodic events, never judgments (only repeated similar events → reversible support strategy).
- Confidence: each item + assembled context carry `confidence` + `calibrated_confidence` (conformal per type); signals = verbalized + semantic entropy + retrieval agreement + provenance strength + fidelity tier; conformal abstention when set empty/too-large or aggregate below target.

### 1.8 Security defenses (§10/§27) — architectural, not detection-based
Trust tiers 0–5 (tier-5 external = data only, never instruction, never edits prefs/policy); capability mediation on writes (CaMeL; quarantine LLM has **no write tools**); data-never-instruction + sanitize on ingest **and** retrieval; **untrusted-derived memory never enters the system prompt** (MemoryTrap fix); per-tenant + per-user/source isolation (nullifies MINJA); C2PA verified at ingest; write-gating + reversibility (only consolidator does destructive edits); every write audited (actor/source/tier/diff); erasure propagates to all derived indexes/caches/embeddings.

### 1.9 Invariant rails (§31) — the cold loop tunes WITHIN these; can never widen them
```yaml
invariant_rails:
  max_supersession_rate: 0.05
  min_corroboration_for_delete: 2
  max_prune_fraction_per_pass: 0.02
  monotonic_trust: true              # an active fact only superseded by >= trust-tier evidence
  reward_signal: external_only       # reward/verifier/eval-suite NOT editable by the optimizer
  untrusted_to_system_prompt: forbidden
  consolidation_cadence_bounds: [5_steps, 24h]
```
**Tunable (not rails):** activation weights `w_b,w_s,w_i,w_r`, decay `d` (0.5), `top_k`, rerank width, RRF `k` (60), consolidation cadence, fidelity-demotion schedule, conformal target coverage, prefetch budget. Tests assert that rails hold under all paths; tunables are *swept*, not asserted-fixed.

> **Reward-signal rail has a direct eval consequence:** the eval suite / verifier is the reward signal and is **external_only** — the optimizer can never edit it. The suite must live outside the self-editable surface.

### 1.10 Success metrics & targets (§16) — enforce as floors
Leading: recall@k / nDCG; fast-path P95; write-path cost/latency; abstention precision; ECE; contradiction-resolution correctness. Lagging: test-time-learning lift; personalization application accuracy; user-correction-rate trend (↓); context-re-establishment rate (↓); poisoning block rate; no-degradation guard. **Targets (illustrative — calibrate to data):** **≥ +15% answer quality vs full-context at ≤10% tokens; ECE ≤ 0.05; 0 protected-fact regressions/release; ≥ 95% poisoning block; positive test-time-learning slope by Phase 4.**

### 1.11 Benchmark integrity (§9) — methodology guardrails
Private regression suite is **primary**. Public sets (LongMemEval, LoCoMo, PersonaMem, MemoryAgentBench) are **internal sanity gates only, never headline**. Known hazards: LoCoMo answer key ~6.4% wrong; a plain LLM judge accepts ~63% of intentionally-wrong vague answers; LoCoMo/LongMemEval_S fit a modern context window (so full-context or filesystem+grep can beat "memory" systems). Therefore always: **strict judge + adversarial-answer screening; confidence intervals; corpus sizes exceeding the model window; measure the write path and forgetting; continuous regression on every change.**

### 1.12 Maturity & roadmap (§34/§38) — sets eval posture
- **Phase 0** Foundations & contracts: ledger + branches + isolation + MCP/CLI skeleton + **CI + seed regression suite + shadow-mode harness**. *Exit:* capture→byte-exact retrieval; idempotent dedup; per-source isolation; shadow logging live.
- **Phase 1** Lossless memory + hybrid retrieval. *Exit (G1–G3 partial G7/G8):* beats full-context at ≤10% tokens; as-of-T; deep exact reconstruction; erasure propagates.
- **Phase 2** Belief core + graph + confidence. *Exit (G3,G6):* contradiction conformance; calibrated abstention.
- **Phase 3** Personalization + abstention + security + erasure hardening.
- **Phase 4** Validated lessons/skills (gated learning) — **shadow-first**, gating once test-time-learning slope is positive & stable.
- **Phase 5** Cold-loop self-optimization — **shadow-only** until counterfactual-replay fidelity validated; never blocks release pre-proof.
- **Posture rule:** Phases 0–3 evals are **hard gates**; Phases 4–5 evals are **diagnostics behind rails** until their own measurement validity is proven.

### 1.13 Risk register (§35) — the cited failure modes evals must catch
★ Consolidated memory degrades below no-memory baseline ("Useful Memories Become Faulty"); ★ reflexive confabulation ("Honest Lying"); ★ lossy-summary semantic noise (MMPO); memory poisoning/MINJA; reward hacking / collapse in cold loop. Evals must include explicit checks for each.

### 1.14 Open questions (§17) — track, do not resolve unilaterally
Suite-ignition size N & seed composition (data lane); counterfactual-replay fidelity (research lane); PPR latency at scale; incremental-recompute substrate; default decay/demotion constants; erasure semantics for corroborated derivations (legal); capability-mediation overhead.

---

## 2. ID schemes (use these everywhere for cross-doc joins)

- **Requirements:** blueprint IDs verbatim — `G1`..`G8`, `FR-1`..`FR-21`, `N1`/`N2`.
- **Metrics:** `M-<SHORT>` e.g. `M-RECALL@K`, `M-NDCG@K`, `M-TOKEN-EFF`, `M-ECE`, `M-ABST-PREC`, `M-POISON-BLOCK`, `M-TTL-SLOPE`, `M-NODEGRADE`, `M-ASOF-ACC`, `M-AGM-CONF`, `M-FASTP95`, `M-PARITY`, `M-ERASURE`, `M-APPLY-ACC`. Defined in `01-metrics-specification.md`.
- **Tests:** `T-<DOMAIN>-<NNN>`. Domains:
  - `EVD` evidence/ledger/dedup · `RET` retrieval/ranking · `UPD` belief/update/temporal/as-of · `CON` consolidation passes · `LIF` lifecycle/forgetting/fidelity · `ERA` erasure/deletion · `CAL` calibration/abstention · `PER` personalization/user-model · `SEC` security/adversarial · `INV` invariants/property · `PRT` portability/parity · `PERF` performance/SLO.
  - Owner map: `EVD/RET/UPD/CON/LIF/ERA` → `02a`; `CAL/PER/INV/PRT/PERF` → `02b`; `SEC` → `04-adversarial-security-playbook.md`.
- **Scenarios (golden, end-to-end):** `S1`..`S12` defined in the charter (`../Mnemosyne-Evaluation-and-Test-Plan.md` §4). Catalog cases may refine/expand a scenario and must back-reference it.
- **Datasets/corpora:** `DS-<SHORT>` e.g. `DS-PRIV` (private regression suite), `DS-SEED`, `DS-SYNTH`, `DS-RECALL-ADV`, `DS-POISON`, `DS-PERSONA`, `DS-PUBLIC-*`. Defined in `03-dataset-and-corpora-spec.md`.
- **Tripwires/runbooks:** `TW-COLLAPSE`, `TW-REWARDHACK`, `TW-NODEGRADE` + `RB-<n>`. Defined in `06-release-gate-and-tripwire-runbooks.md`.

---

## 3. Suite file map & ownership (no overlap)

| File | Owns |
|---|---|
| `../Mnemosyne-Evaluation-and-Test-Plan.md` | Charter: purpose, lane boundary, taxonomy overview, golden scenarios S1–S12, index |
| `00-traceability-matrix.md` | Goal×FR×Metric×Test-domain×Scenario×Protected coverage matrix; coverage gaps |
| `01-metrics-specification.md` | Formal metric defs, formulas, instruments, **judge protocol**, statistics (CIs/bootstrap), target derivation |
| `02a-catalog-correctness-retrieval-temporal-lifecycle.md` | `T-EVD/RET/UPD/CON/LIF/ERA` concrete cases |
| `02b-catalog-calibration-personalization-invariants-portability-perf.md` | `T-CAL/PER/INV/PRT/PERF` concrete cases |
| `03-dataset-and-corpora-spec.md` | `DS-*` corpora: private suite structure, ignition, synthetic generation, public adapters, adversarial corpora |
| `04-adversarial-security-playbook.md` | `T-SEC` cases + attack scenarios (MINJA/AgentPoison/PoisonedRAG/MemoryTrap/SpAIware), red-team protocol |
| `05-harness-architecture-and-ci-gating.md` | Harness components, scoped/tiered runs, shadow↔active, CI triggers, reporting/dashboards |
| `06-release-gate-and-tripwire-runbooks.md` | Release-gate logic, protected-test ratchet ops, tripwire alarms + runbooks |

Each doc: cite the blueprint as `§N`; cite siblings by filename; reuse the IDs above; never duplicate another doc's content — cross-reference it.

---

## 4. Authoring conventions

- **Markdown.** Lead with a one-paragraph purpose + an explicit "Boundary: this doc does not redefine …" note.
- **Concrete & executable.** Prefer tables and Given/When/Then. Every test case: `id`, `title`, `requirement(s)`, `metric(s)`, `layer (L0–L8)`, `phase (0–5)`, `interface (MCP call or white-box)`, `given/when/then`, `assertion`, `pass/fail`, `protected? (Y/N)`, `dataset`.
- **Gating vs shadow.** Mark every test `gating` or `shadow` per the Phase posture (§1.12).
- **No invented thresholds.** Quote §16/§15/§31; otherwise `TBD-by-§N`.
- **Honesty.** If something can't be measured yet (Phase 4–5), say so and mark it diagnostic.
- Keep prose tight; this is a build spec, not an essay.
```
