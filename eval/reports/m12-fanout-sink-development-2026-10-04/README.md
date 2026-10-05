# Bounded mixed-trigger fan-out with an inert sink

The full five-seed, four-virtual-week workload completed all 1,220 operations
from clean recorded source `c7a9d05aab7644b147ea9633fc096e40733564be` on this Mac,
using Python 3.14.7. Every recorded harness hash matched that commit. Development
continued elsewhere in the checkout after launch; the retained source receipt
records the launch state. No production-runtime identity is certified.

| Actions per explicit trigger type | Expected firings across five seeds | Observed true positives | False positives | Misses |
| --- | --- | --- | --- | --- |
| 2 | 50 | 50 | 0 | 0 |
| 4 | 100 | 100 | 0 | 0 |
| 8 | 200 | 200 | 0 | 0 |
| 16 | 400 | 400 | 0 | 0 |

All 150 unmatched-event decoys remained unfired. No duplicate firing or reported
due-time drift was observed. The sink retained 750 data-only receipts and 1,500
attempts: 750 accepted deliveries and 750 deliberately repeated harness deliveries
identified as duplicates. No external payload was executed.

The retained plan, raw operations, per-case/per-load reports and sink annex replay:

```sh
python -m eval.public.action_trigger_run eval/reports/m12-fanout-sink-development-2026-10-04 --recompute
```

The outer monitor exited successfully with return code zero and recorded
226.679 monotonic elapsed seconds. All retained pressure samples were normal
(value 1). This is not RSS/disk admission: that run did not enable the later
optional resource probes. UTC start/end stamps are retained separately and are
not used to calculate the monotonic elapsed interval.

Original artifacts and the SQLite database remain under
`/Users/admin/.local/state/mnemosyne/action-fanout-runs/2026-10-04-c7a9d05a`.
The database is 520,192 bytes, SHA-256
`fef7e2b87867f7c1c273e6f22e330ba1d1e914f50f8cc5e776da34479a7e2f89`.
That final file size is not peak workload disk usage. Annex replay validates
consistency, not independent authentication or reproduction.

This is DEVELOPMENT evidence, `publishable:false`. Bounded fan-out is not
saturation, capacity certification or the complete overloaded-trigger corpus.
Implicit formation, reference calibration, preregistered floors/margins,
resource/cost admission and full M12 acceptance remain open. No comparative
ranking or external-service exactly-once guarantee follows from this capture.
