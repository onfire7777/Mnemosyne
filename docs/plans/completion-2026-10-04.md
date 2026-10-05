# Mnemosyne remaining-plan completion: first development slice

## Objective and authority

Owner request on 2026-10-04: continuously complete the remaining project plans
on a separate development branch, using Ponytail. Initial work used multiple
subagents; the owner's latest directive cancels them and scheduled work and
requires continued solo execution in this chat.
This slice starts at `3c21be5d` on `codex/development`.

The product remains the local-first memory compiler described in the blueprint.
Plan A governs capabilities; Plan B governs measurement and publication.
The whole-memory standard and reference-harness pilot plan govern the module
contracts. Existing code and merged receipts must be checked before treating
old roadmap statuses as unfinished source work.

This is a development successor to the completed Stage B module registrations
and pilot Task 7. It does not rewrite their historical scope, change fixtures,
grant benchmark admission, or claim measured acceptance. Publication flags,
tenant isolation, evidence custody, safety checks, and result-v1 behavior remain
binding. Operator-only data, infrastructure, governance, and publication gates
remain separate from source completion.

## Global constraints

- Work only on the isolated branch; preserve unrelated changes.
- Reuse existing CLI, scoring, registry, and bundle contracts.
- Preserve BurnOS compatibility: signed-session MCP/SDK calls, conversation-turn
  working memory, session-scoped search, lean/token-budget responses and profile
  lifecycle remain backward-compatible. Verify `test_session_aware_reads.py`
  and `test_mcp_validation_regressions.py` alongside relevant transport tests.
- Write a failing regression first for each behavior change, then implement the
  smallest correct fix and run relevant integration tests.
- Continue directly in this chat without subagents or scheduled work. Preserve
  completed agent work, integrate it, run the full suite and explicitly
  self-review the final changes before merging.
- Keep a per-task evidence and rulings ledger in
  `.superpowers/sdd/completion-2026-10-04/progress.md`.
- No historical cleanup/reset plan execution or publication. The owner subsequently
  authorized tested/reviewed merges to main and requires local/GitHub sync with
  only main and codex/development; preserve existing work during consolidation.

## Task 1: Verify and reproduce existing M02/M04/M06 development bundles

Consumes: existing registry cells, immutable fixtures, CLI adapters, and scoring
profiles for the three already registered modules.

Produces: their emitted bundles pass the same custody checks and exact replay
contract as supported sibling modules; changed metrics/traces are rejected.

Files: `eval/public/bundle.py`, tightly scoped M02/M04 adapter corrections in
`eval/public/adapters/whole_memory_reference.py` if proven necessary, focused
bundle regression tests, the obsolete M06 rejection test, and matching README
limitation paragraphs. Registry, fixtures and scorer semantics are unchanged.

1. Run a real development suite through bundle generation, verification, and
   reproduction. Observe the unsupported-profile/label/trace failure.
2. Reuse registered scoring profiles and immutable fixture validation; preserve
   distinct permutation/arm/cycle identities in trace custody.
3. Test rejection of modified metrics, traces and required seed custody.
4. Run the affected tests, then integration and full-suite verification.

Expected: real CLI bundle round trips succeed, tampering fails closed, old
supported profile behavior is preserved, and all publication flags remain false.

## Task 2: Forward explicit recurrence through the public action CLI

Consumes: pilot Task 7's documented recurrence transport gap and the existing
product `intention-schedule`/`intention-update` recurrence policy contract.

Produces: optional explicit recurrence policies reach the public CLI from the
action adapter, with backward-compatible behavior when absent.

Files: `eval/public/action_cli.py` and focused public action tests. Alter the
PM/TriggerBench adapter only if its closed fixture and scoring contract support
the change; otherwise keep that future experiment separate.

1. Write a real CLI test showing the missing schedule/update forwarding.
2. Forward the optional explicit policy using existing JSON argument handling.
3. Verify repeated firing, early evaluation, duplicate-tick suppression,
   max-occurrence stopping, and invalid-policy rejection.
4. Run action/public integration tests and disclose remaining fixture and
   calibrated-baseline gaps without changing benchmark admission state.

Expected: recurrence transport works through the production CLI; the existing
category-only fixtures and historical scored results are not reinterpreted.

## Task 3: Bounded M16 backend and transport development conformance

Execute `docs/plans/wmb-m16-backend-transport-parity-implementation-plan.md`:
compare local and SQLite backends through public CLI and MCP stdio, with five
fresh-store repetitions per cell, a literal oracle, bounded subprocesses, and
fail-closed canonicalization. Record raw evidence and explicit unexecuted
Postgres, HTTP, migration and resource-measurement requirements. This delivers
a partial development harness, not full M16 acceptance or benchmark admission.

## Task 4: Reconcile current plans and roadmaps

Update all current roadmap entrypoints and affected plan statuses against
source and merged receipts. Preserve dated historical evidence. Distinguish
implemented source from live, calibrated, official and production acceptance.
Keep paired Plan A/Plan B PDFs synchronized with their Markdown sources.

## Task 5: Integration, independent review, and synchronization

Run focused tests and `uv run --locked python -m pytest`, inspecting every
failure. Record environmental skips explicitly. Check formatting/lint for the
changed Python files. Inspect the whole branch in a separate self-review pass
against the contracts above, fix important findings with a failing regression, and
commit the verified slice. Reconcile the existing remote development history,
merge the reviewed and verified work to main, then synchronize the Desktop
checkout and GitHub. Keep only main and codex/development; preserve existing
work before removing merged branches. Keep the goal and ledger active for
remaining work.

During integration, investigate concrete dependency alerts. The observed
distribution-name collision is recorded in
`docs/coordination/2026-10-04-distribution-name-collision.md`; fix the CLI's
ambiguous package-index installation hint using a failing regression, and
retain the separate package-identity prerequisite for any future public release.

## Remaining program after this slice

- Owner priority, reaffirmed on 2026-10-04: execute
  `docs/plans/benchmark-proof-delivery-2026-10-04.md` for the visible evidence
  website, real reproducible runs and fair comparisons before expanding more
  development-only benchmark modules. The historical results do not prove
  current performance or superiority.
- M12 multi-week seeded recurrence experiment, lateness magnitude, calibrated
  baseline; M13 multi-capacity and explicit promotion-control experiment.
- Resolve and freeze missing module contracts before implementing them; extend
  partial M16 coverage against its explicit remaining gates. M19 remains deferred.
- Obtain genuine operator/protected/official/reproduction/hardware evidence
  where required. No source patch can substitute for those receipts.

## Review focus

Check trace identity collisions across arms/permutations/cycles, score and
fixture custody, deterministic reproduction without trusting bundle-provided
executables, non-fabricated model answers, recurrence policy validation and
exactly-once/max-occurrence behavior, unchanged absent-policy behavior, and
honest claim boundaries in documentation. For M16, check canonical projections
do not conceal semantic drift, oracle checks are independent of cross-cell
agreement, resource bounds terminate subprocesses, evidence excludes credentials,
and excluded surfaces cannot silently become passing results.
