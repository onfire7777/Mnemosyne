# Mnemosyne — Historical Blueprint Completion Plan

**Author:** Claude · **Date:** 2026-06-21
**Historical blueprint source:** `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` (1,133 lines, v2.0)
**Historical note:** this document is retained for lineage from the original
completion-planning pass. For current status and remaining work, use
`docs/ROADMAP-TO-100.md` plus the controlling
`.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.
**Consolidated at the time:** the earlier `Mnemosyne-PROGRESS-PLAN.md` (now removed).
**Why this exists:** the prior plan was derived from `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (a
*secondary* artifact). This plan is built directly from the blueprint's own requirement sections
(§12 goals/non‑goals, §14 FR‑1…21, §15 NFR, §16 success metrics, §29/App‑A data model, §30.1 engine
contract, §30.7 MCP ABI, §31 invariant rails, §33 eval harness, §34 roadmap, §38 maturity) so that
**nothing is missed and nothing conflicts with the blueprint's stated scope.**

---

## 0. What "full completion" means — calibrated to the blueprint itself

To not cut corners **and** not over‑build, every requirement is held to **two gates**, and "done" =
both gates pass *at the blueprint's own bar*:

- **Gate A — Built‑to‑spec:** the code implements the blueprint's mechanism (not a deterministic
  placeholder that merely returns the right shape).
- **Gate B — Proven:** it meets the blueprint's *Success* criterion (§12 goals G1–G8 / §34 phase exit
  gates), demonstrated through the §33 evaluation harness — not asserted by construction.

**Three calibration rules so the bar is exactly the blueprint's, no higher, no lower:**
1. **Engineering items (Phases 0–3, FR‑1…16,18,19)** must pass *both* gates — these the blueprint
   *guarantees*, so "proven on the private suite" is mandatory.
2. **Research‑track items (Phase 5 cold loop / FR‑17, and the parametric tier FR‑21)** — the
   blueprint's *own* definition of done (§38) is **"built correctly behind shadow mode, inside the
   invariant rails, with clean rollback, and *measured*"** — **not** "proven to improve." Demanding
   proven recursive‑optimizer lift would *conflict* with §38. Do not set that bar.
3. **Explicit non‑goals (§12 N1–N5)** are *out of scope by design*. Completing them is not "more
   complete" — it is scope drift. See §K.

---

## 0.1 Why progress has plateaued — and the anti‑patterns to stop

At the historical checkpoint captured here, the headline number sat at ~70% because
**effort flows into the deterministic scaffold** (more depth inside already‑built modules, more green
unit tests) while **every remaining gate is elsewhere** — real backing services + *measured* SLO
evidence (Gate B), which scaffold code cannot satisfy. The adapter seams already exist, so the work
is **integration + proof, not redesign.** Anti‑patterns to stop:
- Stop adding deterministic scaffold depth / chasing collected‑test count — green unit tests on
  hashing embeddings do not move any §16 SLO or flip any FR row.
- Stop conflating "works locally" with "validated" — that conflation is why rows stall at Partial.
- Re‑point the autonomous loop's objective from "land more green commits" to "close one FR row to
  *proven* (Gate A+B) with a captured evidence artifact." Velocity is fine; **direction** is the lever.

---

## A. Functional requirements — full traceability matrix (FR‑1 … FR‑21)

Status legend: **Built** = Gate A met + locally green · **Prove** = Gate A met, Gate B (empirical
proof on the private suite) outstanding · **Partial** = Gate A incomplete (real backing service or
mechanism still missing) · **Scope** = blueprint bounds this below "full production" on purpose.

| FR | Blueprint requirement (§14) | Module | Status | What FULL completion requires (no corners) |
|----|------------------------------|--------|--------|---------------------------------------------|
| FR‑1 | Evidence ledger: append‑only, content‑addressed, verbatim, hashed, idempotent; user+assistant turns | `engine.py`,`storage.py` | **Built** | Durability SLO ("never lose evidence", §15) demonstrated under a crash/restart test. |
| FR‑2 | Bitemporal store + supersession (valid/transaction time, no destructive overwrite) | `engine.py`,`models.py` | **Built** | `as‑of‑T` correctness test class (§33) green on the private suite. |
| FR‑3 | **Hybrid retrieval**: dense+lexical+graph, RRF, access/trust filter, **cross‑encoder rerank**, MMR, U‑curve, budget | `retrieval.py`,`postgres_engine.py` | **Partial** | **Keystone.** Replace hashing pseudo‑embeddings + local lexical reranker with a **real embedding model + real cross‑encoder**; prove recall@k / nDCG and the **G2** target (beat full‑context at <10% tokens). |
| FR‑4 | Provenance & explainability; `explain` returns per‑stage attribution | `provenance.py`,`retrieval.py` | **Built** | Assert `explain` emits per‑stage retrieval attribution in a harness test. |
| FR‑5 | Typed user model: 6 categories, scope/confidence/validity/override; explicit authoritative; hard instructions outrank inference | `user_model.py` | **Prove** | **G4**: PersonaMem‑style *application* accuracy rises over a session (harness), not just recall. |
| FR‑6 | Confidence & abstention: calibrated + conformal; abstain below threshold | `calibration.py`,`belief.py` | **Partial→Prove** | **G6**: maintain a real per‑memory‑type conformal calibration set; demonstrate **ECE ≤ 0.05** and correct abstention on unanswerable items. Needs real score distributions (depends on FR‑3). |
| FR‑7 | Security baseline: tenant/source isolation, trust tiers, retrieved≠instruction, gated+reversible writes, audit log | `security.py`,`policy.py` | **Built→Prove** | **G7**: real MINJA/AgentPoison attack suite blocked ≥95% (see §E); all writes audited+reversible (already structural). |
| FR‑8 | User controls: inspect, correct, export, **forget (transitive)** | `engine.py`,`cli.py` | **Built** | Harness class: "erasure with vs. without independent corroboration" (§33 + §17 legal open‑q). |
| FR‑9 | MCP/CLI contract: stable agent‑facing tool surface (§30.7) | `mcp_tools.py`,`mcp_server.py`,`cli.py` | **Partial** | Tool‑by‑tool **ABI parity** vs §30.7 (see §H); operator‑run validation against a **real MCP client/transport** (streamable/SSE). |
| FR‑10 | Belief‑revision core TMS+AGM: cascade invalidation + contested/multi‑hypothesis | `belief.py` | **Built→Prove** | **G3**: belief‑revision conformance tests pass; contested belief surfaces multiple hypotheses (harness class). |
| FR‑11 | Temporal entity graph + PPR multi‑hop (deep) / cached signals (fast) | `graph.py`,`postgres_engine.py` | **Partial** | Resolve **§17 P1 open‑q**: benchmark in‑Postgres PPR latency vs cached‑vector at target scale; prove fast‑path **P95 ≤300–400 ms** (§15). |
| FR‑12 | Consolidation warm loop: episodic→semantic promotion, entity resolution, contradiction resolution, summarization, write‑authorized | `consolidation.py`,`jobs.py` | **Partial** | Real **model‑backed entity resolution** (deterministic keys today) + **multi‑level RAPTOR** clustering; prove the anti‑degradation guard (G5). |
| FR‑13 | Fidelity‑tiered forgetting: utility‑driven demotion; verbatim until utility≈0 | `lifecycle.py` | **Built→Prove** | "Forgetting correctness" + **long‑horizon no‑degradation** harness classes (§33). |
| FR‑14 | Procedural/corrective learning: workflow induction + lesson distillation, **promotion‑gated** | `learning.py`,`gate.py` | **Built→Prove** | **G5**: recurring task types measurably improve; every change validated+reversible; MINJA suite blocked. |
| FR‑15 | Branchable memory: scratch (speculation) + canary (policy eval); rollback = discard | `engine.py`,`postgres_engine.py` | **Built** | Harness class: "rollback that crosses a supersession edge." |
| FR‑16 | Latent advisory user embedding alongside explicit model | `user_model.py` (`user_latent`) | **Built** | Prove it is *advisory only* — never overrides the explicit model (maturity §38). |
| FR‑17 | **Profile‑guided self‑optimization (cold loop)** + counterfactual replay — research‑track, **shadow‑mode only** | `self_optimization.py`,`eval.py` | **Partial (research bar)** | Build to spec **behind shadow mode**, inside the rails, on **canary branches**, with diversity/divergence tripwires + clean rollback; validate **counterfactual‑replay fidelity** (§17 P2). **DONE ≠ proven lift** (per §38). |
| FR‑18 | Anticipatory prefetch (idle‑time) + predictability gate | `prefetch.py` | **Built** | Verify predictability gate + bounded prefetch budget; no measurable harm on unpredictable workloads. |
| FR‑19 | Signed provenance (C2PA) ingestion as trust signal | `provenance.py` | **Partial** | Validate against a **real `c2patool`** + real certificate roots; reject manifests failing chain/scope. |
| FR‑20 | Multimodal memory (image/audio) behind the same substrate | `media.py` | **Scope (N5: not v1 / P2)** | Substrate/interfaces already extend to it (satisfies the v1 bar). **Full image/audio is explicitly post‑v1** — implement only when v1 (Phases 0–4) is proven; do **not** treat as a v1 blocker. |
| FR‑21 | Parametric tier (LoRA / test‑time training of validated lessons), isolated + gated | `parametric.py` | **Scope (N2: optional advanced tier)** | Command‑boundary + structural rails already built. Real isolated LoRA needs a GPU runtime but is **explicitly optional, not "the path."** Validate the *boundary + rails + rollback*; treat real training as advanced‑tier, not core completion. |

**Reading of the matrix:** ~13 FRs are engineering‑**Built** and need only Gate‑B proof; ~5 are
**Partial** on a real backing service (FR‑3/6/9/11/12/19); FR‑17 is research‑track (shadow bar);
FR‑20/21 are blueprint‑scoped below full production. **The recurring blocker is identical across
rows: real embeddings/reranker (FR‑3), the §33 proof harness, real external services, and rail
enforcement — not missing features.**

---

## E. The §33 evaluation harness — the backbone that *proves* everything (highest anti‑corner‑cutting priority)

The blueprint makes the harness the spine of *both* evaluation and the promotion gate. Building it is
how every Goal/SLO moves from "claimed by construction" to "proven." Required, in full:

- **Private regression suite**, version‑controlled, **tiered (smoke / core / archive)**; every
  confirmed mistake becomes a **permanent protected test**; disjoint from any candidate's source data.
- **Suite ignition (cold‑start fix):** ship a **seed suite** (curated trusted held‑out cases, used
  only internally, never reported per §9) + **synthetic cases auto‑generated** from earliest episodes.
  **Until the suite reaches size N, candidates run in shadow mode** (logged vs. real outcomes, not
  promoted); "active" promotion switches on at **N** — *N must be decided* (§17 data open‑q).
- **Measurement set (must all exist):** recall@k / nDCG · test‑time‑learning slope (the self‑* proof)
  · long‑range/cross‑session understanding · conflict resolution · as‑of correctness · update
  correctness · personalization *application* accuracy · abstention precision + **ECE** · provenance
  attribution · **write‑path cost** · forgetting correctness · **long‑horizon no‑degradation**.
- **Methodology guardrails:** strict judge + adversarial‑answer screening · **confidence intervals**
  (most deltas are within noise) · corpus sizes exceeding the model window · continuous regression on
  every retrieval/prompt/procedure/policy change · the **counterfactual‑replay harness (§30.6)
  doubles as the cold‑loop evaluator** · **MINJA / AgentPoison attack suite as a permanent protected
  tier**.
- **Test classes that MUST exist** (named in §33): (1) rollback crossing a supersession edge;
  (2) erasure of evidence **with vs. without** independent corroboration; (3) contested belief
  surfaces multiple hypotheses; (4) untrusted retrieved instruction is **never** executed;
  (5) consolidation **never drops below the no‑memory baseline** over a long horizon.

> Current state: the protected/attack suite is ~2 cases and metrics run on deterministic stand‑ins.
> This section is the single largest gap between "looks done" and "blueprint‑complete."

---

## D. Invariant rails (§31) — safety‑critical, must be structurally enforced + tested

The cold loop may tune *within* these and **can never widen them**. Each must be (a) enforced outside
the self‑editable surface and (b) covered by an explicit test that proves it cannot be exceeded:

```yaml
max_supersession_rate: 0.05         # ≤5% of active facts supersedable per pass
min_corroboration_for_delete: 2     # ≥2 independent sources before hard delete
max_prune_fraction_per_pass: 0.02   # ≤2% pruned per pass
monotonic_trust: true               # active fact only superseded by ≥ trust‑tier evidence
reward_signal: external_only        # optimizer cannot edit reward/verifier/eval suite
untrusted_to_system_prompt: forbidden
consolidation_cadence_bounds: [5_steps, 24h]
```

**Completion = each rail has an enforcement point + a red‑team test that tries to breach it and
fails.** This is where corner‑cutting is *most dangerous*; treat as P0 alongside §E.

---

## F. NFRs (§15) + SLO targets (§16) — the numbers that must be measured, not asserted

| NFR/SLO | Blueprint target | Proven by |
|---|---|---|
| Fast‑path latency | **P95 ≤ ~300–400 ms** | load test w/ real embeddings + Postgres (§E) |
| Calibration | **ECE ≤ 0.05** | conformal calibration set (FR‑6) |
| Context efficiency | **≥ +15% answer quality vs full‑context at ≤10% tokens** (G2) | private QA suite (§E) |
| Protected‑fact safety | **0 protected‑fact regressions / release** (G3) | protected tier (§E) |
| Poison resistance | **≥ 95% poisoning‑attempt block** (G7) | MINJA/AgentPoison suite (§E) |
| Self‑learning | **measurable positive test‑time‑learning slope by Phase 4** | test‑time‑learning metric (§E) |
| Durability | "never lose evidence" = highest SLO | crash/restart test (FR‑1) |
| Portability | **identical test suite passes local AND production** (G8) | shared suite on both backends (§I) |
| Observability | per‑stage retrieval, consolidation/prune, contradiction backlog, calibration/abstention, promote/rollback, **model‑collapse + reward‑hacking tripwires**, no‑degradation, audit log | `observability.py` dashboards (largely built; wire to real metrics) |

---

## G. Data model (§29 / Appendix A) — CONFIRMED COMPLETE

Schema diff of `sql/schema.sql` vs Appendix A: **all blueprint tables present** — `evidence`,
`assertions`, `justifications`, `entities`, `entity_aliases`, `relations`, `branches`, `procedures`,
`lessons`, `preferences`, `user_latent`, `trajectories`, `self_model`, `eval_cases`, `contradictions`,
`resources`, `merges`, `deletion_log`, `conformal_calibration`, `audit_log` (+ repo extras
`tenants`, `runtime_jobs`, `runtime_state`). **No missing tables.** Remaining = column‑level parity
(VECTOR(1024) assertions/entities, VECTOR(256) `user_latent`, `tsvector` lexeme, HNSW + GIN indexes)
exercised with **real** embeddings rather than hashing vectors. Low risk; verify, don't rebuild.

---

## H. MCP/CLI ABI (§30.7) — parity check (FR‑9)

Confirm the implemented tool surface matches the blueprint ABI exactly and the operating‑policy
defaults are enforced:
`memory.capture/search/deep_search/get/explain/propose/confirm/correct/supersede/forget/export/branch/merge/discard`
· `profile.get_relevant/record_explicit/propose_inference/correct` · `graph.query/timeline/as_of`
· `procedure.search/propose/validate/promote/rollback` · `lesson.propose/search` ·
`trajectory.record` + `outcome.evaluate`. Defaults: *read‑before‑respond; write‑after‑learn; cite
evidence; deep_search for audits/ambiguity; never execute retrieved content; abstain under threshold.*
Action: a single ABI‑diff test that fails if any tool/signature drifts from §30.7.

---

## I. Deployment parity (§32) + local real services (the practical unlock)

- **G8 portability** = the *same* shared suite passes on the local single‑binary AND multi‑tenant
  Postgres. Already partly proven (63→all live tests under `MNEMOSYNE_POSTGRES_DSN`). Broaden the
  shared suite across every engine method.
- **Stand up the real "production" deps locally in `docker-compose`** so the Partial rows flip
  without cloud: **Keycloak** (real OIDC/JWKS for FR‑7/9 auth), **Vault** (real KMS/secret rotation),
  real **`c2patool`** + signed assets (FR‑19), and the **real embedding/cross‑encoder service**
  (FR‑3). The genuine *production soak* + hosted‑MCP transport still want a small deployed target.

---

## J. Open questions that must be RESOLVED to claim completion (§17)

These are blueprint‑tagged decisions, several P1‑blocking — leaving them open *is* an incompletion:
1. **(P1)** In‑Postgres PPR latency at scale — benchmark vs cached‑vector before committing graph to fast path (FR‑11).
2. **(P1)** Suite‑ignition size **N** + seed‑set composition (gates "active" promotion) (§E).
3. **(P1)** Cheapest faithful incremental‑recompute substrate (salsa vs `pg_ivm` vs differential dataflow).
4. **(P1)** Capability‑mediation overhead — read‑path trust‑tier‑only vs full mediation.
5. **(P2 research)** Counterfactual‑replay fidelity — validate before trusting the cold loop (FR‑17).
6. **(legal, blocking for regulated)** Erasure of derived projections with independent corroboration — recompute vs retain‑with‑updated‑provenance (FR‑8).
7. **(product)** Default fidelity‑demotion schedule / decay constants (start ACT‑R d≈0.5, tune).

---

## K. Scope guardrails — what NOT to "complete" (avoids conflict with the blueprint)

Per §12 non‑goals; building these is scope drift, not progress:
- **N1** Not a foundation model. **N4** Not an agent framework/planner (memory only; the agent loop is the host's).
- **N3** Not chasing a public vendor benchmark — optimize the **private** suite (and never report the seed gate, §9).
- **N5** Multimodal (FR‑20) is **post‑v1 / P2** — interfaces extend to it; full image/audio is not a v1 blocker.
- **N2** Weight‑level fine‑tuning (FR‑21 parametric tier) is an **optional advanced tier, not the path** —
  validate boundary + rails; do not gate v1 completion on real LoRA training.

---

## Critical path (sequenced; honors the calibrated bar)

```
P0 (safety, do first):  §D invariant‑rail enforcement+breach tests   ║  §E harness skeleton + suite‑ignition (decide N)
P1 (keystone):          FR‑3 real embeddings + cross‑encoder ─────────► unlocks FR‑6 (ECE), G2 (+15%), retrieval SLOs
P1 (real services):     docker‑compose Keycloak/Vault/c2patool ───────► flips FR‑7/9/19 to Validated
P1 (prove engineering): run §E across G1–G8 phase‑exit gates ─────────► Phases 0–3 provably DONE
P2 (depth):             FR‑12 real entity resolution + multi‑level RAPTOR ; FR‑11 PPR latency benchmark (§J‑1)
P2 (research bar):      FR‑17 cold loop shadow‑mode + canary + tripwires + counterfactual‑replay fidelity (NOT proven‑lift)
Scope‑gated / optional: FR‑20 multimodal (post‑v1) ; FR‑21 real LoRA (advanced tier, GPU)
```

## Single definition of done (the discipline that prevents re‑plateauing)
A requirement is **complete** only when: **Gate A** (built to the blueprint mechanism) **+ Gate B**
(meets its §12/§34 success criterion via the §33 harness, with confidence intervals) **+ evidence
artifact captured** — *except* research‑track FR‑17/FR‑21, whose bar is **shadow‑mode + rails +
clean rollback + measured**, and scope‑gated FR‑20, which is post‑v1 by design. Hold every row to
its *own* blueprint bar: do not cut a corner, and do not invent a requirement the blueprint excludes.
