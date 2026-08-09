---
type: concept
title: Mnemosyne Phase8 Audit Log Append Only 2026 07 03
ingested_via: put_page
ingested_at: '2026-08-09T03:54:00.142Z'
source_kind: put_page
---

# Mnemosyne Phase 8 audit-log append-only hardening - 2026-07-03

Commit 57d4732ccf3a0b6a505557cc7c098f55b92e8503 on /Users/admin/Mnemosyne branch phase3/providers-consolidation adds source-side Postgres audit-log append-only enforcement.

What changed:
- sql/schema.sql installs mnemosyne_audit_log_append_only() and a BEFORE UPDATE OR DELETE trigger on audit_log.
- infra/postgres/roles.sql narrows audit_log grants back to SELECT, INSERT for mnemosyne_app and mnemosyne_consolidator after broad table grants.
- tests/test_nfrs_and_schema.py pins the schema trigger and runtime grant invariants.
- docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md, .planning/STATE.md, and Phase 8.1 plan notes record this as source-controlled append-only rail progress only.

Verification:
- uv run --locked pytest tests/test_nfrs_and_schema.py tests/test_postgres_security.py -q passed.
- uv run --locked pytest tests/test_nfrs_and_schema.py tests/test_config_drift.py tests/test_prod_compose_policy.py tests/test_postgres_security.py -q passed.
- uv run --locked ruff check passed.
- git diff --check passed.
- uv run --locked pytest -q passed locally.
- GitHub CI run 28683870536 passed for head 57d4732, including Postgres integration loading the canonical schema and running live Postgres tests.

Still open:
- This does not claim Tier-B completion or blueprint parity.
- Vault-HMAC hash chaining, pgaudit, out-of-band WORM copy, scanner/signature artifacts, runtime default-deny egress evidence, and operator-captured production bundles remain required before the parent Phase 8.5/Tier-B rows can close.
