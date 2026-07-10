---
phase: 09-performance-and-refactoring-continuation
plan: 09-11
status: complete
completed: 2026-07-09
---

# 09-11 Summary: Provider Bake-Off Evidence Harness

The source-owned provider bake-off evidence slice is complete locally. The repo
now has an executable harness at `eval/provider_bakeoff/run.py` that turns the
existing bake-off fixture and retained eval reports into a promotion-safe JSON
envelope.

What changed:

- Added `eval/provider_bakeoff/run.py`.
- The harness can read retained `provider-check` JSON or run
  `mneme provider-check --provider-manifest ...`.
- It verifies baseline/candidate JSON and Markdown report presence, records
  missing evidence, summarizes SLO/mandatory-class verdicts, compares common
  metrics, and flags candidate regressions.
- The local smoke fixture remains non-promotional: complete smoke evidence can
  be packaged for review, but cannot flip provider defaults.
- The provider bake-off README now documents the harness commands.

Verification:

- `uv run pytest eval/tests/test_provider_bakeoff.py -q` passed.
- `uv run ruff check eval/provider_bakeoff/run.py eval/tests/test_provider_bakeoff.py` passed.

Remaining gap:

This does not run TEI/Rust sidecar/Python production bake-off measurements and
does not select a provider default. Retained real bake-off output, run-to-run
noise notes, provider-check evidence, and any recalibration/ECE proof remain
required before a provider default or embedding-model identity decision.
