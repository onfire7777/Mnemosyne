# E-mental-models — private maintained answers

Date: 2026-10-22. Baseline: `00d8ea9f7389d3a423d233e5fc0ab959ead8e520`.
Branch: `codex/hindsight-memory-audit`, local uncommitted implementation.

Implemented service: `src/mnemosyne/mental_models.py`; storage validator:
`src/mnemosyne/mental_model_storage.py`. Local/SQLite/PostgreSQL storage and
Python/MCP/CLI surfaces reuse the existing grounded orchestrator. Documentation:
`docs/mental-models.md`, `docs/HINDSIGHT-COMPARISON.md`, and the dated audit report.

Behavior verified: provider-free clean reads; new-correction invalidation; tenant/owner/scope
isolation; no generated-evidence feedback; version conflicts and concurrent refresh;
privacy, deletion, expiry and historical cutoffs; persistence; strict imported-record
output; day rollover before and during publication. SQLite final source validation and
publication exclude writes from other connections. Local protection is same-instance.
PostgreSQL has model CAS and post-save checking, not atomic source publication; no live test.

Independent reviewers reproduced five defects before final fixes: publication privacy race,
permissive cached claim/history output, fabricated source list, historical-cutoff omission,
and a final-view clock override. Their exact repros pass after fixes. Storage integration
also preserved inactive-feature JSON bytes and registered the new SQL table.

Final command: process-local supported `SDKROOT` plus `bash work/hindsight-comparison/verify-mental-models.sh`.
Result: 2003 cases, 1889 passed, 114 skipped, 0 failures/errors, 20.189s. Three new mental-model
modules contribute 170 passing cases. Global Ruff and `git diff --check` passed.
Receipts: `mental-models-final-verification.{xml,log}`, `mental-models-final-lint.log`.
Source manifest: `mental-models-source-manifest.json` (389 unchanged files).
Failed pre-fix integration receipt: `mental-models-integration-before.{xml,log}`.

No benchmark or ranking gain is inferred from this feature's regression tests. No new
provider installation, paid API setup, Mnemetric code/data connection, or Git push occurred.
