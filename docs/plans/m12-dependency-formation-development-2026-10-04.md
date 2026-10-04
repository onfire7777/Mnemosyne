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

Current status: corpus, hand-checked golden expectations and a separate
dependency-aware state scorer are implemented. The scorer resolves stored
intention IDs through full public snapshots, compares prerequisite action
identities, preserves duplicate schedules, and refuses missing-reference
evidence. Ambiguous duplicate prerequisite actions cannot earn dependency
credit. A real public-CLI creation/inspection regression verifies the mapping.
The original scorer is unchanged. Fixed public-only observation probes and inert
receipts now execute through the real ActionCLI. Evaluator-only timing comparison
retains all previously requested schedules, including cancelled and ineligible
ones, so unexpected firings remain false positives. Repeated probes cannot earn
extra correct firings. Integration tests explicitly provision golden tasks to
verify plumbing; they are not model runs. The complete provider-to-report runner is now available; saved-trace replay
and actual model measurements remain before claiming measured dependency formation. Full model execution,
broader language, held-out calibration and M12 admission remain open.


## Executable development runner

`python -m eval.public.action_dependency_run --output NEW_DIRECTORY
--provider-identity ID --timeout-seconds 120 -- PROVIDER_COMMAND ...` runs all
100 frozen cases with a bounded command provider. Each case has its own public
store and scope. The command receives only public conversation prefixes, current
public task snapshots, prior responses and the operation contract. It does not
receive the evaluator's prerequisite or firing labels.

The runner retains public inputs, provider configuration, source hashes, fixed
probes, ordered requests/responses, state/timing diagnostics and inert receipts.
Failure retains the attempted prefix and writes failed status without a success
artifact. No automatic response repair or retry is performed. Model identity
and filesystem isolation remain explicitly unverified. The extension has its
own execution/report schemas; it does not rewrite original-corpus receipts.

Four runner tests cover a scripted successful dependency through actual public
commands, an always-clarifying provider with visible misses, malformed output,
and observation failure. Scripted tests are pipeline conformance, not model
quality. Full-corpus real-provider execution and saved-trace verification remain
open, alongside the original M12 acceptance requirements.
