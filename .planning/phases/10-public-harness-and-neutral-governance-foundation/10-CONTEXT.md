# Phase 10: Public Harness and Neutral Governance Foundation - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Mode:** Autonomous recommendations accepted

## Phase Boundary

Build Plan B M1.1's isolated public-CLI harness and the source-owned portion of
L0 governance. Prove bundle generation/reproduction with a redistributable
development smoke suite, but publish no benchmark number and claim no active
independent governance.

## Locked Decisions

- Reuse `eval.harness.cli_driver.MnemoCLI`; public evaluation may not import a
  Mnemosyne engine/retrieval implementation.
- Reuse existing Wilson/bootstrap metric primitives and stdlib custody code; add
  no dependency and no new console entry point.
- Add `mneme eval-public`, lazily importing `eval/public/` like `cmd_eval`.
- Registry pins require full commits, dataset SHA-256, license, split role, and
  metric family. Scoring never fetches or executes upstream code.
- The initial `smoke` suite is development/self-test only,
  `publishable=false`, `pbpp_headline_eligible=false`, and cannot satisfy M3.
- Bundles are atomically written beneath a new output root, reject links/path
  escape/secrets, bind trace/metric counts and hashes, and carry a complete
  inventory plus build/config/judge metadata.
- Child CLI environment is allowlisted; DSNs/tokens/ambient credentials never
  enter public artifacts.
- Deterministic retrieval and LLM-judged QA are different schema families and
  can never be aggregated into one score.
- Governance documents are operator-adopted drafts/readiness artifacts. L0 is
  not active until a named multi-institution board, including targeted benchmark
  academics, accepts, discloses conflicts, and ratifies the charter.
- Harness work may proceed while board activation is pending. Neutrality claims
  and Phase 16 launch fail closed.
- Mnemosyne's operator conflict is permanent and non-waivable: no extra runs,
  earlier held-out access, private tuning, or score-retraction rights.
- Every system is operator-run through one identical harness; vendor-submitted
  numbers are never accepted as final results.

## Verification

Red-first tests cover CLI-only execution, pin/digest/license enforcement,
private-suite isolation, metric-family separation, atomic bundle custody,
inventory/fingerprint mutation detection, path/link/secret rejection,
dirty-tree publishability, and fresh bundle-only reproduction. Governance tests
lock status, firewall, COI, appeals, change control, one-harness, and launch
blocking language without fabricating external activation.

## Deferred

- LongMemEval/HippoRAG adapters (Phase 11).
- Grounded reader/QA (Phase 12).
- Genuine third-party reproduction (Phase 14).
- Board seating, legal steward, durable multi-owner hosting, paper publication,
  and public launch (external/Phase 16 evidence).

