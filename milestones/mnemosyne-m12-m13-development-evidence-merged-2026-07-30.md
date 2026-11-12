---
type: milestone
title: Mnemosyne M12 M13 development evidence merged
date: '2026-07-30T00:00:00.000Z'
tags:
  - milestone
  - mnemosyne
  - whole-memory-benchmark
---

# Mnemosyne M12 M13 development evidence merged

PR #82 merged the bounded M12/M13 development-evidence confirmations without upgrading any benchmark or publication claim.

## Receipts

- PR: https://github.com/onfire7777/Mnemosyne/pull/82
- Final candidate: `a85e364a9d7682e737bc99fef0e246f634f6c290`
- Merge commit: `3008f4a1089de4a9fb071621e99b273ec3d30ed2`
- Exact-head CI: https://github.com/onfire7777/Mnemosyne/actions/runs/30521721192
- Exact-merge CI: https://github.com/onfire7777/Mnemosyne/actions/runs/30522846090
- Focused receipt: 46 tests passed across `tests/test_public_pm_bench_triggerbench.py` and `tests/test_public_working_memory_action_probe.py`; focused Ruff and `git diff --check` passed.
- Canonical checkout: `/Users/admin/Mnemosyne` fast-forwarded cleanly so `main == origin/main == 3008f4a1`, which contains `a85e364a`.
- CBM: canonical repository refreshed once after merge.

## Evidence boundary

M12 and M13 remain `admission_state=PROPOSED` and `evidence_level=INTERNALLY_MEASURED`. The development suites remain `publishable:false`, `headline_eligible:false`, `independent_reproduction:false`, and `upstream_comparable:false`. No official run, measured pilot cell, recurrence work, promotion-policy work, certification, ranking, or superiority claim was produced.
