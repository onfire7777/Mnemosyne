# Mnemosyne Active Goal Operating Contract

**Status:** Active continuation contract for the long-running 1:1 blueprint-parity goal.
**Last updated:** 2026-06-30.
**Goal-tool state:** Active as of the latest live resume check; there is no
repo-side pause to clear. This contract is the editable continuation objective.
**Unpause directive:** Continue from the verified live checkout without asking
whether to resume. Re-prove root, `HEAD`, dirty tree, and CI before making
current-state claims.

This file is the repo-owned execution contract for continuing the active Codex/GSD
goal after pauses, usage limits, or handoffs. It is deliberately stricter than a
chat recap: future agents should treat it as the prompt-engineered operating
objective for the live run, while still deferring to the blueprint and current
repo evidence when they conflict.

## Prompt-Engineered Goal

**Professionally revised active objective:** Continue Mnemosyne from the live
checked-out state to exact blueprint parity and production release readiness by
converting the source-complete local scaffold into production-attested evidence.
The decisive path is Tier-B production capture and custody: real deployed
services, real provider endpoints, real operator bundles, manifest-bound
`release-audit`, and offline `production-evidence-verify` with an independently
retained fingerprint record. Local tests, generated packet reports, and CI are
verification aids only; they are not substitutes for production evidence.

**Execution posture:** run autonomously from the verified live checkout, choose
the highest-leverage non-conflicting action, and commit/push clean atomic
changes when they materially improve the Tier-B capture path. Continue without
waiting for another "go" unless a blocker requires unavailable production
credentials, endpoints, or operator-owned artifacts.

**Current no-compromise goal text for future agents:**
Drive `/Users/admin/Mnemosyne` on `main` from the current source-complete state
to exact blueprint parity by removing only the blockers that keep the 10 Tier-B
strict-audit rows from real production capture, preserving every §16 SLO and
§31 rail, keeping cognitive-architecture/consciousness claims functional and
measured only, and refusing to mark completion until B1-B10 have retained
production evidence, the final release audit and offline custody review pass,
Tier-C real-path SLO/rail proof is recorded, status docs agree, CI is green, and
local/GitHub state are synchronized.

**Current objective refinement:** Treat this run as a production-evidence
completion program. The only prioritized change classes are:

1. A Tier-B capture/readiness blocker that prevents a real operator evidence
   pass.
2. A concrete source defect exposed by production readiness or capture evidence.
3. A custody, redaction, secret-handling, or reviewer-handoff weakness.
4. A current-status or stale-instruction cleanup that prevents wrong-root,
   false-completion, or manual-custody drift.
5. A generated operator handoff that measurably shortens the path from a blocked
   Tier-B readiness packet to a real capture without retaining secrets, values,
   or substitute evidence.

Everything else is deliberately lower priority, even if it is useful
engineering work.

**Explicit non-goals until production evidence exists:**

1. Do not add generic `*-ops-check` gates, release gates, scorecards, or broad
   tests unless a real Tier-B packet/capture run exposes a concrete missing
   validation contract.
2. Do not reopen Tier-A source-reconciliation work unless the live strict audit
   or a production capture failure proves a source defect.
3. Do not re-score blended completion, update the README badge, or write v1.0
   sign-off language from local readiness, generated reports, or CI alone.
4. Do not create placeholder JSON/PEM/bundle artifacts, fake provider values,
   local stand-ins, or "sample" production evidence to clear readiness checks.
5. Do not preserve historical path, commit, run-id, or percentage claims as
   current truth without refreshing the live checkout and GitHub Actions state.

**Move-the-needle rule:** before editing, state which live blocker the change
removes. A change is on-goal only if it makes a real Tier-B operator capture
more runnable/reviewable, fixes a source defect exposed by that capture path, or
cleans stale instructions that would otherwise send operators or future agents
to the wrong root, wrong artifact, wrong custody boundary, or false status.

**Resume improvement based on prior downfalls:** On every continuation, first
prove the live root and `HEAD`, then work only on items that remove friction from
real production capture or fix source behavior that blocks it. Treat planning
attachments, old agent transcripts, and percentage claims as hypotheses until
the live repo, generated custody packet, and strict audit agree. The next useful
unit of progress is a self-contained Tier-B operator packet and then a real
operator capture pass, not another local-only scoring layer.

**Live resume checkpoint discipline (2026-06-30):** the goal tracker reports
this objective as active and there is no repo-side pause to clear. Exact commit
SHAs and GitHub run IDs in historical checkpoints are not durable instructions:
future continuations must refresh `git status --short --branch`,
`git log -1 --oneline`, and GitHub Actions for the live `HEAD` before writing
current status or claiming sync.

**Pre-edit live verification for this continuation (refresh before reusing):**
`/Users/admin/Mnemosyne` is the canonical checkout; `/Users/admin/Desktop/Mnemosyne`
did not exist as a Git worktree during the resume check. Before later handoff
edits in this continuation, `main` and `origin/main` were cleanly synchronized at
`2b47989e27af9ec911eb08b43589979e1eb6c934`, and GitHub CI run `28475668973`
passed for that head. This proves only source/CI synchronization for that
checkpoint; later commits supersede it, and it does not prove Tier-B production
evidence.

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
2. Use the generated `reports/input-artifact-worklist.{json,md}` as the
   artifact-first operator checklist. It routes every required input artifact to
   packet paths, rows, row runbooks, and consuming checks without creating
   placeholders. Use `reports/input-artifact-contracts.{json,md}` to inspect
   each artifact's kind, consuming validators, release-audit output-key
   contract, advisory validator section/check hints, and minimum operator
   contract before supplying files. It is a contract/readiness aid only, not
   substitute evidence and not a schema sample.
   Use `reports/row-action-plan.{json,md}` as the row-owner
   handoff because it joins each B1-B10 row's runbook, missing render values,
   missing provider refs, missing artifacts, next actions, and row validator.
   Use `reports/render-env-action-plan.{json,md}` as the first blocker-class
   handoff because it maps every non-secret `production-render.env` placeholder
   to affected rows and the packet-local render env file without retaining
   values.
   Use `reports/provider-env-action-plan.{json,md}` as the shared-provider
   handoff because it maps every provider-manifest env ref to its manifest path,
   provider check, primary row ownership, and shared provider-check blast radius
   without retaining values or runtime env-file paths. The top-level
   `operator_input_inventory.runtime_env_file` also groups all and missing
   provider-manifest env refs by primary row, so the runtime env file can be
   filled from the same row-owner split without manual joins. The same top-level
   inventory groups missing non-secret render placeholders and missing input
   artifacts by affected row, while preserving global render placeholders
   explicitly. The generated row action plan separates global render blockers
   from row-scoped render blockers and is ordered `B1` through `B10`, so row
   owners do not miss shared operator metadata or chase lexicographic row order.
   Use the generated row action plan's
   `primary_missing_provider_manifest_env_refs` and
   `shared_missing_provider_manifest_env_refs` fields to assign row-owned
   provider env work without hiding shared blockers. B1 owns embedding/reranker
   refs, B2 owns OIDC/session-secret refs, B4 owns consolidation role-provider
   refs, B6 owns media refs, B7 owns object-key/residency refs, and B9 owns
   parametric refs.
   Use the generated
   `reports/input-artifact-validation-commands.sh` as a
   pre-capture check for all rows, or pass `B1` through `B10` to validate one
   row's required artifact set and manifest-derived validators. Missing
   worklist entries are work to capture from real production systems, not files
   to fake.
3. Render production manifests through the packet's strict external
   `production-render.env`, and pass secret-bearing runtime/provider values
   through a separate external mode-`0600`
   `mnemosyne-production-runtime.env` via
   `render-production-soak-manifest.sh --runtime-env-file` for readiness and
   `capture-production-evidence.sh --env-file` for capture. Do not rely on
   ambient shell exports as the operator handoff; the external runtime env file
   is the reviewable boundary.
4. Capture full production bundles with
   `capture-production-evidence.sh --env-file <runtime-env> --fingerprint-record-output <external-json>`
   so secret-bearing runtime/provider values stay in the strict external
   runtime env file and the expected offline custody fingerprint is retained
   outside the bundle under review.
5. Fill the shared provider stack first because
   `provider-manifest.production.json` unblocks B1, B2, B4, B6, B7, B9, and B10.
6. Capture keystone rows B1 retrieval and B2 tenant/auth evidence.
7. Capture the remaining row bundles B3-B9.
8. Capture B10 live parity evidence, then run Tier C sign-off.

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

## Source-Of-Truth Order

When instructions, summaries, or planning files disagree, resolve them in this
order before writing code or status text:

1. Live Git state and current CI for `/Users/admin/Mnemosyne`.
2. `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` for strict row status.
3. `infra/PRODUCTION-EVIDENCE.md`, `.planning/runbooks/`, and the actual
   `infra/scripts/*production*` behavior for Tier-B operator execution.
4. `docs/ROADMAP-TO-100.md` and `.planning/STATE.md` for human-readable status.
5. Historical chat recaps, old commit ids, and prior agent handoffs only as
   clues to verify, never as current truth.

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
10. **Ambient-env drift:** Do not let prompts or runbooks suggest omitting the
    capture `--env-file` because values are already exported by a supervisor.
    Future operators need one explicit external runtime env-file boundary for
    capture, refresh, review, and incident replay.

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
