# Saved M12 exact-time development execution

Executed locally on 2026-10-04 using committed harness source
`82311010d1eaed41520d335cff50a2b115fbea8b` with a clean working tree at capture.
This is a synthetic development diagnostic, not an admitted M12 benchmark,
official suite, resource certification or comparison against another system.
The source receipt records selected harness hashes; it explicitly does not
attest that the installed production runtime matches the full source tree.

All five seeded cases completed: **145 public adapter operations**, with 40
expected occurrences. The saved reports contain 30 firings: 8 on time and
22 late under deliberately injected polling delays. Ten cancelled occurrences
stayed unfired. There were no early, missed, pending, duplicate or unexpected
firings, and no reported due-date drift in this workload. No action payloads
or models ran. The adapter's synthetic operating-point values are development
controls, not measured precision/recall calibration.

The injected delays are 0, 60, 300 and 86,400 seconds in seeded order. The late
observations must remain in the evidence; they are not measurements of real
background-scheduler latency. Summed wall time for the 65 evaluation subprocess
calls was **9,968.554836988915 ms**; this excludes capture, scheduling and
cancellation commands and is not total run cost or a performance guarantee.
Money cost is unmeasured. No global quality score is derived from these counts.

## Files and replay

- `plan.json`: deterministic expected schedule and public operations, saved
  before execution. Gold expectations are never sent to the candidate.
- `operations.jsonl`: every completed public operation and its returned data.
- `reports.json`: per-case diagnostic reports, including all observed firings.
- `source.json`: source commit, dirty flag, Python version and harness hashes.
- `status.json`: completion state and operation count; publication remains false.

From the repository root:

```sh
uv run --locked python -m eval.public.action_timing_run \
  eval/reports/m12-exact-time-development-2026-10-04 --recompute
```

Both the original external capture and this byte-preserving copy were replayed
successfully. The CLI run and replay outputs were byte-identical. Replay
recalculates reports from observations; it is not a new system execution,
independent reproduction or cryptographic custody verification. A fresh run
must use a new output directory and may have different IDs and wall times.

Full trigger-family timing, a registered multiweek corpus, revision/idempotency
and independent sink evidence, calibrated baselines, cost/resource measurement,
admitted bundles and publication requirements remain open.
