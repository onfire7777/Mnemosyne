---
type: concept
title: Mnemosyne Current Main Status
captured_at: '2026-07-16T20:45:00.000Z'
captured_via: claude-code-session
---

# Mnemosyne current main status

As of 2026-07-16, `/Users/admin/Mnemosyne` `main` is at `489895a30156e372db8784d791248baf5b707fca` (merge of PR #32), local == origin, tree clean.

A host reboot at 2026-07-16T12:41Z killed the goalex round-8 executor mid-way through its review-fix gate. The orphaned work (3 committed review-fix iterations plus an uncommitted 4th) was recovered onto `codex/r8-review-fix-recovery`, completed, adversarially verified by a 27-agent multi-lens review, hardened, and landed via PR #32 with all exact-head checks green: symlinked-store rejection (capture-batch CLI seam plus engine persistence), non-destructive idempotent `PostgresEngine.merge` clone replay with deterministic clone ids and supersession-reference resolution, UUID-shaped deterministic summary-relation ids (the prior `relation-<sha256>` form would have failed PostgreSQL's UUID primary key), and per-merge (not per-row) schema-ensure DDL.

W1 graph-substrate keystone is fully landed (PRs #23–#31): Fix A consolidate-before-search, Fix B deterministic prose relation extractor, receipts, and the disclosure audit. Local dev proof: 7 persisted relations, positive graph contribution, Recall@5/nDCG@5 = 1.0, byte-identical repeat traces.

Open program state: CAP-003, BENCH-005, Plan 12-04 remain partial (production `postgres-recursive-ppr` parity, runtime readiness, grounded-reader QA, single protected `qa_hard_v2` attempt); W2–W5 and Phases 13–16 unstarted. The Colima production VM is intentionally stopped (operator decision 2026-07-15); the rotated MCP client leaf expires 2026-07-16T21:18:25Z, below the ≥6h admission floor, so cert-gated live work is operator-gated (known R3/R4 rotation-proof gap). Known deferred limitation: `_extract_simple_fact` drops facts spanning hard-wrapped lines (per-line handling is test-pinned for line-oriented fixtures) — future W1 eval slice.

CBM project `Users-admin-Mnemosyne` re-indexed at this commit (3,662 nodes / 16,524 edges); gbrain source `mnemosyne-code` synced to this commit. Concluded goalex round plans (r2–r8) live in `docs/plans/completed/`. Note: Mnemosyne code symbols are served by CBM, not gbrain's code graph (never registered there).

## Related

[[ADR 0001 — SqliteEngine per-tenant file isolation]]
