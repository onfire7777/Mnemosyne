# Task t_d7de6faa — W3 P2 A corrective pass

Authoritative plan: docs/superpowers/plans/2026-07-15-W3-taxonomy-completion-plan.md
Corrective contract: Kanban controller comment dated 2026-07-17 14:08.

Allowed write set:
- src/mnemosyne/engine.py
- tests/test_prospective_memory.py

Forbidden files:
- tests/test_shared_engine_contract.py
- src/mnemosyne/sqlite_engine.py
- src/mnemosyne/postgres_engine.py
- CLI/MCP files
- .planning/**
- docs/**

Validation commands:
- .venv/bin/python -m pytest -q tests/test_prospective_memory.py
- .venv/bin/ruff check --quiet src/mnemosyne/engine.py tests/test_prospective_memory.py
- git diff --check

### Task 1: Correct Local prospective-memory semantics
- [x] Sort each intention with its matched signal as one immutable result pair.
- [x] Make schedule, cancel, and evaluate atomic across in-memory state, audit, and persistence failures.
- [x] Enforce explicit single-writer ownership for engines sharing one store_path.
- [x] Reject missing dependency IDs at schedule time and prevent same-batch dependency cascades.
- [x] Make operating-point fields immutable exact finite floats and reject integers.
- [x] Apply one strict fail-closed rule for unknown trigger-context keys, including empty tenant validation.

### Task 2: Add corrective regression coverage
- [ ] Cover reversed-order mixed event/condition matches, injected persistence failures, shared store paths, missing dependencies, integer thresholds, empty tenant IDs, replay, and no-same-batch-cascade behavior.

### Task 3: Validate and hand off
- [ ] Run the focused pytest command.
- [ ] Run focused Ruff and git diff checks.
- [ ] Inspect the complete diff, commit only allowed files, and publish exact results for review.
