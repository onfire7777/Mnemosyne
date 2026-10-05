# First real-provider dependency attempt

Clean source `1fbaa7deaa5d04fb1adab35650646cf14193e214` attempted the full
100-case frozen dependency corpus with Qwen3 1.7B, schema-constrained output,
declared wire order, semantics-v2 prompt and a 12,288 context setting.
The runner stopped after one completed case. Four model responses are retained.
On turn two of the second case the model reused an existing keyed task ID with
no creation key. The public adapter rejected rebinding it. The exact error and
proposed write remain in the trace/stderr; no repair or retry was performed.

The completed case is not a success: its final stored state has zero matching
expected schedules, one extra and two missing schedules. Timing diagnostics
count one expected firing and one miss. State and firing are distinct checks.
`partial-diagnostics.json` retains that completed prefix, one incomplete case
and 98 not attempted. It has no full-corpus score or complete replay claim.

The guarded process ended in 18.652 monotonic seconds with normal sampled
pressure. Client-group sampled RSS reached 96,747,520 bytes, excluding the model
server. The ephemeral engine store was not under the measured disk root; disk
samples therefore do not represent total workload storage. Cleanup observed no
loaded models. `usage.json` retains provider-reported counters for all calls,
including the rejected proposal. No ranking or admission result is claimed.
