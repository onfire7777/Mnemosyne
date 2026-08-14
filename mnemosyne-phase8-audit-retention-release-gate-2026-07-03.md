---
type: concept
title: Mnemosyne Phase8 Audit Retention Release Gate 2026 07 03
ingested_via: put_page
ingested_at: '2026-08-09T03:54:02.010Z'
source_kind: put_page
---

# Mnemosyne Phase 8.5 audit retention release gate (2026-07-03)

Commit `3973b3c` on `/Users/admin/Mnemosyne` branch `phase3/providers-consolidation` adds a source-side production release-audit gate for the Phase 8.5 tamper-evident audit row.

What changed:
- `release-audit` now requires production `ops-report` evidence to include an `audit` section.
- The audit evidence must prove Vault-HMAC hash-chain verification and retention.
- The audit evidence must prove pgaudit is enabled and retained.
- The audit evidence must prove an external retained WORM copy.
- Weak audit evidence fails with `required_ops_report_audit_evidence_incomplete`.

Verification:
- Focused release-audit tests passed.
- `uv run --locked pytest tests/test_cli_runtime_tools.py -q` passed.
- `uv run --locked ruff check` passed.
- Full `uv run --locked pytest -q` exited 0 locally.

Still open:
- Real Vault-HMAC hash-chain artifacts.
- Real pgaudit/WORM-copy evidence retained outside the app role.
- Operator-captured production bundle and release-audit evidence.
