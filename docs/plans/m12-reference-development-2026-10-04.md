# Candidate explicit-action reference semantics

Status: DEVELOPMENT implementation, not the frozen/admitted exact reference
baseline required for M12 ranking. No floor or non-inferiority margin is chosen.

`eval/public/action_reference.py` interprets only public request payloads. It
imports no product engine, generator or scorer, and takes no gold-label argument.
One object represents one isolated case. It emits semantic firing observations;
it does not invent evaluation wall time, resource use, receipts or a system score.

Current supported requests are explicit task creation, identical keyed creation
retry, cancellation, forward-only injected clocks, transient event/condition
input and observation. Exact-time, half-open window, event-match, equality
condition and all-dependencies-completed triggers are implemented. JSON equality
preserves bool/number distinctions. Dependencies must already exist, so creation
cannot introduce a cycle. Each observation sees dependency completions from
before that tick, not iteration-order-dependent same-tick completions.

Exact-time interval recurrence supports a bounded occurrence count. An observation
fires at most one occurrence per task, retaining the original due time; later ticks
can consume remaining overdue occurrences. Cancellation is terminal and identical
creation retries cannot resurrect it. This policy must be reviewed against the
full benchmark contract before calling the reference exact or admitted.

Signals are consumed at each observation, including unmatched or future-dated
signals, matching the current public adapter's transient input boundary. Future
signals cannot fire early. A new input is needed after consumption. Windows end
exclusively. Late exact-time observations preserve lateness rather than rewriting
the due time. Unknown commands/fields and unsupported trigger/recurrence variants
fail explicitly. No unimplemented operation is silently called successful.

Tests use hand-written boundary cases for late firing, recurrence, cancellation,
retry conflict, window expiry, dependency ordering, strict matching, consumed
signals and backward clocks. They also feed only the operation portions of the
existing full five-trigger and fan-out generators: resulting totals are 130 and
750 respectively. This checks development consistency, not independence of the
benchmark design or successful execution by a real memory system.

## Remaining work before reference comparisons

- Review/freeze timing policies, including missed recurrence, simultaneous
  dependencies, all condition operators and update semantics against the full
  public contract; expand hand-computed golden vectors and negative cases.
- Implement revision-keyed update/cancel acknowledgements and recoverable durable
  reference state; the current in-memory object is not recovery certification.
- Define implicit-intent and actual overload fixtures without replacing inputs
  with expected schedules or tailoring the benchmark to this implementation.
- Integrate the reference with the same sink and retained raw-operation protocol,
  measuring actual execution/resources separately from semantic output.
- Validate per-occurrence outcomes and exact replay, then calibrate on disjoint
  data and preregister absolute floors/margins before any candidate ranking.

Existing official protocols, registered fixture bytes, production APIs and
BurnOS behavior are unchanged.

## Per-occurrence validation

The reference tests now compare every emitted action/occurrence key, trigger
type, original due time and first eligible observation against the separately
declared windows in both full development workloads. They reject unexpected,
missing and duplicate keys; aggregate totals alone no longer support this check.
Gold remains solely in the test assertion path, never an interpreter input.

A hand-written maximum-timestamp case exposed an unnecessary date advance after
the final recurrent occurrence. The interpreter now advances only if another
occurrence remains, so a completed schedule cannot overflow while constructing
an unused next due time. This correction changes no product engine code.

## Retained reference execution

`python -m eval.public.action_reference_run OUTPUT` runs the complete explicit
five-trigger workload; add `--fanout` for the full bounded fan-out workload.
Both always deliver every firing to the same durable inert sink implementation,
with a deliberate retry, in a separately identified reference session.

The runner retains the versioned plan, exact ordered requests/responses, source
receipt, reports, sink annex and status. Its report uses a distinct
`m12-draft-reference-report/v1` schema and reference identity, with
`baseline_admitted:false` and `publishable:false`. It cannot be presented as a
Mnemosyne candidate result. Runtime failure retains completed operation records
and a failed status containing the exception type, never its potentially
sensitive text. Existing output directories are never overwritten.

`--recompute` first validates the exact workload and observations, independently
re-executes the request stream to check every semantic response, then checks the
saved report, completion count and reconstructed sink annex. The replay compares
semantic output; it preserves recorded runtime measurements rather than claiming
to regenerate them. Source hashes are descriptive provenance, not signatures or
independent authentication. The interpreter still receives only request payloads.

Evaluation time is measured with `perf_counter` around the in-process interpreter
call. It excludes durable sink writes and differs from the candidate's CLI process
boundary. These measurements must not be used for direct latency rankings.
Cost, peak RSS and full resource admission are not supplied by this runner.

## Paired development diagnostics

`python -m eval.public.action_comparison CANDIDATE_DIRECTORY REFERENCE_DIRECTORY`
replays both retained runs, requires identical versioned plans and sink-enabled
candidate evidence, and rejects artifacts changed during replay. It binds all
six input artifacts per role by SHA-256 and reports candidate-minus-reference
metric differences by case and, for fan-out, by load phase. Undefined rates stay
undefined; there is no pooled winner or hidden substitution of missing values.

This is an unadmitted-reference diagnostic, not the calibrated non-inferiority
comparison required by the original M12 contract. It has explicit false flags
for ranking, admission, publication and non-inferiority evaluation. In-process
reference timing and candidate subprocess timing are excluded. Artifact hashes
and replay establish reproducibility of the diagnostic, not independent custody
or authenticity of the original execution.

## Revision-guarded draft mutations

The reference exposes `task.inspect` with a deterministic SHA-256 content
revision, stable intention identity and current action/status. It accepts
`task.update` override, cancellation and exact-time rescheduling. An optional
idempotency key must be paired with the original expected revision. A known
identical retry returns its original empty acknowledgement before checking the
current revision or terminal state; conflicting reuse and stale fresh requests
fail. Updates are constructed separately and committed only after validation.

Firing and cancellation change content revisions. A fired task cannot be
cancelled or newly updated; a recognized previous mutation retry cannot undo
its final state. Creation and mutation idempotency namespaces are separate.
These in-memory receipts are a prerequisite for reference recovery, not durable
recovery evidence. Recurrence-policy mutations and non-exact rescheduling remain
explicitly unsupported by this draft. Existing reference captures still replay.

## Durable draft reference journal

`DurableActionReference` in `eval/public/action_reference_store.py` binds a
request journal to run/case/tenant/session identity in a separate SQLite database.
Each call obtains a write transaction, validates and replays the existing scoped
journal, applies the new request and commits its request/response record before
acknowledging it. A fresh process reconstructs mutation receipts and terminal
state without relying on the previous Python object. Concurrent calls serialize.

Every record is size-bounded, journals have a per-scope count bound, and an ordered
hash chain binds request/response bytes to their scope. Replayed responses must
match exactly. Failed commands roll back and add no row. Database application
identity/version checks reject unrelated stores. These are accidental corruption
and semantic-drift checks, not signatures or defenses against a malicious writer
who can replace the database and recompute every hash.

Tests cover fresh-process recovery, deliberately discarded mutation responses,
concurrent creation/evaluation, scope separation, moved/modified rows, failed
command rollback and unchanged foreign databases. This does not yet constitute
the full registered recovery workload or arbitrary power-loss certification.
Replaying the bounded journal on every call favors auditability over throughput;
it is reference infrastructure, not a proposed production storage replacement.

## Durable reference recovery workload

`python -m eval.public.action_reference_recovery OUTPUT` executes the same
versioned four-week, five-seed recovery plan as the candidate recovery runner.
All 360 operations use the original symbolic revision references. Fifty
successful write acknowledgements are deliberately discarded after journal
commit; fifty adapter resets reopen the durable reference. The reset also clears
the adapter's clock, requiring the plan to inject it again before evaluation.

The runner retains raw resolved requests, original requests, outcomes, observed
revisions, durable journal and inert sink. Ten eligible actions and ten cancelled
controls remain separately scored. Replay regenerates reference semantics in a
fresh temporary journal and checks the complete candidate-independent trace,
then verifies the sink annex. It does not need the retained SQLite database to
check the trace, and does not authenticate the original execution independently.

The report has a separate `m12-reference-recovery-report/v1` schema and
`draft-durable-action-reference/v1` identity, with admission/publication false.
Measured evaluation time includes local journal replay/commit but excludes sink
writes and is not comparable to candidate subprocess latency. A dropped returned
acknowledgement is not a network outage or power-loss experiment. Process reopening
is independently covered by store tests; each workload adapter reset reopens the
store within the runner process. Full baseline calibration remains unfinished.

## Extended conditions and atomic observations

The draft now implements equality, inequality, membership and ordered conditions
(`eq`, `ne`, `in`, `lt`, `lte`, `gt`, `gte`). Ordering requires matching numeric or
string types, excluding booleans; membership requires a list. Invalid comparisons
reject the observation without consuming any eligible task. All eligibility
checks complete before occurrence counters advance, and signals remain available
for correction after a rejected observation.

Equality/membership retain the draft's strict recursive JSON comparison. Review
found a contract question that must be resolved before baseline freeze: the
current product helper checks outer types then uses Python equality, which can
treat nested booleans and numbers as equal, whereas the draft distinguishes them.
The present retained workloads do not exercise that difference. Do not infer
full semantic equivalence from their matched scores or silently change either
side's results. Add explicit public-boundary vectors and settle the intended
nested-value contract before admitting broader condition comparisons.

The [public condition boundary characterization](../../eval/reports/m12-condition-reference-boundary-2026-10-04.md)
now confirms the nested bool/number difference through authenticated public CLI
requests for `eq`, `ne` and `in`, with scalar and exact-value controls. The
regression records both outcomes explicitly. It does not alter the product or
retroactively assign a preferred policy to prior captures.
