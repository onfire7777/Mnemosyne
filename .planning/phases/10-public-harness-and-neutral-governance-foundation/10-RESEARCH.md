# Phase 10 Research

## Existing Assets

- `eval/harness/cli_driver.py`: the required public subprocess seam.
- `eval/harness/metrics.py`: Wilson and deterministic bootstrap intervals.
- `eval/run_eval.py`: orchestration shape; its private datasets/results must not
  be imported into public suites.
- `src/mnemosyne/cli.py`: lazy `cmd_eval` pattern and mature bundle integrity
  helpers for containment, symlink rejection, SHA inventories, and fingerprints.
- `uv.lock` and `uv run --locked`: canonical reproducible environment.
- Completed PBPP policy and `tests/test_benchmark_publication_policy.py`.

## Missing Harness Contracts

No `eval/public/`, registry, adapter protocol, trace/bundle schema, exact pin or
license enforcement, public build fingerprint, metric-family discriminator,
bundle verifier/reproducer, or `eval-public` command exists.

## Primary Risks

- Mutable upstream references or digest drift.
- Test-split contamination and private-suite imports.
- Ambient environment/argv/trace secret leakage.
- Path traversal, links, partial/pre-existing bundles, and inventory TOCTOU.
- Trace/metric mismatch, NaN/inf intervals, duplicate question IDs, full-pool
  top-k theater, and retrieval/QA blending.
- Dirty builds or local smoke output being mistaken for publishable evidence.
- Governance documents falsely implying a board, neutral host, or paper exists.

## Minimal Architecture

`eval/public/registry.json`, `runner.py`, `bundle.py`, `adapters/smoke.py`, a
small redistributable fixture, CLI wiring, `tests/test_public_eval.py`, and
governance policy documents/tests. The bundle contains canonical manifest,
benchmark/config/build/judge/metrics JSON, per-question JSONL traces, README,
and a fixed reproduction command/script. M1.1/M2 agent reproduction is internal
evidence only; M3 remains external.

