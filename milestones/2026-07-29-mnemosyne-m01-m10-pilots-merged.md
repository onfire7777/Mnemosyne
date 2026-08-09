---
type: milestone
title: Mnemosyne M01 and M10 development pilots merged
captured_at: '2026-07-30T02:07:58Z'
captured_via: mnemosyne-code
---

# Mnemosyne M01 and M10 development pilots merged

PR #81 merged normally from exact source head `98b83e4be373cf0acd5411769b80b98dfd1a8caa` to `main@392b1fc173f454893e1b133ff3a727462586a8b0`. The reviewed candidate lineage includes `c9e7884e4263cdeedeaf2fe5b30f9796226082b3`. All required exact-head checks passed with zero unresolved current review threads, and exact-merge CI run `30506775012` completed successfully.

The focused M01/M10/public-eval/reference suite passed 507 tests and Ruff passed. Canonical `/Users/admin/Mnemosyne` was cleanly fast-forwarded to the merge head, which equals `origin/main`; CBM was refreshed once afterward. CBM 0.8.1 reports the project ready but does not expose a stored Git revision.

This is source delivery only. M01 remains `PILOT-READY-DEV` for Local, M10 remains `PILOT-READY-DEV` for the deterministic reader, and every development result remains `publishable:false` and `pbpp_headline_eligible:false`. No official, enhanced-successor, measured, PBPP, certification, publication, or headline claim advanced.

The next dependency-ready slice is the bounded M03 valid-time integration. Full transaction-time M03 remains deferred and was not implemented in this round.
