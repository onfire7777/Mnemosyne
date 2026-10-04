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
| Implicit cases | Current workload explicitly creates structured intentions | Add public-input implicit formation cases with positive, ambiguous and negative examples; report unsupported adapters explicitly; never insert gold schedules on their behalf |
| Overloaded-trigger cases | Versioned bounded fan-out generator: 2/4/8/16 actions per explicit type; full run from c7a9d05a completed/replayed with 750 expected firings | Define actual overload behavior and resource envelope; bounded fan-out is not saturation evidence |
| Every firing targets harness-owned idempotent sink | Retained full trigger-sink and recovery-sink captures; exact annex replay | Integrate sink into the admitted full corpus and every candidate adapter; no external payload execution |
| Recovery and retry correctness | 360-operation capture: 50 response losses, 50 adapter resets, 10 eligible firings, 10 cancelled controls; 10 sink receipts and 10 deliberate duplicate deliveries | Local response loss is not arbitrary crash recovery or external-service exactly-once behavior |
| Precision, recall, F1, false alarms, misses, lateness, duplicate execution, cancellation correctness and cost | Window scorer and per-case/per-load reports; sink attempt records | Cost remains unmeasured; extend full-corpus reports without pooling away load-specific failures |
| Zero duplicate and cancelled-intention executions | No violations in retained development captures | Verify on full registered corpus; finite local success is not universal certification |
| Preregistered absolute floor and non-inferiority to exact reference | Draft independent explicit-action reference and two retained five-seed executions; no calibrated/admitted baseline claim | Complete semantic review and broader recovery validation; calibrate on disjoint development data; freeze floor/margin before candidate ranking |
| At least five virtual-week seeds | Five-seed, four-week explicit and recovery captures | Retain same repeat/replay guarantees across full workload and adapters |
| Measured resource admission | Current run has wall-time and macOS pressure guard | Measure specified RSS and disk as well as elapsed time; pressure=normal does not establish RSS <=4 GiB; 30 min/4 GiB/1 GiB remains a planning hypothesis |
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

The completed fan-out run did not enable these probes. Do not backfill its
receipt with later samples or claim it measured these resources. Future runs
can collect these diagnostics to inform the separately required admission work.

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
