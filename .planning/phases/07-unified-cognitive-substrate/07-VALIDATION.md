---
phase: 07-unified-cognitive-substrate
status: passed-current-coverage
reconstructed: true
validated: 2026-07-10
nyquist_compliant: true
wave_0_complete: true
---

# Phase 07 Validation Strategy (Reconstructed)

> Present-day sampling contract for Phase 09.3 closure. This reconstruction
> does not assert that the original Phase 7 execution used a phase-level
> Nyquist cadence.

## Evidence Classes

| Class | Meaning | Validation treatment |
|---|---|---|
| Current rerun | Tests/gates executed on the Phase 09.3 closure SHA | Record exact counts and outcomes in Phase 09.3 verification |
| Retained Phase 7 evidence | Plan summaries and committed G5 decisions | Confirm reproducibility without changing their historical timestamps or counts |
| Later supporting closure | Phase 09.2 public `worker-run` mount | Link as later evidence only; never attribute it to original Phase 7 |
| External operator evidence | Retained `capture-bc10` packet | Keep separate from local G0 gates and preserve operator custody |

## Focused Command Matrix

| Surface | Present-day command | Requirements supported |
|---|---|---|
| Standing parity and continuous calibration | `uv run --locked python -m pytest tests/test_standing_parity.py tests/test_standing_continuous.py -q` | REQ-009, REQ-012, NFR-005 |
| Heartbeat safety and bounded workspace stream | `uv run --locked python -m pytest tests/test_always_on_heartbeat.py tests/test_workspace_stream.py tests/test_g0_harness.py -q` | REQ-016, NFR-005 |
| Earned autonomy and adversarial rails | `uv run --locked python -m pytest tests/test_autonomy_promotion.py tests/test_g1_reliability_core.py tests/test_g0_harness.py -q` | REQ-018, NFR-005 |
| Erasure, Standing cascade, and no-toggle controls | `uv run --locked python -m pytest tests/test_standing_parity.py tests/test_parity_retrieval.py tests/test_dreamer.py tests/test_g0_harness.py -q` | REQ-008, NFR-004, NFR-005 |
| Committed preregistration replay | `uv run --locked python -m pytest tests/test_g0_harness.py::test_committed_g0_preregistrations_have_passing_decisions tests/test_g0_harness.py::test_current_g0_candidate_replays_preregistrations_without_regression -q` | All Phase 7 support rows |
| Later public-runtime mount boundary | `uv run --locked python -m pytest tests/test_worker_runtime.py -q -k "workspace or heartbeat"` | REQ-016, REQ-018, NFR-005; Phase 09.2 evidence only |
| Full repository closure | `uv run --locked ruff check && uv run --locked python -m pytest -q && gsd-sdk validate consistency && git diff --check` | All supporting requirements |

## Sampling Rule for the Reconstruction

- Run the closest affected suite after any Phase 7 evidence-graph repair.
- Replay committed G0 preregistrations before aggregate sign-off.
- Run the full repository gate, exact-SHA CI, CBM refresh, and gbrain health at
  Phase 09.3 closure.
- Record missing optional telemetry (for example watts-per-dollar) as missing;
  do not synthesize it to make a gate look complete.
- Keep Phase 09.2 worker-runtime tests labeled as later closure evidence.

## Requirement-to-Suite Coverage

| Requirement | Closest present-day suites |
|---|---|
| REQ-008, NFR-004 | Standing parity, erasure cascade, shared reliability rails |
| REQ-009 | Standing continuous/calibration and G0 replay |
| REQ-012 | Standing/profile authority and proto-self/heartbeat safety |
| REQ-016 | Heartbeat/workspace stream; later Phase 09.2 worker-runtime mount |
| REQ-018 | Autonomy promotion and later bounded worker heartbeat evidence |
| NFR-005 | G0 harness, traces, compute reporting, cascades, and replay |

## Sign-Off Conditions

- [x] Standing, heartbeat, autonomy, observability, erasure, and no-toggle goals
  each have focused automated coverage.
- [x] Current reruns and retained Phase 7 gate records are distinguishable.
- [x] Phase 09.2 is explicitly labeled as later runtime-mount closure.
- [x] No historical Nyquist cadence is asserted.
- [x] Full-suite and exact-SHA closure are delegated to Phase 09.3 verification.
