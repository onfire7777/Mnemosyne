# M12 explicit-trigger eligibility windows

Status: development scorer and public-CLI regression, not a registered corpus,
calibration result or admission decision. This extends the timing definitions
needed by the original M12 plan without changing the existing exact-time or
PM-Bench/TriggerBench scoring contracts.

`eval.public.action_trigger_timing.score_trigger_windows(expected, ticks)` accepts
one isolated case. Each expected occurrence has exactly `action_id`,
`occurrence`, `trigger_type`, `due_at`, `windows`, and `cancelled_at`. Types are
the five explicit public triggers: exact time, time window, event, condition,
and dependency completion. The workload must derive eligibility independently
from its declared inputs, never from the candidate's output.

Each window has `start`, `end`, and Boolean `end_inclusive`. Starts are inclusive;
a null end is unbounded. Windows are ordered and disjoint; an empty list means
no eligibility. Starts cannot precede `due_at`. Time-window triggers require
finite exclusive ends, matching the public `[start, end)` contract. Other
triggers can use inclusive point windows for a signal available at one tick.
Event/condition observations can use point windows or multiple disjoint windows
to model transient signals. A signal's first appearance does not authorize
firing indefinitely after it disappears. `cancelled_at` truncates all windows
exclusively: a firing at the cancellation timestamp is invalid. The workload
must schedule the cancellation before the tick when using that boundary.

The caller supplies complete public `intention.observe` responses. Shared
validation checks clocks, firing identity/occurrence fields, supported trigger
types, action-ID multiplicity, and finite command duration. Limits are 10,000
expected occurrences, ticks, total firings and total windows, with at most 100
windows per occurrence. A sorted-tick lookup checks whether each window was
visited without a full tick-by-window cross product.

For each expected occurrence:

- One firing inside an active window with the expected trigger type contributes
  one true positive. Additional observations are false positives, including
  duplicate otherwise-valid firings.
- Early, inactive-gap, expired, post-cancellation, never-eligible and wrong-type
  firings are retained as invalid observations. Unknown actions are retained
  separately. Each observation contributes at most one false positive; the
  duplicate diagnostic does not add a second metric penalty.
- A false negative requires at least one observed tick in an active window and
  no valid firing. A window with no observed tick is disclosed as having no
  observed opportunity, not silently scored as successful or missed.
- Lateness is the first valid firing time minus the first declared eligibility
  window's start. It includes delays imposed by the workload's polling schedule
  and missed earlier windows. Missing/invalid-only occurrences have null latency.
  This is not a measurement of a continuously running production scheduler.

Reports retain global and per-trigger TP/FP/FN and precision/recall/F1; undefined
denominators are null. They also retain every observation, invalid reason,
duplicate count, provider due-date discrepancies, opportunity counts, latency
denominator, and evaluation-command wall time. No confidence interval, calibrated
floor, admission verdict, total dollar cost or comparative rank is invented.

`workload_completeness_verified` is always false here. A scorer receiving only
observed ticks cannot prove that required ticks or input events were supplied.
The planned multiweek runner must separately bind the complete ordered plan,
input events, cancellations and observations before using these metrics.
Therefore an empty/truncated trace cannot establish a passing benchmark.

The regression case sends five real structured intentions through the public
CLI, supplies event and condition observations, and checks the resulting five
firings. Synthetic edge cases cover disjoint windows, cancellation boundaries,
early/expired observations, missing opportunities, duplicates, unknown actions
and malformed intervals. This is not implicit natural-language intention
formation, an overloaded multiweek corpus or calibrated baseline evidence.
Those requirements and registered recovery, resource/cost and admission remain
open. The existing exact-time saved captures remain replayable unchanged.

## Versioned four-week development workload

`python -m eval.public.action_trigger_run OUTPUT` now writes the immutable
`m12-explicit-trigger-run/v1` plan before running it through the public action
CLI. Five seeded start dates each span four virtual weeks, with 40 expected
occurrences per case. Each week exercises the five explicit trigger types,
a mismatching event, a false condition followed by a matching signal,
a deliberately expired window, a cancelled action and a repeated signal-free
tick. Two interval schedules cover recurrence retention and cancellation after
the second occurrence. Identical keyed creation retries must not add schedules.
This is structured intention creation, not implicit natural-language formation.

Every operation and response is flushed to `operations.jsonl`. The report
validator requires the exact versioned plan, every ordered operation, matching
payloads, clock-bound observations and empty acknowledgements for other
operations. `--recompute` independently regenerates reports from those saved
observations and checks the completion record. Complete execution with no
firings produces 26 false negatives per case, not a passing empty result.
The remaining 14 occurrences per case have no observed eligible opportunity:
expired windows, never-matching events and cancelled occurrences. They remain
visible; any firing from them counts against precision.

The outer report marks `ordered_workload_verified=true` only after these checks.
The standalone scorer's `workload_completeness_verified=false` remains unchanged:
it cannot establish the operation sequence itself. Neither flag authenticates
execution or proves an independent reproduction. Source and harness hashes are
recorded; production runtime matching is explicitly unverified. Failure records
contain the exception type and completed-operation count, never exception text
that might contain a session token. Existing output directories are not reused.

This small deterministic workload does not yet satisfy the full original M12
corpus: overload, implicit intention formation, calibrated reference comparison,
measured resource/cost gates and admission remain open. Revision-keyed mutation
recovery now has a separate retained four-week capture, including a sink-enabled
variant; those measurements are not silently included in this workload's result.
The [acceptance evidence ledger](m12-acceptance-evidence-2026-10-04.md) maps each
original requirement to current evidence and remaining work. The
existing exact-time captures and registered benchmark formats remain unchanged.

## Versioned operation response-loss recovery

`python -m eval.public.action_recovery_run OUTPUT` runs the separate
`m12-operation-recovery-run/v1` development workload. Five seeded dates each
span four virtual weeks. Every week creates an explicit intention, updates its
action, loses the first successful creation and update responses, rebuilds the
adapter and retries the identical requests. Alternate weeks also cancel the
intention and lose the first successful cancellation response. Two evaluations
at the due time detect repeat firing; replaying the original update after the
terminal state must preserve that state.

The fault driver calls the real public subprocess first. Only after successful
exit does it withhold the response from the adapter. It never substitutes a
successful write, kills the memory process, or claims to simulate power loss.
An adapter reset clears its in-memory task mapping and virtual clock; the plan
reconstructs task identity by replaying the original keyed creation and later
reinjects the clock. These are response-loss and client-state recovery cases,
not arbitrary crash recovery or lost event-delivery certification.

Each update/cancel precondition refers to an earlier inspection's revision.
Both the symbolic reference and exact resolved request are retained in the log.
Replay requires the original revision, not the latest available revision. It
also checks task identity, expected action and terminal state, changed content
revisions, planned fault outcomes and firing identity against inspected
intentions. The complete sequence and every raw observation remain available.
A complete sequence with no firings still reports false negatives.

The plan has 10 injected response losses and 10 adapter resets per seed. Its
four intentions include two scheduled-to-fire and two cancelled controls.
Gold and inspection assertions are consumed by the evaluator, never passed to
the memory system. Recompute verifies this development trace but does not
authenticate logs or establish independent custody. Source hashes and dirty
state are disclosed. Registered recovery admission, overload, implicit
formation, calibrated reference systems and full resource/cost gates remain
open; the five-trigger workload and existing registered fixture bytes remain
unchanged.

## Sink-connected execution

Both `action_trigger_run` and `action_recovery_run` accept `--sink`. Each raw
firing is sent to the existing durable, harness-owned SQLite sink, followed by
one explicitly labelled harness retry. The sink binds run, case, tenant,
session, intention and occurrence. It stores one inert receipt per logical
delivery and retains every attempt, including duplicates/conflicts.

The mode preserves existing plan and timing-report bytes. `source.json`
explicitly declares whether the sink was enabled; `sink.json` contains its
per-case snapshots, and `sink.sqlite3` retains the local durable records.
Recompute checks the complete operation sequence first and reconstructs the
annex with the correct workload session. A missing, modified or unadvertised
annex is rejected. Existing captures without a sink remain replayable.

Delivery failure retains completed raw operations and a failed status rather
than writing a successful report. The sink does not execute external payloads.
A deliberately repeated sink attempt tests idempotent recording, not an
independent external service's exactly-once guarantee. Current separate
workloads still need overload/implicit cases, integrated cross-module recovery,
calibration and resource/cost admission before full M12 acceptance.

## Bounded mixed-trigger fan-out

`python -m eval.public.action_trigger_run OUTPUT --fanout --sink` selects the
separate versioned `m12-trigger-fanout-run/v1` workload. Five seeded start dates
span four virtual weeks. The weeks schedule 2, 4, 8 and 16 actions of each
explicit trigger type, with an equal-sized group of never-matching event
decoys. Shared event and condition inputs exercise fan-out; exact-time,
exclusive windows and dependency completions retain their distinct timing.
Negative signals precede matching signals, and a repeated signal-free tick
checks repeat firing. Each seed has 180 expected occurrences and 244 operations.

Reports retain both case totals and one separately scored phase per load level,
so failures at higher loads cannot disappear into a single average. Phase
boundaries and action identities are part of the exact versioned plan. Gold is
never forwarded to the candidate. The existing standard workload remains the
default; replay selects the exact generator from the saved schema.

This is bounded trigger fan-out, not demonstrated saturation, maximum capacity,
or the full overloaded/implicit-intention corpus. It supplies explicit load
conditions for later reference comparison and resource measurement. Its results
remain development-only and cannot set an admission floor or ranking by themselves.
