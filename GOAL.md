# Goal: Phase 16 L2 Signed Run Ledger

## Objective

Implement P16-L2-B, the next dependency-ready production-code package from the
approved benchmark/leaderboard track: an append-only, hash-chained,
Ed25519-signed run ledger with explicit recorded-absence and supersession
semantics.

P16-L2-A's public result contract is merged and post-merge `main` CI is green.
This package makes every attempted, omitted, or superseded evaluation visible
without publishing a score, running a protected benchmark, or claiming a
production, hardware, governance, or launch gate complete.

## Why This Package Is Ready

- `origin/main` contains the merged P16-L2-A result contract at `4e11a00e`, and
  its post-merge CI is green.
- The approved decomposition places P16-L2-B directly after P16-L2-A and before
  the static renderer; no other code package is on this dependency edge.
- The ledger operates only on synthetic records and local test keys. It does
  not depend on Phase 12's protected production evidence or Phase 15's physical
  8 GiB hardware proof.
- P14 reproduction remains gated by a headline-eligible retained result, and
  P13 adapters remain separately leased against pinned upstream inputs.
- No pull request or active writer owns this lease. The Worktrunk worktree
  `codex/phase16-run-ledger` is isolated from `main` and prior Phase 16 work.

## Controlling Sources

Read these before planning or editing. They are authoritative over this goal:

- `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`
- `.planning/OPS-HANDOFF-AND-OWNERSHIP.md`
- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- `.planning/REQUIREMENTS.md`
- `docs/CODEX-HANDOFF-EXECUTION-PROMPT.md`
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md`
- `docs/governance/BOARD-STATUS.md`
- `docs/governance/CHARTER.md`
- `docs/governance/CREDIBILITY-MODEL.md`
- `docs/governance/METHODOLOGY.md`
- `docs/governance/OPERATOR-FIREWALL.md`
- `docs/governance/APPEALS-AND-DISPUTES.md`
- `leaderboard/schema/result-v1.schema.json`
- `leaderboard/validate.py`
- `src/mnemosyne/audit_chain.py`
- `src/mnemosyne/evidence_signing.py`
- `src/mnemosyne/journal.py`

Traceability: Phase 16 L0.3 and requirement `LEAD-001` require every run,
including failed, aborted, and discarded runs, to be retained in an
append-only, hash-chained, Ed25519-signed ledger. Entries are never deleted;
corrections supersede an earlier entry with a stated reason. The operator
firewall additionally requires a `no_run` record with a reason for every
pre-registered entrant that was not run, closing silent omission. Register A
remains open until real evidence exists; passing synthetic tests changes no
governance status.

The approved package order remains:

1. **P16-L2-A (merged):** versioned result contract and validator.
2. **P16-L2-B (this goal, ready):** signed append-only run ledger,
   recorded-absence semantics, and deterministic verification.
3. **P16-L2-C (after B):** static renderer and per-question trace browser.
4. **P13-M1.4/M1.5:** MemoryAgentBench and BEAM adapters, separately leased.
5. **P13-M1.6:** scheduled regression-only CI after adapter inventory.
6. **P14-M2/M3:** one-command reproduction only after a headline-eligible
   retained result exists.
7. **P16-L3/L4:** content and launch only after the pipeline and Register A.

## Exact Lease

The implementation may modify only:

- `GOAL.md`
- `leaderboard/ledger.py`
- `tests/test_leaderboard_ledger.py`
- `docs/plans/2026-07-25-phase16-run-ledger.md`

The goal and round-plan files may update their own task/progress markers.
Do not modify the result schema or validator, product retrieval/storage/reader
code, benchmark adapters, governance status, `.planning` state, release,
deployment, or hardware files. If the package cannot be completed inside this
lease, stop and report the required boundary change.

## Operating Context

Use CBM/codebase-memory-mcp as the primary repository discovery layer: verify or
refresh its index before code reasoning and after meaningful code milestones,
then use architecture, graph search, traces, snippets, impact, and ADRs as
relevant. Use Gbrain as the durable project-knowledge layer and sync it after a
coherent committed or merged milestone without duplicating another memory
owner. Use context-mode for command, log, document, CI, and diagnostic captures.
Record an ADR only for a durable architectural decision.

Apply Ponytail to every implementation choice. Reuse the existing canonical
JSON, audit-chain, journal durability, result validation, and Ed25519 key
loading/signing patterns; add no dependency and no speculative abstraction.
Use the relevant Superpowers/GSD checkpoints: TDD for logic, systematic
debugging for failures, and verification/review before delivery.

Deliver through the isolated Worktrunk branch: inspect the complete diff and
secret/risky-file surface, run relevant checks, commit intentionally, push,
open or update a pull request, and monitor exact-head CI and review. Merge
normally only when every required gate is green and GitHub reports the pull
request mergeable. Never direct-push `main`, force-push, bypass hooks/checks, or
merge unresolved failures. Verify post-merge `main` CI before selecting the
next dependency-ready package.

## Loop Authority and Continuity

Run native RalphEx with `gpt-5.6-sol:low` for plan, task, review, and monitoring;
keep external review, Hermes, and legacy automation bindings off. Use no more
than 12 rounds. Continue autonomously through ordinary startup/configuration,
test, CI, review, branch synchronization, documentation drift, CBM/Gbrain,
stall, and rate-limit repairs. Stop only for a real safety gate, scope-changing
decision, or blocker that cannot be repaired inside the lease.

## Acceptance Criteria

1. `leaderboard.ledger` provides a deterministic JSONL ledger whose entries are
   canonical JSON and form one contiguous hash chain from a fixed genesis.
2. Every entry has an immutable identifier, sequence, UTC timestamp, run or
   roster identity, status, previous-entry digest, signer key fingerprint, and
   Ed25519 signature. Verification fails closed on malformed JSON, non-canonical
   data, gaps/reordering, duplicate identifiers, broken links, key mismatch, or
   invalid signatures.
   The wire form is one newline-terminated UTF-8 JSON object per entry, with
   lexicographically sorted keys, `,` and `:` separators, no insignificant
   whitespace, literal non-ASCII characters, and finite JSON numbers only.
   Timestamps use `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` with one to six optional
   fractional digits. A signer fingerprint is `sha256:` plus the lowercase hex
   SHA-256 of the raw Ed25519 public key. `entry_digest` is the SHA-256 of the
   canonical entry excluding `entry_digest` and `signature`; the base64 Ed25519
   signature covers the canonical entry including `entry_digest` but excluding
   `signature`. The signed head uses the same canonical encoding and excludes
   only its `signature`.
3. Run status supports `succeeded`, `failed`, `aborted`, and `discarded`.
   Successful entries must embed a record accepted by
   `leaderboard.validate.validate_record`; non-success entries must include a
   non-empty reason and must not masquerade as a publishable result.
4. `no_run` entries require a pre-registered entrant identity and a non-empty
   reason, making a rostered absence explicit without fabricating a run.
5. Corrections append a `superseded` entry naming an earlier entry and a
   non-empty reason. The earlier entry remains byte-for-byte present; nonexistent
   targets, self-targets, and repeated supersession are rejected.
6. Appending is durable and prefix-preserving: a successful append writes one
   newline-terminated entry, flushes and fsyncs it, and never rewrites accepted
   history. A torn final fragment is rejected or repaired only if it was never
   acknowledged, following the existing journal precedent.
   Under the sibling-process lock, append first fsyncs and atomically installs a
   pending intent containing the prior entry count, then appends and fsyncs the
   ledger and directory, then fsyncs and atomically installs the signed head,
   and finally removes the pending intent and fsyncs the directory. Recovery
   clears an intent when the signed head already acknowledges the complete
   append; otherwise it verifies the authenticated prior prefix, truncates only
   the unacknowledged suffix named by that intent, fsyncs the repaired file and
   directory, and clears the intent. Without an authentic pending intent,
   acknowledged or unterminated bytes are never truncated.
7. Tests use synthetic records and ephemeral local Ed25519 keys only. They prove
   accepted status/absence/supersession flows and tamper, deletion, reorder,
   duplicate, invalid-result, and signature failures without network,
   protected-environment, external-custody, benchmark, or hardware access.
   Deterministic sibling-process tests signal when append and verification
   attempt the shared lock while another process holds it; both operations must
   complete only after release, so verification cannot observe a mixed
   ledger/head snapshot.
8. No new dependency is added. Errors are stable and explicit enough for a
   deterministic nonzero CLI exit from `python -m leaderboard.ledger verify`.

## Non-Goals and Hard Gates

- Do not run Phase 12's protected environment or create production evidence.
- Do not run or simulate Phase 15's physical 8 GiB acceptance.
- Do not generate benchmark numbers, preregistrations, public results, external
  custody evidence, release bundles, or Register A completion evidence.
- Do not implement P16-L2-C rendering, Phase 13 adapters/CI, or Phase 14
  reproduction in this lease.
- Do not enable or use Hermes.

## Verification

```sh
uv run pytest -q tests/test_leaderboard_ledger.py
uv run ruff check leaderboard/ledger.py tests/test_leaderboard_ledger.py
git diff --check
```

## Completion Evidence

The goal is complete only when the focused tests pass, the worktree contains a
reviewed implementation commit inside the exact lease, and both native
`gpt-5.6-sol:low` review stages report no unresolved high-confidence finding.
Synthetic ledger checks are not evidence for any protected production,
hardware, publication, or governance gate.
