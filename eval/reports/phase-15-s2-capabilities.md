# Phase 15 S2 capability and development-regression evidence

This is the 15-01-06 closure record for P15-S2. It reconciles the already
merged 15-01-01 through 15-01-04 handoffs onto one exact-head candidate and
records development-regression evidence only.

It is not an official result, production rollout, hardware receipt, operator
custody packet, or superiority claim. Development fixtures and a working
feature are not publishable benchmark proof.

## Exact-head candidate

- Integration base (main tip that already contains 15-01-01..04):
  `df3d8101d4fc2e6b09bb74086c19a6085e55e2da`
  (GREEN Unit+drift CI `34665890948`).
- This lease adds only:
  - `eval/g0/continual_learning.py`
  - `eval/reports/phase-15-s2-capabilities.md`
- Exact HEAD SHA is the commit that lands those two paths on that base. Record
  it from the merged or PR tip; do not treat the base SHA as the closure HEAD.

## What landed in 15-01-01..04

| Task | Name | Merge SHA | PR | Source / regression surface |
|---|---|---|---|---|
| 15-01-01 | Fast, medium, and slow consolidation | `72f3d94b87b46f379d9c93a3a029c4d121ecd111` | #147 | `OperatingPolicy` cadence tiers; `tests/test_consolidation_timescales.py` |
| 15-01-02 | Async sleep consolidation and freshness | `8aad159b47b332ea83b3f50424dc0a57dbca2e11` | #149 | `consolidate_sleep` queue job; same timescale tests |
| 15-01-03 | Global map-reduce sensemaking | `3b6763d6b74a886f082cdac9ab8d70c4c237d3e1` | #153 | `query_mode=global_sensemaking`; `eval/g0/sensemaking.py`; `tests/test_global_sensemaking.py` |
| 15-01-04 | Surprise-gated write closure | `a26f36896a3d29e021d6cc6ddc2cd28f03f90289` | #158 | prediction-error priority only; `eval/g0/write_gating.py`; `tests/test_surprise_gated_writes.py` |

CAP-012 and CAP-013 were consumed as completed contracts and were not redefined.

## Continual-learning integration cell

`eval.g0.continual_learning.run_continual_learning_eval` now:

1. Runs the synthetic interference fixture twice on isolated
   `LocalMemoryEngine` instances and records `baseline` and `candidate`
   separately.
2. Attaches the landed S2 cells to the candidate snapshot:
   cadence/sleep source pin, global sensemaking regression, surprise-gated
   write precision/recall aggregates.
3. Scans product evidence metadata for held-out eval keys
   (`held_out_label`, `should_write`, `write_gate_label`, `eval_label`,
   `held_out`, `failure_class`) and fails closed if any appear.
4. Leaves write-gate labels inside `eval/g0/write_gating.py`. Confusion
   counts and denominators are aggregates only.

Top-level G0 fields (`schema_version`, `before_accuracy`, `after_accuracy`,
`interference`, `rows`, `passed`) remain the candidate interference contract
so existing harness assertions stay valid.

## CAP row status

`.planning/REQUIREMENTS.md` is not updated by this lease. The rows below stay
in the admissible 15-01-06 buckets.

| ID | Recorded status | Why |
|---|---|---|
| CAP-007 | Planned | Cadence tiers and queue-backed sleep exist as source plus deterministic tests. Measured forgetting reduction, operator evidence, hardware evidence, and custody receipts are absent. |
| CAP-008 | Planned | Global sensemaking and surprise-gated write development-regression cells exist. Measured, operator, hardware, and custody evidence are absent. |
| CAP-009 | externally deferred to S5 `15-04` | Cartridge A/B and its go/no-go artifact are owned by `.planning/phases/15-security-calibration-performance-and-scale-columns/15-04-PLAN.md`. This lease does not implement, freeze, or run cartridge A/B. |

A later lifecycle owner may record CAP-007/008 as Partial once they accept
source-path evidence. This lease does not flip those rows. Complete remains
blocked on the measured/operator/hardware/custody gates named in
`15-01-PLAN.md`.

## CAP-009 deferral

CAP-009 remains owned by S5 `15-04`. No cartridge comparison, latency or
throughput A/B, model dependency, or go/no-go artifact is produced here.
`cartridge_ab_implemented` on the continual-learning report is `false`.

## Verify command and expected results

```bash
uv run --locked python -m pytest tests/test_consolidation_timescales.py tests/test_global_sensemaking.py tests/test_surprise_gated_writes.py tests/test_planning_traceability.py -q
```

Expected on this exact-head candidate: exit 0; every collected test in those
four modules passes. That outcome is a development-regression pin of the
merged 15-01-01..04 source, not measured CAP-007/008 evidence and not an
official, production, or superiority result.

The same candidate also exposes:

```bash
uv run --locked python -m eval.g0.continual_learning
```

Expected: isolated baseline and candidate snapshots both report
`interference == 0.0`, attached S2 cells pass, and `ingested_label_keys` is
empty.

## Lease boundaries

This lease did not update `GOAL.md`, `.planning/STATE.md`,
`.planning/REQUIREMENTS.md`, the write-lease map, any `src/mnemosyne/*` path,
CAP-012/013 definitions, an M16 invention, or `15-01-PLAN.md`.
