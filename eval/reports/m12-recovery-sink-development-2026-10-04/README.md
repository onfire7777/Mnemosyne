# Recovery workload with durable inert deliveries

The five-seed, four-virtual-week recovery workload completed 360 public CLI
operations, 50 injected response losses and 50 adapter resets on Python 3.14.7.
All ten eligible revised actions fired. The ten cancelled occurrences remained
unfired. There were no observed false positives, misses, duplicate firings or
reported due-time drift. Ten inert receipts and twenty delivery attempts were
retained: ten accepted deliveries and ten deliberately repeated deliveries
identified as duplicates.

The source receipt identifies `0a03fd7696138beed85ff8b127bd25fff5317bd6` and
accurately records `source_dirty:true`: fan-out development was in progress in
the checkout. Every recorded recovery harness file hash was independently
checked against that commit and matched. This is not a clean-checkout claim,
a production-runtime identity claim, or independent reproduction.

Replay the exact ordered operations, report and sink annex:

```sh
python -m eval.public.action_recovery_run eval/reports/m12-recovery-sink-development-2026-10-04 --recompute
```

Original artifacts remain at
`/Users/admin/.local/state/mnemosyne/action-integrated-runs/2026-10-04-0a03fd76/recovery`.
The original SQLite database is 24,576 bytes, SHA-256
`ab19796100664dd372925e14ff8c0d3536b6cc9f9380242bc2d166482ade4a59`.
The tracked annex is replayable without publishing that database. Replay checks
consistency; it does not authenticate execution independently.

This is DEVELOPMENT evidence, `publishable:false`. Response losses follow
successful local CLI writes, not real network failures. Receipts are data-only;
no external action was executed. This does not establish external-service
exactly-once behavior, load saturation, implicit-intent coverage, reference
calibration, resource/cost admission or full M12 acceptance.
