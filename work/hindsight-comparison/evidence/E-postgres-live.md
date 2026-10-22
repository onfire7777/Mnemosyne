# E-postgres-live — real-session validation and integration repairs

Date: 2026-10-22. Parent baseline: `d59d4e5d3b3736cbf28719b659f766a65ad9559c`.

The complete PostgreSQL test set passed **235 mixed live/unit cases**, zero skips,
failures or errors, in **53.296 seconds**. The new mental-model module adds **16
real-session tests** covering source insertion/deletion/retagging, lease fencing,
rollback, tenant/model-owner isolation, readonly denial and lock timeout recovery.
The live role checker passed **9/9**. See [report](../postgres-live/REPORT.md),
[test counts](../postgres-live/verification.json) and [role receipt](../postgres-live/role-check.json).

Repairs preserve the security contract: the app receives DELETE only on the
documented derived-record targets, malformed external CIDs fail closed, and the
provider sanitizer preserves validated structural source IDs while redacting
unrelated secret-like strings. Dedicated regressions and real command-provider
consolidation now pass. Fixture ownership/session mistakes were corrected instead
of relaxing runtime custody rules.

The expanded local regression set passed **2116 tests**, with **114 optional
skips**, zero failures/errors, in **23.933 seconds**. Command and receipts are in
`verify-postgres-comparison.sh` and `postgres-comparison-final-verification.{log,xml}`.
The 114 skips in that command do not invalidate the separate all-green live
PostgreSQL run. Global Ruff and whitespace checks passed on that candidate.

Validation used PostgreSQL 16.15, pgvector 0.8.7 and psycopg 3.3.4. Provider replies
were deterministic fixtures and lease times were controlled; actual database
connections and locks exercised concurrency. Whole-table SHARE locks briefly
block other tenants' source writers during publication. Production throughput,
remote deployments and other PostgreSQL versions remain unmeasured.

The disposable PostgreSQL test container and its tmpfs data were removed. The
separate native Hindsight evaluation and unrelated existing services were preserved.
No Hindsight answer-quality or ranking claim follows from this validation.
