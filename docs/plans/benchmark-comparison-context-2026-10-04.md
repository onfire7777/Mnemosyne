# Declared comparison context v1

This additive contract implements step 3 of the
[platform experience](benchmark-platform-experience-2026-10-04.md). It preserves
result-v1/v2 and projection-v1; candidate grouping is not a projection average.

New runs may include `comparison_context` in the digest-bound `config.json`.
It follows `leaderboard/schema/comparison-context-v1.schema.json`: the exact
schema version plus five SHA-256 digests of the frozen dataset, protocol,
preprocessing specification, scorer and model policy. Model policy includes
model versions, prompts, inference settings and tool budgets; explicit no-model
runs hash their no-model policy rather than supplying an invented model.
Legacy configurations without this field remain browsable and receive an
explicit unavailable-context exclusion from comparison candidates. Never alter
an existing signed configuration to add metadata retroactively.

The grouping implementation verifies all four raw result artifact digests,
validates the record and checks consistency against official lineage when
present. Context parsing rejects duplicate keys and malformed/unknown fields.
Digest declarations are **not** proof that the referenced policy was followed;
source admission, registration, actual policy artifacts and replay remain
separate evidence gates. The output reports `declared-context` compatibility,
no ranking and no publication authorization.

## Candidate population

Every group shares track, benchmark/version, module, division, resource profile,
model-policy ID, dataset split and all five context digests. Metric name, family,
unit and the complete judge identity are also identical. Thus an equally named
metric with a different scorer or judge prompt cannot silently share a group.

Hardware and backend differences remain visible in each atomic row. They split
performance groups because efficiency depends on those conditions. Quality
comparison candidates can include different systems/backends in the same
registered resource profile; this is not an efficiency equivalence claim.
System/build/adapter versions, seeds, runs and attempts stay visible in rows.
Only multiple distinct system IDs set `multi_system=true`; repeat attempts do
not manufacture competitor coverage.

Only measured records with passed safety gates and verified resource treatment
enter candidates. Non-measured states, missing context, invalid/broken artifact
bindings, lineage disagreements and duplicate full atomic identities (including system version, module and seed)
remain in exclusions. Duplicate metric identities within one atomic record are also excluded rather than counted twice. No failed gate is averaged away. Exclusions retain record
IDs so the original detail page and evidence remain reachable.

## Reproducibility and delivery

`data/comparison-index.json` is derived automatically during rendering. Source
IDs are sorted; the source digest hashes the sorted records using UTF-8 JSON
with sorted keys, compact separators and ASCII escaping. Group IDs similarly
hash their exact compatibility object. Input ordering cannot change selection.
Rows preserve original values and reported confidence intervals; the index
invents no confidence level, sample count or weights.

Remaining: interactive selection and URL state, side-by-side presentation,
registered policy-artifact admission, complete attempt-ledger integration and
eligible real competitor runs. Exporting an index does not complete those
requirements or the broader benchmark platform.
