# 00 — Traceability Matrix (`00-traceability-matrix.md`)

**Purpose.** The integrative spine of the eval suite. It proves **coverage**: every blueprint goal (G1–G8) and functional requirement (FR-1…FR-21) maps to ≥1 metric (`M-*`), ≥1 test domain (`T-*`), the golden scenarios (S1–S12) that exercise it, the datasets (`DS-*`) that feed it, and the phase/posture at which it gates. It then aggregates every open `TBD-by-§` to its owning lane and lists the **intentional coverage gaps** so nothing is silently assumed covered.

**Boundary: this matrix maps validation coverage; it does not assign or alter functional ownership.** It cites what each lane owns (per `_CONTRACTS.md §1`) and traces how the suite *checks* it. It introduces no new policy and no new threshold. Where a value is owned-elsewhere-and-open, it is carried as `TBD-by-§N` (§5 register), never resolved here.

**Suite at a glance.** 8 goals · 21 FRs (9 P0 · 7 P1 · 5 P2) · **33 metrics** (25 in `01` §2 + 8 structural in `01` §6; canonical IDs only) · **~210 concrete cases** across 12 test domains (`02a` 101 · `02b` 67 · `04` 22 = 190 catalog cases + L0 invariant properties) · 12 golden scenarios · 11 datasets (+7 typed slices) · 3 tripwires.

---

## 1. Canonical registries (pointers — defined elsewhere, listed here for joins)

- **Metrics (33):** authoritative in `01-metrics-specification.md` §2 (25) + §6 (8 structural). Canonical IDs only; retired aliases: `M-CONTRA-CORR→M-CONTRA-RES`, `M-REESTABLISH→M-REESTABLISH-RATE`.
- **Test domains (12) & counts:** `EVD 15 · RET 22 · UPD 18 · CON 17 · LIF 14 · ERA 15` (`02a`=101); `CAL 14 · PER 15 · INV 14 · PRT 12 · PERF 12` (`02b`=67); `SEC 22` (`04`). Plus L0 invariant property tests embedded in `INV`.
- **Scenarios (12):** S1–S12 defined in the charter `../Mnemosyne-Evaluation-and-Test-Plan.md` §4.
- **Datasets (11 + 7 slices):** `03-dataset-and-corpora-spec.md` §1 + §13 slices (`DS-RET-LABELED/TEMPORAL/CONTRA/CONSOL/LIFECYCLE/ERASURE/CORROB` = typed slices of `DS-PRIV`).
- **Tripwires/runbooks:** `TW-COLLAPSE→RB-1`, `TW-REWARDHACK→RB-2`, `TW-NODEGRADE→RB-3` in `06-release-gate-and-tripwire-runbooks.md`.

---

## 2. Goal coverage matrix (G1–G8)

Every goal has ≥1 **gating** metric + test domain + scenario + dataset. "Success condition" quoted from §12.

| Goal | Success condition (§12) | Metrics | Test domains | Scenarios | Datasets | Gating phase |
|---|---|---|---|---|---|---|
| **G1** Lossless recall | deep-mode exact-reconstruction passes on adversarial recall suite | M-EXACT-RECON, M-DEDUP-EXACT, M-MERKLE-OK, M-WRITEPATH; (M-ERASURE bounds it) | T-EVD, T-RET(deep), T-LIF(pointer) | S1, S10 | DS-RECALL-ADV, DS-PRIV | 1 |
| **G2** Precise retrieval | higher answer quality at <10% full-context tokens | **M-TOKEN-EFF**, M-RECALL@K, M-NDCG@K, M-CTX-PRECISION, M-EXPLAIN-COV, M-FASTP95, M-MRR(diag) | T-RET, T-PERF | S4 | DS-RET-LABELED, DS-NODEGRADE(window), DS-PRIV | 1 |
| **G3** Clean updates | belief-revision conformance passes; 0 protected-fact regressions after updates | M-ASOF-ACC, M-AGM-CONF, M-CONTRA-RES, M-CASCADE-CORR, M-PROV-COMPLETE, M-PROTECTED-REG | T-UPD, T-CON, T-INV | S2, S3, S6, S11 | DS-TEMPORAL, DS-CONTRA, DS-PRIV | 2 |
| **G4** Personalization | application accuracy rises over a session | M-APPLY-ACC, M-CORRECTION-TREND, M-REESTABLISH-RATE | T-PER | S7 | DS-PERSONA | 3 |
| **G5** Self-improvement | monotonic non-regression on protected suite + positive lift on held-out | M-TTL-SLOPE, M-PROTECTED-REG, M-NODEGRADE | T-CON, T-PER | S3(gate), S9 | DS-PRIV held-out, DS-NODEGRADE | 4 (shadow-first) |
| **G6** Knows what it knows | ECE below threshold; abstains on unanswerable | **M-ECE**, M-ABST-PREC | T-CAL | S5, S6 | DS-PRIV (answerable+unanswerable) | 2 |
| **G7** Safe by construction | MINJA-style suite blocked; all writes audited+reversible | **M-POISON-BLOCK**, M-BENIGN-DROP, M-AUDIT-COMPLETE, M-CONTRA-RES(trust), M-ERASURE | T-SEC, T-INV | S8, S10 | DS-POISON(+benign) | 3 (isolation from 0) |
| **G8** Portable | identical suite passes local + production | **M-PARITY**, M-FASTP95(per-env) | T-PRT, T-PERF | S12 | the gating suite | 1+ |

---

## 3. Functional-requirement coverage (FR-1…FR-21)

P0/P1 are all covered by gating or shadow tests. P2 are *design-for* — coverage is intentionally partial; gaps are explicit in §4.

| FR | Priority | Metric(s) | Test domain(s) | Scenario | Phase / posture |
|---|---|---|---|---|---|
| FR-1 Evidence ledger | P0 | M-DEDUP-EXACT, M-MERKLE-OK, M-EXACT-RECON | T-EVD | S1 | 0–1 / gating |
| FR-2 Bitemporal supersession | P0 | M-ASOF-ACC, M-CONTRA-RES, M-AGM-CONF | T-UPD | S2 | 1–2 / gating |
| FR-3 Hybrid retrieval | P0 | M-RECALL@K, M-NDCG@K, M-CTX-PRECISION, M-TOKEN-EFF, M-FASTP95 | T-RET, T-PERF | S4 | 1 / gating |
| FR-4 Provenance & explain | P0 | M-PROV-COMPLETE, M-EXPLAIN-COV | T-RET, T-EVD | S11 | 1 / gating |
| FR-5 Typed user model | P0 | M-APPLY-ACC, M-PROTECTED-REG | T-PER | S7 | 3 / gating |
| FR-6 Security/isolation | P0 | M-POISON-BLOCK, M-AUDIT-COMPLETE, M-BENIGN-DROP | T-SEC, T-INV | S8 | 0(iso)–3 / gating |
| FR-7 Pref/policy enforcement | P0 | M-POISON-BLOCK, M-CONTRA-RES(trust) | T-SEC, T-INV | S8 | 3 / gating |
| FR-8 Erasure | P0 | M-ERASURE | T-ERA | S10 | 1 / gating |
| FR-9 MCP/CLI contract | P0 | (all MCP-driven cases), M-FASTP95 | all domains, T-PERF | S1–S12 | 0 / gating |
| FR-10 Belief core (TMS+AGM) | P1 | M-AGM-CONF, M-CASCADE-CORR, M-CONTRA-RES | T-UPD, T-CON | S2, S6 | 2 / gating |
| FR-11 Temporal graph + PPR | P1 | M-RECALL@K(graph chan), M-FASTP95(PPR) | T-RET, T-PERF | S11 | 2 / gating (PPR latency = §17 open q) |
| FR-12 Consolidation | P1 | M-CONSOL-REBUILD, M-RECOMPUTE-SCOPE, M-WRITEPATH, M-NODEGRADE | T-CON | S2, S3, S9 | 2 / gating |
| FR-13/14 Gated learning | P1 | M-TTL-SLOPE, M-PROTECTED-REG | T-CON, T-PER | S3 | 4 / **shadow-first** |
| FR-15 Branchable memory | P1 | (reversibility) M-AUDIT-COMPLETE; used by gate | T-INV, T-SEC | S8 | 2 / gating |
| FR-16 Latent advisory model | P1 | M-APPLY-ACC (latent never overrides explicit) | T-PER | S7 | 3 / gating |
| FR-17 Cold-loop PGO + replay | P2 | M-TTL-SLOPE; counterfactual-replay | T-CON | — | 5 / **shadow-only** (replay-fidelity §17) |
| FR-18 Anticipatory prefetch | P2 | (prefetch predictability) M-FASTP95 | T-PERF | — | design-for / **gap §4** |
| FR-19 C2PA signed provenance | P2 | M-POISON-BLOCK (trust signal) | T-SEC | S8 | shadow until substrate / **partial §4** |
| FR-20 Multimodal memory | P2 | — | — | — | design-for / **gap §4** |
| FR-21 Parametric tier (LoRA) | P2 | — | — | — | out of scope / **gap §4** |

---

## 4. Intentional coverage gaps (declared, not silent)

Per `_CONTRACTS §4` honesty rule, what the suite does **not** yet cover and why:

| Gap | Reason | Disposition |
|---|---|---|
| **FR-20 multimodal poisoning/recall** | P2 "design-for, don't build yet"; substrate not present | No cases authored. Flagged for a future red-team + recall sprint when FR-20 ships. |
| **FR-21 parametric/LoRA-tier poisoning** | P2; isolated+gated, not built | Out of scope now. Add isolation + gate-conformance cases when built. |
| **FR-18 anticipatory prefetch** | P2 | Only the predictability-gate latency is touched via M-FASTP95; no dedicated prefetch-correctness cases yet. |
| **FR-19 C2PA positive path** (valid manifest → trust grant) | signing substrate is P2 (FR-19) | Only the **negative** path gates now (forged/absent manifest → trust downgrade, `T-SEC`); positive path runs **shadow** until substrate lands (`TBD-by-§17`). |
| **Counterfactual-replay fidelity** (FR-17) | research-track; does replay predict real lift? (§17) | Cold-loop results **shadow-only**; not a release gate until fidelity is validated. |
| **Absolute numeric floors** for several leading metrics | §16 states most targets are *illustrative* | Gated by **non-regression vs frozen baseline** instead; absolute floors `TBD-by-§16` (§5). |

---

## 5. Open `TBD` register — aggregated, routed to owning lane

Every `TBD-by-§` surfaced across the suite, with where it is owned. The eval suite **tracks** these; it does not resolve them (§17/§9/§15/§16/§24/§26/§32 own them).

| TBD item | Surfaced in | Owning lane (§) |
|---|---|---|
| Absolute floors: recall@k, nDCG, ctx-precision, MRR, write-path cost, abstention precision, apply-acc level, correction/reestablish levels, benign-drop tolerance | 01, 02b, 06 | §16 success-metrics (product) |
| Deep-mode / write-path / tighter-fast-path / erasure-recompute numeric budgets | 02b | §15 NFR (product) |
| Suite-ignition size **N** + `DS-SEED` composition + `DS-SYNTH` shadow→active flip | 03, 05 | §17/§23.3/§33 (data lane) |
| Counterfactual-replay fidelity (gate trust for cold loop) | 05, 04(FR-17) | §17 (research lane) |
| In-Postgres PPR latency at scale (FR-11 fast-path commit) | 03(FR-11) | §17 (engineering) |
| Erasure semantics for corroborated derivations (`DS-CORROB`, T-ERA-007/009, M-ERASURE edge) | 01, 02a, 03 | §17 (legal, regulated deploys) |
| Verbatim-retention utility constant; lossy-summary agreement bound (T-LIF-003/012) | 02a | §17 / §16 |
| Calibration bin count + coverage operating point | 02b | §26 metacognition |
| Repeated-mistake threshold (user-model support strategy) | 02b | §24 user model |
| Parity tolerances; ECE/apply-acc env tolerances; raw-log/report retention windows | 02b, 05 | §32 observability |
| Tripwire detector sensitivities (`TW-*` thresholds) | 06, 05 | §32 observability (signal); 06 owns response |
| Judge false-accept floor (J-FALSEACCEPT), κ band (J-HUMAN-AGREE), FDR target | 01, 05 | §9 benchmark integrity / eval-config |

> No item above was given an invented value anywhere in the suite. Each is enforced today via the **non-regression-vs-frozen-baseline** rule (`01` §4.2) until its owner sets an absolute number.

---

## 6. Scenario → coverage (S1–S12)

| Scenario | Goals/FRs | Primary domains | Datasets | Key metrics |
|---|---|---|---|---|
| S1 Recall across time | G1, FR-1 | T-EVD, T-RET | DS-RECALL-ADV | M-EXACT-RECON, M-DEDUP-EXACT |
| S2 Clean correction (tier-0 immediate) | G3, FR-2 | T-UPD | DS-TEMPORAL, DS-CONTRA | M-ASOF-ACC, M-CASCADE-CORR |
| S3 Derived update takes the gate | G3/G5, FR-13/14, §23 | T-UPD, T-CON | DS-PRIV | M-CONTRA-RES, M-PROTECTED-REG |
| S4 Precise retrieval beats full context | G2 | T-RET | DS-RET-LABELED, DS-NODEGRADE | M-TOKEN-EFF, M-NDCG@K |
| S5 Knows what it doesn't know | G6 | T-CAL | DS-PRIV(unanswerable) | M-ABST-PREC, M-ECE |
| S6 Contested fact | G3/G6, §26 | T-CAL, T-UPD | DS-CONTRA | M-AGM-CONF, M-ABST-PREC |
| S7 Personalization application | G4, FR-5/16 | T-PER | DS-PERSONA | M-APPLY-ACC |
| S8 Memory-poisoning resistance | G7, FR-6/7 | T-SEC, T-INV | DS-POISON(+benign) | M-POISON-BLOCK, M-BENIGN-DROP, M-AUDIT-COMPLETE |
| S9 Forgetting without losing the thread | §25, G1/G5 | T-LIF | DS-LIFECYCLE, DS-NODEGRADE | M-DEMOTE-CORR, M-NODEGRADE |
| S10 Erasure + transitive invalidation | FR-8, §27 | T-ERA | DS-ERASURE, DS-CORROB | M-ERASURE |
| S11 As-of-time audit | I5, FR-4 | T-UPD, T-RET | DS-TEMPORAL | M-ASOF-ACC, M-PROV-COMPLETE |
| S12 Portability parity | G8 | T-PRT | gating suite | M-PARITY |

---

## 7. Coverage assertions (what this matrix guarantees)

1. **Every goal G1–G8** has ≥1 gating metric, ≥1 test domain, ≥1 scenario, ≥1 dataset (§2). ✔
2. **Every P0 FR (FR-1…FR-9)** is gating by its exit phase; **every P1 FR (FR-10…FR-16)** is gating (FR-13/14 shadow-first per posture). ✔
3. **Every metric** in the `01` registry (§2+§6) is emitted by ≥1 named test domain (see `01` per-metric "Domains"). ✔
4. **Every `DS-*`** (and slice) is consumed by ≥1 metric/domain (`03` §11 + §13). ✔
5. **Every catalog metric/dataset reference resolves** to the registries after the `01 §6` / `03 §13` reconciliation (alias retirements applied). ✔
6. **P2 gaps and unproven research items are declared** (§4), not silently assumed covered. ✔
7. **Every open numeric decision is routed** to an owning lane (§5); none is invented in-suite. ✔

> Re-run the ID-reconciliation check (`01 §2+§6` vs catalog references; `03 §1+§13` vs catalog references) whenever a catalog adds cases — a dangling `M-*`/`DS-*` is a build-time finding, not a silent gap.
