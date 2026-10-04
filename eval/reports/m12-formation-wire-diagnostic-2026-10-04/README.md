# Formation wire-order diagnostic

The failed HTTP input from the 21-case attempt succeeded once on a diagnostic
repeat with source `30184aeb`. It still produced an unnecessary clarification.
That does not identify or resolve the original HTTP cause.

A four-cell follow-up at source `a927ee4e` held that same public input, prompt,
schema meaning and generation settings fixed, varying two installed models and
two HTTP JSON key orders. All four raw requests/responses are retained. These
are single-input diagnostics; no proposed task was executed.

| Model | Alphabetically sorted keys | Declared schema key order |
|---|---|---|
| Qwen3 0.6B | Clarification, no operation | One exact-time task |
| Qwen3 1.7B | Clarification, no operation | One exact-time task |

The request requires an event trigger with a not-before time. Neither proposed
task preserves the event condition. The results demonstrate order sensitivity
on this input, not correct formation, general causal attribution or comparative
memory-system quality. They qualify the earlier over-clarification finding:
the tested adapter configuration contributed to the observed behavior; it
cannot be attributed solely to intrinsic model ability.

The old transport sorted schema keys, placing `clarification` first. Declared
order places `operations` first. The provider now retains exact request bytes
and their hashes so this difference is visible even though JSON objects compare
semantically equal. The default remains canonical for historical continuity;
future variants must explicitly identify any changed order.

The four-cell monitor completed in about 10.15 monotonic seconds. This is not a
resource-admission result. Earlier failures remain intact; no successful full
formation benchmark or ranking follows from these diagnostics.

Executed source scripts are archived with `.py.txt` suffixes to retain their
exact bytes as evidence snapshots, rather than treating them as maintained
project modules. The manifest maps these names to their original paths.
