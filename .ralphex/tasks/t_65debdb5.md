# W5 I1 — embedder ABI and synthetic selection lane

Authority: W5 embedder contract (t_f52202e5 comment 96), accepted Rust skeleton (t_99a280e2), parity harness (t_663f4bef), provider seam (t_f7154b65), and coordination parent (t_af5f8554).

Allowed write set:
- services/answering-ort/src/embed.rs
- eval/compact_answering/embedder_dev.py
- eval/compact_answering/fixtures/embedder-selection-dev.json
- tests/test_compact_answering_embedder.py

Forbidden/shared files:
- All other repository files, including services/answering-ort/src/lib.rs, Cargo manifests/lockfiles, protocol/runtime/component siblings, eval parity/provider files, deployment, docs, planning/GSD state, protected or held-out data.
- No model fetch/export/quantization/training, heavy or protected execution, spend, deployment change, push, merge, quality winner, or 8-GiB claim.

### Task 1: Implement the versioned embedder ABI
- [x] Add strict fail-closed Rust embed request/response types and validation in the leased module.
- [x] Enforce artifact, tokenizer, preprocessing, and model-space identities plus finite/nonzero vector checks.
- [x] Provide native 768 and zero-padded 1024 cosine/ranking parity behavior with deterministic tie breaks.

### Task 2: Add synthetic TRAIN-only selection contract
- [ ] Add source-owned synthetic fixture and Python validator/selection helpers.
- [ ] Validate immutable bakeoff receipts, identity custody, dimensions, cosine/ranking parity, and deterministic selection without real model artifacts.
- [ ] Add focused malformed, mismatch, non-finite, zero-vector, tie, and receipt immutability tests.

Validation commands:
- ~/.agents/skills/ralphex-kanban-lane/scripts/ralphex-kanban-lane --plan ".ralphex/tasks/${HERMES_KANBAN_TASK}.md" --lease-path services/answering-ort/src/embed.rs --lease-path eval/compact_answering/embedder_dev.py --lease-path eval/compact_answering/fixtures/embedder-selection-dev.json --lease-path tests/test_compact_answering_embedder.py --check
- ~/.agents/skills/ralphex-kanban-lane/scripts/ralphex-kanban-lane --plan ".ralphex/tasks/${HERMES_KANBAN_TASK}.md" --lease-path services/answering-ort/src/embed.rs --lease-path eval/compact_answering/embedder_dev.py --lease-path eval/compact_answering/fixtures/embedder-selection-dev.json --lease-path tests/test_compact_answering_embedder.py --mode full
- pytest -q tests/test_compact_answering_embedder.py
- ruff check eval/compact_answering/embedder_dev.py tests/test_compact_answering_embedder.py
- cargo fmt --check --manifest-path services/answering-ort/Cargo.toml
- cargo test --manifest-path services/answering-ort/Cargo.toml
- cargo clippy --manifest-path services/answering-ort/Cargo.toml --all-targets -- -D warnings
- git diff --check
- git status --short
