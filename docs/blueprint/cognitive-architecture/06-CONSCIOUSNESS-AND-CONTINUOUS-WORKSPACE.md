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

These are functional probes. They do not certify consciousness.

## 3. G1 Reality Monitor

The G1 seed is a confidence-bearing discriminator that tags each representation or answer as:

- `evidence_grounded`
- `self_generated`
- `externally_suggested`
- `unknown`

The initial implementation is deterministic and provenance/source based. A learned discriminator may replace the scorer only if it keeps the same output contract and passes the preregistered G0 target-up / guardrail-not-down gate. This supports HOT-2 and the anti-hallucination mechanism: unknown, self-generated, or externally suggested support must flow into abstention unless grounded evidence is present.

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

Generative replay, imagination, and self-loop outputs are low-trust until gate promoted. They are not on the critical path to an answer.

## 6. Gate Contract

Every consciousness-module change must preregister:

- target indicator or continuity metric expected to improve
- individual indicator guardrails that must not decrease
- existing reliability guardrails: faithfulness, calibration, confabulation, poison-block, and section 31 rails
- evidence that the self-loop remains shadow/advisory unless explicitly promoted

The scorecard lives in `eval/g0/consciousness.py` and is included by `eval/g0/runner.py`. The existing `eval/g0/gate.py` remains authoritative.
