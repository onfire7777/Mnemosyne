# Five-trigger workload with durable inert deliveries

The full standard four-week, five-seed workload completed all 525 operations
with the sink enabled, from clean harness source
`0a03fd7696138beed85ff8b127bd25fff5317bd6`, using Python 3.14.7 on this Mac.
Recorded harness hashes were checked against that exact Git commit.

All 130 eligible occurrences fired, with zero false positives or missed
eligible occurrences. The 70 cancelled, expired or never-matching occurrences
without observed eligibility remained unfired. The sink retained 130 durable
inert receipts and 260 attempts: 130 candidate deliveries and 130 deliberately
repeated harness deliveries. Every retry was identified as a duplicate.

The plan, complete operation log, reports and sink annex replay exactly:

```sh
python -m eval.public.action_trigger_run eval/reports/m12-trigger-sink-development-2026-10-04 --recompute
```

The original run and SQLite database remain under
`/Users/admin/.local/state/mnemosyne/action-integrated-runs/2026-10-04-0a03fd76/triggers`.
The database is 118,784 bytes with SHA-256
`9c957da494e17afc555ac3856b2f191d78224891c2f56d74d664f7230b7f11ec`.
The tracked annex supports replay without publishing the database. Its replay
validates consistency, not independent authentication of execution.

This is DEVELOPMENT evidence, `publishable:false`. Receipts represent data-only
records; no external payload was executed. It establishes neither an external
service's exactly-once guarantee nor full M12 admission. The separately defined
fan-out workload is not part of this capture. Full load/implicit-intent,
reference calibration, resource/cost and registration requirements remain open.
