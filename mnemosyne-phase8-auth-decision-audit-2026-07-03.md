---
type: concept
title: Mnemosyne Phase8 Auth Decision Audit 2026 07 03
ingested_via: put_page
ingested_at: '2026-08-09T03:54:03.709Z'
source_kind: put_page
---

# Mnemosyne Phase 8 auth-decision audit rail

On 2026-07-03, commit f585c3b added source-side auth-decision audit coverage to Mnemosyne. The shared MemoryEngine contract now exposes `record_audit_event`, implemented by LocalMemoryEngine, SqliteEngine, and PostgresEngine. `MemoryTools._authorize` records every allow/deny write-authorization decision with `op=authorize_write`, actor role, `source=mcp_tools`, trust tier, authz tags, operation, decision reason, destructive flag, and target sink. No session token or secret material is written to the audit diff.

This narrows Phase 8.5 item 16 by closing the source-side "log every auth decision" rail alongside the existing write audit stream and the Postgres append-only trigger/grant rail. It does not close the parent tamper-evident audit-log item: Vault-HMAC row hash chaining, pgaudit, out-of-band WORM export, live `audit-verify`, scanner/signature evidence, and retained operator-captured production bundles remain open.

Evidence: local full `uv run --locked pytest -q` passed on f585c3b; focused runtime/shared-engine audit tests and `uv run --locked ruff check` passed before push. PR #7 is still draft and mergeable on `phase3/providers-consolidation`.
