# Clocked public-CLI trigger pressure — retained development result

Clean source: `04f9982486091a8f95070bf892618eabf2951d23`.
Five complete seeds, 320 live intentions and 40 pre-cancelled controls. The
fixed stress profile released alternating exact-time and 50 ms window triggers
at 10 ms intervals. Schedules were preloaded before each timed phase.

207 valid firings: all 160 exact-time intentions and 47 of 160 window intentions.
113 short-window intentions were missed. No false positives, duplicate firings
or cancelled-intention firings were observed. The exact-time pending count peaked
at eight per seed and drained to zero in every seed. These are measurements of
this synchronous public CLI configuration, including process startup, on this
host. They are not intrinsic engine capacity, a production SLO, a calibrated
stress target, a comparison with another system or an admitted benchmark result.
The 50 ms stress windows were fixed before execution, not selected from results.

The full-offered-work scorer counts all missed windows. The retained historical
tick-conditional diagnostic counts a missing firing only when a poll visited its
window; it must not replace the full-workload denominator for this experiment.
Response latency and native evaluation timestamps are retained separately.

The monitor completed in 71.889 seconds, with normal sampled memory pressure,
97,271,808 maximum sampled process-group RSS bytes and 1,524,312 maximum sampled
logical file bytes. Sampling does not certify peaks or resource admission.
Temporary engine stores were inside the monitored workload directory and removed
by normal cleanup. No language model or real action payload was executed.

At the recorded source, full ordered replay passed: versioned inputs, source
hashes, public operation pairing, derived reports, inert sink annex and actual
SQLite rows. `replay-validation.json` retains the observed result. Source-bound
replay requires that checkout: `python -m eval.public.action_pressure PATH/workload
--recompute`. The exact runner source is also archived as text. Future source
hashes are deliberately not substituted for this historical execution.

A subsequent verifier improvement rejects an alleged command duration longer
than its encompassing response interval (with one microsecond rounding allowance).
All retained timings pass that additional check without altering raw records or
scores. This is post-run validation, not a rerun or independent clock attestation.

Next: compare this fixed workload through a long-lived authenticated public
service before attributing the misses to engine behavior. Native saturation,
complete overloaded-trigger acceptance, calibrated baselines and M12 admission
remain open. No uncertainty interval or superiority claim is made.
