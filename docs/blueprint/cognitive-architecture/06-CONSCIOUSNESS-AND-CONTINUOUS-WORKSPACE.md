# Consciousness and Continuous Workspace

**Status:** Accepted addendum for G1+ implementation. **Scope:** functional indicator properties only. **Non-claim:** Mnemosyne must never claim phenomenal or subjective consciousness.

This addendum extends the v2 blueprint and the cognitive-architecture design set with a measurable, reliability-first consciousness module. It does not replace the existing evidence ledger, projections, calibration, abstention, or section 31 rails. The module is shadow-first until a preregistered G0 gate proves target-up / guardrail-not-down behavior.

## 1. Honesty Boundary

Mnemosyne may report functional signatures such as workspace continuity, reality monitoring, metacognitive calibration, self-model accuracy, and indicator-property scores. It must not present a "green light" for subjective experience, sentience, phenomenal consciousness, or welfare status.

If the functional indicator score becomes high, the system must flag the welfare question for human review, following the cautionary frame in Long and Sebo et al. 2024, *Taking AI Welfare Seriously*. This is a review trigger, not a welfare conclusion.

## 2. G0 Indicator Scorecard

G0 reports the Butlin and Long et al. 2023 indicator-property scorecard from *Consciousness in Artificial Intelligence* as architecture/probe metrics:

| Indicator | Functional check |
|---|---|
| RPT-1 | recurrent input/update processing |
| RPT-2 | organized integrated representations |
| GWT-1 | parallel specialist systems |
| GWT-2 | limited-capacity workspace bottleneck |
| GWT-3 | global broadcast to consuming systems |
| GWT-4 | state-dependent attention |
| HOT-1 | metacognitive confidence and abstention |
| HOT-2 | reality monitoring over representations |
| HOT-3 | belief/action selection updated by metacognitive monitoring |
| HOT-4 | sparse and smooth quality-space coding |
| AST-1 | predictive model representing and controlling attention state |
| PP-1 | input modules using predictive coding |
| AE-1 | goal-directed action selection |
| AE-2 | modeling output-input contingencies for control |

Each indicator is scored `0`, `partial`, or `1`, stored as numeric `0.0`, `0.5`, or `1.0`, and emitted as an individual guardrail metric. The total and normalized scores are reported separately. Future G1-G4 work must not reduce any indicator metric unless a human explicitly accepts a documented rollback.

G0 also reports:

- `workspace_loop_liveness`
- `workspace_stream_coherence`
- `self_model_accuracy`
- `metacognition_meta_d_prime`
- `metacognition_m_ratio`
- `reality_monitor_shadow_tag_contract`
- `dreamer_shadow_corroborated_candidate_yield`
- `dreamer_shadow_contract`
- `shadow_workspace_useful_transition_rate`
- `shadow_workspace_contract`
- `workspace_consolidation_advisory_contract`
- `workspace_advisory_promotion_gate_contract`
- `workspace_retrieval_controller_contract`
- `shadow_workspace_rumination_rate`

These are functional probes. They do not certify consciousness.
`metacognition_meta_d_prime` and `metacognition_m_ratio` are backed by the runtime shadow `MetacognitiveMonitor`, which scores bounded confidence/outcome discrimination and abstention alignment from trace rows.
`dreamer_shadow_corroborated_candidate_yield` and `dreamer_shadow_contract` are backed by the G3 shadow replay fixture in `eval/g0/dreamer.py`; they measure tenant-scoped, CID-backed replay candidates and the non-mutation/off-critical-path contract.
`shadow_workspace_useful_transition_rate`, `shadow_workspace_contract`, `workspace_consolidation_advisory_contract`, `workspace_advisory_promotion_gate_contract`, `workspace_retrieval_controller_contract`, and `shadow_workspace_rumination_rate` are backed by the G4 shadow continuous-workspace fixture in `eval/g0/shadow_workspace.py`; they measure bounded useful state progression, cycle consistency, shadow-only safety, default-off advisory behavior, explicit opt-in advisory promotion through prediction/replay inputs, explicit policy/request-gated retrieval ranking from CID-backed candidates only, cross-tenant/source-CID rejection, and anti-rumination exits.

## 3. G1 Reality Monitor

The G1 seed is a confidence-bearing discriminator that tags each representation or answer as:

- `evidence_grounded`
- `self_generated`
- `externally_suggested`
- `unknown`

The initial implementation is deterministic and provenance/source based. A learned discriminator may replace the scorer only if it keeps the same output contract and passes the preregistered G0 target-up / guardrail-not-down gate. This supports HOT-2 and the anti-hallucination mechanism: unknown, self-generated, or externally suggested support must flow into abstention unless grounded evidence is present.

Runtime retrieval reports include these calibrated monitor labels under `explain.reality_monitoring.shadow_tags` with `shadow_tags_shadow_only=true` and `shadow_tags_critical_path=false`. The abstention gate that consumes the derived `ungrounded_only` rail is explicitly reported as critical path under `explain.reality_monitoring.abstention_gate`; the learned/shadow tag details remain advisory until a future gated promotion explicitly changes that contract.
The G0 metric `reality_monitor_shadow_tag_contract` exercises the local retrieval path and the Postgres report contract to verify calibrated shadow tags, evidence-grounded alias handling, and non-critical-path status.

## 4. Interoceptive Proto-Self

The proto-self is a shadow service that models internal operating state:

- resource health
- error rate
- latency
- memory pressure
- confidence
- section 31 rail budget
- cycle index and cycle budget

It computes attention-lock risk and escalation requirements. It is allostatic: it regulates task continuation by detecting thrash, low confidence, resource pressure, or rail-budget depletion. This supports AST-1, PP-1, and AE-2 as measurable functional signatures.

## 5. Reliability Stack

The continuous workspace loop is never unbounded:

- fixed tick interval
- maximum cycles per task
- watchdog and impasse escalation
- low-bandwidth workspace bottleneck
- shadow/advisory mode for self-loop and imagination
- reality-monitor plus abstention
- section 31 rails, especially R5/R6/R1/R3
- anti-rumination cadence bound
- cycle-consistency self-supervision

Generative replay, imagination, and self-loop outputs are low-trust until gate promoted. They are not on the critical path to an answer. The runtime seed is `ShadowWorkspaceController` in `src/mnemosyne/workspace.py`, which applies the bounded cognitive cycle, interoceptive proto-self, low-bandwidth workspace bottleneck, default-mode idle ticks, cycle-consistency self-supervision, tenant/access-policy validation, redacted shadow traces, anti-rumination exits, bounded `workspace-consolidation-advisory.v1` exports, and `specialist-promotion-evidence.v1` invocation evidence before recruiting typed specialists. Its first specialist is `SandboxedDreamer` in `src/mnemosyne/dreamer.py`; it emits tenant-scoped, CID-backed low-trust replay candidates with `production_mutation=false` and is registered as `dreamer.shadow` with `critical_path_allowed=false`. The controller enforces the shadow dreamer budget at one call per stream and records promotion evidence with `promoted=false` and `gate_result=null`. Route and retrieval paths now accept bounded workspace focus through `workspace_focus`/`workspace_broadcast` context and expose redacted broadcast metadata in `RoutePlan.signals` and retrieval `explain`; this broadcast remains `shadow_only=true`, `critical_path=false`, and `used_for_ranking=false`. A separate promoted retrieval seam accepts `workspace-retrieval-advisory.v1` only when `OperatingPolicy.workspace_retrieval_advisory_enabled=true` and the caller passes `apply_workspace_retrieval_advisory=true`; the worker validates tenant, branch, shadow/non-critical/non-mutating input flags, candidate CID membership, bounded item count, and bounded boost before ranking already-retrieved hits. That ranking effect is explicitly reported as `critical_path=true`, `used_for_ranking=true`, and `production_mutation=false`. Consolidation accepts workspace advisories as report-only by default. With explicit `apply_workspace_advisory=true` or `workspace_advisory_mode=apply`, the worker validates tenant match, source-CID membership, shadow/non-critical/non-mutating flags, non-preapplied flags, and bounded replay scores before max-merging advisory prediction-error and replay-priority scores into the existing consolidation inputs. The merge can raise effort and replay priority, never lower explicit payload signals, and still reports `applied_to_mutation=false`; the normal prediction-error gate, extractor/resolver, promotion gate, and §31 rails remain the live authorities.

## 6. Gate Contract

Every consciousness-module change must preregister:

- target indicator or continuity metric expected to improve
- individual indicator guardrails that must not decrease
- existing reliability guardrails: faithfulness, calibration, confabulation, poison-block, and section 31 rails
- evidence that the self-loop remains shadow/advisory unless explicitly promoted

The scorecard lives in `eval/g0/consciousness.py` and is included by `eval/g0/runner.py`. The dreamer shadow ablation lives in `eval/g0/dreamer.py`, uses `eval/datasets/dreamer_shadow_ablation.json`, and is preregistered in `eval/g0/preregistrations/g3-dreamer-shadow-ablation.json`. The shadow continuous-workspace fixture lives in `eval/g0/shadow_workspace.py`, uses `eval/datasets/shadow_workspace_loop.json`, and is preregistered in `eval/g0/preregistrations/g4-shadow-continuous-workspace-loop.json`, `eval/g0/preregistrations/g4-workspace-advisory-promotion-gate.json`, and `eval/g0/preregistrations/g4-workspace-retrieval-controller-gate.json`. The existing `eval/g0/gate.py` remains authoritative.
