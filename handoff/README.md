# 🧭 HANDOFF — start here (next AI agent)

_Compiled 2026-10-05. Covers the Codex (ChatGPT) session of 2026-09-30 → 2026-10-04. Codex stopped on 2026-10-04 at 18:34 PT
because it **hit its usage limit**. It did not stop because the goal was finished._

## Where the full handoff lives

The complete handoff is in the companion repo **[onfire7777/Mnemetric → `handoff/`](https://github.com/onfire7777/Mnemetric/tree/codex/development/handoff)**
on branch `codex/development` (private). It contains the full Codex chat as one Markdown file, every diff, the timeline, the websites,
the exact stopping point, the owner's standing rules and the next steps. **Read `handoff/README.md` there first.**

## Ownership split

- **This repo (Mnemosyne)** owns the memory engine: storage, retrieval, consolidation, native runtime, MCP/serving, memory-runtime
  deployment and **BurnOS API compatibility (must not break)**.
- **Mnemetric** owns the WMBS benchmark suite, adapters, scoring, benchmark plans and evidence, plus both websites
  (https://mnemetric.burnos.app and https://mnemosyne.burnos.app). See [`docs/benchmark/MNEMETRIC-REPOSITORY.md`](../docs/benchmark/MNEMETRIC-REPOSITORY.md).
  The benchmark copies still in this repo are a compatibility bridge only.

## State of this repo at handoff

- Only two branches: `main` and `codex/development`. Local and GitHub match.
- `codex/development` is ~294 commits ahead of `main`. **[PR #214](https://github.com/onfire7777/Mnemosyne/pull/214)** (dev → main) is open
  with CI green and is **not merged**. The Codex goal said *don't merge to main without the owner's authorization*, so **ask first**.
- Latest engine change: `3595dc86` added the read-only evaluation retrieval policy overrides
  (`eval-query-batch --retrieval-token-budget/--retrieval-top-k`, which require `--evaluation-read-only`). The latest doc update is `db42ce13`.
- Codex's task ledger: [`docs/plans/completion-2026-10-04.md`](../docs/plans/completion-2026-10-04.md) (see "Remaining program after this slice").

## Next engine-side work (from the ledger)

1. M12 multi-week seeded recurrence experiment and M13 multi-capacity/promotion-control experiment.
2. Freeze missing module contracts before implementing them. Extend partial M16 coverage. M19 is deferred.
3. The M08 reversible-delete contract is still unresolved (tombstone regression recorded).
4. Keep BurnOS compatibility tests green on every change. Never fabricate measurements or relax gates.
