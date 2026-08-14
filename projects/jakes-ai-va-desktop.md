---
type: project
title: Jake's AI VA Desktop
updated: '2026-08-01T00:00:00.000Z'
visibility: private
ingested_via: 'mcp:put_page'
ingested_at: '2026-08-02T00:40:59.207Z'
source_kind: 'mcp:put_page'
tags:
  - desktop
  - electron
  - jakes-ai-va
  - repository
---

# Jake's AI VA Desktop

Jake's AI VA Desktop is the end-user Electron application. It is a distinct repository from the operator-facing release manager and must retain its own Git, CBM, and Gbrain identity.

## Canonical identity

- Local checkout: `/Users/admin/Documents/Jakes AI VA`
- GitHub: `onfire7777/jakes-ai-va-desktop`
- Branch: `master`
- Gbrain source: `gstack-code-528debbf-8af93b`
- CBM project: `Users-admin-Documents-Jakes-AI-VA`
- Version at the 2026-08-01 setup receipt: `3.6.22`
- Verified receipt: commit `a9d038e6704f9e571943c49dc859c8fb6cb8a75e`

## Release relationship

The desktop consumes GitHub release metadata and Windows artifacts produced for this repository. Its `electron-updater` flow reads the release manifest and installer assets. The separate [[projects/jakes-ai-va-release-manager]] prepares and publishes those releases; it is not part of this application's source tree.

## Index ownership

- CBM owns current architecture, symbols, traces, snippets, and impact analysis.
- This worktree's Gbrain source owns semantic retrieval for this checkout.
- Durable repository and workflow knowledge lives in Gbrain pages such as [[runbooks/jakes-ai-va-repository-sync-map]].
- Always scope automation to the exact Gbrain source ID so results cannot mix with the release-manager corpus.

## T9 custody

The Samsung T9 clone is an older offline backup, not a canonical checkout. Do not index it as another source or copy it over this repository. See [[runbooks/jakes-ai-va-repository-sync-map]] for the dated inventory and exclusions.
