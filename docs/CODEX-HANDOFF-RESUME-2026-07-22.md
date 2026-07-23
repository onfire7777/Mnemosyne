# Mnemosyne Paused Fleet Resume Handoff — 2026-07-22

> Evidence cutoff: `2026-07-23T06:05:15Z` (`2026-07-22 23:05:15 PDT`).
>
> This file is an operational restart receipt, not a replacement roadmap or a
> grant of authority to cross protected gates. On resume, inspect live state
> first. The canonical product and lifecycle owners remain `GOAL.md`,
> `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`,
> the two execution plans, and the live Hermes board. Where those sources are
> stale, the task owners named below must reconcile them after accepted code,
> not before it.

Read these governing sources before changing the board or code:

- [`GOAL.md`](../GOAL.md);
- [GSD state](../.planning/STATE.md),
  [roadmap](../.planning/ROADMAP.md), and
  [requirements](../.planning/REQUIREMENTS.md);
- [operations ownership](../.planning/OPS-HANDOFF-AND-OWNERSHIP.md) and
  [self-hosted architecture handoff](../.planning/SELF-HOSTED-ARCHITECTURE-HANDOFF.md);
- [Memory System execution plan](EXECUTION-PLAN-A-Memory-System.md) and
  [Benchmark/Leaderboard execution plan](EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md);
- [8-GiB full-capability design](superpowers/specs/2026-07-13-8gb-full-capability-unblock-design.md);
- [production MCP client certificate-rotation plan](superpowers/plans/2026-07-13-production-mcp-client-cert-rotation.md).

## 1. Objective and completion contract

Resume the paused Mnemosyne Hermes/RalphEx program from its preserved evidence,
finish all agent-owned implementation and review work, converge accepted heads
through serialized integration, reconcile documentation and GSD state, and
leave protected hardware, benchmark, governance, and publication decisions to
their named operator gates.

Completion requires all of the following:

- every dependency-ready, exact-lease-disjoint card is admitted without an
  arbitrary concurrency cap;
- every active lane has a real process, fresh heartbeat, substantive production
  diff or read-only review target, focused verification, and independent
  acceptance;
- all accepted heads are converged through dedicated synthesis/integration
  worktrees before a coherent candidate is claimed;
- local branch, remote branch, PR, exact-head CI, documentation, wiki, GSD,
  CBM, and gbrain state are reconciled by their named owners;
- TLS, Vault, runtime, custody, physical-memory, protected-data, governance,
  and publication gates fail closed;
- no task is forced, duplicated, direct-promoted past a parent, or assigned a
  second writer;
- no roster-capacity claim is presented as live activity. The fleet has 100
  numbered personas, but only evidence-backed active lanes count as work.

## 2. Clean stop receipt

| Surface | State at cutoff |
|---|---|
| Repository | `/Users/admin/Mnemosyne` |
| Branch | `main` |
| HEAD | `0669c606a2c9519aa2cc0f2deba7a818fbd8eb45` |
| Local `origin/main` ref | same `0669c606a2c9519aa2cc0f2deba7a818fbd8eb45` |
| Working tree before this handoff | clean |
| Board database | `/Users/admin/.hermes/kanban/boards/mnemosyne/kanban.db` |
| Board integrity | immutable SQLite `integrity_check = ok` |
| Board database mtime | `2026-07-22T18:37:19-0700` |
| RFX pause sentinel | `/Users/admin/.config/rfx/PAUSE` |
| Sentinel contents | `paused_at=2026-07-23T05:55:00Z`; user-requested clean stop |
| Hermes dispatcher on disk | `HERMES_KANBAN_DISPATCH_IN_GATEWAY=0` |
| Recurring monitor | `mnemosyne-rfx-fleet-monitor` deleted |
| Running/ready cards | `0 / 0` |
| Open/running task runs | `0` |
| Claims, worker PIDs, current-run pointers | `0` |
| RalphEx/Kanban lane worker processes | `0` |
| Gateway | PID `88876` remained alive as the control plane |

The gateway was intentionally not killed or restarted on the unhealthy host.
Its next supported start must load dispatcher `0`; verify this before removing
the pause. The handoff file itself is the only intended repository change made
after the clean-tree receipt.

## 3. Host recovery gate — first action, no exceptions

At cutoff the Mac had not been rebooted:

- uptime: approximately 6 days and 50 minutes;
- `kern.num_files = 13235`;
- `kern.maxfiles = 122880`;
- the earlier `syspolicyd` per-process file-descriptor failure
  (`UNIX error 24` / `Failed SecStaticCode`) had not been cleared by a full
  restart;
- `syspolicyd` was not discoverable in the final process read;
- the supported `rfx pause --status` attempt was killed with exit `137`.

A quiet recent log window is not proof of recovery when the faulted host has
not rebooted. Before any RFX, Hermes, Codex, GitHub, Python-heavy validation,
task retry, live apply, model/runtime operation, or board dispatch:

1. Save human work and perform an orderly Apple-menu **Restart**.
2. Do not kill or kickstart `syspolicyd`, reset the policy database, disable
   macOS security, or restart Bitdefender/Hermes/Claude as a workaround.
3. After reboot, run the following read-only checks:

   ```bash
   uptime
   sysctl kern.num_files kern.maxfiles
   ps -axo pid=,lstart=,etime=,stat=,command= \
     | rg '/usr/libexec/syspolicyd($| )'
   log show --last 20m --style compact \
     --predicate 'process == "syspolicyd" AND
       (eventMessage CONTAINS[c] "Failed SecStaticCode" OR
        eventMessage CONTAINS[c] "UNIX error 24" OR
        eventMessage CONTAINS[c] "Too many open files")'
   codesign --verify --verbose=2 /bin/ls
   /bin/ls /System >/dev/null
   ```

4. Require a new uptime, a live policy process, an error-free recent policy
   window, and one successful signed executable launch.
5. If the same fault recurs, stop. Do not consume task retries while the host
   remains pathological.

## 4. Paused fleet and board truth

### 4.1 Exact board counts

| Status | Count |
|---|---:|
| done | 94 |
| archived | 11 |
| todo | 18 |
| blocked | 4 |
| triage | 2 |
| ready | 0 |
| running | 0 |

There are no live leases. The persistent empty board dispatch/init lock files
are not task leases.

### 4.2 Current dependency shape

The existing ordinary work is two dependency-serial chains that may advance in
parallel only while their exact leases remain disjoint:

```text
W2/W4:
t_3cb547fc
  -> t_636f6c38
  -> t_00f9b733
  -> t_1dcf12b9
  -> t_dc7d0cf3
  -> t_3ef76c76
  -> t_8f4c31bd

W5:
t_44ec0580
  -> t_9084e720
  -> t_fb5bcbc3
  -> t_448b8a6c
  -> t_36ebac01
  -> t_3ecbb8da
  -> t_2d7832cb
  -> t_bda76b41
  -> t_67049976
  -> t_9a8af328
  -> t_28937307
```

Convergence:

- `t_a93fce34` waits for accepted W2/W4 work and `t_67049976`;
- `t_f9bdbd9f` waits for `t_1dcf12b9`, `t_a93fce34`,
  `t_67049976`, and `t_28937307`;
- the protected sequence is `t_eced0115 -> t_4c812510 ->
  t_e01da9e7 -> t_f759db7a`, but each gate also retains its full board
  parent set and operator evidence contract.

Do not flatten this DAG to inflate utilization.

### 4.3 Manual recovery roots

#### `t_3cb547fc` — W2 cert-rotator harness repair

- Status/owner: `triage`, `mnexecutor01`.
- Block: `needs_input`; recurrence 2; retry limit 2.
- Preserved clean candidate:
  `3eea1348fa28616c3c1696d9f5e965fde9ad07a1`.
- Branch:
  `mnemosyne/t_3cb547fc-repair-cert-rotator-harness-timeout-and`.
- Exact lease: `tests/test_production_mcp_client_cert_rotator.py`.
- Candidate commits:
  - `28164d2` — RED characterization;
  - `7f261d4` — bounded process-group cleanup;
  - `3eea134` — remove the accidentally tracked task-local plan.
- Passed: forced-timeout descendant cleanup, Bash syntax, Ruff, and diff check.
- Missing: repeated validation and independent review. The first required
  repetition exceeded the measured 300-second bound under the pathological
  host, so there is no acceptance receipt.
- Recovery: after host repair, inspect watchdog evidence and resume the
  preserved candidate through the governed triage/review route. Do not
  integrate, increase the timeout again, create a second writer, or blindly
  retry.

#### `t_636f6c38` — independent review of the W2 repair

- Status/owner: `todo`, `mnreviewer08`.
- Parent: `t_3cb547fc`.
- Preserved clean review worktree head: `7f261d4d0256`.
- It must independently accept the final `t_3cb547fc` head before
  `t_00f9b733` can recover.

#### `t_00f9b733` — W2 deletion integration

- Status/owner: `triage`, `mnexecutor10`.
- Block: `needs_input`; recurrence 3.
- Unresolved parents: `t_3cb547fc`, `t_636f6c38`; other parents are done.
- Preserved clean candidate: `cc9de02d16d7`.
- Branch: `codex/hermes-w2-deletion-integration`.
- Exact lease:
  - `src/mnemosyne/deletion.py`;
  - `src/mnemosyne/deletion_manifest.py`;
  - `tests/completion/security/test_deletion_residue.py`.
- Passed: focused checks, Ruff, diff check, disposable PostgreSQL 45/45.
- The old repository-wide run exceeded the former 720-second semantic
  watchdog; later classification found unrelated CLI-soak and cert-rotator
  failures.
- Recovery: only after both unresolved parents are accepted and the governed
  recovery route is installed, use the audited dependency-safe
  `--from-triage` path. Never force, reclaim, or direct-promote it.

#### `t_44ec0580` — W5 Runtime constructor review

- Status/owner: `blocked`, `mnreviewer20`.
- Block: `transient`; recurrence 1; retry limit 1.
- Parent `t_98995c44` is done.
- Exact clean candidate:
  `dfeef88e7d5d2167b4dbb19f07f6fb4c3cdb8c7c`.
- Branch: `codex/w5-custody-repair-review`.
- The adapter check and exact-scope preconditions passed, but the mandatory
  `gpt-5.6-sol:low` review was killed immediately with
  `command wait: signal: killed`.
- The explicitly authorized retry is consumed. There is no review or
  validation receipt, and `t_9084e720` must remain locked.
- Recovery requires a repaired governed Codex route or explicit authority for
  one new audited retry. If accepted, serialization must omit the empty
  `dfeef88` commit while preserving the equivalent `ffbd9d0` code tree.

### 4.4 Remaining todo inventory

| ID | Owner | Purpose | Unresolved predecessor(s) |
|---|---|---|---|
| `t_1dcf12b9` | `mnexecutor11` | W2 public-harness and traceability integration | `t_00f9b733` |
| `t_dc7d0cf3` | `mnexecutor05` | W4 neutral shared-harness integration | `t_1dcf12b9` |
| `t_3ef76c76` | `mnreviewer10` | W4 adapter/custody review | `t_dc7d0cf3` |
| `t_8f4c31bd` | `mnexecutor14` | BENCH-007 deterministic regression CI | `t_3ef76c76` |
| `t_9084e720` | `mnexecutor04` | Serialize accepted W5 custody protocol | `t_44ec0580` |
| `t_fb5bcbc3` | `mnreviewer02` | Validate serialized custody base | `t_9084e720` |
| `t_448b8a6c` | `mnexecutor03` | GroundedReader/Phase 12 integration | `t_fb5bcbc3` |
| `t_36ebac01` | `mnexecutor08` | Compact/server deployment wiring | `t_448b8a6c` |
| `t_3ecbb8da` | `mnexecutor09` | Synthetic QA and parity matrix | `t_448b8a6c`, `t_36ebac01` |
| `t_2d7832cb` | `mnexecutor45` | Answering-plane contract documentation | `t_448b8a6c`, `t_36ebac01`, `t_3ecbb8da` |
| `t_bda76b41` | `mnreviewer07` | W5 custody/correctness review | W5 implementation plus `t_2d7832cb` |
| `t_67049976` | `mnexecutor21` | W5 final candidate | W5 implementation/review chain |
| `t_9a8af328` | `mnexecutor45` | Reconcile execution handoff | `t_67049976` |
| `t_28937307` | `mnexecutor45` | Reconcile GitHub wiki | `t_9a8af328` |
| `t_a93fce34` | `mnexecutor17` | W4/portfolio code-union candidate | W2/W4 chain and `t_67049976` |
| `t_f9bdbd9f` | `mnexecutor15` | Final GSD/traceability reconciliation | W2, W4/W5 finals, wiki |
| `t_f759db7a` | `mnplanner01` | Materialize Phase 15/16 roadmap work | protected `t_e01da9e7` |
| `t_636f6c38` | `mnreviewer08` | Review W2 harness repair | `t_3cb547fc` |

### 4.5 Protected blocked cards

| ID | Gate | Required disposition |
|---|---|---|
| `t_eced0115` | W1/Phase 12 protected graph refresh and headline measurement | Keep blocked until ordinary portfolio work, runtime, custody, exact-scale development proof, hardware admission, and operator authority are complete. |
| `t_4c812510` | W5 protected QA, byte parity, physical 8-GiB acceptance | Keep blocked until W5 and portfolio finals, runtime readiness, exact artifacts/parity, admitted Windows/Linux AVX2 hosts, and process-tree memory proof exist. |
| `t_e01da9e7` | W4 BEAM-10M and independent-publication acceptance | Keep blocked until W4/W5/portfolio finals, exact dataset/model/judge/custody proof, independent reproduction, and operator publication approval exist. |

Never auto-promote these gates and never mutate their acceptance-only purpose.

## 5. Missing plan-backed cards to materialize after host recovery

The live board does not yet cover twelve explicit implementation/review slices
from the governing plans. After the host and RFX control plane are healthy,
recheck all live leases and use supported Hermes commands to materialize the
smallest nonredundant backlog below. Do not write directly to SQLite. Resolve
every external path and lock before creating an operational card.

### 5.1 Phase 12 — nine cards

| Card | Exact lease / scope | Parents and conflicts |
|---|---|---|
| **O1 — atomic Vault CA trust-file repair** | External exclusive lease on `${MNEMO_SECRETS_DIR}/vault-tls/ca.crt` plus an exact same-filesystem, hash-bound rollback path. No repository writes. | Requires merged R2a receipt, fresh TLS/Vault/topology preflight, and the exclusive shared lock. May overlap source-only work, never live capture/eval/runtime work. |
| **R2c — shared lock in protected QA runner** | `eval/datasets/v2/run_grounded_qa_v2.py`; `tests/test_grounded_qa_v2.py`. | Accepted R2a/R2b. Add R2c as a parent of `t_448b8a6c` because the test lease overlaps. |
| **R2d — shared lock in performance apply/rollback** | `infra/scripts/apply-perf-runtime.sh`; `infra/scripts/rollback-perf-runtime.sh`; `tests/test_perf_runtime_interlock.py`. | Accepted R2a/R2b. Lease-disjoint from current W2/W5 chains. |
| **R3a — managed cert-rotator LaunchAgent** | `infra/launchd/com.mnemosyne.mcp-client-cert-rotator.plist.in`; `infra/scripts/install-production-mcp-client-cert-rotator.sh`; `tests/test_production_mcp_client_cert_rotator_install.py`; `infra/prod/README.md`. | Accepted R1c/R2a/R2b. May run with source-only W2/W5 and R2c/R2d. |
| **R3b — rotation metrics and alerts** | `src/mnemosyne/ops_metrics.py`; `src/mnemosyne/cli.py`; `tests/test_ops_metrics.py`; `infra/docker-compose.prod.yml`; `infra/observability/vmalert/mnemosyne.yml`; `tests/test_prod_compose_policy.py`. | Accepted R1c/R2a/R2b. Add R3b as a parent of `t_36ebac01` because `infra/docker-compose.prod.yml` overlaps. |
| **RT0 — restore installed grounded runtime** | External targets `/opt/mnemosyne/bin/role-llm` and `/opt/mnemosyne/bin/role-ladder`; no repository lease. | Requires fresh strong model/runtime admission and an accepted clean head. If source edits become necessary, block and create a separate narrowly leased repair. |
| **R4 — live rotation and idempotent no-op proof** | No repository writes. Resolve exact plist/status/log/receipt paths from accepted R3a before creation. | O1, R2c, R2d, R3a, R3b, exact-head CI/reviews, and fresh three-sample admission. Exclusive shared lock; no parallel test/capture/protected/model/runtime/index work. |
| **C0 — freeze candidate-v19 external manifest/runtime custody** | Absolute, no-overwrite, non-symlink external manifest/runtime paths resolved before creation; no repository writes. | RT0 plus accepted O1/R2/R3/R4 source/live head. Run only when changing candidate code has stopped. |
| **C1 — digest-bound 24/24 `qa_scale_dev_v1` receipt** | Read-only repository inputs `eval/datasets/v2/run_grounded_qa_v2.py` and `eval/datasets/v2/qa_scale_dev_v1.json`; resolve exact external store/output/receipt paths. | C0 and strong runtime admission. Require 24 non-abstained traces, EM/F1 1.0, Recall@5 1.0, nDCG@5 1.0. Add C1 and R4 as parents of protected `t_eced0115`. |

### 5.2 Phase 14 — three cards

| Card | Exact lease / scope | Parents and convergence |
|---|---|---|
| **M2 — REPRO-001 clean-room receipt and fail-closed release overlay** | `eval/public/bundle.py`; new `eval/public/publication.py`; `tests/test_public_eval.py`; `tests/test_benchmark_publication_policy.py`; new `leaderboard/reports/repro-001-m2-readiness.md`. | Parent `t_3ef76c76`. Prove bundle-alone fresh/no-cache and offline reproduction, relative identities, production-evidence digest binding, and a no-overwrite M2 receipt. Keep all M3/publication flags false. May overlap `t_8f4c31bd` and W5. |
| **P0 — inactive M3/governance/publication packets** | New `docs/governance/INDEPENDENT-REPRODUCTION-PACKET.md`; new `docs/governance/PUBLICATION-DECISION-PACKET.md`; `docs/governance/README.md`; `tests/test_leaderboard_governance_policy.py`. | Parents `t_069e1913` and `t_76d33491` are done. It is immediately dependency-ready after materialization and lease-disjoint from W2/W5. Reuse existing governance artifacts and preserve inactive status. |
| **R0 — independent REPRO/PBPP review** | Read-only review; no write lease. | Parents M2, P0, and `t_8f4c31bd`. Feed accepted heads into `t_a93fce34`; preserve `t_e01da9e7` as the human/operator acceptance surface. |

Do not create Phase 15/16 cards here; `t_f759db7a` owns their later
materialization. Do not duplicate BENCH-007 or create another protected gate.

## 6. Fleet configuration state and required repair

### 6.1 Intended roster and model authority

Exactly 100 numbered personas exist:

- 15 planners;
- 45 executors;
- 30 reviewers;
- 10 captains.

The required authority for planner, executor, reviewer, captain, task stages,
fallback, delegation, and all 13 auxiliaries per profile is:

```text
provider/model: openai-codex/gpt-5.6-sol
reasoning_effort: low
```

Configured profiles are capacity, not activity. A stopped per-profile gateway
is normal when no live turn is assigned.

### 6.2 Known unapplied drift to repair at the source

The last complete pre-pause audit found:

- auxiliary `reasoning_effort` absent for all 1,300 numbered-profile auxiliary
  bindings and all 1,352 auxiliary bindings across 104 profiles;
- `mnexecutor45` has the correct documentation-steward description in
  `profile.yaml`, but the persona manifest/SOUL still assigns ordinary
  executor parity specialization.

At cutoff, direct inspection still showed:

- `/Users/admin/.config/rfx/personas/manifest.toml` defines ordinary executor
  specializations only;
- `/Users/admin/.hermes/profiles/mnexecutor45/profile.yaml` contains the
  documentation/repository steward description;
- `/Users/admin/.hermes/profiles/mnexecutor45/SOUL.md` still says
  `Specialization focus: parity`.

Repair generated-profile ownership at the RFX transform/generator or supported
manifest command, then rebuild/apply and run `rfx doctor`. Do not hand-edit all
generated profiles. Re-audit the complete 104-profile surface after repair.

The desired gateway `max_spawn` is 100. The pre-pause process had captured a
lower value; after reboot, verify the new gateway loaded 100 before dispatch.

## 7. RFX control-plane repair worktrees

The RFX repository state at cutoff:

- `/Users/admin/rfx` is on `main@190d769cf75e252b05462e76765eb335b1c6672d`,
  one intentional local commit ahead of `origin/main`;
- `origin/main = ee9324528799ea1c38b5fc174652f09f8f880a95`;
- do not use the locally ahead `main` as the synthesis base.

### 7.1 Python 3.11 launcher

- Worktree: `/Users/admin/rfx/.worktrees/python311-launcher`.
- Branch: `codex/rfx-python311-launcher`.
- Clean head: `7eb5590b2604bec0a79d6a198b6b2d903b8b2228`.
- Static review: accepted.
- Still required after reboot: focused installer tests, Bash 3.2, ShellCheck,
  smoke/process-group behavior, diff check, secret sweep, and independent
  exact-head review.

### 7.2 RalphEx heartbeat/process supervision

- Worktree:
  `/Users/admin/rfx/.worktrees/ralphex-kanban-heartbeat-supervision`.
- Branch: `codex/ralphex-kanban-heartbeat-supervision`.
- Base: `1da29c088c5e8ea55bf111bab8fdd97adadc3c6f`.
- Uncommitted scope:
  - `skills/ralphex-kanban-lane/scripts/ralphex-kanban-lane`;
  - `skills/rfx-lane/scripts/rfx-lane`.
- Diff: 1,174 insertions, 66 deletions.
- Static syntax/diff/parity and independent review were clean.
- Still required after reboot: watchdog, fork-parity, focused tests,
  ShellCheck, diff/secret/scope gates, commit, and independent exact-head
  review.

### 7.3 Semantic drift diagnostics

- Worktree:
  `/Users/admin/rfx/.worktrees/semantic-drift-diagnostics`.
- Branch: `codex/rfx-semantic-drift-diagnostics`.
- Base: `01ac475688b7bd29facf79ce155467e16c0ca81b`.
- Uncommitted scope:
  - `bin/rfx`;
  - `config/USAGE.md`;
  - `config/personas/generate.py`;
  - `tests/test_profile_drift.py`.
- Diff: 1,610 insertions, 101 deletions.
- Status: coherent but **REJECTED**. Do not commit, install, or apply it.
- Remaining blockers:
  - compact sequence-map YAML aliases evade anchor checks;
  - write-boundary symlink-parent TOCTOU;
  - restore/run/lane bypass the fleet transaction;
  - `sol`/`fable` and manifest-derived model-pin gaps;
  - missing explicit layer-C targets can report healthy;
  - duplicate-child healing can discard operator comments.
- After reboot, prefer the smallest fail-closed fix, including refusal on
  ambiguous YAML rather than a larger parser framework. Add focused tests,
  run the complete dynamic gate, and obtain independent exact-head review.

### 7.4 RFX synthesis

Only after all three worktrees are dynamically green and independently
accepted:

1. create a dedicated synthesis worktree from
   `origin/main@ee9324528799ea1c38b5fc174652f09f8f880a95`;
2. reconcile unique launcher, heartbeat, semantic, documentation, install,
   binary, and test hunks;
3. run the combined focused/full gates, diff check, secret sweep, and
   independent exact-head review;
4. deliver one feature branch/PR;
5. never force-push or merge a protected branch as part of the automated
   recovery.

## 8. Preserved Mnemosyne worktrees

Required preserved evidence:

| Task/surface | Head | Branch |
|---|---|---|
| `t_00f9b733` | `cc9de02d16d7` | `codex/hermes-w2-deletion-integration` |
| `t_3cb547fc` | `3eea1348fa28` | `mnemosyne/t_3cb547fc-repair-cert-rotator-harness-timeout-and` |
| `t_448b8a6c` | `1e4e6f01e493` | `codex/hermes-w5-grounded-integration` |
| `t_44ec0580` review | `dfeef88e7d5d` | `codex/w5-custody-repair-review` |
| `t_636f6c38` review | `7f261d4d0256` | `codex/w2-cert-rotator-repair-review` |
| `t_28937307` wiki | `064fd78b875b` | `codex/wiki-final-reconciliation` |

Before admitting `t_8f4c31bd`, `t_9084e720`, or `t_9a8af328`, replace their
recorded main-checkout workspace with a verified isolated task worktree. Never
let them write directly to `main`.

Do not bulk-prune worktrees:

- Git reported 41 registered Mnemosyne worktrees;
- 31 belong to tasks now marked done, but several remain inputs to unfinished
  synthesis or audit work;
- `w3-p2-p3-union` is the strongest likely stale candidate because it is clean,
  contained in `main`, and 121 commits behind;
- `t_ceccd108-rejected-4d7f0be` is rejected evidence and may have retention
  value;
- both W5 custody worktrees and the W2 cert-rotator review worktree are required;
- `gsd-fleet-state-reconcile` is clean, one commit ahead of `main`, and is not
  tied to a board card. Audit it before deciding its disposition.

Prune only after accepted-head ancestry/patch equivalence, synthesis
consumption, audit-retention needs, and branch/worktree ownership are proven.

## 9. Documentation, planning, indexes, GitHub, and delivery

The checked-in trackers are stale relative to the paused board:

- `.planning/STATE.md` still names `main@0784340` and was last updated
  `2026-07-20`;
- `docs/CODEX-HANDOFF-EXECUTION-PROMPT.md` still contains historical v19 and
  earlier-main receipts;
- this file records the pause/resume cutoff but must not become a competing
  roadmap.

Ownership remains serialized:

- `t_2d7832cb` / `mnexecutor45` exclusively owns
  `docs/ENGINE-CONTRACT.md` and `docs/ARCHITECTURE-OVERVIEW.md` after its four
  parents are done;
- `t_9a8af328` owns execution-handoff reconciliation after `t_67049976`;
- `t_28937307` owns GitHub wiki reconciliation after `t_9a8af328`;
- `t_f9bdbd9f` exclusively owns final `.planning/STATE.md`,
  `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, and
  `tests/test_planning_traceability.py` reconciliation after the portfolio
  finals.

Do not edit those surfaces early just to make the trackers look current.

CBM was ready for `/Users/admin/Mnemosyne` at cutoff with 19,381 nodes and
85,182 edges. Refresh CBM after accepted code lands. Run gbrain doctor before
sync, inspect unresolved warnings, and never acknowledge them blindly.

The local `main` and local `origin/main` refs matched at cutoff. No network
fetch, GitHub PR/CI read, push, or merge was performed while the host policy
fault remained active. After recovery:

1. fetch read-only remote state;
2. verify exact branch heads and PRs;
3. require exact-head CI for every delivered candidate;
4. perform a secret/risky-file sweep before staging;
5. never force-push or bypass hooks;
6. keep protected branch merge/release decisions with the authorized owner.

## 10. Safe resume procedure

Keep the pause sentinel present and dispatcher off until steps 1–7 pass.

1. **Recover the host.** Complete Section 3 and stop if any policy error remains.
2. **Verify the paused control plane.**

   ```bash
   rfx pause --status
   grep '^HERMES_KANBAN_DISPATCH_IN_GATEWAY=' /Users/admin/.hermes/.env
   ```

3. **Repair and validate RFX.** Use a known-good Python 3.11+ runtime, then run
   `rfx doctor` and `rfx current`. Heal only supported drift and re-run doctor.
4. **Re-audit the fleet.** Verify all 100 numbered personas, four roles,
   specializations, primary/fallback/delegation/stage bindings, all 13
   auxiliaries, Sol-low authority, and gateway `max_spawn=100`.
5. **Finish the three RFX repair worktrees.** Do not apply the rejected semantic
   patch until its blockers are fixed and independently accepted.
6. **Re-read the live board.** Check stats, triage/blocked/todo/ready/running,
   dependencies, diagnostics, recent runs/logs, exact leases, processes,
   heartbeats, diffs, and worktree heads. Recompute the DAG from live data.
7. **Materialize the twelve missing cards.** Recheck exact leases and external
   paths first. Use supported Hermes commands only; no direct database writes.
8. **Resolve manual recovery authority.**
   - W2: recover `t_3cb547fc`, independently review it, then use the audited
     `--from-triage` route for `t_00f9b733`.
   - W5: repair the governed review route or obtain explicit authority for one
     fresh audited retry of `t_44ec0580`.
9. **Resume through the supported command.** Use `rfx resume` only when the
   above gates are green. Verify the sentinel is removed, dispatcher is enabled
   deliberately, and the supervised gateway is healthy.
10. **Dispatch maximum safe substantive work.** Use non-force Hermes dispatch
    with `--max 100`, but admit only genuinely ready, dependency-safe,
    exact-lease-disjoint cards in isolated worktrees. Do not create work merely
    to fill capacity.
11. **Maintain convergence.** Preserve separate review and synthesis cards,
    serialize conflicting leases, and feed accepted heads to the named W4, W5,
    portfolio, documentation, wiki, and GSD owners.
12. **Close with fresh evidence.** Focused tests, full applicable gates,
    independent review, exact-head CI, protected-gate evidence, documentation,
    indexes, branch/worktree cleanup, and delivery status must all be current.

## 11. Non-negotiable safety and truth boundaries

- Never use `--force`, bypass a dependency, or direct-write board SQLite.
- Never create a second writer for a live or preserved lease.
- Never kill VMs, the gateway, Hermes, Claude, Bitdefender, or macOS policy
  services as a recovery shortcut.
- Never reset policy databases, disable security, force-push, discard dirty
  work, bypass hooks, or merge protected branches without the required owner.
- Never run protected QA, graph refresh, BEAM-10M, physical 8-GiB acceptance,
  independent reproduction, governance activation, or publication without the
  exact named gate and real evidence.
- Never present synthetic/development receipts as protected, production, or
  publishable evidence.
- Never claim all 100 personas are simultaneously working unless live
  processes, fresh task heartbeats, substantive diffs/review targets, and
  independent evidence prove it.
- Idle capacity must be attributed to dependency, lease, gate, or real process
  constraints. Newly unlocked disjoint work should be admitted promptly.
- Testing-only churn is not implementation. It must proceed into the planned
  production change and independent review.

## 12. First resume status report

The first post-reboot report should include:

- host uptime, policy-process/log health, file-descriptor counts, and signed
  executable receipt;
- RFX doctor/current result and every remediation;
- exact persona counts, binding parity, auxiliary effort parity, steward goal,
  gateway state, and `max_spawn`;
- board delta from this cutoff: done `94`, archived `11`, todo `18`,
  blocked `4`, triage `2`, ready `0`, running `0`;
- every live lane with task ID, owner, process, heartbeat age, exact lease,
  worktree/head, substantive diff or review target, tests, and reviewer;
- the reason for every idle persona;
- `t_3cb547fc`, `t_44ec0580`, `t_2d7832cb`, and protected-gate status;
- the twelve-card materialization result and new DAG width;
- local/main/origin/PR/CI state, RFX repair status, CBM/gbrain status, and any
  remaining blocker with its owner and next safe action.
