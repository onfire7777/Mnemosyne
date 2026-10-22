# Live PostgreSQL validation — 2026-10-22

**Latest validation:** the subsequent source-change refresh extension passed
**239 mixed live/unit tests**, including **20 live mental-model cases** (the
original 16 plus four new cases), with no failures or skips. The role probe again
passed 9/9 checks and the disposable database was removed. See the
[source-change refresh report](change-refresh/REPORT.md) and its receipts. The
235-test results below document the earlier validation and remain unchanged.

Validation used a disposable PostgreSQL 16.15 container on `127.0.0.1:55432`, with the repository schema and role policy. Runtime tests used `consolidator_user`, with separate `app_user` and `eval_user` permission probes. All three logins were non-superuser and did not bypass row-level security. The isolated schema-upgrade test alone used the local administrator DSN. No production data or external model provider was used.

Environment details and image digest are in [environment.json](environment.json); the relevant code hashes are in [source-manifest.json](source-manifest.json). The existing Colima virtual machine and unrelated containers were preserved. This is functional/concurrency validation, not a performance benchmark or a Hindsight score comparison.

## Confirmed defects and repairs

1. **Advisory model deletion permissions.** `roles.sql` revoked table-owner DELETE on `mental_models`. Owner-authorized service deletion failed for the app role; branch deletion also failed because the foreign-key cascade runs as the table owner. A narrow `mental_models` DELETE grant repairs both. The service still denies a different model owner; DELETE on evidence, branches, and audit rows remains outside the app allowlist. The role-check CLI now recognizes the documented model grant. [Before-fix failures](permissions-before.log).
2. **Untrusted external evidence identifiers.** A command retrieval adapter's non-hexadecimal identifier caused PostgreSQL source revalidation to raise instead of treating the source as missing. `get_evidence` now returns `None` before database access for an invalid identifier. The new regression covers pooled and fresh connections. The command-adapter integration fixture now supplies a real source CID and asserts that the authoritative stored text replaces its untrusted preview. [Before-fix failures](invalid-cid-before.log).
3. **Provider request CID redaction.** Real command consolidation exposed SHA256 source references being replaced with `[secret-omitted]` inside the provider payload. Custody replay correctly rejected the now-missing reference. The separate sanitizer fix preserves valid references in the known structural field while retaining secret filtering elsewhere. [Diagnostic](custody-diagnostic.log) and [queue failure](consolidation-recheck.log).

Two working-memory fixtures were also corrected: a changed user must have that user's source evidence, and different sessions need distinct source identities/content. Their former fixtures violated the intended source-ownership checks. Prospective-memory tests now retain randomized tenant data until the disposable database is destroyed; their previous eager tenant purge conflicted with intentionally restricted cascade permissions and append-only audit retention. The schema-upgrade test accepts a separate administrator DSN rather than requiring elevated runtime credentials.

## Coverage and receipts

- The final complete `tests/test_postgres*.py` run completed **235 passed, zero skipped/failed/errors in 53.296 seconds** across eight test modules: [XML](postgres-final.xml) and [machine-readable counts](verification.json). This includes live integration tests and the PostgreSQL modules' mocked/unit contracts; 235 is not a count of exclusively live tests.
- The focused set completed **172 passed, zero skipped/failed/errors in 25.223 seconds**: [XML](focused-final.xml).
- The new live module covers source insertion, deletion and privacy tightening against publication; source changes during generation; lease takeover and expiry; transaction rollback; pooled tenant and model-owner isolation; five-second lock timeout/recovery; app deletion boundaries; and readonly publication/deletion denial.
- The role-check command completed **9 checks, no findings**: [receipt](role-check.json).
- Provider output was deterministic fixture data. Lease expiry/takeover used a controlled UTC clock with real concurrent database connections; this did not wait through a real lease duration. Lock contention used real PostgreSQL locks and the actual five-second timeout.

The guard pins one transaction/connection, selects READ COMMITTED, and holds SHARE locks on the source tables until publication commits or rolls back. The tests verify competing source writes wait and become visible after the guard exits. Those locks cover whole source tables, so unrelated-tenant writers can also wait during this short publication section. Provider inference remains outside the guard. High-load throughput, other PostgreSQL major versions, remote/TLS deployments, and production privilege drift are not validated here.

## Reproduction

Use a disposable database initialized with `sql/schema.sql` followed by `infra/postgres/roles.sql`. Supply separate credentials through these environment variables (credentials are not recorded in the environment receipt):

```sh
export MNEMOSYNE_POSTGRES_DSN='<local consolidator DSN>'
export MNEMOSYNE_POSTGRES_APP_DSN='<local app DSN>'
export MNEMOSYNE_POSTGRES_READONLY_DSN='<local readonly DSN>'
export MNEMOSYNE_POSTGRES_ADMIN_DSN='<local admin DSN for isolated schema upgrade>'
export MNEMOSYNE_POSTGRES_RLS_TEST_ROLE=mnemosyne_app
.venv/bin/python -m pytest -q tests/test_postgres*.py --junitxml=postgres-final.xml
```

The macOS native test helper used the process-local `SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk`. The schema-upgrade test drops its isolated schema; all remaining synthetic tenant/audit data is removed by destroying the disposable container. Do not run this test setup against a production database.

Cleanup was completed and verified: `mnemosyne-audit-pg-d59d4e5d` is absent, its tmpfs data was removed, and the separate Hindsight/PentestSwarm containers remain present. [Cleanup receipt](cleanup.json).
