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
