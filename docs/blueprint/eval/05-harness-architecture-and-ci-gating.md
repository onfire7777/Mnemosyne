# 05 — Harness Architecture & CI / Gating

**Purpose.** This document specifies the **evaluation harness**: the program that loads test cases, drives the system-under-test (SUT) through its agent-facing surface, scores results with the metrics defined in `01-metrics-specification.md`, and reports them to CI and to the promotion gate. It defines *how the harness runs, schedules, scopes, scores, and reports tests* — the validation-lane plumbing that exercises the fixed contracts and feeds the gate. It implements the cost-bounded tiering of §23.3, the shadow↔active lifecycle of §33, and the eval-rollout posture of §34/§38 (`_CONTRACTS §1.12`).

**Boundary: this doc does not redefine functional policy.** It does **not** define the promotion-gate decision logic (`§23`) or the policies the gate protects (retrieval `§22`, consolidation `§21`, lifecycle `§25`, belief `§23/I2`, user model `§24`, confidence `§26`, security `§10/§27`, invariant rails `§31`). Those are **owned by other lanes** and the gate logic itself is owned by `06-release-gate-and-tripwire-runbooks.md`. The harness *consumes* the gate contract and *supplies* it tiered results — it never decides promotion. Per the **reward-signal rail** (`§31`: `reward_signal: external_only`, `_CONTRACTS §1.9`) the harness, its case store, judge, and metric calculators are designed to live **outside the self-editable surface** the cold-loop optimizer can touch. No product thresholds are invented here; numeric floors are quoted from `§16/§15/§31` or marked `TBD-by-§N`.

Cross-doc dependencies: metric IDs `M-*` from `01`; test IDs `T-<DOMAIN>-<NNN>` and scenarios `S1..S12` from `02a/02b/04` and the charter; dataset IDs `DS-*` from `03`; tripwire IDs `TW-*` / runbook `RB-*` and the gate logic from `06`.

---

## 1. Harness architecture

### 1.1 Components

| Component | Role | Reads | Writes | Owned-policy it must NOT redefine |
|---|---|---|---|---|
| **Case store / loader** | Authoritative, versioned, read-only-to-SUT registry of `T-*` cases (`02a/02b/04`), golden scenarios `S1–S12`, protected flags, and dataset bindings `DS-*` (`03`). Tags each case with `layer L0–L8`, `phase 0–5`, `gating|shadow`, `protected?`, and a **change-signature** (§3.3). | `02a/02b/03/04` | — | — |
| **Runner / scheduler** | Selects the case set for a trigger (§2, §3), resolves relevance scope, executes in tier order, enforces seeds/determinism, collects raw outputs. | case store, change manifest | results store | — |
| **SUT driver** | Drives the system **only through the §30.7 MCP surface** (`_CONTRACTS §1.3`): `capture/search/deep_search/get/explain/propose/confirm/correct/supersede/forget/export/branch/merge/discard`, `profile.*`, `graph.*`, `procedure.*`, `lesson.*`, `trajectory.record`, `outcome.evaluate`. White-box store/property assertions (L0/L1) use a separate read-only inspection adapter, never the gate path. | MCP surface | SUT state (test tenant) | retrieval/belief/lifecycle internals |
| **Judge service** | Strict LLM-judge + adversarial-answer screening per the judge protocol in `01`; pinned model + prompt (§8.4). Emits per-case correctness used by `M-*` calculators. | SUT outputs, gold | raw verdicts | judge protocol owned by `01` |
| **Metric calculators** | Pure functions implementing `M-RECALL@K, M-NDCG@K, M-TOKEN-EFF, M-ECE, M-ABST-PREC, M-POISON-BLOCK, M-TTL-SLOPE, M-NODEGRADE, M-ASOF-ACC, M-AGM-CONF, M-FASTP95, M-PARITY, M-ERASURE, M-APPLY-ACC` with bootstrap CIs (`01`). | judge verdicts, raw logs | scored metrics | metric defs owned by `01` |
| **Reporter** | Renders the CI report, dashboards, gate payload (§6), and tripwire feed (§8) for `06`. | scored metrics | report artifacts, gate payload | tripwire/alarm logic owned by `06` |
| **Results store** | Append-only, content-addressed record of every run: case id, seed, corpus pin, deployment, verdict, metric+CI, judge build, SUT commit. Retention per §5.4. | all above | immutable run rows | — |
| **Counterfactual-replay runner** | Replays historical sessions against a candidate memory state on a canary branch (§7). Output stays **shadow-only** until replay fidelity is validated (`§17`). | DS-replay sessions | shadow results | replay-fidelity question owned by research lane (`§17`) |

### 1.2 Data-flow diagram

```
        ┌──────────────┐   change manifest (§3.3)
        │  CI trigger   │──────────────┐
        │ (§2/§5)       │              ▼
        └──────────────┘     ┌───────────────────┐
                              │ Runner/Scheduler   │  selects tier (§2.2)
   ┌────────────┐  cases      │  + relevance scope │  + scope (§3.3)
   │ Case store │────────────▶│  + seeds/corpus pin│
   │ +DS bind   │             └─────────┬─────────┘
   └────────────┘                       │ drive (§30.7 MCP only)
   02a/02b/03/04                         ▼
                              ┌───────────────────────┐
                              │   SUT driver            │  white-box adapter
                              │  (MCP surface)          │◀── L0/L1 read-only
                              └─────────┬─────────────┘
                                        │ raw outputs + per-stage logs
                                        ▼
                              ┌──────────────┐   verdicts   ┌───────────────────┐
                              │ Judge service │────────────▶│ Metric calculators │ (M-*, + CIs)
                              │ (pinned)      │             │   from 01           │
                              └──────────────┘             └─────────┬─────────┘
                                                                     │ scored metrics
                              ┌────────────────┐                     ▼
                              │ Results store   │◀──────────  ┌──────────────┐
                              │ (append-only)   │            │   Reporter    │
                              └────────────────┘            └──────┬───────┘
                                                                   │
                          ┌────────────────────────────────────────┼───────────────┐
                          ▼                       ▼                 ▼               ▼
                   CI report (§5)         Gate payload (§6)   Dashboards (§8)  Tripwire feed (§8)
                                          → consumed by §23      → 06             → TW-* in 06

  ── trust boundary ───────────────────────────────────────────────────────────────
  Everything above lives OUTSIDE the self-editable surface (§31 reward_signal: external_only).
  The cold-loop optimizer (§23/Phase 5) can read gate verdicts but CANNOT mutate the
  case store, judge, metric calculators, or results store.
```

### 1.3 Local-first vs production harness — same code, G8 parity

The harness is **one codebase** with a deployment adapter, mirroring the SUT's local→production portability (`§32`). G8 (`_CONTRACTS §1.1`) requires the **identical suite** to pass on both; divergence is a release blocker (L7).

| Aspect | Local-first single binary | Production worker-fleet |
|---|---|---|
| Form | One process; embedded Postgres SUT; in-process runner | Worker fleet (consolidation/embedding/eval workers, `§32`); stateless dispatch |
| Concurrency | Sequential / small pool | Sharded across cases & corpora |
| Corpus | Bundled `DS-SEED` + user corrections (`03`) | Full `DS-PRIV` archive (`03`) |
| Judge | Pinned local/smaller judge, same prompt | Pinned hosted judge, same prompt+version |
| Tiers run | Smoke + scoped core locally; full archive deferred to fleet | All tiers including nightly/pre-release full archive |
| Parity gate | — | `M-PARITY` asserts identical pass/fail on `S1–S12` (L7, `T-PRT-*`) |

Same-code requirement: case store, calculators, judge protocol, and assertion logic are shared modules; only the scheduler/executor backend differs. The **parity check itself** (`M-PARITY`, L7, pre-release gating) runs the shared suite on both deployments and diffs verdicts case-by-case.

---

## 2. Test layering & execution model

### 2.1 Layers L0–L8 → where they run (charter §2)

| Layer | Proves | Default cadence | Default posture |
|---|---|---|---|
| **L0** Invariant & property (deterministic) | structural guarantees never break: dedup/idempotency FR-1; append/supersede/versioned mutability §19; AGM conformance §23/I2; safety invariant over random op sequences §31; data-never-instruction §10/§27 | **per-commit** | gating (P0–3) |
| **L1** Component / contract | each component honors its contract on fixed inputs: planner recall floors §22; consolidation projection §21; belief supersession+as-of §23; lifecycle ladder §25; abstention §26; user-model precedence §24 | **per-commit** | gating |
| **L2** Integration / behavioral (golden) | end-to-end capture→consolidate→retrieve→correct loop; golden `S1–S12` §4 | **per-PR** (scoped); **nightly** full | gating |
| **L3** Longitudinal / temporal | behavior over time: `M-TTL-SLOPE` G5; `M-NODEGRADE` §25/§32; cross-session > window; correction/re-establishment trend §16 | **nightly + pre-release** | gating P0–3; shadow for Phase 4–5 capability |
| **L4** Adversarial / security | safety-by-construction G7: poisoning block ≥95% `M-POISON-BLOCK`; AgentPoison/PoisonedRAG/MemoryTrap/SpAIware (`04`); audited+reversible | **pre-release** (+ scoped on security-surface change §5.1) | gating |
| **L5** Calibration & abstention | `M-ECE` ≤0.05; `M-ABST-PREC` §26 | **nightly** | gating P3 |
| **L6** Personalization-application | `M-APPLY-ACC` G4 §24 | **nightly** | gating P3 |
| **L7** Portability parity | identical suite passes local↔production `M-PARITY` §15/§32 G8 | **pre-release** | gating |
| **L8** Performance / SLO | fast-mode `M-FASTP95` P95 ≤ 300–400 ms §15/§22.5; write-path/gate cost sub-linear §23.3; evidence durability | **per-PR + continuous** | gating |

### 2.2 Cost-bounded tiering (§23.3)

The harness runs in **three tiers** so cost tracks change-size, not total suite size:

```
┌─────────────────────────────────────────────────────────────────────┐
│ TIER 1 — SMOKE              per commit / per batch · SYNCHRONOUS       │
│   • L0 + L1 + L8 deterministic subset, relevance-scoped (§3.3)        │
│   • point estimates, no CIs needed (deterministic)                    │
│   • blocks merge if red                                               │
├─────────────────────────────────────────────────────────────────────┤
│ TIER 2 — STRATIFIED CORE    per PR · SAMPLED, WITH CIs                 │
│   • L2 golden + L3/L5/L6 sampled strata; bootstrap CIs (01)           │
│   • scoped to change-signature overlap; protected cases always in     │
│   • "delta within noise" = NO SIGNAL (not pass, not regression) §6    │
├─────────────────────────────────────────────────────────────────────┤
│ TIER 3 — FULL ARCHIVE       nightly + pre-release · EXHAUSTIVE         │
│   • entire DS-PRIV archive, all layers incl. L4/L7, full CIs          │
│   • produces the pre-release gate payload (§6) + parity (§1.3)        │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 Relevance scoping — cost ∝ affected cases

Tiers 1–2 run **only cases whose change-signature overlaps the change** (`§23.3`, charter §6.4):

1. Each case declares a **signature**: the policy surfaces / components it exercises — `{retrieval, prompts, procedures, policies, belief, lifecycle, security, user-model, schema}` (drawn from its `requirement(s)` + `interface`).
2. CI derives a **change manifest** from the diff (touched modules/configs/prompts/skills).
3. Runner selects `cases where signature ∩ change-manifest ≠ ∅`, **union all protected cases** (protected cases run on every change — never scoped out), **union L0** (always runs; cheap & deterministic).
4. Cost is then proportional to affected cases, not the archive. Nightly/pre-release ignore scoping and run full.

> Scoping selects *which* cases run; it never relaxes *what* a case asserts and never narrows the protected ratchet.

---

## 3. Triggers, scheduling & determinism

### 3.1 Trigger matrix

| Trigger | Tier | Layers | Blocking? |
|---|---|---|---|
| commit push | Smoke | L0,L1,L8(subset) scoped | yes |
| PR open/update | Smoke + Stratified core | L0,L1,L8 + L2 golden + L3/L5/L6 sampled, scoped | yes (merge gate, §5) |
| security-surface change | + L4 scoped | adds `T-SEC` overlap (`04`) | yes |
| nightly | Full archive | all layers, full corpus, full CIs | no (alerts only) |
| pre-release | Full archive + parity + counterfactual replay | all + L7 `M-PARITY` + §7 | yes (release gate, §6) |

### 3.2 Reproducibility — see §8.4 (seeds, fixed corpora, pinned judge).

---

## 4. Shadow ↔ active lifecycle (§33)

A test/metric is **shadow** (logged, never gates) or **active** (gates per posture). The harness owns the *mechanism*; the **gate/owning lane owns the flip decision** (`§33`, charter §6.7).

```
              suite size < N  OR  capability is Phase 4–5
                         │
            ┌────────────┴────────────┐
            ▼                          ▼
        SHADOW                       (else)
   log prediction vs              ┌──────────┐
   real outcome; never  ──flip──▶ │  ACTIVE   │ gate per L-posture (§2.1)
   blocks; feeds dashboards       └──────────┘
   (§8) + replay (§7)        flip authority = gate/owning lane,
                              NOT the harness, NOT the optimizer (§31)
```

- **When shadow:** (a) total confirmed-case suite size is **below ignition size N = `TBD-by-§17`** (suite-ignition size & seed composition is an open question owned by the gate/data lane, `§17/§23.3/§33`); or (b) the capability is **Phase 4 (validated lessons/skills) or Phase 5 (cold-loop)** — shadow-first until its own measurement validity is proven (`§1.12`, charter §9). Shadow mode records the harness's predicted verdict alongside the real downstream outcome so the metric's validity can itself be measured before it is trusted to gate.
- **When active:** Phases 0–3 hard-gating layers above suite size N flip to active per `§2.1`. Phase 4 flips to gating **once `M-TTL-SLOPE` is positive and stable** (charter §9); Phase 5 flips **only after counterfactual-replay fidelity is validated** (`§17`, §7).
- **Posture rule (`§1.12`):** Phases 0–3 = hard gates; Phases 4–5 = diagnostics behind rails until validated. The harness emits both verdicts always; gating consumption is toggled by the owning lane via a config flag the optimizer cannot edit (`§31`).

---

## 5. CI triggers, merge-blocking & retention

### 5.1 Continuous regression — what triggers a scoped run

Per `§23.3` / charter §6.5, the harness runs a scoped regression on **every change to**: **retrieval, prompts, procedures/skills, or policies** (plus belief/lifecycle/security/user-model/schema surfaces). The change manifest (§3.3) maps the diff to signatures; no change in those surfaces merges without a **green scoped run**.

### 5.2 What blocks merge (PR gate)

A PR cannot merge unless its scoped Smoke + Stratified-core run is green under these conditions:
- **0 protected-case regressions** (protected cases always in scope, §3.3).
- L0/L1 deterministic layers all pass.
- L8 SLO subset within budget: `M-FASTP95` ≤ 300–400 ms (`§15/§22.5`).
- Stratified-core metrics meet stored floors *with margin > run-to-run noise* (§6); a delta inside CI noise is **no signal**, neither pass nor regression (charter §6.6).
- If security surface touched: scoped `T-SEC` (`04`) green.

> The merge gate is a **subset** of the release gate (§6). Release adds the full archive, parity (L7), L4/L5/L6, and counterfactual replay (§7).

### 5.3 How scoped runs are selected — §3.3 (change-signature overlap ∪ protected ∪ L0).

### 5.4 Artifact / report retention

| Artifact | Retention |
|---|---|
| Results-store run rows (immutable: case id, seed, corpus pin, deployment, verdict, metric+CI, judge build, SUT commit) | permanent (audit + ratchet provenance) |
| Per-stage retrieval/judge raw logs | rolling window `TBD-by-§32` |
| CI report HTML/JSON per run | per-PR until merge + N releases `TBD-by-§32` |
| Gate payload (§6) | permanent (tied to release) |
| Shadow predictions + real-outcome pairs | until metric flips active + validation window |

Retention windows beyond "permanent" are an ops decision owned by observability (`§32`) → `TBD-by-§32`.

---

## 6. Integration with the promotion gate (§23) — consumed, not redefined

The harness **supplies inputs**; the gate (logic owned by `06`, semantics by `§23`) **decides**. The harness never encodes the decision.

**What the harness supplies to the gate:**
1. **Tiered-suite result** — full-archive (Tier 3) scored metrics with bootstrap CIs (`01`), protected-case verdicts, and the per-floor pass/fail vs `§16` stored floors.
2. **Counterfactual-replay-on-canary-branch result** (§7) — supplied as **shadow signal** until replay fidelity is validated (`§17`); flagged so the gate treats it as non-blocking pre-proof.

**The gate's contract (asserted by this lane, defined in `§23` / charter §6.3) — promote only if:**

```
   promote ⇔  non-inferior
          AND no protected-case regression
          AND margin > run-to-run noise        (delta inside CI = "no signal" → not promote)
   rollback = discard the candidate branch     (no destructive edit to main)
```

**Teaching-to-the-test prevention (harness-enforced).** The harness enforces **source/suite disjointness**: candidate-generating data (corrections, induced lessons, replayed sessions) must be **disjoint** from the evaluation suite that judges the candidate (charter §6.3, `§9`). The case store tags each case with its provenance lineage; the runner **rejects a gate run** whose candidate source intersects the scoring suite, and the disjointness check is logged in the gate payload. Combined with `reward_signal: external_only` (`§31`), this keeps the optimizer from gaming or editing its own grader.

---

## 7. Counterfactual-replay runner (§17, FR-17, shadow-only)

**What it does.** Reconstructs a **candidate memory state on a canary branch** (`memory.branch`), then **replays historical sessions** (`DS-replay` from `03`) against that branch — re-issuing the recorded turns through the §30.7 surface and comparing the candidate's responses/outcomes to the **real recorded outcomes**. The intent (per `§23`/§17) is to predict whether a candidate change would have improved real sessions before promoting it.

```
 real session log ──► branch = candidate memory state (canary)
        │                         │
        │  replay recorded turns via MCP surface
        ▼                         ▼
   real outcome  ── compare ──  candidate outcome  ──► predicted-lift signal
                                                        (SHADOW until §17 validated)
   branch is DISCARDED after replay (rollback = discard, §6)
```

**The open question (must be stated, not resolved).** **Replay fidelity is itself unproven** — whether "replay this historical session against the candidate" actually predicts real lift is an open question owned by the **research lane** (`§17`, charter §7/§10). The harness therefore:
- runs replay only on a **canary branch**, discarding it afterward (never mutates main; rollback = discard, §6);
- keeps the replay/cold-loop result **shadow-only** (logged, fed to dashboards §8, **never gating**) until fidelity is validated;
- records predicted-lift vs real-lift pairs so fidelity *can* be measured before the signal is ever trusted (the §4 shadow mechanism). Phase 5 evals flip active only after this proof (`§1.12`, §4).

---

## 8. Reporting & observability hooks (feed `06`'s tripwires)

### 8.1 Signals the harness emits (continuous + per-run, → `§32` dashboards / `06` tripwires)

| Emitted signal | Source | Feeds |
|---|---|---|
| Per-stage retrieval metrics + P95 (channel hit-rates, `M-RECALL@K`, `M-NDCG@K`, `M-FASTP95`) | metric calc + L8 | retrieval dashboard |
| Calibration + abstention rates (`M-ECE`, `M-ABST-PREC`) | L5 | calibration dashboard |
| Promote / rollback counts (candidate→promote→rollback) | gate payload (§6) | gate dashboard |
| **Diversity / entropy of learned lessons** | L3/Phase-4 shadow | **`TW-COLLAPSE`** (model-collapse) → freeze promotion |
| **Proxy-vs-true success divergence** | shadow vs real outcome (§4/§7) | **`TW-REWARDHACK`** → freeze promotion, re-anchor proxy |
| **Long-horizon no-degradation** (`M-NODEGRADE` vs no-memory baseline) | L3 | **`TW-NODEGRADE`** → halt cadence changes, rebuild from evidence |
| Security audit-log completeness | L4 (`04`) | security dashboard |

> The three tripwires `TW-COLLAPSE / TW-REWARDHACK / TW-NODEGRADE` and their runbooks `RB-*` are **defined in `06`** (consumed from observability `§32`, charter §8). The harness only **emits** the underlying signals; alarm thresholds and responses are owned by `06`.

### 8.2 CI dashboard
Per-run report: tier, scope set, layer pass/fail, each `M-*` with point estimate + CI, protected-case roll-up, floor-comparison table (vs `§16`), parity diff (L7), shadow-vs-active annotations, and the gate payload (§6). Trend views render `M-TTL-SLOPE`, `M-NODEGRADE`, correction/re-establishment trends over releases.

### 8.3 Flake handling
- Deterministic layers (L0/L1) **must not flake**; a non-reproducible L0/L1 failure is itself a defect, quarantined with rationale by the owning lane (never silently retried).
- Stochastic layers (judge-scored L2–L6): repeat-`r` sampling with bootstrap CIs (`01`); a result is a regression only if the **CI margin clears run-to-run noise** (charter §6.6) — this absorbs benign flake without hiding real regressions. Flake rate per case is tracked; chronically flaky cases are flagged for `01`/owning-lane review, not auto-deleted.

### 8.4 Reproducibility
- **Seeds:** every run records and re-uses fixed RNG seeds for sampling, MMR, and any stochastic SUT path exposed for test.
- **Fixed corpora:** corpora are **content-addressed and pinned** (`DS-*` from `03`); a run records the exact corpus hash. Corpus size must exceed the model window (`§9`, charter §7) so full-context baselines stay valid.
- **Pinned judge:** judge model id + prompt + version are pinned and recorded per run (`01`); judge upgrades are themselves a change that triggers re-baselining and a human-audit recalibration of the judge's false-accept rate (open question, charter §10 / `§9`).

---

## 9. Phase rollout of the harness itself

| Phase | Harness capability shipped | Posture |
|---|---|---|
| **Phase 0** | **CI pipeline + seed regression suite (`DS-SEED`) + shadow-mode harness** stood up; case store, runner, SUT driver (§30.7), results store, reporter; smoke tier wired to per-commit (`§1.12` exit: capture→byte-exact retrieval; idempotent dedup; per-source isolation; **shadow logging live**) | shadow + L0/L1 gating bootstrap |
| **Phase 1** | Stratified-core tier; judge service + calculators for retrieval/recall; L2 golden `S1,S4`; L8 SLO; parity scaffold | hard-gating L0/L1/L8 |
| **Phase 2** | L3 longitudinal + as-of; belief/temporal cases `S2,S3,S11`; full-archive nightly | hard-gating L2/L3 |
| **Phase 3** | L4 (`04`)/L5/L6/L7 wired; pre-release full archive + parity + counterfactual-replay runner (shadow); `S5–S10,S12` | hard-gating L4–L7 |
| **Phase 4** | Phase-4 capability metrics emitted **shadow-first**; flip to gating once `M-TTL-SLOPE` positive & stable | shadow → gating |
| **Phase 5** | Cold-loop counterfactual-replay signal supplied to gate **shadow-only** until replay fidelity validated (`§17`); never blocks release pre-proof | shadow-only |

---

## 10. TBD-by-§ register (no invented thresholds)

| Item | Status |
|---|---|
| Suite-ignition size **N** (shadow→active threshold) & seed composition | `TBD-by-§17` (gate/data lane, §23.3/§33) |
| Counterfactual-replay fidelity (does replay predict real lift) | `TBD-by-§17` (research lane) — replay shadow-only until proven |
| Judge false-accept rate floor + human-audit recalibration cadence | `TBD-by-§9` / charter §10 |
| Raw-log & report retention windows | `TBD-by-§32` (observability/ops) |
| Tripwire alarm thresholds + `RB-*` responses | owned by `06` (consumed from §32) |

All gating numeric floors are quoted, not set: poisoning block ≥95%, `M-ECE` ≤0.05, fast-path P95 ≤300–400 ms, 0 protected-fact regressions, `≥ +15%` answer quality at `≤10%` tokens (`§16/§15`, `_CONTRACTS §1.10`).
