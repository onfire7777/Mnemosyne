---
phase: v1.0-00-foundations-and-contracts
plan: 0
status: complete
wave: 1
---

# Phase 0: Foundations and Contracts - Plan

## Tasks

- [x] Create Python package, typed models, stable IDs, content addressing, and policy rails.
- [x] Implement local engine persistence, append evidence, byte recall, deduplication, branch, merge, discard, and audit log.
- [x] Implement MCP-compatible tool facade and CLI.
- [x] Implement seed regression harness and tests for the foundation invariants.

## Verification

- [x] Run `python -m pytest`.
- [x] Confirm evidence deduplication and byte recall.
- [x] Confirm branch discard rollback.
- [x] Confirm seed suite passes.
