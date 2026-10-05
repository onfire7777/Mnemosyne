# Paired JSON and schema decoding diagnostic

Clean source `c4a9d32a` evaluated the first turn of the first 11 frozen cases
with Qwen3 1.7B. Every input was sent once in JSON mode and once in schema mode,
with the same semantic-v2 instructions, declared wire order, 12,288 context
setting and generation settings. The plan was written before execution.
The exact executed script is archived as `run.py.txt`.

All 22 provider responses were retained. All 11 JSON-mode responses failed the
bridge envelope validation: eight combined nonempty clarification with writes,
and three had invalid top-level envelopes. All 11 schema-mode responses passed
envelope validation. No response was repaired and no task was executed.
The first JSON-mode response still replaced an event gate with an exact timer,
so removing schema constraints did not resolve that observed semantic failure.
This supports retaining constrained output for syntax, not claiming semantic
correctness or an overall benchmark win. These are development first-turn
observations, not held-out, complete-conversation or scheduling measurements.

The guarded process completed in 78.564 monotonic seconds with normal sampled
memory pressure. Client-group RSS peaked in samples at 78,266,368 bytes, excluding
the separate model server. Cleanup observed no loaded models. `usage.json`
includes provider-reported usage for all 22 calls, including the 11 rejected
outputs. It supplies no monetary-cost or resource-admission claim.
