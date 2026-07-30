# M15 canonical replay review repair

## Authority and isolation

- Work only in `/Users/admin/Mnemosyne.codex-wmb-m15-canonical-replay`.
- Branch must remain `codex/wmb-m15-canonical-replay`.
- Base is `7f60d8ba8274a8ac8036a80737467654f862008f`.
- Starting candidate is `dc8023a302d4b6009adc247fe3db8ddc6283c971`.
- Exact product lease:
  - `eval/public/bundle.py`
  - `eval/public/adapters/whole_memory_reference.py`
  - `tests/test_public_eval.py`
  - `tests/test_public_whole_memory_reference.py`
- Do not edit GOAL, planning, docs, schemas, registries, fixtures, CLI, dependencies, result-v2, or sandbox code.
- Do not push, open a PR, merge, or run operator/hardware/protected evidence.

## Confirmed review finding

`canonical_replay_projection` validates manifest digests only as 64 hex
characters. It must also parse the closed `<suite>@sha256:<digest>` fixture
reference and require that digest to equal `manifests.fixture_manifest_sha256`.
The composed cassette must not label custody complete from truthiness alone.

### Task 1: Reproduce the custody mismatch

- [x] Add a focused negative test proving a fixture-reference/manifest-digest mismatch fails closed.
- [x] Run it to confirm the intended RED failure.

### Task 2: Bind the fixture reference to its manifest digest

- [x] Implement the minimum shared validation in `eval/public/bundle.py`, reusing existing parsing/validation patterns.
- [x] Strengthen composed `custody_complete` to depend on validated ref-bound custody, not merely nonempty strings.
- [x] Run only the narrow new/affected tests plus focused Ruff and `git diff --check`; do not rerun the full two-file suite.

### Task 3: Verify the repaired exact head

- [x] Verify the committed diff remains exactly inside the four leased product paths.
- [x] Commit the repair and report the exact SHA and retained deferrals.

Preserve all development-only/nonpublishable/nonheadline/nonindependent/
nonupstream labels. Do not claim exact executable-build provenance; `build`
currently records the system seam, not a code revision.
