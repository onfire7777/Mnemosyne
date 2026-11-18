# Mnemosyne Memory Quality Implementation Plan

> **For Hermes:** Use subagent-driven-development and test-driven-development. Implement and independently review; do not stop at this plan.

**Goal:** Improve actual memory correctness, evidence selection, temporal reasoning, outcome learning, and reliability without inventing evidence, weakening safety, or tuning on held-out answers.

**Architecture:** Reuse the existing compiler, retrieval pipeline, conformal calibration, native LearningRuntime, storage engines and evaluation harness. Repair observed faults with red/green regressions before adding capabilities. Prove integration and separate synthetic mechanics, development-set performance, held-out evidence and production claims.

**Tech stack:** Python 3.12+, existing pytest/ruff environment, Local/SQLite/PostgreSQL, existing provider adapters. No new paid services or model downloads.

**Workspace:** Real checkout `/Users/admin/Desktop/Mnemosyne`, branch `hermes/memory-quality`, base `750041e327c0ef1ebeb1b0fb87ec1e82fcdd618d`. No clone. Personal databases, installed host hooks, external service settings, protected datasets and prior benchmark reports are not modified.

## Acceptance and scope

- Capture a baseline before changing each component. Initial selected baseline: 131 tests passed (compiler, calibration, temporal, abstention, quantized vectors, quality report contracts, experience runtime/credit).
- New behavior must fail a focused regression first, pass after the repair, and pass surrounding tests. Never regenerate golden outputs to conceal unexplained changes.
- Independent specification and code-quality review are required before delivery.
- Memory off/frozen/on comparisons use matched workloads. No fabricated outcomes, synthetic personal credit, weakened admission gates, or unsupported mechanism wins.
- No claim of global best memory, full safety, or broad learning benefit is made from unit tests or development diagnostics.
- Publishing, deployment, paid model evaluation and changes to personal memory require separate authorization.

## Work streams

### A. Evidence compilation and compact context

Inspect `src/mnemosyne/compiler_context.py`, `premise_verifier.py`, `answering.py` and their tests. Reproduce faults on freshly authored synthetic histories: irrelevant filler, cross-session comparisons, speaker attribution, negation, contradictory updates, quoted instructions, wrong-date attribution and constrained context. Fix source selection/packing/annotations without adding benchmark-specific words. Preserve source text and identity; expose truncation/omitted support rather than making an incomplete context look complete.

Verification: existing compiler/premise tests, new red/green cases, invariant checks on exact evidence text, stable budget limits, deterministic order. Compare development recall only; sealed inputs remain unopened for tuning.

### B. Confidence and abstention

Own `src/mnemosyne/calibration.py` and new `tests/test_calibration_fail_closed.py` / `tests/test_isotonic_calibration.py`. Test missing/invalid/nonfinite calibration, invalid confidence, empty prediction sets, tied isotonic scores, permutation invariance and persistence validation. Fail closed on unsupported confidence rather than clipping NaN into certainty. Only introduce learned calibration into serving if its scope/data provenance are explicit; never infer a tenant model from benchmark labels.

Verification: calibrated confidence, belief/calibration, adversarial abstention, specificity and engine contract tests. Record any downstream behavior change; do not lower quality/safety targets.

### C. Outcome learning and retention

Inspect production `experience/` and the existing learning harness. Run sufficient bounded development probes to distinguish unsupported prerequisites from actual failures. Repair demonstrable outcome attribution, lifecycle or retention faults; keep verified outcomes as the only reward. Assess concrete components rather than enabling new speculative mechanisms. No rewriting evaluation expectations to turn an unsupported run into a pass.

Verification: focused runtime/credit/retention/erasure tests and paired diagnostic reports with raw rows, runtime, seed, source identity and explicit limits. Full all-arm/multi-model/longitudinal acceptance remains open until actually run.

### D. Durable evidence and reminder audit semantics

Reproduce the PostgreSQL forgetting failure and classify tenant chaos failures. Fix loss of non-sensitive firing/audit receipts without retaining erased source content. Use an isolated disposable test database only; do not apply schemas to a personal DB. For chaos tests distinguish defective fixture preconditions from isolation violations.

Verification: same regression on Local/SQLite/PostgreSQL as available, source erasure checks, repeated forget, fired-receipt duplicate suppression, independent tenant controls.

### E. Evaluation provenance and usability

Strengthen `eval/run_quality_gate.py` receipts: record dirty state and content fingerprints, detect source drift during a run, distinguish historical/dirty diagnostics from release evidence, and optionally require a clean fixed revision. Test with temporary git repositories before running the existing gate. Do not rewrite historical reports. Fix false documentation/tool counts from runtime rather than regex counts.

Verification: provenance tests for clean/staged/untracked/modified sources and mid-run drift, current report contract tests, reproducible diagnostic on a fixed source tree.

### F. Retrieval configuration and integration

Audit the existing automatic local embedding/reranking discovery and expose it consistently through CLI/server only if it remains offline by default, explicit and tested. Assess retrieval multi-hop/facet/temporal improvements from reproduced defects; avoid a new parallel retrieval system. Test that sensitive evidence stays filtered before ranking and does not become visible through derived indexes.

## Audit item disposition (prior 49-item review)

| Prior items | Disposition |
|---|---|
| 1–9 learning validation/retention/portability | C; actual repairs plus bounded evaluation now, full-scale and real longitudinal evidence tracked separately |
| 10–14 multi-session/time/abstention/multi-hop/context | A/B/F; fix reproduced general faults, measure rather than promise a target score |
| 15–17 full-context/local/personal comparisons | Evaluation work; provider costs and private-data evaluation need separate approval; use offline development comparisons now |
| 18–24 benchmark freshness/provenance/calibration/docs | B/E; fresh independently authored unseen benchmark cannot be created by retuning existing held-out data |
| 25 inaccurate tool inventory | E; inspect runtime-composed tool list, not static regex |
| 26–29 CI/PG/isolation/macOS | D plus actual baseline investigation; external CI remains unverified unless run on exact final commit |
| 30 branch protection | Repository governance, not memory algorithm; no external setting changes in this scope |
| 31–32 test skips/golden baselines | Verification work; classify skip dependencies and preserve unexplained failing tests |
| 33–36 speed/scale/footprint | Measure selected real paths; 100K and production-load claims remain open until exercised |
| 37 encryption | Security design needs key lifecycle/recovery/migration specification; do not retrofit or re-encrypt personal stores silently |
| 38–43 scanning/contributing/release/name/install/adapters | Product/governance tasks outside this memory-quality implementation; no publishing or account mutation |
| 44–46 tool profiles/provider config/media extractors | F where directly useful; do not introduce model downloads or external extractor dependencies without approval |
| 47–49 maintenance/size/commit scope | Small owned-file changes, reuse modules, independent reviews; no wholesale risky rewrite |

## Verification commands

Use `.venv/bin/python -m pytest -o addopts='' -q -p no:cacheprovider <owned-tests>` from the checkout, writing logs under the Hermes scratch directory. Use `.venv/bin/ruff check --no-cache <changed files>`, then the repository lint. Run the full appropriate local regression suite after integrating (report skips and failures, not only exit status). Run exact-head independent reviews and record baseline vs candidate diagnostics in `docs/` with portable source references.

## Status

- Preflight complete: base pinned, clean checkout, no active local pytest run found; active host runtime services left untouched.
- Initial selected baseline: 131 passed.
- Investigation in parallel: compiler/evidence quality, learning/retention, Postgres/chaos.
- Implementation of streams A–F complete in the working tree (uncommitted). Independent review run; its
  confirmed findings were fixed with regressions. Results, pre-existing failures and open items:
  [`2026-11-16-memory-quality-diagnostics.md`](2026-11-16-memory-quality-diagnostics.md).
- Still open: commit and exact-head CI, held-out/longitudinal evaluation, and the items listed under
  "Known open items" in the diagnostics record. Not a release or quality claim.
