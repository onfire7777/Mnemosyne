# Frozen quarantined TRAIN partition plan

Clean implementation: `db54506a`. The first execution used the complete
919-component, 220,744-row grouped corpus. No label, model score, or protected
result is an input. The fixed policy sorts components by descending size and
then ID, placing each in the partition with the largest remaining absolute
80/10/10 target deficit. Ties use train, selection, calibration. Whole groups
are indivisible, even when the resulting source balance is poor.

| Partition | All rows | SQuAD | Hotpot |
| --- | ---: | ---: | ---: |
| Train | 176,595 | 86,665 | 89,930 |
| Selection | 22,075 | 21,829 | 246 |
| Calibration | 22,074 | 21,825 | 249 |

`partitions.json` freezes all assignments with input and transformer hashes.
An independent membership count checked all 220,744 identities exactly once,
all 919 group IDs, partition totals and per-source counts (`audit.json`).
The preceding document-edge audit proves no shared key crosses groups.
Thirty-six focused corpus/BurnOS/provider tests passed.

This is a frozen plan, not admitted training data. Semantic entity resolution,
pre/post protected-overlap checks, whole-component exclusions and complete
attribution custody are unresolved. Later exclusions must remove whole
contaminated components without reassigning or rebalancing survivors. If later
entity resolution connects components assigned to different partitions, the
connected set must be excluded, not split or moved based on results. A changed
corpus/policy requires separately versioned custody; do not overwrite this plan.

The small Hotpot selection/calibration populations limit source-specific
precision and representativeness. The near-80/10/10 total split does not establish
balanced task coverage, benchmark quality, independence from protected data,
or readiness to train. No model was loaded.

Reproduce into a new path:
`python -m eval.compact_answering.train_partitions /absolute/groups /absolute/new-plan`
