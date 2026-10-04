# Public condition semantics versus draft reference

A real public-CLI characterization on 2026-10-04 confirmed the contract question
identified during reference review. Run:

```sh
python -m pytest tests/test_public_condition_reference_boundary.py -q -o addopts=''
```

The test uses an isolated local store, authenticated `ActionCLI` scheduling,
condition injection and evaluation, plus the independent draft reference. All
conditions are due at the same injected time. It imports no product engine.

| Case | Operator | Expected value | Observed value | Public CLI fires | Draft fires |
| --- | --- | --- | --- | --- | --- |
| Scalar control | eq | true | 1 | no | no |
| Nested equality | eq | {"enabled": true} | {"enabled": 1} | yes | no |
| Nested inequality | ne | {"enabled": true} | {"enabled": 1} | no | yes |
| Nested membership | in | [{"enabled": true}] | {"enabled": 1} | yes | no |
| Exact nested control | eq | {"enabled": true} | {"enabled": true} | yes | yes |

The product currently checks outer types and uses Python equality for nested
contents. The draft uses recursive JSON identity. This test characterizes the
observable difference; it neither endorses the behavior nor declares a benchmark
winner. The current retained explicit/fan-out/recovery workloads do not exercise
these nested cases, so their equal metrics cannot establish broader equivalence.

Before admitting a shared baseline for these cases, the benchmark contract must
state the intended nested-value semantics and tests must enforce that decision.
Do not silently reinterpret old results or change the product API solely to make
it agree with the draft. If different policies are supported, identify them as
different conditions of evaluation. This is development conformance evidence,
not a calibrated or official benchmark run.
