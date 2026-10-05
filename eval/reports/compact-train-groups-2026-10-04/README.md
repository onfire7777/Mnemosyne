# TRAIN source-document connectivity

Implementation: `51bb3975`, run on the full quarantined staged dataset whose
SHA-256 is bound in `summary.json`. This uses the standard library; no model or
protected dataset was loaded. Membership stays outside Git at
`/Users/admin/.local/state/mnemosyne/compact-train-groups-2026-10-04/groups.jsonl`.

The deterministic policy joins rows sharing any document title alias or
normalized context, including all Hotpot distractors. Context normalization
uses NFKC, casefold and whitespace collapse. Title aliases additionally decode
URL escapes, HTML entities and underscores. These mechanical aliases are not
complete semantic entity resolution. Transitive components have stable IDs
(the minimum hashed upstream identity), independent of input row order.

The run found **919 components across 220,744 rows**, using 982,911 distinct
document keys. The largest component contains **152,706 rows**: 89,667 Hotpot
and 63,039 SQuAD. Outside it remain 758 Hotpot and 67,280 SQuAD rows. The full
component-size histogram is preserved in the receipt.

This is an actual split-design constraint: assigning the largest component to
training leaves relatively little independent Hotpot material for selection
and calibration. Random row splitting would break source-document isolation.
No row or title was removed to make these counts look better, and no partition
has been selected. A later policy must disclose the resulting source coverage;
it must not silently ignore distractors or split connected components.

`audit_groups.py` checks every membership against staged row identity/hash,
component ID minimum, complete row coverage, and every shared-document edge.
It reuses the named key normalizer but does not reuse the union algorithm.
Results are in `edge-audit.json`. The check proves no policy-defined shared
document crosses components, not complete semantic-entity independence.
Thirty-three focused TRAIN/BurnOS/provider tests and Ruff passed.

Reproduce into a new directory:

```sh
python -m eval.compact_answering.train_groups /absolute/staged /absolute/new-groups
PYTHONPATH=. python eval/reports/compact-train-groups-2026-10-04/audit_groups.py /absolute/staged /absolute/new-groups
```

All records remain quarantined. Protected overlap is unchecked; semantic
entity grouping, before/after transformation decontamination, whole-cluster
exclusions, immutable grouped partitions and full attribution custody remain
required. No training, quality, hardware admission or benchmark claim follows.
