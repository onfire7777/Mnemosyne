# Four-week explicit-trigger development capture

Real public-CLI execution on 2026-10-04, Python 3.14.7, this Mac. This is a
DEVELOPMENT diagnostic; `publishable:false`. It is neither registered M12
acceptance nor an independent reproduction or a comparative memory ranking.

The five seeded dates each span four virtual weeks. All 525 planned operations
completed. Of 200 expected occurrences, 130 had observed eligible windows and
all 130 fired once: zero false positives, false negatives, duplicate firings or
reported due-date discrepancies. The 70 without eligible observed windows
(expired, never-matching or cancelled) remained unfired. These counts cover
structured exact-time, window, event, condition and dependency actions,
recurrence, negative signals, cancellation and identical creation retries.
No model inference was required. Recorded wall time is evaluation-command time,
not total workload cost or a production scheduler latency measurement.

`source.json` accurately records dirty development source based on
`6a25e446d646aa4d52f319e8a7cd6856aa336a9d`: the new runner had not yet been
committed when execution began. Its recorded harness file hashes were checked
against the retained source after completion. Do not represent this capture as
a clean-checkout run or as verified production-runtime identity.

Replay without invoking a model or memory system:

```sh
python -m eval.public.action_trigger_run eval/reports/m12-explicit-trigger-development-2026-10-04 --recompute
```

The replay checks every planned operation and its payload/clock, then regenerates
metrics from raw observations. It detects omissions and report drift, but does
not authenticate the logs. The original files also remain at
`/Users/admin/.local/state/mnemosyne/action-trigger-runs/2026-10-04-development-first`.

Remaining original M12 work includes overload, implicit intention formation,
registered mutation/recovery sequences, reference-system calibration and
resource/cost/admission gates. These remain open under the
[workload contract](../../../docs/plans/m12-trigger-window-development-2026-10-04.md).
