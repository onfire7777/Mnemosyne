---
type: milestone
title: Mnemosyne bounded M03 valid-time development delivery
date: '2026-07-30T00:00:00.000Z'
project: Mnemosyne
tags:
  - m03
  - mnemosyne
  - source-delivery
  - whole-memory
---

# Mnemosyne bounded M03 valid-time development delivery

Mnemosyne delivered the bounded M03 valid-time development slice to `main` through PR #83 on 2026-07-30. This is source delivery only: it does not establish full bitemporality, a measured benchmark result, publication eligibility, upstream comparability, independent reproduction, superiority, or production readiness.

## Source evidence

- PR: https://github.com/onfire7777/Mnemosyne/pull/83
- Reviewed source head: `3189cc24c570f12be06e3d04252a06f48c71f971`
- Normal merge commit: `7f60d8ba8274a8ac8036a80737467654f862008f`
- Exact-head CI: `30532543366`, all required jobs successful
- Exact-merge CI: `30534061552`, successful
- CodeRabbit and Greptile green; zero unresolved review threads
- Exact implementation lease: eight paths covering the frozen fixture, authorized write facade and CLI, CLI-only adapter/scorer, and focused tests
- Gitleaks diff/commit-range scans and `git diff --check` passed

## Delivered boundary

The public assertion and supersession paths accept optional timezone-aware `valid_from`, preserve authorization-first behavior, normalize UTC, and reject caller-owned `valid_from` inside nested replacement data plus all caller-owned `valid_to` and `transaction_time` fields. The development fixture freezes five timelines across five seeds, fresh-store replay agreement, valid-scope graph-as-of behavior, exact claim-custody flags, and a distinct pre-first-event boundary.

The cell remains `PROPOSED`, non-publishable, non-headline-eligible, non-independent, and non-upstream-comparable. Full transaction-time queries and full bitemporal M03 remain deferred.

## Next dependency

M15 canonical replay and the composed M01 to M03 to M10 development cassette are now the highest-value dependency-ready package. Result-v2 remains protected; sandbox enforcement remains quarantined; measured, hardware, official, custody, and publication work remain externally gated.

## Related

- [[Mnemosyne whole-memory common ABI delivery]]
- [[Mnemosyne — Execution Plan B: Benchmarking & the Leaderboard]]
- [[Memory-Native Benchmark (MNB)]]
