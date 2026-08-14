---
type: concept
title: Mnemosyne Phase8 Privacy Release Gate 2026 07 03
ingested_via: put_page
ingested_at: '2026-08-09T03:54:05.386Z'
source_kind: put_page
---

# Mnemosyne Phase 8 Privacy Release Gate 2026-07-03

Production `release-audit` now rejects weak `privacy-ops-check` evidence unless replayed retained output proves non-local KMS custody, key lifecycle/shred proof, strict runtime residency, allow-and-deny residency cases, tombstone recompute plus legal hard delete, operator delete corroboration, case-count coverage, and raw privacy-material redaction.

Evidence:
- Repo: `/Users/admin/Mnemosyne`
- Branch: `phase3/providers-consolidation`
- Commit: `9f1c065 fix(release): require privacy runtime evidence`
- CI: GitHub run `28686764026` passed for head `9f1c06501843828ab7a93a6df2217d2bda9c262a`.
- Local verification: focused privacy/release-audit tests passed, `tests/test_cli_runtime_tools.py -q` passed, full `uv run pytest -q` passed, `uv run ruff check` passed, and `git diff --check` passed.
- CBM: `/Users/admin/Mnemosyne` was refreshed after the commit as project `Users-admin-Mnemosyne`.

Scope boundary: this is source-side gate hardening only. It does not close Tier-B, blueprint parity, or the self-hosted production privacy rows. Operator-retained production object-store, KMS/Vault, residency, erasure, LUKS/PITR/restore, and release-audit evidence remain required.

## Related

- [[Mnemosyne Phase 8 MCP Runtime Release Gate 2026-07-03]]
- [[Mnemosyne Tier-B Evidence Custody Status]]
