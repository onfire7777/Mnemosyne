# Phase 12 Production TLS Validator Hardening Report

Date: 2026-07-12

## Status

The bounded production TLS validator hardening increment is implemented and
passes every authorized focused check. Heavy work remains blocked by the
unchanged 55% memory-admission floor; no full suite, model, index, benchmark,
exact-scale run, or protected capture was attempted.

## Scope and preserved boundaries

- Preserved both wrapper scripts' three-argument interface and the successful
  Vault output `production Vault TLS chain verified`.
- Reused the shared generic validator, shell/Python standard facilities, and
  the existing cryptography test fixture. No dependency was added.
- Did not change CA duration policy, Caddy, Vault, compose topology, runtime
  secrets, protected ledgers, benchmark gates, or Sections 31/33 rails.
- Preserved all pre-existing TLS recovery, runtime, state, runbook, and report
  changes in the worktree.

## RED -> GREEN -> REFACTOR evidence

### RED

Admission immediately before RED was 40% free memory, load averages
5.53/4.81/5.11, and no Ollama model resident.

Command:

```bash
uv run --locked pytest -q \
  tests/test_production_vault_tls_validator.py::test_production_tls_validator_rejects_missing_openssl_capabilities \
  tests/test_production_vault_tls_validator.py::test_production_tls_validator_rejects_encrypted_private_key_without_prompt \
  tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_dual_root_trust_pool \
  tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_noncanonical_caller_root \
  tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_symlinked_canonical_root
```

Observed result: all five tests failed for the intended reason. Each validator
returned `0` and its existing success output instead of rejecting the missing
rail. The short summary named exactly those five failures.

### GREEN

Minimal production changes were then made only in the MCP wrapper and shared
validator. Admission immediately before GREEN was 42% free memory, load
averages 5.41/4.89/5.12, and no Ollama model resident.

The exact RED command was rerun and produced:

```text
.....                                                                    [100%]
```

### REFACTOR

No refactor was needed. The production change already used the smallest shared
implementation: shell `case`, `awk`, and `cmp`, plus one empty `-passin`
source on the existing OpenSSL key-read command. The GREEN command remained
passing.

The private-key symlink and group-readable-key cases are characterization
tests for pre-existing fail-closed behavior; they required no production
change.

## Implementation

### Exact MCP client-auth trust pool

`validate-production-mcp-client-tls.sh` now resolves the canonical Caddy
client-auth root as:

```text
${MNEMO_SECRETS_DIR:-/secure/outside/repo}/stepca-acme-root.crt
```

Before calling the shared validator, the wrapper requires that canonical path
to be a regular non-symlink file containing exactly one PEM certificate and
requires the caller-supplied root to be byte-identical via `cmp -s`. This
rejects the broader two-root compatibility bundle even when it can validate
the submitted leaf.

### OpenSSL capability prerequisite

`validate-production-tls.sh` resolves the selected `openssl` executable once,
probes its `verify -help` and `x509 -help` output before certificate
validation, and reports every missing required feature:

- `verify -verify_hostname`
- `verify -attime`
- `x509 -checkend`

This prevents an otherwise valid certificate from being misreported as a
chain error on an incompatible CLI.

### Non-interactive private-key validation

The existing `openssl pkey` read now uses `-passin pass:`. An encrypted key
therefore fails promptly with an empty supplied passphrase instead of reading
stdin or prompting. The real-behavior regression supplies the correct fixture
passphrase on stdin and proves that the validator still rejects the key within
three seconds while emitting neither the passphrase nor encrypted key bytes.

## Final authorized verification

Admission immediately before final verification was 42% free memory, load
averages 4.75/4.79/5.08, and no Ollama model resident.

An initial command construction used a zsh scalar as a multi-file argument;
`bash -n` therefore exited `127` before checking any file. No validator or test
failure occurred. After root-cause identification, the same authorized group
was rerun with explicit file arguments after a fresh 42%/4.75/no-model gate.

Final results:

- `bash -n` on all three validator scripts: PASS.
- `shellcheck` on all three validator scripts: PASS.
- `uv run --locked ruff check tests/test_production_vault_tls_validator.py`:
  `All checks passed!`.
- `uv run --locked ruff format --check
  tests/test_production_vault_tls_validator.py`: `1 file already formatted`.
- `uv run --locked pytest -q tests/test_production_vault_tls_validator.py
  tests/test_prod_bootstrap_tls_staging.py`: 18/18 passed.

The focused suite covers the required dual-root, noncanonical caller root,
canonical-root symlink, OpenSSL capability, encrypted-key, private-key
symlink, and private-key permission behaviors, along with the existing Vault,
MCP purpose/hostname, key-match, and expiry rails.

## Documentation and evidence boundary

- The production README now names exact trust-pool identity, required OpenSSL
  features, and encrypted keys among the fail-closed rails.
- State and grounded-QA evidence now report 18 focused TLS/bootstrap cases.
- The pre-existing live Vault/MCP evidence was preserved. No post-hardening
  live production validation was rerun in this focused stream; live validation
  remained optional under the brief and no secret-bearing path or value was
  printed.
- No candidate, exact-scale, held-out, or protected attempt was consumed.

## Pre-stage security sweep

The exact nine intended files were scanned by filename and content for private
key headers, common production credential prefixes, JWT-shaped values, risky
secret-file names, and oversized files. No credential signature or risky file
matched, and the largest intended file was 63,417 bytes. The passphrase in the
encrypted-key regression is an explicit synthetic fixture value only.

## Files in the increment

- `.planning/STATE.md`
- `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`
- `eval/reports/phase-12-grounded-qa.md`
- `infra/prod/README.md`
- `infra/validate/validate-production-vault-tls.sh`
- `infra/validate/validate-production-mcp-client-tls.sh`
- `infra/validate/validate-production-tls.sh`
- `tests/test_production_vault_tls_validator.py`
- `.superpowers/sdd/task-phase12-tls-validator-hardening-report.md`

## Remaining concern

The 55% heavy-work admission gate is still unmet. This increment is complete
for the authorized targeted surface, but the full suite and all protected or
benchmark work remain correctly blocked.
