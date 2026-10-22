# E-background-refresh — scheduling and publication

Date: 2026-10-22. Parent baseline: `00d8ea9f7389d3a423d233e5fc0ab959ead8e520`.

Added opt-in periodic full refresh through `mental_model_schedule`, `mneme mental-model
schedule`, and a standalone `mental-model-worker`. Durable schedule state includes next due,
attempt outcome, capped retry count/backoff and an expiring lease. The worker uses caller-supplied
authority, never reconstructs it from stored scope, and checks it before provider work and
immediately before guarded writes. Stored answers remain outside the evidence plane.

Independent review reproduced authority expiry during initial and final source snapshots;
both now reject the operation before unauthorized provider work or publication. Lease expiry,
takeover, manual cancellation, source privacy changes, malformed schedules, restart recovery,
two SQLite workers and no-provider clean checks have regression coverage.

Grounded answers now retain a private failure kind so operational failures retry instead of
becoming permanent no-answer caches. PostgreSQL source reads and model writes share a pinned
READ COMMITTED transaction protected with SHARE locks. Those locks block cross-tenant source
writers briefly and require live deployment validation; only mocks/contracts ran here.

Final: 2143 cases, 2029 passed, 114 skipped, zero failures/errors, 22.472 seconds.
The 136 cases in the four new test modules passed. Global Ruff and diff checks passed.
Command: `SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk bash work/hindsight-comparison/verify-background-refresh.sh`.
Receipts: `background-refresh-final-verification.{xml,log}` and `background-refresh-final-lint.log`.
Identity: `background-refresh-source-manifest.json`, 395 stable files.
Narrow offline SAST: seven changed Python files, three rules, no matches/errors; this is not
evidence of comprehensive security or the absence of all bugs.

Still open: live PostgreSQL contention and permissions, delta synthesis and incremental
invalidation, consolidation-triggered jobs, wiki/knowledge pages, freeform synthesis and a
controlled Hindsight comparison. No production provider installation or new scored answer
benchmark was performed.
