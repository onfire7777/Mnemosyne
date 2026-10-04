# M12 inert delivery sink: saved development execution

Executed from clean committed harness source
`d2af156aa81f2ecae7b2c025e03beb9885e65d34` on 2026-10-04.
This is the same five-seed exact-time development workload with the optional
data-only delivery sink enabled. It is not an admitted benchmark or a claim
about external side effects.

All 145 adapter operations completed. Thirty candidate firing observations
created **30 durable action records**. The harness deliberately retried each
delivery once: all 30 retries returned duplicate receipts without creating
additional records. The annex retains **60 attempts**, labelled by origin,
and no conflicting deliveries. Candidate duplicate observations would still
remain in the timing scorer; sink deduplication does not conceal them.

`plan.json`, `operations.jsonl`, `reports.json`, `source.json`, `status.json`
and `sink.json` are exact copies of the local capture. Both timing reports
and the sink annex recomputed successfully. The earlier capture without a
sink remains unchanged and still replays.

```sh
uv run --locked python -m eval.public.action_timing_run \
  eval/reports/m12-inert-sink-development-2026-10-04 --recompute
```

The original SQLite store remains local at
`/Users/admin/.local/state/mnemosyne/action-timing-runs/2026-10-04-d2af156a/sink.sqlite3`.
It is 40,960 bytes; SHA-256
`4f0199eff84c82aa88407f833fad208ee8166e6b4cfc00181dabbbe9188f9f3b`.
It is not needed for JSON observation replay and is not committed. Replay
rebuilds an independent temporary sink from the saved observations; it does
not authenticate the original SQLite database or certify physical power-loss
recovery. The source receipt also leaves production-runtime matching unverified.

Validation: 34 sink/runner/scorer tests passed in 13.63 seconds. After ensuring
snapshots read both tables in one transaction, all 12 sink tests passed again
in 0.20 seconds. Cases cover simultaneous delivery, reopen/retry, scope
separation, content conflicts, receipt/attempt rollback, inert payload text,
foreign-database protection, and older capture replay. Ruff passed.

Full M12 still requires the public schedule/update revision and idempotency
contract, registered full-trigger corpus, calibrated comparisons, cost/resource
evidence and admission. Nothing here changes official results or publication
eligibility.
