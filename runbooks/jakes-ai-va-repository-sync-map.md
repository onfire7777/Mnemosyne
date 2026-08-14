---
type: note
title: Jake's AI VA Repository Sync and Memory Map
updated: '2026-08-01T00:00:00.000Z'
visibility: private
ingested_via: 'mcp:put_page'
ingested_at: '2026-08-02T01:16:22.620Z'
source_kind: 'mcp:put_page'
tags:
  - cbm
  - gbrain
  - jakes-ai-va
  - repository
  - runbook
  - sync
---

# Jake's AI VA Repository Sync and Memory Map

This runbook keeps Jake's AI VA Desktop and the AI VA Release Manager distinct while preserving their release relationship across Git, CBM, Gbrain, and Gstack.

## Canonical repository map

| System | Jake's AI VA Desktop | AI VA Release Manager |
|---|---|---|
| Purpose | End-user Electron application | Operator release-building and publishing tool |
| Local checkout | `/Users/admin/Documents/Jakes AI VA` | `/Users/admin/Documents/AI VA release manager` |
| GitHub | `onfire7777/jakes-ai-va-desktop` | `onfire7777/jakes-ai-va-release-manager` |
| Branch | `master` | `main` |
| Gbrain source | `gstack-code-528debbf-8af93b` | `gstack-code-d6ac5310-45a34f` |
| CBM project | `Users-admin-Documents-Jakes-AI-VA` | `Users-admin-Documents-AI-VA-release-manager` |
| Exact-head receipt | `a9d038e6704f9e571943c49dc859c8fb6cb8a75e` | `c78a132fe15f946ae1fe7f2858fa137d1c8e18cb` |

These are two independent repositories and two independent code indexes. Never merge their source IDs, CBM projects, branches, or checkouts.

## Release relationship

The release manager targets the desktop checkout through its ignored local `release-manager.config.json`, builds desktop release artifacts, and publishes them to the desktop GitHub repository. The desktop's `electron-updater` consumes the GitHub release manifest and installer assets. This is an artifact flow, not an HTTP, IPC, or async runtime channel, so CBM correctly finds no cross-repository call edge.

```text
AI VA Release Manager -> desktop build/release assets -> GitHub Releases -> Jake's AI VA updater
```

## Memory ownership

- CBM owns live code architecture, symbols, call traces, snippets, and impact analysis for each exact checkout.
- The two source-scoped Gbrain corpora own semantic code retrieval for their respective repositories.
- Gbrain default-source pages such as [[projects/jakes-ai-va-desktop]], [[projects/jakes-ai-va-release-manager]], and this runbook own durable cross-repository knowledge.
- Gstack owns workflow artifacts and operational learnings in `artifacts-only` sync mode; it does not replace either code index.
- The Samsung T9 owns offline backup and historical custody only. Its stale clones must not become canonical sources.

## Recommended sync workflow

1. Resolve the exact checkout, branch, remote, and `HEAD` before any claim.
2. Confirm the repo-local ignored `.gbrain-source` points to the correct distinct source ID.
3. Check Gbrain source status. Sync only the intended repo and verify the resulting commit receipt and 100% embedding coverage.
4. Check CBM `index_status`; refresh the exact canonical checkout when its commit changed, then verify architecture/search/trace surfaces.
5. Run Gstack artifact sync only for workflow artifacts.
6. Update the Gbrain project pages and typed links only when durable identity or release-flow knowledge changes.
7. Keep `gbrain autopilot` running as the machine-wide queue and freshness supervisor. Do not run a manual full Gbrain sync concurrently; pause the supervisor first if an operator-only rebuild is required.

## Health gates

- Desktop Gbrain source path, branch, and exact commit match the canonical desktop checkout.
- Release-manager Gbrain source path, branch, and exact commit match the canonical manager checkout.
- Both sources have zero missing embeddings and no waiting, active, failed, or dead jobs.
- Both canonical CBM projects are `ready`; stale worktree indexes are absent.
- Repository tests/checks/builds and dependency audits pass independently.
- The T9 remains read-only and no T9 clone or packaged application is indexed.

## Known diagnostic boundary

The active Gbrain schema pack is `gbrain-base-v2`. Its dream wrapper warns that it is not code-symbol aware; CBM remains the authoritative code graph. A raw source page count may include a soft-deleted recovery-window page while source health counts only active pages. Do not purge recoverable data just to make those counters match.

## T9 planning custody

The curated historical planning catalog is [[archives/jakes-ai-va-t9-planning-catalog]]. Its safe files were copied byte-for-byte to `/Users/admin/Jakes AI VA T9 Planning Archive`, outside both repositories, with SHA-256 verification. Treat them as historical research, not current implementation truth.
