# Draft reference: explicit workload

This is execution of the draft reference interpreter, not Mnemosyne or an
external memory system. It is DEVELOPMENT evidence, `publishable:false` and
`baseline_admitted:false`. It cannot establish a ranking or admission threshold.

The five-seed workload completed 525 operations, produced 130 expected
firings and retained 130 inert receipts plus 130 deliberate delivery
retries recognized as duplicates. Ordered workload validation, semantic
re-execution and sink-annex replay passed. No external payload was executed.

Both the clean source receipt and every recorded harness hash were checked
against `44d578fa891c53245a6e20ea80045cb84e746fd5`. The run used Python 3.14.7.
A clean source match is descriptive provenance, not independent authentication.

```sh
python -m eval.public.action_reference_run eval/reports/m12-reference-explicit-development-2026-10-04 --recompute
```

Original artifacts and the database remain at
`/Users/admin/.local/state/mnemosyne/reference-runs/2026-10-04-44d578fa/explicit`.
The database SHA-256 is `68a44e10620f3c038f9866c3682dbd27bc4cd6a5365647c2fcdcd42942856250`. The tracked annex allows replay without
publishing the database.

Evaluation duration measures only an in-process interpreter call. It is not
comparable to the candidate's CLI subprocess duration. No RSS/disk admission,
external reproduction, official score, calibrated floor, non-inferiority margin
or superiority claim follows from this capture. Full semantic review, durable
revision recovery, implicit/overloaded cases and calibration remain unfinished.
