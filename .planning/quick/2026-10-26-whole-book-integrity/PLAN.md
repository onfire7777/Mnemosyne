---
phase: quick-whole-book-integrity
plan: "01"
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/BURNSKILL.md
  - docs/whole-book-processing.md
  - .planning/quick/2026-10-26-whole-book-integrity/VERIFICATION.md
  - .planning/quick/2026-10-26-whole-book-integrity/SUMMARY.md
autonomous: true
requirements: [WB1, WB2, WB3, WB4, WB5, WB6, WB7]
estimate:
  tokens: 12000
  raw_tokens: 12000
  tasks: 3
  confidence: low
must_haves:
  truths:
    - Whole-book inventory, chapter coverage, quote grounding, and contribution retention have focused local regression evidence.
    - Unverified or incomplete imports stay reviewable and cannot replace a valid active revision.
    - Bounded processing and cached retries retain evidence of unfinished work without claiming semantic completeness.
    - Documentation matches the delivered source, and the explicit book-work commit is confirmed on origin/main.
  artifacts:
    - path: .planning/quick/2026-10-26-whole-book-integrity/VERIFICATION.md
      provides: WB1–WB7 evidence with commands, outcomes, regression locators, and remaining limitations
    - path: .planning/quick/2026-10-26-whole-book-integrity/SUMMARY.md
      provides: Actual delivery status and commit/push evidence
    - path: docs/whole-book-processing.md
      provides: Accurate import, inspect, retry, and completion guidance
  key_links:
    - from: tests/test_book_import_integrity.py
      to: src/mnemosyne/skills.py
      via: Source retention, TOC resolution, recomputed integrity, and safe activation regressions
    - from: tests/test_book_framework_integrity.py
      to: src/mnemosyne/frameworks.py
      via: Chapter coverage, grounded quotations, contribution-preserving joins, and bounded audits
    - from: tests/test_book_cli_wait.py
      to: src/mnemosyne/cli.py
      via: Terminal conversion status and exit behavior
---

<objective>
Complete the remaining validation, documentation reconciliation, and delivery of
the already in-flight whole-book changes, per D-01–D-04. This is a quick
continuation under the user's current scope, not retrospective implementation
planning and not full Phase 15 or milestone acceptance.

Purpose: make the book conversion's source accounting, failure behavior, and
delivery claims concrete and reviewable.
Output: focused evidence, accurate usage documentation, and the authorized
book-work commit pushed to main.
</objective>

<execution_context>
@/Users/admin/.codex/gsd-core/workflows/execute-plan.md
@/Users/admin/.codex/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/quick/2026-10-26-whole-book-integrity/CONTEXT.md
@docs/BURNSKILL.md
@docs/whole-book-processing.md
@tests/test_skill_frameworks.py
@tests/test_book_framework_integrity.py
@tests/test_book_import_integrity.py
@tests/test_book_cli_wait.py
</context>

All commands run from the repository root. Source and test edits listed in
CONTEXT already exist and are owned by the active implementation/integration
agents. Coordinate with those owners before any correction. This plan's file
ownership is the remaining documentation and evidence work. Do not overwrite
others' source changes or treat their current diff as a newly planned task.

The tasks are sequential because they consume the same final revision and
evidence. Task 1 needs the implementation owners' completed edits and creates
verification evidence. Task 2 needs Task 1 and creates accurate documentation.
Task 3 needs both and produces delivery evidence. No task has a human checkpoint;
the orchestrator already has authorization for normal commit/push to main.

<tasks>

<task type="tracer">
  <name>Task 1: Verify the existing import-to-activation path and its failure boundaries</name>
  <files>.planning/quick/2026-10-26-whole-book-integrity/VERIFICATION.md</files>
  <precondition>The active source/test owners have finished their book changes, the existing .venv/bin/python runs, and the existing bundled site-packages directory supplies pypdf without installation.</precondition>
  <action>Per D-01, D-03, and D-04, collect the orchestrator's final focused suite result against the completed source diff. The leading tracer is validation of the existing local path from imported book bytes through framework conversion, saved revision, integrity validation, and activation; it does not rebuild that path. Use the tests' deterministic model doubles and isolated stores. Account for all WB1–WB6 criteria, including small-book chapter mapping, publisher TOC failures, substantive quotes with preserved case, node and edge contribution audit views, bounded workers/cache, forged success flags, draft retention, correct-source retry, and CLI terminal outcomes. Retain evidence for tests/test_skill_frameworks.py::test_a_long_book_keeps_every_passage and label its size precisely as 400 paragraphs and 48,000 words; separate chapter-range and TOC regressions establish chapter accounting. Record command, result counts, skipped tests with reasons, revision/diff identity, and any unverified item in VERIFICATION.md. Reuse an already completed result for the identical final source; rerun only if source changed, the prior command failed, or an unresolved criterion requires it. If a real failure appears, return its reproducer to the owning implementation agent, then verify the correction before marking that criterion passed. No live model or benchmark execution is authorized.</action>
  <verify>
    <automated>.venv/bin/python -c 'import sys, pytest; sys.path.append("/Users/admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages"); raise SystemExit(pytest.main(["tests/test_skill_frameworks.py", "tests/test_book_framework_integrity.py", "tests/test_book_import_integrity.py", "tests/test_book_cli_wait.py", "tests/test_book_ask_integrity.py", "--tb=short", "--junitxml=/tmp/mnemosyne-book-final-validation.xml"]))'</automated>
  </verify>
  <done>WB1–WB6 have explicit passing or unresolved evidence against the final source. All required focused checks pass before delivery; the 400-paragraph synthetic regression and chapter-range checks have exact retained locators. No partial result is labeled whole-book semantic completeness.</done>
</task>

<task type="auto">
  <name>Task 2: Reconcile the book guides with verified behavior</name>
  <files>docs/BURNSKILL.md, docs/whole-book-processing.md, .planning/quick/2026-10-26-whole-book-integrity/VERIFICATION.md</files>
  <action>Per D-04 and WB7, review both in-flight guides against Task 1's final code and evidence. Correct stale descriptions of short-book mapping, case-sensitive grounding, source-duplicate equality, EPUB TOC provenance, joined edge contributions, and audit contribution counters. Explain source/page/spine/TOC distinctions, retained unresolved targets, text-only limits, source accounting versus semantic completeness, bounded work/cache, CLI wait/status, draft inspection, and retry of unfinished revisions. Keep examples aligned with parser/tool signatures. Record the doc review in VERIFICATION.md. Do not add performance, provider-quality, visual-completeness, or exhaustive-understanding claims absent evidence.</action>
  <verify>
    <automated>git diff --check HEAD -- docs/BURNSKILL.md docs/whole-book-processing.md .planning/quick/2026-10-26-whole-book-integrity</automated>
    <human-check>The orchestrator reviews each documented state, field, command, and bound against the final source and WB1–WB7 evidence. This is an agent documentation review, not a user approval gate.</human-check>
  </verify>
  <done>Both guides match delivered behavior, explain usable versus draft results, and preserve the distinction between source coverage and semantic understanding.</done>
</task>

<task type="auto">
  <name>Task 3: Review and deliver the exact authorized book-work change</name>
  <files>.planning/quick/2026-10-26-whole-book-integrity/SUMMARY.md, .planning/quick/2026-10-26-whole-book-integrity/VERIFICATION.md</files>
  <action>Per D-01, D-02, and D-04, have the orchestrator finish source/test/doc review and resolve relevant findings. Record accurate implemented, verified, and remaining states in SUMMARY.md. Use the explicit delivery set in CONTEXT.md plus this quick task's artifacts and any separately owned scoped STATE/ROADMAP notes; inspect staged paths and exclude unrelated work files. Confirm main is the active branch, inspect remote state, commit the reviewed changes, and perform a normal push to origin/main without force. Verify the resulting commit is present remotely. Preserve all old phase counters and official acceptance gates. If push fails, retain the local commit and report local delivery plus the actual push blocker; do not label the remote updated. Do not trigger old roadmap execution, milestone transition, or cleanup.</action>
  <verify>
    <automated>.venv/bin/python -c 'import subprocess as s; s.run(["git", "diff", "--check", "HEAD^", "HEAD"], check=True); assert s.check_output(["git", "branch", "--show-current"], text=True).strip() == "main"; local = s.check_output(["git", "rev-parse", "HEAD"], text=True).strip(); remote = s.check_output(["git", "ls-remote", "--heads", "origin", "main"], text=True).split(); assert remote == [local, "refs/heads/main"]'</automated>
  </verify>
  <done>The reviewed book-work commit is identified and confirmed on origin/main, or the exact local-only delivery state and blocker are reported. WB7 evidence and the final user report do not close historical Phase 15 acceptance.</done>
</task>

</tasks>

<threat_model>
## Trust boundaries

| Boundary | Required check |
|---|---|
| Untrusted EPUB/PDF or imported framework → retained source and active revision | Reject missing/unsafe source paths and recompute substantive integrity rather than trust supplied success flags. |
| Model-generated chapter/graph data → source coverage and approval | Check grounded quotations, range accounting, and all retained contributions; keep failures visible and inactive. |
| Concurrent work/cache → persisted draft and delivery evidence | Check bounded execution, atomic completed-cache reuse, prior-active preservation, and explicit staged paths. |

## STRIDE threat register

| Threat ID | Category | Component | Severity | Disposition | Mitigation plan |
|---|---|---|---|---|---|
| T-WB-01 | Tampering | Book source and imported framework | high | mitigate | Task 1 validates archive target restrictions, missing-content errors, forged approval rejection, and defensive copies. |
| T-WB-02 | Tampering | Joined framework and approval | high | mitigate | Task 1 checks case-preserving source quotes, retained node/edge contributions, bounded complete review, and inactive unresolved results. |
| T-WB-03 | Denial of service | Mapping, audit, and retry | medium | mitigate | Task 1 retains prompt/window/concurrency/cache bounds and failure-preservation evidence. |
| T-WB-04 | Repudiation | Completion and release claims | medium | mitigate | Tasks 1–3 retain exact regression locators, documented limits, and local/remote commit evidence. |
| T-WB-SC | Tampering | Package installation | high | mitigate | This continuation installs no packages and uses the existing verified runtime import path. |
</threat_model>

<verification>
The five-file book suite and the retained CLI/parity/runtime suite validate the
changed runtime behavior with deterministic local doubles. Review any skipped
PDF checks explicitly; the available pypdf runtime should allow those checks to
run. Keep raw JUnit results or summarize their exact path/counts in the durable
verification record. Final source changes invalidate affected earlier results.
Document review and staged-path review complement the executable checks; they
do not substitute for a failed behavioral check.
</verification>

<success_criteria>
WB1–WB7 have reviewed evidence; the final book-work source and docs are committed
and pushed to main; source accounting and incomplete-state limitations remain
clear; historical milestone and Phase 15 acceptance are unchanged.
</success_criteria>

<output>
The orchestrator creates VERIFICATION.md and SUMMARY.md in this quick-task
directory after collecting actual results. The planning agent creates neither
completion artifact and performs no commit or push.
</output>
