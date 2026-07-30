---
type: milestone
title: Mnemosyne M12 M13 development evidence merged
date: '2026-07-30T00:00:00.000Z'
ingested_via: 'mcp:put_page'
ingested_at: '2026-07-30T07:42:44.945Z'
source_kind: 'mcp:put_page'
tags:
  - milestone
  - mnemosyne
  - whole-memory-benchmark
---

# Mnemosyne M12 M13 development evidence merged

PR #82 merged the bounded M12/M13 development-evidence confirmations without upgrading any benchmark or publication claim.

## Receipts

- PR: https://github.com/onfire7777/Mnemosyne/pull/82
- Final candidate: `a3ca8108c22de350810dc3f574931a0d85810ed5`
- Merge commit: `7e9cd01feb2a31cbba96252943697245a4edd024`
- Exact-head CI: https://github.com/onfire7777/Mnemosyne/actions/runs/30521721192
- Exact-merge CI: https://github.com/onfire7777/Mnemosyne/actions/runs/30522846090
- Focused receipt: 46 tests passed across `tests/test_public_pm_bench_triggerbench.py` and `tests/test_public_working_memory_action_probe.py`; focused Ruff and `git diff --check` passed.
- Canonical checkout: `/Users/admin/Mnemosyne` fast-forwarded cleanly so `main == origin/main == 7e9cd01f`, which contains `a3ca8108`.
- CBM: canonical repository refreshed once after merge.

## Evidence boundary

M12 and M13 remain `admission_state=PROPOSED` and `evidence_level=INTERNALLY_MEASURED`. The development suites remain `publishable:false`, `headline_eligible:false`, `independent_reproduction:false`, and `upstream_comparable:false`. No official run, measured pilot cell, recurrence work, promotion-policy work, certification, ranking, or superiority claim was produced.
