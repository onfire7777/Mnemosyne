# Evaluation report disclosure audit

This receipt audits the 37 report artifacts that existed under `eval/reports/`
before this receipt was added. It distinguishes executed engine metadata from
configured adapter labels and does not infer an undisclosed model, provider, or
custody state.

## Findings and disposition

| Report family | Files audited | Executed system and model disclosure | Custody disposition |
|---|---:|---|---|
| Root, `before/`, and `after/` SLO reports | 18 | Their JSON `meta.backend` is `local`; model/provider identity is limited to each report's recorded embedding path. | Historical local harness output; no publication claim. |
| `after_postgres/` SLO reports | 5 | JSON `meta.backend` is `postgres`. Two Markdown projections incorrectly used a hard-coded local-engine paragraph; the renderer and both projections were corrected from their retained JSON without altering measurements. | Historical harness output; no publication claim. |
| Phase 11 public bundle reports | 4 | The public CLI executed the `local` engine. `postgres-recursive-ppr` is only the configured/self-reported graph-backend label. No reader or judge ran. | Source/reproduced bundles and external reports verify; all remain non-publishable, non-headline, and not independently reproduced. |
| Phase 12 graph baseline and Fix B receipt | 2 | Both explicitly disclose the local engine, no reader/model, no PostgreSQL, and development-only scope. | Non-headline, non-production development evidence. |
| Grounded-QA status | 1 | Discloses the exact local Ollama reader where a candidate used one and records unrun/abstained states literally. | Protected-attempt ledger boundaries remain in force; no held-out result is claimed. |
| Keystone proof | 1 | Separates the ignored local adapter flags from the genuinely exercised Postgres path and names the observed retrieval services/judge. | Diagnostic evidence, not a PBPP headline result. |
| Replay fidelity | 2 | No backend/model claim is made; the files report replay-store diagnostics only. | Local diagnostic output. |
| Scope conformance | 1 | Missing real-model deployment evidence is stated as deferred rather than inferred. | Local conformance diagnostic. |
| Harness/charter notes (`m1.1`, `m4`) | 2 | No executed backend/model result is claimed. | Policy and harness status notes. |
| `suite_state.json` at the report root | 1 | Per-suite notes disclose `backend=local`; no model identity is inferred. | Local harness state. |

## Digest-bound verification

The retained source and reproduced bundles for LongMemEval, MuSiQue, 2Wiki,
and HotpotQA were verified with the pinned `mneme eval-public` verifier. Their
`traces.jsonl` and `metrics.json` files match byte-for-byte, and each external
report verifies against its committed Markdown note. No bundle byte, metric,
trace, protected attempt, or held-out benchmark was changed or rerun.

## Remaining evidence boundary

The W1 development proof does not establish production-Postgres parity,
runtime readiness, grounded-reader QA, CAP-003, BENCH-005, or eligibility for a
protected attempt. Those remain separately admission- and operator-gated.
