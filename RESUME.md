# Mnemosyne Resume Checkpoint

The complete pause/resume handoff is:

- [`docs/CODEX-HANDOFF-RESUME-2026-07-22.md`](docs/CODEX-HANDOFF-RESUME-2026-07-22.md)

Evidence cutoff: `2026-07-23T06:05:15Z`.

## Paused state

- Board: 94 done, 11 archived, 18 todo, 4 blocked, 2 triage, 0 ready,
  0 running.
- Active task runs, claims, worker PIDs, and RalphEx/Kanban lane processes: 0.
- RFX pause sentinel:
  `/Users/admin/.config/rfx/PAUSE`.
- Hermes gateway dispatch on disk:
  `HERMES_KANBAN_DISPATCH_IN_GATEWAY=0`.
- Repository cutoff:
  `main@0669c606a2c9519aa2cc0f2deba7a818fbd8eb45`, matching the local
  `origin/main` ref.

## First action

Do not run `rfx resume`, Hermes dispatch, task retries, live apply, GitHub,
Python-heavy validation, or model/runtime work yet. The Mac must first receive
an orderly Apple-menu restart to clear the unresolved `syspolicyd` file-
descriptor/signature-validation fault. After reboot, require fresh uptime,
error-free recent policy logs, and a successful signed executable launch.

Then follow the detailed handoff in order:

1. run `~/.config/rfx/bin/rfx-resume-scan`;
2. verify `rfx doctor` and `rfx current` with Python 3.11+;
3. repair fleet/profile drift at its source and re-audit all 100 numbered
   personas;
4. finish and independently accept the three preserved RFX repair worktrees;
5. re-read the live board/DAG/worktrees/leases;
6. materialize the twelve plan-backed missing cards through supported Hermes
   commands;
7. resolve the two manual recovery roots without force or duplicate writers;
8. only then use the supported `rfx resume` path and admit every genuinely
   ready, dependency-safe, exact-lease-disjoint card.

## Current model authority

This checkpoint supersedes stale RFX-resume examples that mention mixed
providers. Every planner, executor, reviewer, captain, stage, fallback,
delegation, and auxiliary binding must resolve to:

```text
openai-codex/gpt-5.6-sol
reasoning_effort=low
```

Never treat the 100 configured personas as 100 active workers without live
process, heartbeat, task, diff/review, test, and independent-review evidence.
Never force a task, bypass dependencies, overlap leases, direct-write Kanban
SQLite, discard preserved worktrees, or mutate protected gates.
