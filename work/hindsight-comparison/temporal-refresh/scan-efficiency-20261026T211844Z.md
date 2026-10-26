# Bounded mental-model scan verification

Date: 2026-10-26. Baseline: `0d947f5c`. This is a small provider-free operation-count regression, not a latency measurement or benchmark score.

## Change

- Pending/error model views return metadata with empty prose, claims, source IDs, and reader disclosure without scanning evidence. Listing filters owner/scope first and skips a snapshot for an empty or metadata-only result.
- A long-lived refresh worker waits five monotonic seconds after an advisory change scan finishes before scanning again. Poll interval and scan runtime are additional. The bound applies after failed scans too. A new worker scans immediately, regardless of the monotonic clock origin.
- Only stale model IDs and exact record versions remain between scans. Current owner/scope, schedule eligibility, record version, lease, authority, and refresh source checks still apply. Queued hints can drain through `max_batch` during the cooldown.
- Due work, ready public reads, provider preflight, and publication checks do not reuse advisory source snapshots and are not delayed by the cooldown.

## Measured counts

Eight source records and three fresh abstained model records per disposable engine. Both Local and SQLite produced the same counts:

| Operation | Baseline exports / evidence point reads | Updated exports / evidence point reads |
|---|---:|---:|
| Two consecutive unchanged early-change polls | 2 / 16 | 1 / 8 |
| Create one pending model | 1 / 8 | 0 / 0 |
| Process three due, unchanged models | 3 / 24 | 3 / 24 |

The due-work count deliberately remains unchanged: each refresh performs its independent current-source preflight. Neither version constructed a provider.

Artifacts:

- `scan-efficiency-20261026T211844Z.py`: repeatable bounded probe.
- `scan-efficiency-20261026T211844Z-baseline.json`: probe run with the two original modules loaded from `git show 0d947f5c:src/mnemosyne/{mental_models,mental_model_refresh}.py` in a fresh interpreter.
- `scan-efficiency-20261026T211844Z-results.json`: probe run with the updated workspace modules.

Updated probe command:

```sh
.venv/bin/python work/hindsight-comparison/temporal-refresh/scan-efficiency-20261026T211844Z.py
```

## Tests

```sh
.venv/bin/python -m pytest -q tests/test_mental_model_scan_efficiency.py tests/test_mental_models.py tests/test_mental_model_refresh.py tests/test_mental_model_change_refresh.py
```

Result: **207 passed**. The 30 dedicated Local/SQLite cases cover exact counts, pending/error suppression, owner/scope filtering, monotonic timing, every-poll authority, due work during cooldown, immediate ready-read invalidation after erasure/privacy changes, fresh worker startup, failed scans, backlog drainage, and deleted/disabled/rescheduled/out-of-scope hint rejection. Existing source-drift and lease/publication checks also pass.

The existing change-refresh fixture now advances its mocked monotonic clock together with its mocked wall clock; no assertion was weakened. Ruff and `git diff --check` passed for the changed source/tests.
