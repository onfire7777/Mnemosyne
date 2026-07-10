---
phase: 07-unified-cognitive-substrate
plan: 01
status: implemented
standing_fn_version: standing.mirror.v1
target_metric: standing_decision_divergence
target_value: 0.0
gate_decision: passed
---

# 07-01 Standing Mirror Summary

Phase 7 P1 introduced Standing as a derived, deterministic, versioned mirror
over existing reality-monitoring and shadow/advisory decisions. Standing is
report-only metadata plus a P1 authority mirror; it does not write evidence,
mutate the ledger, change retrieval order, change confidence semantics, or
replace the retained boolean fields.

## Implementation

- Added `src/mnemosyne/standing.py` with `standing.mirror.v1`, fixed-precision
  groundedness/salience, fail-closed unknown handling, and explainable inputs.
- Wired Local and Postgres retrieval reality-monitoring reports to compute
  hit-level Standing, derive the abstention mirror from Standing, and assert it
  equals the pre-existing `ungrounded_only` boolean path.
- Added Standing metadata to the consolidation shadow/advisory contract while
  preserving the existing `shadow_only=true`, `critical_path=false`,
  `applied_to_* = false` behavior.
- Added `eval/g0/standing_parity.py` and the G0 metric
  `standing_decision_divergence`, measured from grounded-only,
  self-generated-only, externally-suggested-only, unknown-only, mixed-support,
  and consolidation mirror cases.
- Preregistered the G5 Standing parity gate and regenerated
  `eval/g0/reports/report.json`, `eval/g0/reports/report.md`, and
  `eval/g0/baselines/baseline-0.json`.

## Verification

- `standing_decision_divergence`: `0.0`
- G0 coverage after regeneration: `46/47` measured; only
  `controller_watts_per_dollar` remains intentionally missing.
- G5 gate:
  - command: `.venv/bin/python -m eval.g0.gate --baseline eval/g0/baselines/baseline-0.json --candidate /tmp/mnemosyne-g0-standing-candidate/report.json --prereg eval/g0/preregistrations/g5-standing-byte-stable-parity.json --decision-log eval/g0/decision-log.jsonl --print-json`
  - result: passed
  - `target_delta`: `0.0`
  - guardrails checked: `19`, all passed
- `CodeRabbit`: `coderabbit review --agent --fast -t uncommitted --dir src`
  returned `findings: 0`; subsequent `tests` review hit the CodeRabbit
  account rate limit.
- `Greptile`: no `greptile` executable was available on PATH.

## Local Checks

- `.venv/bin/ruff check .`
- `.venv/bin/python -m pytest tests/test_standing_parity.py tests/test_g0_harness.py -q`
- `.venv/bin/python -m pytest -q`
- `git diff --check`

All completed successfully.
