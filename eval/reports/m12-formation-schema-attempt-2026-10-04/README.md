# Schema-constrained small-model attempt

The full 220-case development corpus was attempted once, in its frozen order,
from clean source `dec911009a8312e375cf677b357563d724498143`, using Qwen3 0.6B
with the public-operation JSON Schema. This variant preserves the first
plain-JSON attempt separately. No response was repaired or replaced.

The attempt completed 21 cases, receiving 25 model responses, then failed on
its 26th HTTP attempt. The wrapper recorded `HTTPError` after `/api/chat`, but
that version did not retain the status or response body. The HTTP cause is
unknown; it must not be attributed to memory pressure or model quality without
more evidence. The newer wrapper retains bounded HTTP error details.

The completed prefix also exposes a real quality failure: the model issued no
task creates or updates. All 25 responses asked for clarification, including
when timing was supplied. Recomputed timing diagnostics for the 21 completed
cases contain 17 missed eligible occurrences, no successful firings and no
false-positive firings. These are descriptive counts for the completed prefix,
not a full-corpus accuracy estimate. The formation role never asked the memory
engine to schedule a task, so this is not a test of its scheduling accuracy.

The run lasted 195.715 monotonic seconds. All 161 pressure samples were normal.
Client process-group RSS excludes the separate Ollama server and is not a
resource-admission result. Cleanup confirmed no loaded models afterward.
UTC timestamps are retained as observed; use the monotonic duration for elapsed
run time. The capture is incomplete, unadmitted and not eligible for ranking.

`manifest.json` binds raw inputs, HTTP attempts, trace, monitor, cleanup and
`partial-diagnostics.json`. The partial report includes every completed case
in order, rather than selecting favorable cases. It does not claim complete
trace replay or independent execution custody. Recompute its state/timing
contents with `tests/test_action_formation_feasibility.py`.
