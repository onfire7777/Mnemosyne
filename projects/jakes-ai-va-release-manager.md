---
type: project
title: AI VA Release Manager
updated: '2026-08-01T00:00:00.000Z'
visibility: private
ingested_via: 'mcp:put_page'
ingested_at: '2026-08-02T00:42:15.433Z'
source_kind: 'mcp:put_page'
tags:
  - electron
  - jakes-ai-va
  - release-manager
  - repository
---

# AI VA Release Manager

AI VA Release Manager is the operator-facing Electron tool used to build and publish releases for Jake's AI VA Desktop. It is a distinct repository and must not be indexed or synchronized as part of the desktop application's corpus.

## Canonical identity

- Local checkout: `/Users/admin/Documents/AI VA release manager`
- GitHub: `onfire7777/jakes-ai-va-release-manager`
- Branch: `main`
- Gbrain source: `gstack-code-d6ac5310-45a34f`
- CBM project: `Users-admin-Documents-AI-VA-release-manager`
- Version at the 2026-08-01 setup receipt: `1.0.2`
- Verified receipt: commit `c78a132fe15f946ae1fe7f2858fa137d1c8e18cb`

## Target mapping

The ignored local `release-manager.config.json` targets:

- Project path: `/Users/admin/Documents/Jakes AI VA`
- Repository: `onfire7777/jakes-ai-va-desktop`
- Branch: `master`

The release manager builds and publishes artifacts for [[projects/jakes-ai-va-desktop]]. The desktop updater consumes those GitHub release artifacts; the two repositories do not communicate through a runtime HTTP, IPC, or async channel.

## Index ownership

- CBM owns current architecture, symbols, traces, snippets, and impact analysis.
- This worktree's Gbrain source owns semantic retrieval for this checkout.
- Durable repository and workflow knowledge lives in Gbrain pages such as [[runbooks/jakes-ai-va-repository-sync-map]].
- Always scope automation to the exact Gbrain source ID so results cannot mix with the desktop corpus.

## T9 custody

The Samsung T9 clone is an older offline backup, not a canonical checkout. Do not index it as another source or copy it over this repository. See [[runbooks/jakes-ai-va-repository-sync-map]] for the dated inventory and exclusions.
