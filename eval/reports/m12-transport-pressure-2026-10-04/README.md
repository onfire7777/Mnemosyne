# Paired public-transport pressure measurement

Development evidence only. Not admitted, publishable, or ranking eligible.

Clean source: `d59949edacaaaddc6ae6ae7313d4343a6d45873f`.
Sequential order on the same Mac: persistent MCP stdio, then CLI. Both use the
identical frozen v2 offered workload: five seeds, 320 live intentions (160 exact,
160 with 50 ms windows), and 40 pre-cancelled controls. Each seed drains for at
least 1.64 seconds. Commands are authenticated; deliveries go to an inert sink.

| Transport | Correct firings / live | Missed windows | False positives | Total with setup |
|---|---:|---:|---:|---:|
| Persistent MCP stdio | 320 / 320 | 0 | 0 | 12.374 s |
| CLI process per command | 200 / 320 | 120 | 0 | 78.113 s |

Both recovered all 160 exact-time intentions; neither duplicated firings or
fired cancelled controls. CLI pending exact-time work reached 8–9 per seed;
MCP reached 1. Both ran under normal sampled memory pressure. Maximum sampled
process-group RSS was 102,547,456 bytes (MCP) and 98,320,384 bytes (CLI).
These are sampled diagnostics, not verified peak memory or resource admission.

This supports a transport-dependent explanation for this short-window workload.
It does not isolate process startup as the only cause: caching, serialization,
and persistent process state also differ. Order was fixed, with no independent
repetitions; these observations are not a causal or statistical generalization.
The earlier v1 CLI failure remains retained separately and is not this paired
comparison's CLI baseline. V2 increases the evaluation safety ceiling for both
paths while preserving all offered intentions and deadlines.

This explicitly programmed trigger experiment does not test natural-language
intention formation, overall AI memory quality, native saturation, HTTP/BurnOS
latency, or superiority over another memory system. Neither native admission
limits nor the full M12 acceptance criteria are established. The 50 ms window
is a stress parameter, not a promised production service level.

## Reproduce the evidence summary

At the pinned source checkout, with its Python dependencies installed:

```sh
PYTHONPATH=. python /path/to/capture/reproduce.py.txt /path/to/capture
```

Compare the JSON to `comparison.json`. The script replays both saved traces,
checks identical offered plans and clean matching source, validates ordered
public requests/responses, timing consistency, scores and durable sink state,
and requires successful terminal monitor records. It does not rerun the
candidate or independently attest elapsed time. Both full replays passed before
capture. Raw artifact bytes are unchanged; `manifest.json` binds every file.
Absolute operator paths in monitor metadata describe the original run.
