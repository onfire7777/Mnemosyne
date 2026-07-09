---
phase: 09-performance-and-refactoring-continuation
plan: 09-12
status: complete
completed: 2026-07-09
---

# 09-12 Summary: Native Wheel Install Smoke

The source-owned native wheel smoke slice is complete locally. The
`native-wheels` CI job now installs the wheel it just built and imports
`mnemosyne_native` before uploading the artifact.

What changed:

- Added Python 3.12 setup to `.github/workflows/ci.yml` for the native wheel
  matrix.
- Added a merge-gating smoke step that installs
  `rust/mnemosyne-native/dist/*.whl` with `--no-deps --force-reinstall`.
- The smoke step imports `mnemosyne_native`, checks `__version__`, and asserts
  `parity_marker() == "strict-ieee-scalar-v1"`.

Verification:

- Workflow YAML parses locally.
- A local `maturin build` wheel installs into a fresh venv and imports with the
  expected parity marker.
- Focused native packaging test passes.

Remaining gap:

This does not expand the release matrix, publish wheels, or prove production
runtime adoption. The broader wheel distribution/default-tier decision still
needs release evidence beyond the current macOS arm64 and Linux x86_64 CI lanes.
