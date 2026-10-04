# Benchmark proof and website delivery

## Owner priority and present evidence

This document organizes execution only. It does not replace, narrow or amend
the original Plans A and B, accepted specifications, roadmap deliverables or
acceptance criteria. The owner reaffirmed on 2026-10-04 that all original plans
must still be followed as written. Every original requirement remains in scope;
website preparation and a subset of passing benchmarks cannot close the whole
program. Reconcile stale factual status against evidence without lowering gates
or silently dropping work.

On 2026-10-04 the owner reaffirmed the unfinished Plan B deliverables: a
website showing auditable benchmark evidence and real measurements against
other memory systems. This is the next priority after the current integration
gate, ahead of further development-only module expansion. Continue solo in
this chat, on `codex/development`, preserving BurnOS compatibility and the
two-branch workflow.

The static renderer, result schemas, signed ledger, publication validator and
launch-readiness code exist in `leaderboard/`. Their source completion does
not establish a deployed site, populated real-result pages, methods content,
or a completed launch. The original suggested `web/` tree is absent; reuse the
existing static renderer rather than introduce a second result authority.

`eval/reports/phase-11-evidence.md` records historical real-dataset retrieval
runs, including LongMemEval Recall@5 0.2806 on 500 records. These are explicitly
non-publishable historical results, not current-version measurements or proof
of superiority. On this machine the referenced
`/Users/admin/mnemosyne-public-artifacts` directory and the external candidate
directory are absent. The initially absent Ollama runtime and pinned Qwen3 8B
model were restored locally on 2026-10-04; a generic generation smoke check
passed. This is runtime availability, not benchmark evidence. See the
[delivery receipt](../coordination/2026-10-04-proof-site-and-runtime.md).
Do not reconstruct missing evidence from report numbers.

## 1. Finish the current verified integration

Resolve or precisely account for every current local-suite failure; complete
current-head CI and the self-review before merging PR #214. Preserve the
BurnOS HTTP regression and live PostgreSQL session checks. Synchronize Desktop
main, the development worktree and GitHub. Record actual test outcomes and
environment prerequisites rather than relabeling failures as passes.

## 2. Audit the real-run prerequisites

- Reconcile Register A's statements against the existing ledger, renderer,
  publication and readiness implementations. Distinguish implemented tools
  from missing signed run evidence and publicly available artifacts.
- Inventory benchmark assets by their already-approved registry revisions,
  hashes and rights; fetch only the permitted pinned assets needed for the
  next run. Preserve the distinction between development and held-out inputs.
- Inspect the current grounded-reader candidate, scale-preflight requirements,
  and any recoverable attempt records before creating a new candidate. Never
  overwrite old attempts or reuse a consumed protected attempt.
- Restore an appropriate local reader runtime from its official distribution,
  record exact executable/model digests and resource requirements, and verify
  it using unprotected development inputs first. This 16-GiB Mac is not
  evidence of physical 8-GiB Windows/Linux acceptance.

Deliver a concrete prerequisite inventory with ready, missing and blocked
items; no generic claim that all real benchmarking is externally blocked.

## 3. Prepare the visible proof site

- Exercise `leaderboard.render` with validated inputs and inspect the actual
  rendered pages. Keep any synthetic demonstration unmistakably labeled and
  separate from real results; never use it to fill an empty leaderboard.
- Complete the Plan B L2/L3 surface using the existing result authority:
  result tables, confidence intervals, system/configuration disclosures,
  per-question stored/retrieved/answer traces, downloadable evidence, methods,
  and a plain-language distinction between retrieval and answer quality.
- Show missing measurements and competitor coverage honestly. Do not present
  historical report values as verified current data when their bundles cannot
  be inspected. A preparation preview may be empty of eligible results.
- Produce a local, reviewable site and test its links, trace navigation,
  disclosure labels, escaping and deterministic output before deployment.

## 4. Produce real, reproducible measurements

Freeze a clean candidate and explicit experiment registration before scoring.
Use the existing public harness, approved dataset pins, isolated scorer labels,
recorded configuration, resource bounds and append-only attempt history.
Complete the required development/scale gates before any protected QA attempt.
Retain failed and aborted attempts as well as successes. Reproduce each
eligible result from its immutable bundle in a clean checkout; a unit test or
synthetic round trip does not satisfy REPRO-002.

For comparisons, freeze a roster and run each supported system under the same
protocol and disclosed budgets. List absent systems with their reasons. Do not
treat published vendor numbers from different settings as head-to-head results.
Report quality, uncertainty, latency, cost and resource use separately. Publish
losses and limitations. "Best" requires evidence for a precisely named track
and comparison set; it is not an assumed outcome or a universal claim.

## 5. Close publication and launch

Populate Register A with actual evidence, including signed preregistration,
roster-to-ledger completeness, reproduction, methods, adversarial self-report,
public dispute process and permitted public assets. Keep the optional external
board separate from these source-owned tasks. Preserve operator-entry labeling.

Run the existing publication and readiness checks on the real release inputs.
Prepare the final site and deployment details for the owner's publication
approval; do not ask them to approve an unspecified or unfinished site. After
authorized deployment, verify the public URL and download/trace paths. Only
then update the corresponding Plan B and roadmap deliverables as complete.
