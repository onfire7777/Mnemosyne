# E-change-refresh — bounded source-aware polling

Date: 2026-10-22. Added `MentalModelRefreshWorker(..., check_changes=True)` and
`mneme mental-model-worker --check-changes`. The default remains interval-only.

Eligible polls share one authorized-corpus snapshot across matching scheduled
models. A stale model can run before its next interval, with at least 60 seconds
since its previous start and finish. Due work runs first; the existing batch limit,
retry backoff and active leases remain enforced. Early claims compare the model
version observed during detection. Source and authority checks before provider
input and final publication are unchanged; the shared scan is only a scheduling
hint. A reverted source avoids an unnecessary provider call. Failed scans skip
early candidates while ordinary scheduled work can proceed.

Verification: 52 new Local/SQLite cases; 326 passed in the focused worker/service/
storage/transport regression. Independent review covered 117 distinct worker
cases. Expanded final local regression: **2192 passed, 114 optional skips, zero
failures/errors**, 27.614 seconds. Global Ruff and whitespace checks passed.
See `change-aware-refresh-tests.{log,xml}`, `change-refresh-final-verification.xml`
and `verify-change-refresh.sh`. The separate `postgres-live` report records live
database checks; deterministic fixture providers are not production inference.

Final live PostgreSQL follow-up: **239 mixed live/unit tests passed**, zero skips,
failures or errors, in 59.271 seconds, including four additional live checks for
this feature. The role probe passed 9/9. See `postgres-live/change-refresh/REPORT.md`.

The owner cancelled the Hindsight benchmark before any Hindsight case or common
reader/judge phase completed. Its partial usage, process termination and owned
database cleanup are recorded in `controlled/run-v1/hindsight-cancellation.json`.
No comparison score or superiority claim is made. Review-found evaluator bugs
were repaired separately: exclusive process-held output locks, bounded cancellation
and durable per-job receipts. Their tests use mocks and do not resume inference.

This change provides polling-based early refresh, not event-driven consolidation,
incremental synthesis or cheaper source indexing. Snapshot cost still grows with
the authorized corpus, and PostgreSQL publication retains its table-lock tradeoff.
