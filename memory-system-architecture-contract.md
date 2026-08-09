---
type: architecture
title: Memory system architecture contract
created: '2026-07-03T00:00:00.000Z'
updated: '2026-07-03T00:00:00.000Z'
captured_at: '2026-07-03T09:20:48.883Z'
captured_via: capture-cli
tags:
  - bridge-memory
  - cbm
  - codex
  - context-mode
  - gbrain
  - gbrain-codex
  - gstack
  - memory-architecture
  - primary-memory
---

# Memory system architecture contract

Preferred memory routing order:

1. context-mode
2. Codex memory
3. gbrain
4. gstack
5. CBM/codebase-memory-mcp
6. GSD
7. BridgeMemory

Codex memory and gbrain are the primary durable memory pair. context-mode comes first operationally because it protects the context window and captures session/search state before anything is promoted. Gbrain owns durable knowledge, research, RAG, and broad synthesis. Codex memory owns agent continuity, user preferences, rollout evidence, and compact prior-work context.

## Routing contract

| System | Owns | Does not own |
|---|---|---|
| context-mode | Session/search cache: command output, indexed docs, file summaries, decisions/errors/compaction context. | Durable canonical memory, curated human-facing notes. |
| Codex memory | Primary agent-continuity memory: user preferences, prior rollout evidence, recurring repo/task gotchas, interaction conventions. | Raw logs, large docs, human note hub, code graph structure. |
| gbrain | Primary long-term knowledge memory: durable project knowledge, research, RAG, source-indexed knowledge, architecture notes, broad synthesis. | Tiny session facts, raw command output, CBM code graph replacement, gstack workflow state. |
| gstack | Workflow state, artifacts, privacy-gated sync, operational learnings. | General knowledge storage, code graph storage, curated note hub. |
| CBM/codebase-memory-mcp | Repository code graph: architecture, symbols, calls, snippets, impact, ADRs, runtime traces. | Personal preferences, broad research, general notes. |
| GSD | User-profile-driven project methodology and phase skills. | General memory storage, code graph storage, session cache. |
| BridgeMemory | Human-readable curated note layer and manual review surface. | Primary memory graph, raw logs, large code indexes, transient session output. |

## Promotion rules

- Save each durable fact in one authoritative system by default.
- Follow the preferred routing order for lookups and task setup unless the user names a specific system.
- Put durable knowledge, research, architecture, and synthesis into gbrain first unless it is only Codex-specific continuity.
- Keep user preferences, prior-run evidence, and interaction conventions in Codex memory.
- Use context-mode first for large output, raw tool output, temporary recall, and session-resume search.
- Mirror important human-facing decisions to BridgeMemory when the user should be able to browse or edit them.
- Use CBM before broad file reads in real repositories; do not use gbrain as a CBM replacement.
- Use gstack/GSD for workflow artifacts and operational learnings only.

## Current setup

- Active Codex instructions: `/Users/admin/.codex/AGENTS.md`.
- BridgeMemory mirror: `/Users/admin/Desktop/Bridgememory/.bridgememory/memory-system-architecture-contract.md`.
- gstack setting: `artifacts_sync_mode=artifacts-only`.
- gbrain sources: `default`, `gstack-code`, `mnemosyne-code`.
- CBM has an active index for `/Users/admin/Mnemosyne`.
- BridgeMemory is not force-synced into gbrain as a source because gbrain source sync expects a git repo; BridgeMemory remains a curated human-facing mirror.

## Related

- BridgeMemory: `Memory system architecture contract`
- BridgeMemory: `Mnemosyne gstack gbrain separation`
