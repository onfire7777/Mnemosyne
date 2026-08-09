---
type: concept
title: Mnemosyne Phase 8 Retrieval Release Gate 2026-07-03
captured_at: '2026-07-03T23:14:41.567Z'
captured_via: default
---

# Mnemosyne Phase 8 Retrieval Release Gate 2026-07-03

Production `release-audit` now rejects weak `retrieval-ops-check` evidence unless retained output proves non-local Postgres lexical and graph backends, provider forbid-local posture, graph/lexical/reranker/vector adapter probes, production calibrated retrieval cases, adapter fingerprints, latency bounds, and raw query/embedding/document/credential redaction.

Evidence:
- Repo: `/Users/admin/Mnemosyne`
- Branch: `phase3/providers-consolidation`
- Commit: `391f09a fix(release): require retrieval runtime evidence`
- PR: https://github.com/onfire7777/Mnemosyne/pull/7
- CI: https://github.com/onfire7777/Mnemosyne/actions/runs/28687245979 passed for head `391f09a874f553ede4242dfc5242c1d7a9190b61`
- Local checks passed: focused retrieval release-audit tests, full `tests/test_cli_runtime_tools.py`, `uv run ruff check`, `git diff --check`, and full `uv run pytest -q`.
- CBM refreshed after the commit: project `Users-admin-Mnemosyne`, fast index, no repo artifact.

Scope boundary: this is a source-side release gate only. It does not claim Phase 8/Tier-B blueprint parity or production/operator completion; operator-retained production evidence artifacts are still required.

## Related
- [[Mnemosyne Phase 8 MCP Runtime Release Gate 2026-07-03]]
- [[Mnemosyne Phase 8 Privacy Release Gate 2026-07-03]]
- [[Mnemosyne Tier-B Evidence Custody Status]]
