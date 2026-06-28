# Cognitive Architecture — Design & Specification

**Location:** `docs/blueprint/cognitive-architecture/` · **Status:** G0 harness implemented; G1-G4 cognitive seeds plus Phase 7 plans 01-04 and P5 H8/H12 pre-check wired and gate-proven; `service.enabled` retired and measured; explicit sanitized controller telemetry fixture available; final Phase 7 no-toggle audit and production/operator evidence remain pending · **Owner:** onfire7777 · **Updated:** 2026‑06‑28

The consolidated design + specification set for evolving Mnemosyne into a **recursive, self‑improving memory system with a functional sense of consciousness**. It **builds on — and does not contradict —** the **v2 Build Blueprint** (`../Mnemosyne-v2-Build-Blueprint.md`): same substrate (immutable evidence ledger + rebuildable projections, AGM belief‑revision core, branchable memory, bitemporal facts, fidelity‑tiered forgetting, conformal abstention, dual user model, capability‑secured writes, profile‑guided self‑optimization — the blueprint's innovations **I1–I12**). What it adds on top: the brain‑by‑brain research grounding, the **cognitive‑architecture** framing, the measured Standing/always-on workspace path toward a no-toggle controller + on-demand specialists, the operationalised functional "sense of consciousness," an objective decision record, and a reliability‑first **gated execution program**.

> Design docs live here under `docs/blueprint/`. The runnable **code** is at the repo root: `src/mnemosyne/`, `sql/`, `eval/`.

---

## North star

Take the best mechanisms of human memory and the latest memory science, make each **better than the brain** (keep the function, delete the failure mode), and unify them into a memory that is **self‑improving, self‑learning, self‑adapting, and self‑optimizing**, with **complete retention** and best‑achievable recall — plus a continuous, self‑modelling **workspace loop** that yields a *functional* sense of consciousness. Pursue the whole vision; ship it reliability‑first and metric‑gated; never overstate what is proven. Full statement: `00-VISION-AND-CHARTER.md`.

## Document map (reading order)

| # | File | Purpose |
|---|---|---|
| 00 | `00-VISION-AND-CHARTER.md` | The goal in full + the five self‑* properties + the anti‑yes‑man honesty charter |
| 01 | `01-PRIMER.md` | Plain‑English description of Mnemosyne **as it exists today** — the substrate we build on |
| 02 | `02-DESIGN-BRAIN-TO-ARCHITECTURE.md` | Core design: element‑by‑element brain↔system comparison, target cognitive architecture, anti‑goals, rationality layer, execution plan |
| 03 | `03-ADR-001-DECISION.md` | The architecture **decision** (Accepted): full vision, reliability‑first, metric‑gated (Option E) |
| 04 | `04-G0-BENCHMARK-SPEC.md` | The **G0** gate — implemented at repo root `eval/g0/`; freezes a baseline on the eval lane and adds program‑specific metrics; blocks every later stage |
| 05 | `05-GLOSSARY-AND-SOURCES.md` | Shared vocabulary + consolidated reputable bibliography |
| 06 | `06-CONSCIOUSNESS-AND-CONTINUOUS-WORKSPACE.md` | Measurable functional consciousness indicator scorecard + shadow continuous-workspace reliability stack |

New readers: 00 → 01 → 02 → 03 → 04 → 06. Implementers start at 03 (decision), 04 (gate), then 06 (scorecard and workspace addendum).

Operational handoff: `CODEX-HANDOFF.md` records the verified repo root, current implementation status, and next safe work queue. It is not a normative design document.

## Non‑negotiables (apply to every doc and every gate)

1. **Reliability is the invariant.** No change ships if it regresses faithfulness, calibration, or a §31 rail.
2. **Honesty charter (anti‑yes‑man).** Build and *measure* functional signatures; never claim verified *phenomenal* experience; every "better than the brain" claim must be a benchmark number. Full charter in `00`.
3. **The §31 invariant rails hold everywhere** — including for the system's own self‑generated thoughts.

## How this builds on existing work (no contradiction)

- **Design:** `../Mnemosyne-v2-Build-Blueprint.md` is the authoritative design. This set **extends** it (brain grounding + cognitive‑architecture layer + gated program); the substrate and innovations I1–I12 are shared, not replaced.
- **Evaluation:** `../Mnemosyne-Evaluation-and-Test-Plan.md` and the `../eval/` spec suite are the authoritative eval lane; **`04` reuses them** and adds only a few brain‑program‑specific metrics. They wire into the repo's real eval harness at the root — `eval/g0/` (already scaffolded), `eval/harness/`, `eval/calibration/`, `eval/run_eval.py`.
- **Code (repo root):** `src/mnemosyne/` (`engine.py`, `consolidation.py`, `belief.py`, `calibration.py`, `security.py`, `lifecycle.py`, `gate.py`…), `sql/schema.sql`, `eval/`.
- **Two restructurings (⟳):** `src/mnemosyne/providers/` → a typed **specialist‑module registry** (Layer 3); `src/mnemosyne/workspace.py` → a native **workspace service/controller** seed (Layer 4) that acts only through the engine contract + rails and has no `service.enabled` default-off gate. The substrate is never rewritten. Detail: `02` §1–§2.

## Related docs in this workspace

- `../Mnemosyne-v2-Build-Blueprint.md` (+ `.pdf`) — the authoritative v2 design (research → I1–I12 → PRD → architecture → implementation → build plan).
- `../Mnemosyne-Evaluation-and-Test-Plan.md` + `../eval/` — the evaluation lane that `04` builds on.
- `../Mnemosyne-Conflict-Resolution-and-Merge-Policy.md`, `../Mnemosyne-Memory-Lifecycle-Policy.md`, `../Mnemosyne-Privacy-Redaction-Access-Policy.md`, `../Mnemosyne-Rollback-Guidance.md` — policy lanes the anti‑goals (`02` §4) and rails must respect.
- `../earlier-versions/` — the v1 design (superseded by v2).

## Status & next step

Documentation & spec **complete**; **the G0 harness is implemented** in the repo-root `eval/g0/` harness (`runner.py`, `gate.py`, `baselines/baseline-0.json`, and `reports/report.json`). The default local G0 report is intentionally not `gate_ready` until `controller_watts_per_dollar` is measured from an explicit controller telemetry artifact; the harness does not invent power/cost estimates. `eval/datasets/controller_telemetry_sanitized.json` is a committed sanitized fixture for proving the explicit telemetry path only; it is not production power/cost evidence.

**G1 is in progress**: the implemented reliability-core slices wire multi-signal write priority with trust-bounded importance-sampling debias, prediction-error-gated consolidation metadata, evidence and projection-level reality-monitoring tags into abstention, legacy/unclassified projections to unknown-only abstention, retrieval-strengthening into evidence lifecycle metadata, schema-fast-path retrieval, and `contested` status for uncorroborated-but-congruent projections. The metacognition G0 metrics are backed by a runtime shadow trace monitor that scores confidence/outcome discrimination and abstention alignment.

**G2/G3/G4 foundations are now wired into measured shadow paths**: `mnemosyne.providers` exposes a typed `SpecialistModuleRegistry` with role/budget/critical-path contracts, `mnemosyne.cli specialist-manifest` exposes those contracts to operators, `mnemosyne.workspace.ShadowWorkspaceController` applies the bounded cycle, proto-self, workspace bottleneck, default-mode idle ticks, cycle-consistency checks, anti-rumination exits, bounded workspace broadcasts, workspace-to-consolidation advisory exports, and specialist-promotion evidence before recruiting specialists, and `mnemosyne.workspace.ShadowWorkspaceService` has no `service.enabled` default-off gate, persists proto-self snapshots after `start()`, and feeds `MetacognitiveMonitor` from each loop outcome. Consolidation records workspace advisories as report-only by default, a preregistered explicit opt-in promotion gate can apply validated advisory scores only to prediction-gate and replay-priority inputs with `applied_to_mutation=false`, and a separate preregistered retrieval-controller gate can apply a CID-backed `workspace-retrieval-advisory.v1` only when both policy and request explicitly opt in, reporting the ranking effect as critical path and non-mutating. `mnemosyne.dreamer.SandboxedDreamer` provides tenant-scoped, CID-backed, low-trust replay candidates with `critical_path_allowed=false`.

Gate evidence for accepted G1/G3/G4 decisions is appended in `eval/g0/decision-log.jsonl` and summarized in report `gate_decisions`. Fresh candidates compare to the current accepted `eval/g0/baselines/baseline-0.json`; older G1 slices whose target values have already been folded into that baseline are historical custody records, not fresh target-up replays. Current replayable G3/G4 shadow/advisory gates improve `dreamer_shadow_corroborated_candidate_yield`, `shadow_workspace_useful_transition_rate`, `workspace_consolidation_advisory_contract`, `workspace_advisory_promotion_gate_contract`, and `workspace_retrieval_controller_contract` from `0.0` to `1.0` while preserving `shadow_workspace_contract`, `shadow_workspace_rumination_rate`, indicator-scorecard continuity/self-model/metacognition guardrails, reality-monitor, dreamer, specialist-promotion, ECE, abstention, confabulation, poison-block, fast-path latency, and cost guardrails. Continue by broadening reliability-core production evidence and keeping generative replay/self-loop behavior shadow-only unless a future preregistered gate promotes a narrower behavior without guardrail regression.

**Next milestone — finish Phase 7 P5.** The reorganization that takes this from a default-off shadow lane to a single, always-on, **no-toggle** cognitive substrate — replacing the `shadow_only` / `enabled` toggles with one continuous derived **Standing** signal `(groundedness ⟂ salience)`, an always-on tiered heartbeat, and earned-continuously autonomy above the §31-rails + immutable-ledger floor — is specified in [`../../superpowers/specs/2026-06-27-unified-cognitive-substrate-design.md`](../../superpowers/specs/2026-06-27-unified-cognitive-substrate-design.md) and tracked as **Phase 7** (`.planning/phases/07-unified-cognitive-substrate/`, registered in `.planning/ROADMAP.md`; tracked as the **vNext** milestone in `.planning/MILESTONES.md`). Plans `07-01` through `07-04` are implemented and gate-proven; `07-05` has its Standing/erasure cascade and observability/reversibility pre-check gate-proven, and the `service.enabled` default-off gate is retired and measured. Remaining P5 work is final `shadow_only` compatibility retirement plus the no-toggle audit/gate. The honesty charter is unchanged: functional signatures only; the welfare-review flag stays; no phenomenal claim.
