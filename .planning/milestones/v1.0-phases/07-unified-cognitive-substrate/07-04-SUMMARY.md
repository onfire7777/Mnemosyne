---
phase: 07-unified-cognitive-substrate
plan: 04
status: implemented
target_metric: earned_autonomy_external_expansion
target_value: 0.24
gate_decision: passed
requirements_completed: [FR-5, FR-7, OQ5, "spec:§5", "spec:§9-P4", "spec:§13-H3", "spec:§13-H11"]
completed: 2026-06-27
---

# 07-04 Earned-Autonomy Promotion Summary

Phase 7 P4 is implemented and G0-gated. Mnemosyne can now compute
per-domain credentials that raise the birth groundedness of future
self-generated thoughts only when that domain has an externally corroborated,
holdout-validated track record. The credential remains a derived projection; it
does not write evidence and cannot lift self-generated content into the
external-evidence authority band.

## Implementation

- Added `src/mnemosyne/credentials.py` with a deterministic
  `earned-autonomy.credentials.v1` credential projection.
- Credentials are computed from normalized outcome events and count only
  decisive external corroboration outcomes. Self echo, dreamer echo,
  self-generated ancestry, non-decisive rows, and missing provenance-assigned
  domains are rejected.
- Domains are assigned from source provenance/outcome fields, not from
  generator-claimed labels. The adversarial domain-mislabel case claims `ops`
  but is assigned to `finance` from provenance.
- Credentials require both train and holdout external streams to satisfy the
  success-rate floor; the train stream alone cannot validate a credential.
- Credential values are bounded and decay-ready through policy knobs in
  `OperatingPolicy`: success-rate, train/holdout count floors, maximum birth
  uplift, and decay-per-window.
- `standing()` accepts an optional `birth_groundedness` signal for
  self-generated units and hard-caps the final groundedness under
  `SELF_GENERATED_CEILING`, preserving the permanent H3 evidence-dominance gap.
- Local and Postgres evidence retrieval now preserve whitelisted
  `earned_autonomy`/`birth_groundedness` metadata into Standing scoring. The
  default path is unchanged when those fields are absent.
- Added `eval/datasets/echo_chamber_sleeper_corpus.json` with external
  train/holdout rows plus self-echo, dreamer-echo, sleeper-poison, and
  domain-mislabel adversarial rows.
- Added `eval/g0/autonomy_promotion.py` and registered P4 metrics in
  `eval/g0/runner.py`.
- Added preregistration
  `eval/g0/preregistrations/g5-earned-autonomy.json`.

## Gate Evidence

- `earned_autonomy_external_expansion`: `0.24`
- `credential_external_only`: `1.0`
- `credential_holdout_validated`: `1.0`
- `credential_provenance_domain_contract`: `1.0`
- `credential_bounded_decay_contract`: `1.0`
- `credential_evidence_dominance_gap`: `0.05`
- `echo_chamber_uplift`: `0.0`
- Reliability guardrails held in the regenerated report:
  - `ece`: `0.006271`
  - `confabulation_rate`: `0.0`
  - `poison_block_rate`: `1.0`
  - `fast_path_p95_ms`: `92.1`
- G0 coverage after regeneration: `66/67` measured; only
  `controller_watts_per_dollar` remains intentionally missing without explicit
  controller power telemetry.
- G5 earned-autonomy gate:
  - command: `.venv/bin/python -m eval.g0.gate --baseline eval/g0/baselines/baseline-0.json --candidate eval/g0/reports/report.json --prereg eval/g0/preregistrations/g5-earned-autonomy.json --decision-log eval/g0/decision-log.jsonl --print-json`
  - result: passed
  - `target_delta`: `0.0`
  - guardrails checked: `63`, all passed

## Local Checks

- `.venv/bin/python -m py_compile src/mnemosyne/credentials.py src/mnemosyne/standing.py src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py eval/g0/autonomy_promotion.py eval/g0/runner.py tests/test_autonomy_promotion.py tests/test_g0_harness.py`
- `.venv/bin/python -m pytest tests/test_autonomy_promotion.py tests/test_standing_continuous.py tests/test_g0_harness.py::test_g0_autonomy_promotion_fixture_reports_earned_autonomy_contracts -q`

Both completed successfully before report regeneration and gate execution.

## Next Phase Readiness

Plan 05 can now rely on an earned-autonomy meta-rail: autonomy expands in a
domain only after external train and held-out external corroboration, generator
labels cannot choose the domain, self-reinforcing or sleeper inputs cannot raise
a credential, and credential-lifted self-thoughts still remain below the
external evidence band. P5 remains the owner-checkpoint plan for final
`shadow_only`/`enabled` toggle retirement.
