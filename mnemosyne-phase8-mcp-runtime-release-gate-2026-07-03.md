---
type: concept
title: Mnemosyne Phase 8 MCP Runtime Release Gate 2026-07-03
source: codex
created: '2026-07-03T00:00:00.000Z'
tags:
  - mcp
  - mnemosyne
  - phase8
  - release-audit
  - tier-b
---

# Mnemosyne Phase 8 MCP Runtime Release Gate 2026-07-03

Production `release-audit` now rejects weak `mcp-ops-check` evidence unless replayed retained output proves hosted non-local MCP transports, bearer-token enforcement, signed-session binding, required client certificates, control-loop checks, latency bounds, and raw token/request/response redaction.

Evidence:
- Repo: `/Users/admin/Mnemosyne`
- Branch: `phase3/providers-consolidation`
- Commit: `9d21d53 fix(release): require mcp runtime evidence`
- CI: GitHub run `28686363935` passed for head `9d21d5384e10a0587a5cdeeb331d30c48843fa9b`.
- Local verification: focused MCP/release-audit tests passed, `tests/test_cli_runtime_tools.py -q` passed, full `uv run pytest -q` passed, `uv run ruff check` passed, and `git diff --check` passed.

Scope boundary: this is source-side gate hardening only. It does not close Tier-B or claim blueprint parity. Hosted MCP operator evidence from real production infrastructure is still required before the fail-closed production-defaults row can close.
