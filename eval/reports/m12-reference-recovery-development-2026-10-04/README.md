# Durable draft-reference recovery capture

This is execution of the draft reference, not a new Mnemosyne measurement or
an admitted baseline. Five seeds and four virtual weeks completed all 360
operations with 50 responses deliberately discarded after successful commits
and 50 adapter resets. The ten eligible revised actions fired; the ten cancelled
controls did not. Ten inert receipts and twenty delivery attempts were retained,
including ten deliberate retries identified as duplicates. No payload executed.

Full ordered workload checks, reference-semantic regeneration and sink-annex
replay passed. The clean source receipt and every recorded harness hash matched
`fb6731fcaae0b0ad54b0f1484ed9b91b11a29286`. The run used Python 3.14.7.

```sh
python -m eval.public.action_reference_recovery eval/reports/m12-reference-recovery-development-2026-10-04 --recompute
```

Original artifacts remain at
`/Users/admin/.local/state/mnemosyne/reference-runs/2026-10-04-fb6731fc/recovery`.

| Database | Final bytes | SHA-256 |
| --- | ---: | --- |
| Reference journal | 147456 | 73046576d682e277cf5d97cc95710c96af7f9a15017c219a2b46ce9dfc247c51 |
| Inert sink | 24576 | a5ef7cd32cf344d99564fc5cce8232c51d29568521d09c45edec097ca3252ae0 |

Final database sizes are not peak disk admission. The tracked logs replay without
publishing the databases. Hashes/replay verify consistency, not independent
execution authenticity. Workload resets reopen the durable store in the runner
process; separate store tests exercise fresh-process reopening. This capture does
not simulate arbitrary power loss, real network failure or external-service
exactly-once behavior. In-process timing is not comparable to candidate CLI timing.

Publication and baseline-admission flags remain false. Full semantic review,
implicit/overloaded workloads, resource/cost admission, disjoint calibration and
preregistered quality/non-inferiority thresholds remain unfinished.
