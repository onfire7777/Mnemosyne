# Dependency formation development extension

This separately versioned extension implements the missing dependency-language
corpus portion of M12. It does not change the original frozen 220 conversations.
The generator and fixture use `m12-dependency-formation-corpus/v1`, with 100
conversations: five seeds, four weekly dates and five controls per date.

The user first asks for an approval reminder, then a publication reminder gated
on the approval reminder firing. Dependency labels use action identity rather
than candidate-chosen task IDs or engine intention IDs. The scorer must resolve
observed dependencies through public inspection; it must not give labels to the
formation provider or create the expected schedule on its behalf.

Controls cover satisfied and unsatisfied prerequisites, cancellation of the
dependent, cancellation of the prerequisite without unlocking the dependent,
and an unrelated reminder firing while the prerequisite remains pending.
Repeated observations at 3600 and 3601 seconds expose duplicate execution.
Observation ends at 7200 seconds; late prerequisites are at 10800. An unsatisfied
prerequisite within this horizon is not a permanently impossible dependency.

The dependency becomes eligible at 3601, after the prerequisite's 3600 probe,
so results do not assume same-tick ordering of engine evaluations. Cancellation
turns occur before all probes. Public projections preserve prefixes and exclude
all evaluator labels. Public inputs and labels are stored separately with hashes.

Current status: corpus and hand-checked golden expectations only. The existing
formation bridge can supply these public conversations, but the original state
and timing scorers are not yet extension-aware. Add dependency identity
normalization, per-case execution, inert receipts, timing comparison and saved
trace replay before claiming measured dependency formation. Full model execution,
broader language, held-out calibration and M12 admission remain open.
