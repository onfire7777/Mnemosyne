# M12 acceptance evidence and remaining work

Authority: `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`,
M12 Prospective action. This ledger preserves that acceptance scope. It does not
replace the original specification or promote development evidence to admission.

## Evidence by requirement

| Original requirement | Current evidence | Remaining acceptance work |
| --- | --- | --- |
| Typed scheduling, revision, authorization, idempotency and virtual tick | Public action adapter; revision-keyed recovery workload; public authorization and retry regression tests | Bind exact adapter/runtime identity into registered multi-system runs; do not infer authorization coverage from happy-path scheduling |
| Exact-time, window, event, condition and dependency cases | Retained five-trigger, five-seed four-week capture; 525 operations | Incorporate in registered full corpus with pinned reference behavior |
| Recurrence, cancellation and negative controls | Five-trigger capture includes recurring schedules, cancellation and unmatched/expired controls | Preserve these controls in the full corpus, including failures under load |
| Implicit cases | Frozen 220-conversation original and 100-conversation dependency corpora; public runners, state/firing diagnostics and saved-trace checks; failed actual-provider attempts and controlled prompt/decoding diagnostics retained | Complete actual-provider full-corpus execution with identity/custody, broaden language/dependency coverage, and establish held-out evaluation; never insert gold schedules on a candidate’s behalf |
| Overloaded-trigger cases | Bounded fan-out capture with 750 firings; complete clock-driven CLI pressure capture from 04f99824: 207/320 valid firings, 113 missed windows, exact-time backlog recovered | Paired v2 service/CLI measurement is complete (320/320 and 200/320 respectively); establish native saturation/resource behavior. Neither paired pressure nor bounded fan-out closes full overload acceptance |
| Every firing targets harness-owned idempotent sink | Retained full trigger-sink and recovery-sink captures; exact annex replay | Integrate sink into the admitted full corpus and every candidate adapter; no external payload execution |
| Recovery and retry correctness | 360-operation capture: 50 response losses, 50 adapter resets, 10 eligible firings, 10 cancelled controls; 10 sink receipts and 10 deliberate duplicate deliveries | Local response loss is not arbitrary crash recovery or external-service exactly-once behavior |
| Precision, recall, F1, false alarms, misses, lateness, duplicate execution, cancellation correctness and cost | Window scorer, full-offered-work pressure metrics and per-case/per-load reports; sink attempt records | Provider token/time counters are now reported for one 22-call formation diagnostic; full-corpus and end-to-end cost remain unmeasured. Extend reports without pooling away load-specific failures |
| Zero duplicate and cancelled-intention executions | No violations in retained development captures | Verify on full registered corpus; finite local success is not universal certification |
| Preregistered absolute floor and non-inferiority to exact reference | Draft independent explicit-action reference with retained explicit, fan-out and durable recovery executions plus paired replay diagnostics; no calibrated/admitted baseline claim | Resolve the verified nested-condition policy difference and complete broader semantic/recovery validation; calibrate on disjoint development data; freeze floor/margin before candidate ranking |
| At least five virtual-week seeds | Five-seed, four-week explicit and recovery captures | Retain same repeat/replay guarantees across full workload and adapters |
| Measured resource admission | Retained full fan-out resource observation: 304.701 seconds, 292 samples, maximum sampled RSS 88 MiB and logical files 3,913,523 bytes | Sampling is not certified peak RSS/disk or an enforced admission limit; 30 min/4 GiB/1 GiB remains a planning hypothesis |
| Licensed pinned official variants | Development captures carry no official label | License and pin upstream PM-Bench/TriggerBench datasets and scorers before official evaluation |

## Capture custody

- `eval/reports/m12-trigger-sink-development-2026-10-04`: source 0a03fd76,
  clean receipt; 130 inert receipts, 260 attempts. All recorded hashes matched
  that commit, and complete ordered replay passed.
- `eval/reports/m12-recovery-sink-development-2026-10-04`: source 0a03fd76,
  dirty receipt retained honestly. All recorded recovery harness hashes matched
  that commit, and complete ordered replay passed. The dirty flag is not erased.
- `eval/reports/m12-fanout-sink-development-2026-10-04`: clean source c7a9d05a,
  all recorded harness hashes verified. 1,220 operations, 750 expected firings,
  750 inert receipts and 1,500 delivery attempts replay exactly. Retained monitor
  records normal pressure throughout and successful exit. This is bounded fan-out,
  not saturation or resource admission.

Next dependency-ready work is reference semantics and full-corpus design alongside
resource instrumentation. No result from the current run may retroactively choose
an admission floor or be presented as evidence of superiority over another system.

## Optional local resource diagnostics

`eval.public.monitor` now accepts repeated `--usage-root PATH` options before
its child command. This opt-in records `usage.jsonl` and terminal maxima for
sampled process-group RSS and logical regular-file bytes beneath the explicit
roots. Overlapping roots and hard links are deduplicated, and symbolic links
are not intentionally followed. Use owned, quiescent directory structure;
this live filesystem walk is not a hostile-filesystem sandbox.

RSS is sampled with POSIX `ps` (KiB converted to bytes). It sums the monitored
process group, including descendants that remain in that group, and can miss
short-lived peaks or escaped descendants. Logical file sizes are not allocated
blocks, quotas or peak disk use; unlisted temporary directories are not counted.
A missing/deleted file contributes nothing to that snapshot. Other probe errors
stop the monitored run and retain a monitor-error receipt rather than inventing
zero usage. Neither diagnostic maximum populates the ABI's certified peak RSS
field. `peak_rss_verified` and `admission_verified` remain false.

The original c7a9d05a fan-out run did not enable these probes. Its receipt is
unchanged. A [separate complete resource observation](../../eval/reports/m12-fanout-resource-development-2026-10-04/README.md)
from clean source 421a1fcd now retains 292 samples: maximum sampled process-group
RSS 88 MiB, maximum logical files 3,913,523 bytes and 304.701 monotonic seconds.
All 1,220 operations and the sink annex replay; all 291 pressure samples are
normal. Its temporary stores were inside the measured root. The host had 16 GiB
physical memory. This establishes local execution of this bounded structured
workload, not full-corpus admission or feasibility of model-heavy QA. The initial
argument-validation failure is retained separately and supplies no workload metric.

## Retained draft reference executions

The [explicit reference capture](../../eval/reports/m12-reference-explicit-development-2026-10-04/README.md)
and [fan-out reference capture](../../eval/reports/m12-reference-fanout-development-2026-10-04/README.md)
retain 525/1,220 operations and 130/750 inert receipts respectively. Both replay
semantically and through the sink, with clean recorded harness hashes matching
44d578fa. These are draft reference outputs, not additional candidate runs.
The reference remains unadmitted; no calibration or superiority claim is made.

## Paired diagnostic evidence

[Retained paired reports](../../eval/reports/m12-paired-development-2026-10-04/README.md)
replay both roles on identical explicit/fan-out requests and bind their source
artifacts. All observed count and precision/recall/F1 differences are zero in
these fixtures. This is neither superiority evidence nor an approved
non-inferiority result. Full reference semantics, broader recovery coverage,
implicit/overloaded cases, disjoint calibration and admission remain open.

## Durable reference recovery evidence

The [committed reference recovery capture](../../eval/reports/m12-reference-recovery-development-2026-10-04/README.md)
completed 360 operations with 50 post-commit discarded responses and 50 adapter
resets. Original revision retries preserved identity and final state; ten eligible
actions produced ten inert receipts while cancelled controls remained unfired.
Full trace/semantic/sink replay passed against recorded source fb6731fc. This
closes the missing durable reference-workload execution step, not broad crash
recovery, calibrated baseline approval or M12 admission.

The paired diagnostic now also covers the retained candidate/reference recovery
captures in `m12-paired-development-2026-10-04/recovery.json`. Both inputs replay
before comparison; case-specific response-loss/reset counts are retained and
observed metric differences are zero. The reference remains unadmitted and this
is not the preregistered non-inferiority decision required for ranking.

Reference freeze also has a verified nested-condition semantics gap: the public
CLI and draft differ on nested boolean/number equality and membership. See
`eval/reports/m12-condition-reference-boundary-2026-10-04.md` and its public-seam
regression. Full semantic equivalence is not established by existing matched
workloads; the intended policy must be explicit before extending admission.


## Natural-language formation corpus

The [implicit-formation development protocol](m12-implicit-formation-development-2026-10-04.md)
now defines 220 conversations across five seeds and four weekly dates. Public
inputs and evaluator labels are separately materialized with byte hashes;
turn-prefix projection prevents revealing later cancellations prematurely.
The structured action adapter is now connected to a separate bounded formation
provider through the public bridge. Failed actual-model attempts and small
controlled first-turn diagnostics are retained, alongside per-turn state and
fixed-probe firing evaluation. No actual-provider full-corpus run has completed.
Broader language/dependency coverage and held-out/calibration splits remain required.


The natural-language development path now has an opt-in bounded command
transport, a public-action bridge and a sequential execution runner with raw
stdout, operation outcomes and failed-attempt retention. Scripted test providers
exercise real public creation and revision-keyed cancellation; these tests are
not model quality measurements. New creations now bind to public CIDs of their available conversation prefixes;
mutation provenance remains in ordered per-turn records. Actual provider
identity/custody, complete provenance admission, filesystem isolation,
broader state-equivalence policy and independent reproduction remain unverified or unfinished. No formation score has been admitted.


Stored-state diagnostics now compare complete public inspection snapshots to
per-turn formation labels, preserving duplicate schedules, wrong due times,
premature firing and missing intentions. Clarification presence is reported
without claiming semantic correctness. The runner retains the separate
`formation-state.json` artifact; no real-model score or complete M12 ranking
has been established.


The formation runner also retains twelve fixed virtual-time probes and inert
receipts per conversation. Evaluator-only diagnostics score labeled eligibility,
including cancellation and recurrence. Saved-trace recomputation checks ordered
requests/responses, both reports and the SQLite receipt rows, and binds input
hashes without executing the recorded provider command. This is internal
consistency checking, not authenticated model/engine execution or independent
reproduction. No completed actual-model formation benchmark or M12 admission is claimed.


A [retained Qwen3 0.6B attempt](../../eval/reports/m12-formation-feasibility-2026-10-04/README.md)
now provides one actual local model response. The intended 220-case run stopped
on the first invalid response, before any task write. All three pressure samples
were normal and the model was unloaded afterward. This is a failed development
attempt, not a zero accuracy estimate or a successful M12 measurement.


The [schema-constrained model attempt](../../eval/reports/m12-formation-schema-attempt-2026-10-04/README.md)
completed 21 cases before an HTTP error. It issued no task writes and missed
17 eligible occurrences in that prefix. Partial per-case diagnostics preserve
this loss; no full-corpus, engine-quality or resource-admission claim follows.
The HTTP error cause is unknown because the old wrapper omitted status/body.
New source records bounded HTTP error detail for future attempts.


A [single-input wire-order diagnostic](../../eval/reports/m12-formation-wire-diagnostic-2026-10-04/README.md)
shows an adapter effect: both compact models changed from clarification to an
incorrect exact-time proposal when schema key order changed. Future comparisons
must bind actual request bytes and adapter order, not just semantically equal
JSON. This finding does not replace the failed full attempts or establish correct
formation. The original HTTP cause remains unresolved after one successful repeat.


## Provider usage accounting

`python -m eval.public.action_formation_usage LOG.jsonl ...` derives descriptive
usage from retained Ollama responses. It preserves each call, its model/prompt
profile and source hash, and exposes missing counters rather than filling them
with zero. A failed call with a retained response still contributes its reported
usage. Missing responses have unknown usage. Monetary cost, wall elapsed time,
resource admission and ranking eligibility are not inferred from token counters.

The [22-call usage report](../../eval/reports/m12-formation-semantic-usage-2026-10-04.json)
contains 18,180 reported input tokens and 3,788 generated tokens, with
79.592173665 seconds of summed provider-reported duration. This is distinct from
the monitor's 80.544-second elapsed time and excludes unreported engine, energy,
and infrastructure costs. It is neither a full M12 cost result nor independent
verification of the model server's counters. Full-corpus cost remains open.


## Reconciled next implementation work — source `c86f99eb`

Controlled prompt and JSON/schema comparisons are complete as development
experiments, not acceptance gates. Repeating these unchanged variants is not
next-step evidence. Their failures must remain visible in subsequent reporting.

The next corpus implementation gap is dependency-aware natural-language
formation. Add a separately versioned extension with public task prerequisites,
multiple turns and evaluator-only labels across the existing five virtual-week
seeds. Preserve the frozen 220-case corpus and its historical hashes. Cover a
satisfied prerequisite, an unsatisfied prerequisite, cancellation, unrelated
completion and duplicate observation. Extend firing/scoring/replay together;
corpus source alone must not close the implicit or dependency acceptance rows.

Actual overload remains a separate gap: a higher fan-out count or deliberately
late virtual tick is not evidence of saturation. A future measured workload must
retain offered load, admitted/rejected work, service time, outstanding work and
recovery after pressure, with bounded execution on this host. Do not silently
rename the existing fan-out evidence as overload completion.


The [dependency extension](m12-dependency-formation-development-2026-10-04.md)
now supplies a separate frozen 100-conversation corpus with evaluator-only
prerequisite identities and firing expectations. The dependency-aware scorer, executable observation bridge and saved-trace
verifier are implemented. A real Qwen3 1.7B attempt completed one case, failed
on task-ID rebinding in the second, and left 98 unattempted. The completed case
missed an expected firing. Full-corpus model execution and acceptance remain
open; source availability is not substituted for measured quality.


## Clock-driven pressure result

The [retained full workload](../../eval/reports/m12-clocked-pressure-2026-10-04/README.md)
measures wall-clock-paced evaluation through the synchronous public CLI. All
five seeds completed: 207 valid firings from 320 live intentions, 113 missed
50 ms windows, no duplicate or cancelled firings, and full exact-time drain
recovery. The full-workload denominator includes windows never visited by a
poll. Historical tick-conditional scores remain separate.

Normal pressure and 97,271,808 maximum sampled RSS bytes support feasibility of
this specific 71.889-second run on this Mac. They do not establish peak limits,
native saturation, admission or performance of a long-lived service. The next
step is that identical public-service comparison, not changing the stress
parameters or discounting the misses. Full M12 and original plan gates remain.


### Paired public-transport pressure follow-up

The [v2 capture](../../eval/reports/m12-transport-pressure-2026-10-04/README.md)
replays both clean-source runs: persistent MCP stdio 320/320 correct; CLI 200/320,
120 missed short windows. Every exact-time intention recovered, and neither
transport produced duplicate or cancelled firings. Fixed sequential order and
one run per transport limit inference. Explicit preloaded triggers do not close
natural-language formation, native saturation, calibration, resource admission,
or cross-system comparison gates. Historical v1 evidence remains unchanged.
