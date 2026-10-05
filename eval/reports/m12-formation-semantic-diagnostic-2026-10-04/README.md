# Paired semantic-prompt diagnostic

At clean source `cccb4b24d1b40a078ff94240848a15889af4c7a0`, Qwen3 1.7B
processed the first turn of each of the first 11 frozen development cases under
both `contract-v1` and `semantics-v2`. The same public inputs, declared wire
order, JSON Schema, 12,288 context setting and generation options were used.
The plan and inputs were saved before the 22 calls. This is a development
prompt comparison, not a held-out evaluation or a complete conversation run.
The exact executed script is archived as `run.py.txt`.

All 22 calls returned valid bridge envelopes. Envelope validity is not semantic
correctness. Both profiles replaced the event gate in case 00 and condition gate
in case 05 with exact-time triggers. Both incorrectly created tasks for the
negative statement in case 03. The semantic variant formed the requested finite
weekly recurrence in case 02, where the original proposed wrong dates/actions,
but introduced an unrelated extra task in case 04. These mixed observations do
not establish an overall improvement. The original profile remains the default.
All raw responses, including additional failures, are retained in case order.
No response was repaired. No task was executed, no state/firing score is claimed,
and no result is eligible for ranking. This tests a model-plus-provider variant,
not the engine's ability to execute correctly formed schedules.

The guarded process completed in 80.544 monotonic seconds. Sampled client-group
RSS reached 76,070,912 bytes; this excludes the separate model server and is not
resource admission. Cleanup observed no loaded models. The manifest binds all
archived files; hashes do not independently attest execution.
