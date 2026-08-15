# GoalEx Full Reset Design

## Objective

Return the Mnemosyne GoalEx/RFX/Hermes control plane to one clean, explicit, recoverable operating path. Remove overlapping auto-restart machinery, stale controller state, unsafe preset redundancy, and obsolete Mnemosyne-specific Hermes fleet material without losing historical evidence or modifying the canonical dirty checkout.

## Current failure

The old GoalEx worktree is controlled by four overlapping LaunchAgents:

- `com.openai.mnemosyne.goalex-fable-9697`
- `com.openai.mnemosyne.goalex-opus-9697`
- `com.openai.mnemosyne.goalex-watchdog-9697`
- `com.openai.mnemosyne.goalex-opus-monitor-9697`

The Opus supervisor uses `KeepAlive`, the watchdog runs every five minutes and can commit a dirty worktree automatically, and the monitor remains resident. The supervisor repeatedly invokes a Claude planner that cannot authenticate because organization subscription access is disabled. The result is a permanent retry/relaunch loop rather than useful execution.

The controller worktree is also stale, its upstream is gone, and it contains one branch-only receipt commit plus several megabytes of runtime history. RFX is separately paused on an unavailable Claude-only preset. Three Codex-only presets overlap, while two disable external review.

The RFX source repository is wired directly into the installed CLI and has one uncommitted functional fix in `bin/rfx`: it preserves the configured wait duration instead of collapsing it to boolean `true`. The installed `hermes-fleet` preset also has comment-only drift from source. This state is operationally healthy but not clean or reproducible.

Hermes fleet dispatch is already disabled (`HERMES_KANBAN_DISPATCH_IN_GATEWAY=0`) and its gateway LaunchAgent is unloaded. However, the live Hermes home still contains four Mnemosyne fleet profiles (about 381 MiB), a Mnemosyne kanban board (about 5.3 MiB), a resource-requeue script, and fourteen old Mnemosyne kanban backup files. The Hermes desktop app, Siri bridge, and reports dashboard are separate services and are not GoalEx/RFX workers.

## Approved approach

Use a recoverable full reset:

1. Capture a timestamped private archive containing:
   - all four LaunchAgent plists;
   - the old worktree's `.goalex` and `.ralphex` state;
   - the bespoke supervisor, watchdog, and monitor scripts;
   - relevant `/tmp` logs;
   - a Git bundle and patch for the stale GoalEx branch-only commit;
   - the RFX dirty patch, installed preset set, and snapshot inventory;
   - Mnemosyne-specific Hermes profiles, kanban board, requeue script, and kanban backups;
   - a top-level manifest with SHA-256 hashes for the bundle, patch, compressed state, and live receipts.
2. Bootstrap-out every Mnemosyne GoalEx LaunchAgent, then verify their complete process trees exit.
3. Remove the four plists from `~/Library/LaunchAgents` after the archive is verified so login cannot recreate the loop.
4. Remove the stale GoalEx worktree and delete only its local stale branch after confirming the bundle and patch are readable. Do not touch `origin/main`, canonical dirty files, the active topology-verifier worktree, or gbrain custody.
5. Normalize RFX:
   - keep `solo-sol-low-goal` as the single reviewed Codex-only solo preset;
   - archive and remove the four installed-only presets (`solo-fable-medium`, `solo-opus-medium`, `solo-sol-low-clean`, and `solo-sol-low-workspace`) because canonical RFX source is the installation authority and none of these projections exists there;
   - reconcile the existing one-line `bin/rfx` wait-duration fix through a clean branch, tests, PR, merge, and synchronized source checkout rather than discarding it;
   - resynchronize installed presets from the canonical RFX source so comment/config drift does not persist;
   - compact snapshot history only after preserving the reset snapshot and the newest valid rollback point;
   - apply `solo-sol-low-goal` as the active configuration;
   - leave RFX paused so reset does not silently launch work.
6. Normalize Hermes without disturbing unrelated services:
   - keep the global gateway unloaded and kanban dispatch disabled;
   - archive and remove only the Mnemosyne-specific profiles, board, requeue script, and historical kanban backups;
   - preserve the Hermes desktop application, Siri bridge, reports dashboard, credentials, global state database, non-Mnemosyne profiles, and other project data.
7. Create one fresh clean GoalEx worktree from the latest `origin/main`, with no LaunchAgent, watchdog, monitor, Hermes fleet binding, or copied runtime history. GoalEx is launched explicitly from that worktree only after its planner provider is usable.

## Authority and safety boundaries

- The user authorized a complete GoalEx reset and redundancy cleanup.
- All removal is recoverable from the private reset archive.
- No force-push, history rewrite, direct `main` write, or canonical dirty-file edit is allowed.
- The active topology-verifier owner keeps exclusive ownership of its worktree and branch.
- Claude credentials, subscription changes, API keys, and administrator actions are outside this reset. No secret is requested or written.
- The standard GoalEx contract remains Fable/Claude planning with Codex execution. The reset does not fake cross-provider health while Claude access is unavailable.
- RFX source changes are delivered in `/Users/admin/rfx`; Mnemosyne repository changes remain isolated in the reset worktree. The two repositories are not mixed into one commit or PR.
- Hermes cleanup is name- and ownership-scoped to Mnemosyne. The general Hermes installation and unrelated background applications are preserved.

## Fresh worktree contract

The new worktree must:

- start from the latest fetched `origin/main`;
- have a clean Git status and a new `codex/goalex-*` branch;
- contain a repository-owned `GOAL.md` whose runtime contract names the new worktree and branch;
- contain no copied `.goalex` or `.ralphex` runtime history;
- have no persistent launchd entry;
- have no Hermes kanban/fleet binding;
- remain stopped until an explicit launch request, successful provider preflight, and successful execution of the `GOAL.md` verification block.

## Verification

The reset is complete only when all of the following pass:

1. `launchctl print gui/$UID/<label>` fails for all four old labels.
2. No process command references the old GoalEx worktree, its supervisors, watchdog, monitor, GoalEx, or RalphEx descendants.
3. No matching plist remains in `~/Library/LaunchAgents`.
4. The archive manifest exists, hashes verify, the Git bundle verifies, and the branch patch is non-empty.
5. The old worktree is absent from `git worktree list`; its stale local branch is absent.
6. `rfx current`, `rfx pause --status`, and `rfx doctor` report the reviewed Codex-only preset, paused state, no drift, and healthy configuration.
7. The four installed-only presets are absent; the canonical source-backed presets remain valid.
8. `/Users/admin/rfx` is clean and synchronized; its one-line wait-duration fix has a passing test/PR receipt, and installed presets match canonical source.
9. The Hermes gateway remains unloaded, gateway dispatch remains `0`, and no Mnemosyne-specific Hermes profile, board, requeue script, or backup remains live outside the reset archive.
10. Unrelated Hermes desktop, Siri bridge, reports dashboard, credentials, databases, profiles, and project state remain unchanged.
11. The new GoalEx worktree is clean and exactly based on the latest `origin/main`; its reconciled `GOAL.md` runtime contract and executable verification pass before launch readiness is claimed.
12. `bash -n ~/.local/bin/goalex` passes and all required executables resolve to one authoritative path.
13. Canonical `/Users/admin/Mnemosyne` remains on the same branch with the same pre-existing dirty files; the topology-verifier worktree remains untouched.

## Rollback

Restore plists and scripts from the reset archive, bootstrap only the explicitly chosen job, restore the branch from the Git bundle, and recreate the worktree. Never restore all four LaunchAgents together.
