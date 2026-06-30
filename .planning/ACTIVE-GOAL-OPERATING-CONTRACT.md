# Mnemosyne Active Goal Operating Contract

**Status:** Active continuation contract for the long-running 1:1 blueprint-parity goal.
**Last updated:** 2026-06-30.

This file is the repo-owned execution contract for continuing the active Codex/GSD
goal after pauses, usage limits, or handoffs. It is deliberately stricter than a
chat recap: future agents should treat it as the prompt-engineered operating
objective for the live run, while still deferring to the blueprint and current
repo evidence when they conflict.

## Prime Objective

**Prompt-engineered goal statement:** Continue Mnemosyne from the live checked-out
state to exact blueprint parity and production release readiness. Prioritize the
remaining blockers that materially change the strict audit state: real Tier-B
operator production evidence, real production-path SLO/rail proof, and precise
stale-surface cleanup that prevents operators or future agents from following
obsolete instructions. Do not spend effort on redundant gates, duplicate tests,
or percentage bookkeeping unless they directly protect the production evidence
path. Every claim of progress must be backed by current source, retained
artifacts, CI, or an explicit operator-evidence record.

Drive Mnemosyne from the current source-complete state to exact blueprint parity
and production release readiness:

1. Preserve Tier A source reconciliation as closed.
2. Complete Tier B by capturing real operator production evidence for B1-B10
   without local stand-ins, fake providers, or validator weakening.
3. Complete Tier C by re-proving SLOs on real production paths, reconciling the
   parity matrix, and publishing the final 100% sign-off only after evidence and
   CI agree.

The goal is intentionally ongoing. Do not mark it complete because a checkpoint,
script, planning file, test suite, or CI run passed. Completion requires every
blueprint-required capability, audit row, evidence bundle, SLO, rail, release
artifact, and current-status document to be genuinely implemented, verified,
documented, and clean.

## Current Highest-Leverage Path

The next work is not more generic gates or percentage re-scoring. The
substantive path is operator-execution work against Tier B, with source edits
limited to defects that directly block that path:

1. Prepare an external Tier-B custody packet with
   `infra/scripts/prepare-production-evidence-custody.py`.
   Recompute row readiness after filling operator inputs with
   `infra/scripts/prepare-production-evidence-custody.py --refresh <packet>`.
2. Render production manifests through the packet's strict external
   `production-render.env`, and pass secret-bearing runtime/provider values
   through a separate external mode-`0600`
   `mnemosyne-production-runtime.env` via
   `render-production-soak-manifest.sh --runtime-env-file` for readiness and
   `capture-production-evidence.sh --env-file` for capture.
3. Capture full production bundles with
   `capture-production-evidence.sh --fingerprint-record-output <external-json>`
   so the expected offline custody fingerprint is retained outside the bundle
   under review.
4. Fill the shared provider stack first because
   `provider-manifest.production.json` unblocks B1, B2, B4, B6, B7, B9, and B10.
5. Capture keystone rows B1 retrieval and B2 tenant/auth evidence.
6. Capture the remaining row bundles B3-B9.
7. Capture B10 live parity evidence, then run Tier C sign-off.

## Resume Baseline Rules

Every continuation starts from live repository evidence, not from a remembered
commit, old run id, or copied chat recap:

1. Resolve the canonical checkout first. Current expected root is
   `/Users/admin/Mnemosyne`; treat `/Users/admin/Desktop/Mnemosyne` and
   `/Users/admin/Projects/Mnemosyne` as historical unless `git rev-parse`
   proves otherwise.
2. Run `git status --short --branch`, `git log -1 --oneline`, and the latest
   GitHub Actions status for the current `HEAD` before writing "current"
   status text.
3. If a prompt, roadmap, or state file names an older commit or run id as the
   latest verified baseline, either replace it with live-baseline wording or
   update it to the current commit only after CI is green.
4. Treat renderer/custody readiness output as routing metadata. It can make the
   operator pass runnable, but it does not move any strict-audit row from
   `Partial` to `Done`.
5. Keep the blended completion percentage stable until the controlling audit
   changes. Do not re-score progress to make local code changes look larger
   than they are.

## Execution Loop

For each substantive move:

1. Confirm the live checkout, branch, dirty tree, latest commit, and CI state.
2. Read the row runbook or blueprint section being changed before editing.
3. Prefer the smallest architecture-aligned change that closes a real parity,
   custody, operator-readiness, or evidence gap.
4. Verify with focused tests, custody checks, and CI when pushing source changes;
   avoid turning verification into the main workstream.
5. Stage explicit paths, commit atomically, push, and confirm local and GitHub
   state are synchronized.
6. Update only current-status docs that became stale because of the change.

Use subagents only for bounded independent review or clearly separable work. If
subagent orchestration becomes the bottleneck, continue locally on the critical
path and record the result.

## Non-Negotiables

- Never fabricate evidence. Mocked endpoints, local stand-ins, pseudo-embeddings,
  synthetic latency, self-signed production roots, or hollow `{ok: true}` bundles
  are failures.
- Never flip a strict audit row from `Partial` to `Done` without wrapper-captured
  production evidence, passing manifest-bound `release-audit`, and passing
  offline `production-evidence-verify` with an independently retained expected
  fingerprint from the external fingerprint record plus external
  `--report-output`.
- Keep Mnemosyne distinct from gbrain, mempalace, gstack, and BridgeMemory tool
  state. Do not import their repo-local metadata into Mnemosyne.
- Use `/Users/admin/Mnemosyne` as the canonical implementation checkout unless
  current live state proves otherwise. Treat `/Users/admin/Desktop/Mnemosyne` as
  stale or docs storage until verified as a Git checkout.
- Stage explicit paths only. Do not use `git add -A` or `git add .`.
- Remove generated byproducts before staging, including `__pycache__/`, `bin/`,
  `production-inputs/`, temporary evidence packets, and local output roots.
- Use tests to verify substantive work, not as a substitute for closing real
  Tier-B operator evidence gaps.
- Use CodeRabbit/Greptile only when available and bounded. If an external review
  hangs past the wait window or the tool is unavailable, report it honestly and
  continue with local/CI evidence instead of stalling.

## Known Downfalls To Avoid

1. **False completion:** Green local tests do not prove blueprint parity; Tier-B
   requires real production evidence.
2. **Stale baseline drift:** Refresh `git status`, `git log -1`, and GitHub CI
   before writing current-state docs.
3. **Wrong-root edits:** Confirm the active checkout before editing because this
   project has moved between Desktop, Projects, and home-directory paths.
4. **More gates instead of progress:** Do not add redundant release gates when
   the real blocker is missing operator artifacts or production infrastructure.
5. **Evidence fabrication risk:** Do not weaken validators or create fake bundles
   to make rows pass.
6. **Untracked implementation:** New scripts and docs must be included explicitly
   in the staged set.
7. **Subagent drag:** Use subagents for bounded, disjoint read-only or write-owned
   work; close them promptly and continue locally on the critical path.
8. **Historical text confusion:** Preserve historical lineage, but scrub current
   status surfaces that reopen already-closed local feature gaps.
9. **Manual custody drift:** Do not ask operators to hand-copy a bundle
   fingerprint when the wrapper can write an external no-overwrite fingerprint
   record for review.

## Completion Standard

The goal remains active until all of the following are true in current evidence:

- B1-B10 are `Done` in `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` with retained
  production evidence fingerprints.
- `render-production-soak-manifest.sh --check-environment` reports no missing
  render env, no missing provider env refs, no missing input artifacts, and all
  row readiness entries complete.
- Full production capture and offline custody verification pass.
- All six §16 SLOs and seven §31 rails are re-proven on real production paths.
- `BLUEPRINT-PARITY-MATRIX.md`, `.planning/STATE.md`, `docs/ROADMAP-TO-100.md`,
  and README status/badge agree with the current evidence.
- Local working tree and `origin/main` are synchronized and CI is green.
