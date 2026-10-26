# Whole-book integrity continuation

Recorded: 2026-10-26. Scope: the in-flight Mnemosyne book-import and framework work.

## Authority and routing

The current user request, as relayed by the active orchestrator, is to improve
Mnemosyne's whole-book processing, fix relevant bugs, validate the result, and
commit/push the completed changes to `main`. The user invoked Karpathy guidelines
and GSD autonomous. Mnemosyne remains independent; this continuation does not run
full benchmarks or provider inference.

This is a scoped GSD quick continuation, not a new Phase 15 plan. The historical
roadmap still describes the benchmark/Mnemetric milestone. Its Phase 15 source
delivery and official, provider, hardware, custody, and publication acceptance are
different claims. The quick work does not alter their counters or close their
gates. The orchestrator owns any scoped STATE/ROADMAP note.

GSD autonomous's normal roadmap discovery must not enqueue unrelated historical
work here. Resume the tasks in `PLAN.md`, record their evidence, then stop this
scoped run. Do not invoke phase transition, milestone completion, or cleanup for
the older milestone. No additional user approval is needed for the authorized
local fixes, focused tests, documentation, or normal push to `main`.

## Decisions

- **D-01 — Current scope:** Whole-book import, framework integrity, auditability,
  and truthful completion in Mnemosyne. No full benchmark runs, live provider
  inference, Mnemetric work, or unrelated roadmap execution.
- **D-02 — Surgical delivery:** Preserve others' edits; review and fix only this
  work, document verified behavior, then commit and push the explicit delivery
  files to `main`. Leave unrelated `work/*.json` files alone.
- **D-03 — Retain regression evidence:** Keep the 400-paragraph, 48,000-word
  synthetic regression `test_a_long_book_keeps_every_passage` in
  `tests/test_skill_frameworks.py`. It verifies retained passages and processing
  across parts, not exactly 400 semantic chapters. Use the separate chapter-range
  and TOC regressions to establish chapter accounting.
- **D-04 — Honest claims:** Complete source accounting is not proof of exhaustive
  semantic understanding. Incomplete or ungrounded conversions remain reviewable
  drafts; they must not displace a valid active revision.

These IDs normalize the active handoff's constraints for traceability; they are
not quotations from a new user discussion.

## Snapshot at plan creation

The following changes already existed in the shared working tree before this
continuation was written. This plan does not retroactively claim to have planned
their implementation or certify them complete:

- Source: `src/mnemosyne/frameworks.py`, `src/mnemosyne/skills.py`,
  `src/mnemosyne/cli.py`.
- Regressions: `tests/test_skill_frameworks.py`,
  `tests/test_book_framework_integrity.py`,
  `tests/test_book_import_integrity.py`, `tests/test_book_cli_wait.py`.
- Documentation: `docs/BURNSKILL.md`, `docs/whole-book-processing.md`.

The implementation owners were finishing merged-edge audit views and
case-preserving quote grounding. The orchestrator owns the final integration
review, test results, release evidence, commit, and push. Source completion is
in flight until those results are recorded against the delivered revision.

The orchestrator reported 659 passing CLI/parity/runtime checks using:

` .venv/bin/python -m pytest tests/test_book_cli_wait.py tests/test_cli_mcp_parity.py tests/test_cli_runtime_tools.py --tb=short --junitxml=/tmp/mnemosyne-book-cli-validation.xml `

The final four-file book suite was still running when this plan was created.
Do not convert either statement into an independent planner verification claim.

## Integration additions after planning

The final delivery also includes `tests/test_book_ask_integrity.py` for the
confirmed 40,000-character Q&A truncation bug, README usage updates, and
`work/hindsight-comparison/whole-book/` source-bound receipts. The final suite
contains all five book test files. These are scoped additions to the existing
work; the snapshot above remains historical.

## Acceptance criteria

| ID | Observable result | Required evidence |
|---|---|---|
| WB1 | A supported book retains its exact source bytes and page/spine inventory. EPUB TOC titles, order, nesting, resolved targets, and unresolved targets remain inspectable. Missing or unreadable source content cannot silently disappear. | Import integrity regressions and source/TOC status output contracts. |
| WB2 | All numbered source units and chapter ranges are accounted for, including short books and boundaries within one spine item. Nonempty substantive nodes establish representation; reference and duplicate decisions remain explicit. Failed chapters remain incomplete and visible. | Coverage, short-book, TOC, failure-retention, and retained 400-paragraph/48,000-word synthetic evidence, with separate chapter-range checks. |
| WB3 | Every substantive node requires source-grounded quotation evidence. Case changes and other invented or wrong-source text cannot pass mechanical grounding. Long quotes are retained with findings; unresolved graph, logic, or mechanical findings block approval. | Mechanical/quote regressions across substantive node types and combined approval checks. |
| WB4 | Joining chapters retains original node fields, quotations, citations, and relationship rationales. Bounded global audits account for every retained node and edge contribution or report incomplete review. | Node/edge join and bounded audit-view regressions, with contribution counts. |
| WB5 | Source windows, prompt context, chapter workers, mapping workers, and audit batches remain bounded; completed identical calls can be reused safely. Oversized or failed work preserves completed results and explains what remains. | Boundedness, concurrent cache, partial-failure, and large synthetic regressions. No live-provider performance claim. |
| WB6 | Import/activation recomputes substantive integrity rather than trusting supplied success flags. Invalid work stays a readable draft, preserves the prior active revision, and retries the correct unfinished source. CLI `--wait` reports a terminal outcome with nonzero failure status. | Forged-approval, defensive-copy, retry, active-revision preservation, and CLI regressions. |
| WB7 | Usage and limits agree with the final code: TOC versus inferred chapters, text-only extraction, coverage versus semantic completeness, contribution provenance, bounds/cache, wait/status, and safe retry. | Reviewed `docs/BURNSKILL.md` and `docs/whole-book-processing.md`; focused validation and final commit/push receipt. |

## Discovery and execution environment

Discovery level 0: validate established Python/pytest paths and the in-flight
implementation; no new dependency selection or package installation. No project
skill directory or local AGENTS.md was present during discovery. The supplied
AGENTS instructions still apply. GSD graph status reported no graph.

The initialized GSD runtime is
`node /Users/admin/.codex/gsd-core/bin/gsd-tools.cjs`. The resolver's unavailable
model identifier is not a reason to launch provider calls; the active supported
session model is used. Estimate calibration returned factor 1, zero samples,
confidence `low`.

The final book command uses the existing `.venv/bin/python` and adds the already
installed bundled Python site-packages directory for `pypdf` 6.10.0. Verify that
directory still exists before reuse. This is an existing runtime import path,
not authorization to install packages or change the environment.

## Source audit

| Source | Item | Disposition | Plan coverage |
|---|---|---|---|
| GOAL | Current whole-book integrity and delivery request | COVERED | Tasks 1–3, WB1–WB7 |
| GOAL | Historical Phase 15 benchmark/performance/custody goal | OUTSIDE THIS QUICK TASK | Remains open in its existing plans; no phase completion claim. |
| REQ | WB1–WB6 current behavior acceptance | COVERED | Task 1 |
| REQ | WB7 current documentation and delivery acceptance | COVERED | Tasks 2–3 |
| REQ | Historical CAP/BENCH/RAIL milestone acceptance | OUTSIDE THIS QUICK TASK | No reassignment or closure by this continuation. Existing security rails remain constraints. |
| RESEARCH | No quick-task RESEARCH.md exists; current code, test names, and draft documentation supply the implementation context | COVERED | Task 1 validates behavior; Task 2 reconciles the draft docs. No new integration is proposed. |
| CONTEXT | D-01, D-02, D-03, D-04 | COVERED | Task 1: D-01/03/04; Task 2: D-04; Task 3: D-01/02/04. |

## Deferred ideas

None introduced by this quick task. Historical official acceptance remains in
its original milestone scope; it is not silently deferred or declared complete.
