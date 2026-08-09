---
type: milestone
title: Whole-memory ABI remediation merged
date: '2026-07-29T00:00:00.000Z'
tags:
  - abi
  - milestone
  - mnemosyne
  - whole-memory-benchmark
---

# Whole-memory ABI remediation merged

PR #80 merged the bounded post-merge whole-memory ABI remediation normally into `main` as merge commit `28805ccf54f99f098a5abc23fe6f1155400d0f22` on 2026-07-29. The immutable remediation head `0d42f9436397a04e12ceaa3bdbd60d925e2640e9` is an ancestor of that merge.

Post-merge CI run `30484986865` completed successfully on the exact merge SHA. Required jobs passed: Ruff, unit and drift checks, provider conformance, Postgres integration, and native wheels on macOS and Ubuntu. The nightly DST/chaos soak was non-gating and skipped.

The canonical checkout `/Users/admin/Mnemosyne` was cleanly fast-forwarded so local `main` equals `origin/main` at the merge SHA. The benchmark-spec and signed-publication worktrees were not modified.

Source-grounded next increment: `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md` keeps result-v2 compatibility fixtures and local ledger support open. No result-v2 implementation or benchmark execution occurred in this remediation round.

Sources:
- https://github.com/onfire7777/Mnemosyne/pull/80
- https://github.com/onfire7777/Mnemosyne/actions/runs/30484986865
- `docs/plans/goalex-r14-land-the-exact-head-abi-remediation.md`
- `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
