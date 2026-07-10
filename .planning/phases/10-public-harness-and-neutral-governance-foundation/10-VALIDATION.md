---
phase: 10-public-harness-and-neutral-governance-foundation
status: ready
nyquist_compliant: true
wave_0_complete: true
---

# Phase 10 Validation Strategy

| Seam | Focused check | Backstop |
|---|---|---|
| Public CLI-only runner | `tests/test_public_eval.py` subprocess/monkeypatch contract | Full suite/CI |
| Registry and contamination | exact pin/digest/license/split/private-import tests | Bundle reproduction |
| Bundle custody | traversal/link/secret/mutation/count/fingerprint tests | Independent verifier |
| Metric separation | deterministic vs judged schema rejection tests | PBPP policy test |
| Reproduction | fresh temp output verifies canonical trace/metric digests | Exact-SHA CI |
| Governance | `tests/test_leaderboard_governance_policy.py` | Independent review |
| Existing rails | Ruff, full pytest, G0 preregistrations, native parity | Required CI jobs |

No Phase 10 artifact authorizes a public number, neutral-board claim, or
headline eligibility.

