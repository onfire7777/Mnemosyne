---
phase: v1.0-02-belief-core-graph-and-confidence
plan: 2
status: complete
wave: 1
---

# Phase 2: Belief Core, Graph, and Confidence - Plan

## Tasks

- [x] Add deterministic local scaffolding for graph, confidence, security, lifecycle, and gates.
- [x] Add `Justification` and `Contradiction` models with dependency edges.
- [x] Implement ADD, UPDATE, SUPERSEDE, NOOP classification with AGM entrenchment.
- [x] Implement cascade invalidation through the justification DAG.
- [x] Implement conformal calibration updates and abstention thresholds by memory type.
- [x] Add multi-hypothesis result shape and contested-belief tests.
- [x] Add graph adapter benchmark harness.

## Verification

- [x] Current suite: `python -m pytest` returns `22 passed`.
- [x] New Phase 2 suite verifies contradiction conformance, cascade invalidation, calibration, and multi-hypothesis surfacing.
