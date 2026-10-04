# Proof-site preparation and local reader receipt

Date: 2026-10-04. This receipt advances original Plan B L2/L3 and real-run
preparation; it does not close those deliverables or replace Plans A/B.

## Implemented and checked

The existing static renderer now supplies a responsive results table, explicit
empty state, methods reading guide, and consistent result/trace navigation.
Rows preserve record IDs, operator and publication disclosures, supplied
uncertainty and immutable artifact digests. Missing intervals are labeled as
missing; the renderer does not invent a confidence level or a universal ranking.

The CLI supports an empty JSON array without trace mappings. Nonempty results
still require validated trace mappings and existing artifact custody checks.
An empty preview can be generated without synthetic leaderboard entries:

```sh
printf '[]\n' > /tmp/mnemosyne-empty-results.json
python -m leaderboard.render /tmp/mnemosyne-empty-results.json /tmp/mnemosyne-proof-preview
python -m http.server 8791 --bind 127.0.0.1 --directory /tmp/mnemosyne-proof-preview
```

Validation: 352 tests passed across render, output smoke, publish, readiness,
result contract and signed ledger modules. Ten governance/publication-policy
tests passed; Ruff passed for changed Python files. The broader repository
suite remains in progress with four certificate-rotation failures; these
focused passes are not an all-suite or release-readiness claim.

Browser checks used the actual generated pages: Results → Methods → Results;
an explicitly labeled synthetic UI fixture → run disclosures → result →
question trace. This checks navigation only, not measured system quality.
At 390px the empty page has 390px document width and no horizontal overflow.

Visual comparison against the generated desktop concept retained: (1) white
background and navy text; (2) serif headline hierarchy; (3) Results/Methods
navigation; (4) five-column bordered table; (5) explicit empty evidence state;
(6) two explanatory columns, stacked on mobile; (7) operator-entry footer.
The implementation uses a narrower centered content area and native system
body type, so wrapping differs from the concept. Primary copy is preserved.
Local screenshots are in the ignored completion evidence directory.

## Reader runtime restored

Official Ollama 0.35.1 macOS distribution installed in the user's Applications
directory. Deep strict code-signature verification passed; signing authority
is Infra Technologies, Inc. The service binds to `127.0.0.1:11434`.

- CLI SHA-256: `5f0e245e8369a66b7b24654c51c8ec95f3eab9a1e263f6e95e20d2d4374b8e26`.
- Model: `qwen3:8b`, Q4_K_M, 5,225,388,164 bytes as reported by `/api/tags`.
- Installed manifest digest matches the planned pin:
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Generic smoke prompt requested the word `READY`; generation returned `READY`
  with `done=true`. It used no benchmark input or protected attempt.
- Host: arm64 Mac, 16 GiB RAM. This does not satisfy physical 8-GiB
  Windows/Linux acceptance or establish performance results.

## Remaining evidence and delivery

| Requirement | Current state / next evidence |
|---|---|
| Original raw benchmark artifacts | Referenced local artifact directory absent; recover or create new properly registered runs, never synthesize old evidence. |
| Frozen Phase 12 v19 candidate | Original external manifest absent; preserve its identity and historical attempt records. Do not recreate a manifest and claim the old digest. |
| Canonical scale gate | Evaluator and unprotected `qa_scale_dev_v1` exist. Exact candidate/runtime-bound 24-case passing receipt still needed before protected execution. |
| Real comparisons | Current-version registered runs under the same protocol, budgets and supported adapters; retain failed attempts and disclose absent systems. |
| L2 completion | Public versioned data, permanent URLs, deployed site, data mirror and at least one real fully browsable system remain unverified. |
| L3 completion | The reading guide is a start. Primary-source-reviewed system architecture explainers and full transparent methodology remain to publish. |
| Launch | Register A real evidence, methods paper, populated adversarial report and operational public dispute channel remain open. |

`BOARD-STATUS.md` now distinguishes implemented tools from missing launch
evidence. No gate was removed or marked satisfied by this receipt. BurnOS
production APIs and transport behavior are unchanged by the renderer work.
