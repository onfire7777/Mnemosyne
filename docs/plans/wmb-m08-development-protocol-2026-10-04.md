# M08 development protocol and remaining freeze decisions

Status: proposed implementation detail for the original M08 contract; not
admitted, preregistered, runnable or a completed C10 capability. The parent is
[wmb-m08-reversible-forgetting-implementation-plan.md](wmb-m08-reversible-forgetting-implementation-plan.md).
This document supplies concrete candidate semantics for review/implementation;
remaining decisions below must be resolved before calling the protocol frozen.

## Public operation boundary

Use a module-local adapter contract until the shared ABI explicitly includes
delete/restore. Do not silently extend `wmbs/0.1-draft`.

- A selector contains exact `tenant_id`, `branch_id` and an ordered, nonempty,
  duplicate-free list of public source handles obtained from ingestion. No
  substring matching, wildcard tenant, inferred global scope or engine handles.
- `delete(selector, mode="reversible")` returns a receipt with a unique operation
  ID, the exact selector, mode, outcome and adapter version. Outcome is one of
  `completed`, `failed`, `aborted`, `unsupported`; attempted work is retained.
  A completed receipt is an operation report, not evidence that probes pass.
- `restore(receipt)` is optional and explicitly declared before execution.
  A receipt from a different tenant, branch, adapter or operation must not
  authorize restoration. A failed/aborted/unsupported delete cannot be restored
  as though it completed. Restoration is not emulated by re-ingestion.
- Each adapter declares retained recovery material, its access boundary and
  interaction with subsequent irreversible deletion. Existing Mnemosyne
  `tombstone_recompute` clears content and is not automatically this operation.
- Unsupported delete means the cell is unsupported and receives no numeric
  quality result. Unsupported restore excludes only restore-specific probes;
  it does not excuse failed delete probes or disqualify supported deletion.

## Population and ordering

Use at least five declared seeds and two delete/re-ingestion cycles per case.
Each seed generates separate exact, paraphrase, multi-hop, re-ingestion,
unrelated-control and optional restore case families. Case identity includes
seed, family, cycle and generation; preserve that identity through every trace.
Bound event counts before execution; do not stop after favorable outcomes.

Every case first ingests its target and control facts into the SUT, retaining
public handles. Verify the baseline through public retrieval and answering.
Do not remove cases that fail baseline; report baseline failures and preserve
them in the declared source population. Gold answers and probe classifiers
remain outside the SUT; target canaries themselves must enter the SUT.

Each deletion cycle records the request and receipt, then exact, paraphrase,
multi-hop and unrelated-control probes. Re-ingestion cases subsequently ingest
an explicitly new generation with a different canary and public handle, then
probe old and new facts separately. Reappearance of the deleted generation is
contamination; inability to retrieve the new generation is a separate utility
failure. Duplicate re-ingestion of the identical generation is an additional
anti-resurrection probe, not evidence of successful new learning or restoration.

Restore cases use independent fresh stores with the same generated baseline,
then delete, restore through the declared public hook and probe original facts
and unaffected controls. This avoids assuming every system supports snapshots
or branches. Later legal-erasure and conflicting-update cases remain mandatory
before making a production restoration claim; they are not covered by the
isolated baseline restore case.

## Observations, metrics and denominators

Retain exact public retrieval payloads, ordered source handles, answer text,
operation receipts, errors and timing. An explicit answer abstention is an
observed response. A timeout, missing response or failed operation is not an
abstention. Duplicate/foreign probe IDs invalidate the trace rather than being
silently deduplicated. Every expected probe has an explicit terminal state.

- Direct leakage: scan both returned retrieval content and answer text for the
  exact case-sensitive UTF-8 canary. Report leaking probes / observed eligible
  post-delete probes, and both counts. Normalized or paraphrased disclosure is
  a different metric; exact scanning alone does not establish semantic safety.
- Semantic leakage: use a versioned, independent harness grader with declared
  equivalence rules and calibration. Report attributable leaks / observed
  eligible semantic probes. A system's own leakage flag is not a grade.
- False removal: report unaffected controls that passed baseline but fail the
  corresponding post-delete probe / observed controls that passed baseline.
  Also publish total controls and baseline failures to expose selection effects.
- Unrelated utility loss: on paired baseline/post-delete control observations,
  report baseline success rate minus post-delete success rate in percentage
  points. Keep signed changes, pair counts and missing pairs visible.
- Restore correctness: original facts and unaffected controls must both satisfy
  the declared restoration assertions. Report correct observed restore cases /
  observed eligible restore cases, alongside failed/missing operations. Do not
  infer this metric from successful ingestion of replacement facts.
- Re-ingestion contamination: report probes disclosing deleted generations /
  observed eligible old-generation probes; report new-generation utility
  separately. Never blend the two into a favorable average.

For every metric retain full expected population, observed denominator, and
missing/failed/aborted/unsupported counts. Empty denominators produce null,
never zero. Incomplete populations are incomplete even when an observed-only
rate meets a threshold. Descriptive Stage A supplies no invented confidence
intervals or general-population safety claim. Storage and operation costs stay
separate from quality; no weighted overall score.

Original acceptance remains zero exact leakage, semantic leakage at most 1%,
unrelated utility loss at most 0.5 percentage points and 100% restore correctness
when restoration is claimed. All applicable evidence must be complete, with
resource admission and the original run-governance requirements independently
satisfied. A numerical rate alone cannot discharge those gates.

## Decisions still required for freeze

1. Close the trace/observation schema. Operation request/receipt schemas and field bounds are now implemented below; the complete protocol is not yet frozen.
2. Exact seed list, deterministic generation algorithm, per-family population,
   canonical canary-digest algorithm and byte-identical fixture artifact.
3. Semantic-grader definition, source/model pins if applicable, calibration and
   attribution rules; controlled synthetic paraphrases alone cannot establish
   general semantic leakage coverage.
4. Public Mnemosyne reversible-delete capability and retained-data policy, or an
   explicit unsupported adapter result. No current tombstone proxy is admitted.
5. Restore conflict/legal-erasure rules when restore is offered, without
   reviving superseded, unauthorized or irreversibly erased information.

These are finite implementation tasks, not grounds to remove M08 from scope.
The full fixture, scorer, public execution, resource receipt and acceptance
measurements remain required by the parent plan.

## Implemented operation contract v0.1

`eval/public/schema/wmbs-m08-operation-v0.1.schema.json` now defines closed
module-local delete/restore requests and receipts. Identity strings are bounded
to 256 characters without control characters, source sets to 1–128 unique
handles, and failure explanations to 1–2,000 characters. Successful receipts
require a null reason; failed, aborted and unsupported receipts require an
explanation. Only mode `reversible` is accepted. Unknown fields are rejected.

`eval/public/m08_contract.py` validates messages and cross-message bindings.
Tenant, branch, ordered source handles, adapter/version and operation IDs must
match. Restoration requires a completed embedded delete receipt, the same
scope/adapter, a new operation ID and the matching delete-operation reference
in its response. These checks establish shape and reference consistency, not
signatures, authorization, truthful execution or a passing benchmark.

Seventeen contract checks pass, covering a valid full exchange and mismatched
identity/scope, duplicate/empty selectors, mode substitution, extra approval
claims, incomplete failure disclosures and invalid restoration predecessors.
Ruff passes. The shared ABI and current product deletion semantics are untouched.
The trace schema, generator, semantic grader, product capability, resource
admission and complete measured acceptance remain open.

### Ordered operation custody

The module-local validator now also checks an ordered list of request/receipt
exchanges, bounded to 10,000 operations. Every exchange must contain its request
and terminal receipt, operation IDs may not repeat, and a restore must embed
the exact completed delete receipt already present in the preceding sequence.
Matching fields within a forged restore request are insufficient. Failed and
aborted operations remain valid terminal observations rather than disappearing.

All 25 contract checks pass, including future/missing deletion references,
reused IDs, altered embedded scope, a failed deletion misrepresented as completed,
missing terminal receipts and undeclared exchange fields. Ruff passes. These
checks do not establish authenticity, authorization, actual effects or full
fixture population coverage: detecting an entirely omitted planned exchange
still requires comparison against the frozen fixture, which remains open.
