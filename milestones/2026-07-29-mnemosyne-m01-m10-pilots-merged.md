---
type: milestone
title: Mnemosyne M01 and M10 development pilots merged
captured_at: '2026-07-30T02:07:58Z'
captured_via: mnemosyne-code
---

# Mnemosyne M01 and M10 development pilots merged

PR #81 merged normally from exact source head `8efa67377fc88d7aa1be15358a4b56edbb0a723a` to `main@2d07577653b88b8fb15943a704f42d9ee8820981`. The reviewed candidate lineage includes `81847c44f34d5dac31a3a369599255576fc527bd`. All required exact-head checks passed with zero unresolved current review threads, and exact-merge CI run `30506775012` completed successfully.

The focused M01/M10/public-eval/reference suite passed 507 tests and Ruff passed. Canonical `/Users/admin/Mnemosyne` was cleanly fast-forwarded to the merge head, which equals `origin/main`; CBM was refreshed once afterward. CBM 0.8.1 reports the project ready but does not expose a stored Git revision.

This is source delivery only. M01 remains `PILOT-READY-DEV` for Local, M10 remains `PILOT-READY-DEV` for the deterministic reader, and every development result remains `publishable:false` and `pbpp_headline_eligible:false`. No official, enhanced-successor, measured, PBPP, certification, publication, or headline claim advanced.

The next dependency-ready slice is the bounded M03 valid-time integration. Full transaction-time M03 remains deferred and was not implemented in this round.
