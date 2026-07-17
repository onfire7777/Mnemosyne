# RalphEx Kanban Task Plan: t_663f4bef

Authority: `docs/superpowers/plans/2026-07-15-W5-compact-answering-plane-plan.md` requirements CAP-001/002/003 and CAP-011, Phase 1 parity harness, and Phase 4 cross-profile parity; `.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md` sections Immutable prerequisites, Quality and rail parity, and Claim boundary.

Allowed write set:
- `eval/compact_answering/__init__.py`
- `eval/compact_answering/manifest.py`
- `eval/compact_answering/parity.py`
- `eval/compact_answering/fixtures/synthetic-parity.json`
- `tests/test_compact_answering_parity.py`

Forbidden/shared files and actions:
- Every file outside the allowed write set, including shared eval harnesses, registries, Phase 12 files, reports, docs, planning state, service code, and dependency/lock files.
- Model downloads, network model access, protected data, physical 8 GiB runs, benchmark or compatibility claims, and provider fallback.

Acceptance criteria:
- A strict manifest schema binds code, artifact, configuration, and provider identities to SHA-256 digests and fails closed on missing, malformed, drifted, or unsupported identity.
- No-overwrite custody rejects attempts to replace an existing manifest.
- Parity compares exact decoded span bytes, answer type, ordered supporting facts, null margin, and abstention decision.
- Any parity mismatch or malformed row fails closed.
- A deterministic synthetic/dev fixture covers Unicode, repeated answers, null answers, window boundaries, multi-window reconstruction, and an explicit mismatch case.

Validation commands:
- `.venv/bin/python -m pytest -q tests/test_compact_answering_parity.py`
- `.venv/bin/ruff check --quiet eval/compact_answering tests/test_compact_answering_parity.py`
- `git diff --check`

### Task 1: Define strict custody manifest
- [x] Implement schema validation for exact identities and SHA-256 digests.
- [x] Implement no-overwrite manifest creation with fail-closed drift detection.
- [x] Add focused tests for missing, malformed, drifted, unsupported, and overwrite inputs.

### Task 2: Define byte-exact parity contract
- [ ] Implement strict parsing and comparison of decoded span bytes, answer type, ordered support facts, null margin, and abstention.
- [ ] Fail closed on malformed rows and every mismatched field.
- [ ] Add deterministic synthetic fixture cases for all required edge conditions and a mismatch case.

### Task 3: Validate and reconcile
- [ ] Run the focused pytest command.
- [ ] Run the focused Ruff command.
- [ ] Run `git diff --check` and confirm only the five leased files changed.
