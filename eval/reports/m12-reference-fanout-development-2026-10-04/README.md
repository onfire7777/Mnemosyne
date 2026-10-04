# Draft reference: fanout workload

This is execution of the draft reference interpreter, not Mnemosyne or an
external memory system. It is DEVELOPMENT evidence, `publishable:false` and
`baseline_admitted:false`. It cannot establish a ranking or admission threshold.

The five-seed workload completed 1,220 operations, produced 750 expected
firings and retained 750 inert receipts plus 750 deliberate delivery
retries recognized as duplicates. Ordered workload validation, semantic
re-execution and sink-annex replay passed. No external payload was executed.

Both the clean source receipt and every recorded harness hash were checked
against `44d578fa891c53245a6e20ea80045cb84e746fd5`. The run used Python 3.14.7.
A clean source match is descriptive provenance, not independent authentication.

```sh
python -m eval.public.action_reference_run eval/reports/m12-reference-fanout-development-2026-10-04 --recompute
```

Original artifacts and the database remain at
`/Users/admin/.local/state/mnemosyne/reference-runs/2026-10-04-44d578fa/fanout`.
The database SHA-256 is `244653854ee8d74df448e19b4b3dd2cf9df565da00fd5aea5d20657d5e235551`. The tracked annex allows replay without
publishing the database.

Evaluation duration measures only an in-process interpreter call. It is not
comparable to the candidate's CLI subprocess duration. No RSS/disk admission,
external reproduction, official score, calibrated floor, non-inferiority margin
or superiority claim follows from this capture. Full semantic review, durable
revision recovery, implicit/overloaded cases and calibration remain unfinished.
