# Round 37 delivery record — the stranded M12/M13 gap-disclosure delivery

Recorded: 2026-08-01
Controller branch: `codex/goalex-whole-memory-pilot`
Baseline entering the round: `main@a8e9444ca54633707e88263ce3e0307c5731fc9d`
(PR #89, post-merge CI `30672194635`)
Baseline leaving the round: `main@061c2e1c13cbf1fd5324361a6ff61f47cd2a6534`
(PR #90, post-merge CI `30680201900`)

## What was delivered

Rounds 19–36 left committed work on the controller branch that had never been
delivered through a PR. Round 37 moved exactly that stranded delta onto `main`
through one normal reviewed PR, from a lane branched off then-current clean
`origin/main` (branch `codex/m12-m13-gap-disclosure-delivery`, worktree
`/Users/admin/Mnemosyne.codex-m12-m13-gap-disclosure-delivery`).

Five files, 274 insertions / 36 deletions:

- `eval/public/README.md` — M12 fixture-size / recurrence / lateness gap
  disclosures and M13 seed / capacity / no-promotion-control gap disclosures.
- `tests/test_public_pm_bench_triggerbench.py` — pins the M12 disclosures.
- `tests/test_public_working_memory_action_probe.py` — pins the M13
  disclosures.
- `tests/test_production_mcp_client_cert_rotator.py` — replaces hard-coded
  10s/15s waits in `test_rotator_holds_process_lock_for_entire_invocation`
  with `ROTATOR_LOCK_TEST_TIMEOUT_SECONDS = 120` and a 3× child deadline
  (flake fix).
- `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
  — M01/M10, M12/M13, and M15 delivery checkpoints plus the Task 5/7/8
  checkbox closures.

Every README claim was re-verified against the fixtures committed on `main`
before delivery: `pm-bench-development` seed `7`, 1 case, 5 tasks, 7 steps;
`triggerbench-development` seed `7`, 20 one-step cases with no
`baseline`-bearing key at any depth; `working-memory-action-development` seed
`94125`, 6 cases, `operating_point == {"policy":
"highest-task-relevance-then-item-id", "positive_threshold": 0.75}` with no
capacity parameter and no `arm`/`control`/`condition` key at any depth.
Recurrence exists only as task `regularity` metadata; `late` is a plain count
in the adapter with no magnitude or cost field. No claim needed correction and
no test was weakened to make a claim fit.

## Receipts

| Receipt | Value |
|---|---|
| PR | #90 — "docs(eval): land M12/M13 development gap disclosures with pinning tests" |
| Lane head / exact-head CI | `7b5b9c03b024e3ab0e9aa9f5d748f88027ba69e1` — run `30679262270`, conclusion `success` |
| Review | CodeRabbit `APPROVED`; Greptile Review check `SUCCESS`; 0 inline comments — no finding raised, none dismissed |
| Merge | `gh pr merge 90 --merge` at `2026-08-01T02:32:10Z`; merge commit `061c2e1c13cbf1fd5324361a6ff61f47cd2a6534` |
| Post-merge `main` CI | run `30680201900` on `061c2e1c`, conclusion `success` (Lint, Unit + drift checks, Provider conformance, Postgres integration, Native wheels macos-14 and ubuntu-latest all `success`; DST / chaos soak `skipped`, nightly non-gating) |

Local `main` in the controller worktree was fast-forwarded to
`origin/main@061c2e1c`; `git rev-parse main == git rev-parse origin/main`.

## What this did not change

Development-source documentation and tests only. `eval/public/registry.json`,
the fixtures, and all adapter and scoring code are untouched. No module was
promoted, no measurement changed, no benchmark, comparability, or headline
claim was asserted. M12 and M13 remain `PROPOSED`, `publishable:false`, and
`pbpp_headline_eligible:false`.

`GOAL.md`, `.planning/STATE.md`, and
`docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` were
updated on the controller branch in this round to record the receipts above
and to recompute the map from the new baseline. Those three lifecycle files
are **not on `main`**; landing them is deferred to the next round's
GoalEx-owner PR so the GoalEx lifecycle lease and the public-harness lease
stay unmixed.

## Remaining open gates

- **P13-C** — first real scheduled-cadence receipt. The workflow cron is
  `23 7 * * 1`; the first eligible real `schedule` event is 2026-08-03. The
  existing manual dispatch `30561430522` is not a substitute.
- **P12-E** — Phase 12 CAP-003/BENCH-005 operator measurement (frozen /
  held-out EM/F1 and positive graph/PPR evidence). Protected data,
  production/runtime, and operator authorization gated.
- **P13-O** — official MemoryAgentBench and BEAM upstream execution.
  Rights/license, provider/model/judge disclosure, capacity, and operator
  admission gated.
- **N12** — result-v2 / M20 publication-integrity dispatch, blocked until the
  protected signed-publication paths are released on current `main`.
- **SBOX** — the OCI sandbox candidate stays quarantined: no immutable image,
  daemon probe, filesystem/network/write-boundary enforcement receipt, SBOM,
  provenance, or resource receipt exists.
