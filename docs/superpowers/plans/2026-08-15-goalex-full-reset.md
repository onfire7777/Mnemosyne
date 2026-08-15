# GoalEx Full Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the overlapping Mnemosyne GoalEx/RFX/Hermes machinery with one stopped, explicit, recoverable GoalEx path based on current `origin/main`.

**Architecture:** Preserve all removed state in one private reset archive, quiesce every bespoke launchd/process surface, reconcile the RFX source and installed projection, remove only Mnemosyne-owned Hermes fleet state, then create one fresh inert GoalEx worktree. Each repository and runtime surface is verified independently before the final closure audit.

**Tech Stack:** macOS `launchctl`, Git/GitHub CLI, Bash, Python standard library, RFX CLI, GoalEx, RalphEx, Hermes.

## Global Constraints

- Use Ponytail full: no new daemon, dependency, cleanup framework, or speculative abstraction.
- Archive path is `/Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z`; permissions are directory `0700`, files `0600` where applicable.
- Never edit or discard `/Users/admin/Mnemosyne` canonical dirty files.
- Never edit `/Users/admin/Mnemosyne/.worktrees/topology-contract-verifier` or its branch.
- Never force-push, rewrite history, expose credentials, or restore all four old LaunchAgents together.
- Preserve unrelated Hermes desktop, Siri bridge, reports dashboard, credentials, databases, profiles, and project state.
- Leave the final RFX/GoalEx runtime paused and stopped.

---

### Task 1: Capture a Recoverable Pre-Reset Archive

**Files:**
- Create: `/Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-reset-state.tar.gz`
- Create: `/Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.bundle`
- Create: `/Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.patch`
- Create: `/Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/RECEIPT.md`

**Interfaces:**
- Consumes: the four LaunchAgent plists, old GoalEx worktree, RFX dirty/config state, Mnemosyne-specific Hermes state, and relevant `/tmp` logs.
- Produces: one verified archive root used by every later destructive step and rollback.

- [ ] **Step 1: Re-prove exact targets and ownership**

Run read-only receipts for canonical Git state, old GoalEx worktree status, RFX status, launchd labels, process trees, and exact Hermes-owned paths. Abort if a target differs from the approved design.

- [ ] **Step 2: Create the private archive directory**

```bash
install -d -m 700 /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z
```

- [ ] **Step 3: Create branch recovery artifacts**

```bash
git -C /Users/admin/Mnemosyne bundle create /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.bundle codex/goalex-whole-memory-pilot
git -C /Users/admin/Mnemosyne format-patch --stdout origin/main..codex/goalex-whole-memory-pilot > /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.patch
chmod 600 /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.bundle /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.patch
```

- [ ] **Step 4: Archive exact runtime/config paths**

Stage explicit approved paths in a `mktemp -d` directory, preserve modes with `ditto`, create `goalex-reset-state.tar.gz`, then delete only the temporary staging directory. Include plists, `.goalex`, `.ralphex`, RFX dirty diff and installed presets/snapshot inventory, Mnemosyne Hermes profiles/board/script/backups, and matching `/tmp` logs.

- [ ] **Step 5: Verify recovery artifacts before cleanup**

```bash
git bundle verify /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.bundle
test -s /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.patch
tar -tzf /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-reset-state.tar.gz >/dev/null
shasum -a 256 /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-reset-state.tar.gz /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.bundle /Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/goalex-branch.patch
```

- [ ] **Step 6: Write the receipt**

Record exact hashes, pre-reset SHAs, statuses, process IDs, loaded jobs, preserved paths, and rollback commands in `RECEIPT.md` using `apply_patch`.

### Task 2: Quiesce and Remove Bespoke GoalEx Background Machinery

**Files:**
- Remove after archive: `/Users/admin/Library/LaunchAgents/com.openai.mnemosyne.goalex-fable-9697.plist`
- Remove after archive: `/Users/admin/Library/LaunchAgents/com.openai.mnemosyne.goalex-opus-9697.plist`
- Remove after archive: `/Users/admin/Library/LaunchAgents/com.openai.mnemosyne.goalex-watchdog-9697.plist`
- Remove after archive: `/Users/admin/Library/LaunchAgents/com.openai.mnemosyne.goalex-opus-monitor-9697.plist`

**Interfaces:**
- Consumes: verified archive from Task 1.
- Produces: no loaded or loadable Mnemosyne GoalEx job and no associated process.

- [ ] **Step 1: Bootstrap-out every exact label**

Use `launchctl bootout gui/$(id -u) <exact-plist>` for each of the four explicit plist paths. Treat an already-unloaded job as success only after `launchctl print` confirms absence.

- [ ] **Step 2: Wait for graceful termination and terminate only verified descendants if needed**

Poll the four labels and process commands for up to 30 seconds. Send `TERM` only to remaining processes whose full command references `/Users/admin/.codex/worktrees/9697/Mnemosyne/.goalex/bin/`; use `KILL` only if the same verified PID survives the grace period.

- [ ] **Step 3: Remove only the archived plist files**

Move the four exact plists to the user's Trash using `/usr/bin/trash` when available; otherwise move them into the reset archive. Do not touch `ai.hermes.gateway.plist`, the Siri bridge, or reports dashboard.

- [ ] **Step 4: Verify no relaunch occurs**

Check every label twice, at least one watchdog interval boundary apart where practical, and verify no process references the old worktree, `goalex-supervisor-*`, `goalex-watchdog`, or `goalex-monitor-opus`.

### Task 3: Reconcile the RFX Source and Installed Projection

**Files:**
- Modify: `/Users/admin/rfx/bin/rfx:249`
- Create: `/Users/admin/rfx/config/presets/solo-sol-low-goal.toml`
- Modify or create minimal test in: `/Users/admin/rfx/tests/test_profile_drift.py`
- Remove after archive from installed projection: `solo-fable-medium.toml`, `solo-opus-medium.toml`, `solo-sol-low-clean.toml`, `solo-sol-low-workspace.toml`

**Interfaces:**
- Consumes: existing one-line dirty fix and installed `solo-sol-low-goal` preset.
- Produces: a clean RFX source PR, canonical reviewed Codex solo preset, synchronized installation, healthy paused configuration.

- [ ] **Step 1: Move the existing dirty fix onto a delivery branch without discarding it**

```bash
git -C /Users/admin/rfx switch -c codex/rfx-goalex-reset-reconcile
```

- [ ] **Step 2: Add the canonical reviewed preset**

Create `/Users/admin/rfx/config/presets/solo-sol-low-goal.toml` with the exact validated content below; do not invent a second variant.

```toml
# Isolated all-Codex preset for the scoped Mnemosyne goal loop.
# No Hermes fleet; the preserved solo-opus preset remains unchanged.

[meta]
name = "solo-sol-low-goal"
description = "Direct RalphEx on GPT-5.6 Sol low for plan, task, and review; no fleet."

[executor]
kind = "codex"
external_review = "codex"

[models]
codex_reasoning_effort = "low"
codex_model = "gpt-5.6-sol"
plan = "gpt-5.6-sol:low"
task = "gpt-5.6-sol:low"
review = "gpt-5.6-sol:low"

[loop]
max_iterations = 12
wait = "1h"
skip_finalize = false

[kanban]
enabled = true
required_model = "gpt-5.6-sol:low"
use_codex_flag = true

[hermes]
enabled = false
```

- [ ] **Step 3: Add the smallest regression check**

Add this test to `ProfileDriftTests` in the existing standard-library `unittest` harness:

```python
def test_config_lines_preserve_wait_duration(self) -> None:
    rendered = RFX._config_lines({"loop": {"wait": "1h"}})
    self.assertEqual(rendered["wait_on_limit"], "1h")
```

- [ ] **Step 4: Run RFX gates**

```bash
python3 -m unittest tests.test_profile_drift
python3 tests/hermes_projection_audit.py
bash -n install.sh
python3 -m py_compile bin/rfx
git -C /Users/admin/rfx diff --check
```

- [ ] **Step 5: Commit, push, open a PR, and merge only the exact reviewed head**

Commit the one-line fix, preset, and test atomically. Push `codex/rfx-goalex-reset-reconcile`, open a PR against `main`, wait for required checks/review, merge only the exact head, and verify post-main state.

- [ ] **Step 6: Return the canonical RFX checkout to clean synchronized `main`**

Switch `/Users/admin/rfx` back to `main`, fast-forward from `origin/main`, verify the original dirty bytes equal the merged bytes, and confirm `git status --porcelain` is empty.

- [ ] **Step 7: Apply the canonical reviewed preset and synchronize installation**

Run the repository's supported install command, apply `solo-sol-low-goal`, preserve the pause sentinel, archive/remove the four installed-only presets listed above, and run `rfx current`, `rfx pause --status`, and `rfx doctor`.

- [ ] **Step 8: Compact RFX snapshots conservatively**

Keep the reset snapshot and newest valid pre-reset rollback snapshot. Move older snapshot directories into the verified reset archive rather than deleting them unrecoverably.

### Task 4: Remove Only Mnemosyne-Owned Hermes Fleet State

**Files:**
- Remove after archive: `/Users/admin/.hermes/profiles/mnemosyneintegrator`
- Remove after archive: `/Users/admin/.hermes/profiles/mnemosynecaptain`
- Remove after archive: `/Users/admin/.hermes/profiles/mnemosynereviewer`
- Remove after archive: `/Users/admin/.hermes/profiles/mnemosyneplanner`
- Remove after archive: `/Users/admin/.hermes/kanban/boards/mnemosyne`
- Remove after archive: `/Users/admin/.hermes/scripts/mnemosyne_ralphex_resource_requeue.py`
- Remove after archive: fourteen `/Users/admin/.hermes/backups/mnemosyne-*` files

**Interfaces:**
- Consumes: verified archive from Task 1 and paused RFX state from Task 3.
- Produces: no live Mnemosyne Hermes fleet surface while unrelated Hermes services/data remain unchanged.

- [ ] **Step 1: Prove Hermes is not dispatching the Mnemosyne loop**

Verify `ai.hermes.gateway` is unloaded, `HERMES_KANBAN_DISPATCH_IN_GATEWAY=0`, RFX fleet is disabled, and no Hermes process has an open file or command rooted in the exact Mnemosyne profile/board/script paths.

- [ ] **Step 2: Move exact Mnemosyne-owned paths out of live Hermes state**

Move the four profiles, board, requeue script, and fourteen named backup files into the reset archive's Hermes holding directory. Do not use a broad `mnemosyne*` recursive deletion.

- [ ] **Step 3: Verify unrelated Hermes state**

Recheck the Hermes desktop app, Siri bridge, reports dashboard, gateway plist/value, global databases, credential files, and non-Mnemosyne profiles. Compare paths and process identities with the pre-reset receipt.

### Task 5: Retire the Stale Controller and Create One Fresh Inert Worktree

**Files:**
- Remove after archive: `/Users/admin/.codex/worktrees/9697/Mnemosyne`
- Create: `/Users/admin/.codex/worktrees/goalex-reset/Mnemosyne`

**Interfaces:**
- Consumes: verified branch bundle/patch, quiesced jobs, and latest fetched `origin/main`.
- Produces: one clean stopped GoalEx worktree with no copied runtime state or background binding.

- [ ] **Step 1: Recheck the old worktree is clean and quiescent**

Verify no process has the old path as cwd/open file and `git status --porcelain` is empty.

- [ ] **Step 2: Remove the old worktree and stale local branch**

Use `git worktree remove /Users/admin/.codex/worktrees/9697/Mnemosyne`, verify the branch bundle again, then delete only `codex/goalex-whole-memory-pilot` locally.

- [ ] **Step 3: Fetch and create the fresh worktree**

```bash
git -C /Users/admin/Mnemosyne fetch --no-prune origin
git -C /Users/admin/Mnemosyne worktree add -b codex/goalex-reset-20260815 /Users/admin/.codex/worktrees/goalex-reset/Mnemosyne origin/main
```

- [ ] **Step 4: Verify inert GoalEx readiness**

Confirm the new worktree is clean, exactly at the fetched `origin/main`, contains `GOAL.md`, has no `.goalex` or `.ralphex` history, has no LaunchAgent/Hermes binding, and `bash -n /Users/admin/.local/bin/goalex` passes. Do not launch GoalEx while Claude/Fable access remains unavailable.

### Task 6: Final Requirement-by-Requirement Closure Audit

**Files:**
- Create: `/Users/admin/.config/rfx/resets/mnemosyne-goalex-20260815T164908Z/FINAL-RECEIPT.md`

**Interfaces:**
- Consumes: all task receipts and final live state.
- Produces: evidence that every approved reset requirement is achieved or a literal residual blocker.

- [ ] **Step 1: Verify all thirteen design gates**

Run exact launchctl, process, filesystem, Git/worktree, RFX, Hermes, executable, and canonical-dirt checks from the design spec. Record command, revision, exit, and result.

- [ ] **Step 2: Verify recovery**

Re-run tar listing, archive hashes, `git bundle verify`, and confirm the rollback instructions reference paths that exist.

- [ ] **Step 3: Verify no scope damage**

Compare canonical Mnemosyne dirty files, topology-verifier branch/worktree, unrelated Hermes services/data, and RFX remote/main identity against the pre-reset receipt.

- [ ] **Step 4: Write the final receipt and close only on complete evidence**

Write `FINAL-RECEIPT.md` with the final process/job counts, active preset/pause state, worktree SHAs, archive hashes, RFX PR/run IDs, preserved services, and any external provider limitation. Do not call the reset complete if any required gate is missing or indirect.
