# M12 clocked trigger-pressure development workload

Status: implementation and first full development measurement retained. Original M12 acceptance remains PROPOSED.
This supplements the fixed-tick fan-out workload; it does not replace it or
claim to measure native scheduler maximum capacity.

## Contract and scope

Use the authenticated public action CLI and inert idempotent sink. Preload 64
live intentions per seed, alternating exact-time and 50 ms time-window triggers
at 10 ms release intervals, plus eight pre-cancelled intentions. Use the five
existing virtual-week seeds. Store writes finish before timing begins, so this
measures trigger service, not ingestion throughput or native admission policy.

Map elapsed monotonic time to the virtual clock at every evaluation dispatch.
Evaluation is synchronous; no artificial sleep, concurrency, or invented queue
is inserted. Retain dispatch, response and sink-delivery elapsed nanoseconds.
Stop after the release interval plus one second of draining, with a final
evaluation at or after that horizon. Bound each case to 64 evaluations and ten
seconds of dispatch time; CLI commands have a ten-second timeout. A bounded
case that cannot finish is a failed attempt, never a completed score.

Report offered/live/cancelled counts, successful setup, evaluation service time,
observed exact-time backlog, still-open windows, expired unobserved windows,
response latency and drain recovery. Retain raw public operations and every
firing in the sink, including invalid/duplicate firings. Setup errors abort with
partial records; the benchmark must not invent accepted/rejected totals for an
incomplete setup. Native admission limits are not exposed by this interface.

**Scoring ruling:** the existing window diagnostic conditions false negatives
on a polling opportunity. Under pressure, missing a whole window must not be
rewarded. Keep that historical diagnostic unchanged, and add full-offered-work
precision/recall/F1 with every noncancelled intention in the denominator. Show
response completion lateness separately from the virtual evaluation timestamp.
Expired windows with no valid firing count as missed even if no poll visited.

## Execution steps

1. Add deterministic plan and scorer; test missing-window accounting, strict
   monotonic timing validation, cancellation and duplicates.
2. Add bounded public runner and offline consistency replay, retaining requests
   before execution, raw responses, source receipt, sink and terminal status.
3. Run a real small integration check, then a clean-source complete five-seed
   attempt with host pressure monitoring. Retain failures without selective retry.
4. Reconcile the M12 evidence map using the actual observations. Admission,
   intrinsic engine capacity, independent custody, calibration and a fair
   multi-system comparison remain separate requirements.

Ruling: this public CLI configuration includes process startup and sink costs.
They are disclosed rather than subtracted. Evidence of backlog here does not
establish native scheduler saturation or the complete overloaded-trigger gate.
No model is loaded and no real action payload is executed.

## Implementation evidence

The plan, public runner, full-workload scorer and saved-trace verifier are now
implemented in `eval/public/action_pressure.py`. The verifier checks ordered
setup/tick requests, nanosecond timing consistency, the versioned workload and
source hashes. It regenerates inert sink deliveries and compares both the
annex and the SQLite database. This is consistency verification, not independent
attestation of elapsed time or execution.

Nine new checks and 25 existing timing/sink checks passed (34 total). They
include a real reduced public-CLI workload, never-polled expired windows,
duplicate/cancelled firings, damaged clock records, incomplete drain, a corrupted
sink database and failed-setup request retention. The complete five-seed measurement is now retained below; these original checks
preceded it.


## First complete clocked-pressure measurement

[Raw capture](../../eval/reports/m12-clocked-pressure-2026-10-04/README.md) from
clean `04f99824`: all five seeds completed in 71.889 seconds under normal sampled
pressure. Of 320 live intentions, all 160 exact-time intentions and 47 of 160
short-window intentions fired correctly. The other 113 windows were missed.
Forty pre-cancelled controls never fired; no duplicates or false positives were
observed. Pending exact-time work peaked at eight per seed and drained fully.

Ordered replay, source hashes and the durable sink database were verified at the
recorded source. A post-run verifier fix now also rejects command durations that
exceed the enclosing response interval; all retained measurements pass it.
Original source and artifact bytes remain unchanged. The maximum sampled RSS
was 97,271,808 bytes; peak/resource admission remains unverified.

Next work is an identical workload through a long-lived authenticated public
service, to separate CLI process startup from native evaluation behavior. The
current result is not native saturation, a complete overload acceptance gate,
a calibrated deadline requirement or a competitor comparison.
