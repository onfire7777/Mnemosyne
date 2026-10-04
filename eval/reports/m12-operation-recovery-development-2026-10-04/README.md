# Public operation response-loss recovery

A real public-CLI development execution on this Mac, with Python 3.14.7,
completed all 360 operations across five seeded four-week timelines.

- 50 successful subprocess responses were deliberately withheld: creation,
  update and cancellation requests, followed by 50 adapter resets.
- Retried requests retained their original idempotency keys and exact revisions.
- All ten uncancelled actions fired once. All ten cancelled actions remained
  unfired. No false positives, misses, duplicates or due-date drift occurred.
- Inspections confirmed stable intention identity, revised action content and
  correct terminal state even after retrying the earlier update.

The executed source was clean commit
`1fddb7d7` (full ID in `source.json`). Every recorded harness-file hash was
checked against that Git commit. The stricter canonical-JSON replay validation
added afterward also reproduced the reports exactly. It did not change any
recorded input or output. Production runtime identity is still explicitly
unverified; clean harness source alone does not establish it.

```sh
python -m eval.public.action_recovery_run eval/reports/m12-operation-recovery-development-2026-10-04 --recompute
```

This is DEVELOPMENT evidence and `publishable:false`. Faults happen after a
successful subprocess exit, before the adapter receives its response. No memory
process was killed and no external action was executed. This run does not test
power loss, lost event delivery, or recovery of an external side effect. It does
not include the independent inert sink yet; absence of duplicate firing
observations is not proof of exactly-once external execution.

The first development attempt completed the same 360-operation plan and remains
at `/Users/admin/.local/state/mnemosyne/action-recovery-runs/2026-10-04-first`.
It began from dirty source and preceded the final identity checks; it is not
presented as this clean-source capture. The retained clean-source execution is
also at `/Users/admin/.local/state/mnemosyne/action-recovery-runs/2026-10-04-1fddb7d7`.

Remaining original M12 work includes one integrated full workload with every
firing sent to the idempotent sink, overload, implicit intention formation,
registered recovery/admission, calibrated exact-reference comparisons and full
resource/cost evidence. No acceptance threshold or publication gate was relaxed.
