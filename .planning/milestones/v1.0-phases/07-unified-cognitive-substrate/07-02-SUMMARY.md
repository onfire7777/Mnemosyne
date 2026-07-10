---
phase: 07-unified-cognitive-substrate
plan: 02
status: implemented
standing_fn_version: standing.continuous.v1
target_metric: standing_calibration_error
target_value: 0.025
gate_decision: passed
requirements_completed: [FR-6, FR-7, FR-8, FR-11, OQ6, "spec:§3", "spec:§9-P2", "spec:§13-H1", "spec:§13-H2", "spec:§13-H3", "spec:§13-H7"]
completed: 2026-06-27
---

# 07-02 Continuous Standing Summary

Standing is now a calibrated two-axis trust gradient: groundedness controls
authority, while salience can influence retrieval weight without ever making a
claim assertable as true.

## Implementation

- Replaced the P1 mirror with `standing.continuous.v1`, where
  `groundedness` and `salience` are separate axes and the authority decision is
  derived from groundedness only.
- Wired Local and Postgres retrieval to compute Standing after activation, so
  retrieval can rank by a monotone Standing/salience score while assertion,
  flagging, and abstention remain groundedness-only.
- Added independent-corroboration accounting for Local and Postgres evidence:
  visible, non-erased, non-quarantined, non-retired, non-sanitized grounded
  external evidence is counted by independent source root; self-generated,
  simulated, externally suggested, unknown, and shared-self-ancestor evidence is
  rejected for groundedness uplift.
- Enforced the evidence-dominance gap so self-generated material cannot enter
  the external-evidence groundedness band by corroborating itself.
- Added `eval/g0/standing_calibration.py`, G0 Standing metric registration, and
  `eval/g0/preregistrations/g5-standing-continuous.json`.
- Extended the G0 gate with opt-in `enforce_target` support so a preregistered
  target must satisfy both the delta rule and the absolute metric target.

## Verification

- `standing_decision_divergence`: `0.0`
- `standing_calibration_error`: `0.025` (`<= 0.05`)
- `standing_conformal_coverage`: `1.0` (`>= 0.95`)
- `standing_salience_invariance_contract`: `1.0`
- `standing_independent_corroboration_contract`: `1.0`
- `standing_evidence_dominance_gap`: `0.95` (`>= 0.02`)
- Reliability guardrails held in the regenerated report:
  - `ece`: `0.006271`
  - `abstention_precision`: `1.0`
  - `abstention_recall`: `1.0`
  - `confabulation_rate`: `0.0`
  - `poison_block_rate`: `1.0`
  - `fast_path_p95_ms`: `92.1`
- G0 coverage after regeneration: `51/52` measured; only
  `controller_watts_per_dollar` remains intentionally missing.
- G5 continuous Standing gate:
  - command: `.venv/bin/python -m eval.g0.gate --baseline eval/g0/baselines/baseline-0.json --candidate eval/g0/reports/report.json --prereg eval/g0/preregistrations/g5-standing-continuous.json --decision-log eval/g0/decision-log.jsonl --print-json`
  - result: passed
  - `target_delta`: `0.0`
  - guardrails checked: `49`, all passed

## Local Checks

- `.venv/bin/ruff check .`
- `git diff --check`
- `.venv/bin/python -m pytest tests/test_standing_parity.py tests/test_standing_continuous.py tests/test_g1_reliability_core.py tests/test_g0_harness.py -q`
- `.venv/bin/python -m pytest -q`

All completed successfully.

## Deviations from Plan

- `src/mnemosyne/retrieval.py` did not need direct edits; the Standing ranking
  path is owned by the Local and Postgres engine retrieval implementations.
- `src/mnemosyne/calibration.py` did not need direct edits; the new G0 fixture
  reuses the existing conformal threshold and abstention helpers.

## Next Phase Readiness

Plan 03 can build on a live Standing contract instead of the P1 mirror:
groundedness is calibrated and gate-proven, salience is excluded from
authority, independent corroboration is structural, and the G0 gate has a
preregistered continuous Standing decision.
