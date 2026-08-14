---
type: concept
title: Mnemosyne Phase 8 TLS Release Gate 2026-07-04
captured_at: '2026-07-04T03:01:07.739Z'
captured_via: default
---

# Mnemosyne Phase 8 TLS Release Gate 2026-07-04

Production `release-audit` now rejects weak `tls-lifecycle-ops-check` retained output unless it proves production/operator validation, non-local CA/ACME issuance, renewal validity and automation, HTTPS non-local deployment with matching issued cert, non-local private-key custody, lifecycle monitoring, redaction, and a report fingerprint.

Evidence:
- Repo: `/Users/admin/Mnemosyne`
- Branch: `phase3/providers-consolidation`
- Commit: `7370c45 fix(release): require tls lifecycle evidence`
- PR: https://github.com/onfire7777/Mnemosyne/pull/8
- CI: https://github.com/onfire7777/Mnemosyne/actions/runs/28692775553 passed for head `7370c459a67d401c8ee3f24a11e5be82d9d4137d`.
- Local checks passed: focused TLS release-audit tests, full `tests/test_cli_runtime_tools.py`, `uv run ruff check`, `git diff --check`, and full `uv run pytest -q`.
- CBM refreshed after the commit: project `Users-admin-Mnemosyne`, fast index, no repo artifact.

Scope boundary: this is a source-side release gate only. It does not claim Phase 8/Tier-B blueprint parity or production/operator completion; real TLS/step-ca/Caddy operator evidence is still required.

## Related
- [[Mnemosyne Phase 8 Parametric Release Gate 2026-07-03]]
- [[Mnemosyne Phase 8 Retrieval Release Gate 2026-07-03]]
- [[Mnemosyne Phase 8 Privacy Release Gate 2026-07-03]]
- [[Mnemosyne Phase 8 MCP Runtime Release Gate 2026-07-03]]
- [[Mnemosyne Tier-B Evidence Custody Status]]
