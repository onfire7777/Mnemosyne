# Paired explicit-action development diagnostics

These reports compare the retained Mnemosyne public-CLI runs with the retained
**draft explicit-action reference**, on identical deterministic requests.
Both inputs were fully replayed before comparison. The complete diagnostic was
computed twice and matched byte-for-byte. Each JSON report binds all six source
artifacts per role by SHA-256 and preserves case and load-phase results.

- `explicit.json`: five seeds, 525 operations per run, 130 expected firings.
- `fanout.json`: five seeds, 1,220 operations per run, 750 expected firings;
  separate 2/4/8/16-actions-per-type phases.

Observed precision/recall/F1 and count differences were zero in these finite
fixtures. This is not evidence that Mnemosyne is superior to another system,
that an admission floor is met, or that the draft reference is approved.
Neither report is publishable or ranking-eligible. The comparison does not test
implicit formation, actual saturation, durable reference revision recovery or
external-system performance. Runtime/resource boundaries are unmatched; latency
and cost are not compared. No confidence interval or non-inferiority verdict is
computed.

Reproduce with the comparator introduced in source commit `4f8aefe2`:

```sh
python -m eval.public.action_comparison eval/reports/m12-trigger-sink-development-2026-10-04 eval/reports/m12-reference-explicit-development-2026-10-04
python -m eval.public.action_comparison eval/reports/m12-fanout-sink-development-2026-10-04 eval/reports/m12-reference-fanout-development-2026-10-04
```

The matching stdout bytes are retained in the corresponding JSON files. Input
capture READMEs document their exact source identities and limitations. Hashes
and replay support integrity checking; they are not signatures or independent
execution authentication. All original M12 acceptance requirements remain binding.

## Recovery pair

`recovery.json` adds the five-seed 360-operation recovery pair. Both runs contain
50 deliberately lost successful responses and 50 adapter resets, ten eligible
firings and ten cancelled controls. The report retains each case's fault/reset
counts alongside metrics, binds both input captures, and reproduces byte-for-byte.
Observed metric differences are zero in this workload. That does not establish
non-inferiority on other workloads or certify the draft reference.

```sh
python -m eval.public.action_comparison eval/reports/m12-recovery-sink-development-2026-10-04 eval/reports/m12-reference-recovery-development-2026-10-04
```

The candidate source receipt is explicitly dirty, with its recorded harness
hashes separately verified against the source commit; the reference receipt is
clean. See both capture READMEs. The comparison does not erase either limitation.
