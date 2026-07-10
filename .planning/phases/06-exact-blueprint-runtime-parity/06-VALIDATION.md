---
phase: 06-exact-blueprint-runtime-parity
status: passed-current-coverage
reconstructed: true
validated: 2026-07-10
nyquist_compliant: true
wave_0_complete: true
---

# Phase 06 Validation Strategy (Reconstructed)

> Present-day sampling contract for Phase 09.3 closure. This file was created
> retrospectively and makes no claim that Phase 6 historically followed a
> phase-level Nyquist cadence.

## Evidence Classes

| Class | Meaning | Validation treatment |
|---|---|---|
| Current rerun | A command executed on the Phase 09.3 closure SHA | Record the exact result in Phase 09.3 verification |
| Retained repository evidence | Historical commands/results in `06-01` through `06-09` summaries | Confirm files, contracts, and focused behavior still exist; do not relabel old counts as current |
| Retained external evidence | `capture-bc10` production packet and independent fingerprint/custody result | Verify references and integrity records only; do not mutate or recreate the packet |
| Operator boundary | Production credentials, endpoints, live captures, and recapture | Remains external and operator-owned |

## Focused Command Matrix

| Surface | Present-day command | Requirements supported |
|---|---|---|
| Shared Local/Postgres contract and cached PPR | `uv run --locked python -m pytest tests/test_shared_engine_contract.py tests/test_config_drift.py -q` | REQ-004, REQ-006, REQ-014, NFR-002, NFR-003 |
| Runtime parity, multimodal, and provider extensions | `uv run --locked python -m pytest tests/test_runtime_parity_extensions.py -q` | REQ-004, REQ-006, REQ-008, NFR-002 |
| Learning, parametric rollback, and protected gates | `uv run --locked python -m pytest tests/test_learning_and_attack_suite.py -q` | REQ-010, REQ-011 |
| Live Postgres collection behavior | `uv run --locked python -m pytest tests/test_postgres_engine_live.py -q` when the documented DSN/service prerequisites are available | REQ-003, REQ-006, REQ-008, REQ-014, REQ-016, NFR-002, NFR-004 |
| Evidence custody and release-audit code paths | `uv run --locked python -m pytest -q -k "production_evidence or release_audit or deployment_soak"` | REQ-010, REQ-011, NFR-001, NFR-004, NFR-005 |
| Full repository closure | `uv run --locked ruff check && uv run --locked python -m pytest -q && gsd-sdk validate consistency && git diff --check` | All supporting requirements |

## Sampling Rule for the Reconstruction

- Run the closest focused command after any evidence-graph repair affecting its
  surface.
- Run the full repository closure gate before the Phase 09.3 verification
  commit.
- Verify exact-SHA CI and current CBM/gbrain state at Phase 09.3 closure.
- Treat unavailable optional live services as an explicit environment result,
  never as a fabricated pass.
- Do not rerun production capture merely to validate documentation. A future
  production recapture must use the sanctioned operator custody path.

## Sign-Off Conditions

- [x] Every Phase 6 goal has a focused present-day command.
- [x] Retained local, retained external, and current evidence are separated.
- [x] The `capture-bc10` operator boundary is preserved.
- [x] No historical Nyquist cadence is asserted.
- [x] Full-suite and exact-SHA closure are delegated to Phase 09.3 verification.
