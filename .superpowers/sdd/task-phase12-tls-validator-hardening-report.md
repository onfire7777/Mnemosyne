# Phase 12 Production TLS Validator Hardening Report

Date: 2026-07-12

## Status

The bounded production TLS validator hardening increment is implemented and
passes every authorized focused check. Heavy work remains blocked by the
unchanged 55% memory-admission floor; no full suite, model, index, benchmark,
exact-scale run, or protected capture was attempted.

## Independent review disposition

All Important findings from the independent review are resolved in a second,
non-amended fix cycle:

1. The MCP wrapper now rejects a caller root that is a symlink or not a
   regular file before `cmp`; a real FIFO regression proves the validator
   returns within one second instead of blocking.
2. The dual-root regression now leaves the canonical Caddy root as one
   certificate and supplies a separate two-root caller bundle. The canonical
   multi-certificate rejection remains as its own test.
3. The encrypted-key regression now requires empty stdout, the exact sanitized
   stderr line, absence of the fixture passphrase, and absence of every PEM
   payload line.
4. Exact raw RED/GREEN/final evidence for the review cycle is recorded below.
   The original five-test transcript limitation is stated rather than filled
   with reconstructed output.
5. State and grounded-QA evidence now distinguish preserved pre-hardening live
   evidence from post-hardening checks and explicitly state that live
   validation was not rerun after hardening.

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

### Initial five-behavior cycle

Admission immediately before RED was 40% free memory, load averages
5.53/4.81/5.11, and no Ollama model resident.

Exact command:

```bash
uv run --locked pytest -q \
  tests/test_production_vault_tls_validator.py::test_production_tls_validator_rejects_missing_openssl_capabilities \
  tests/test_production_vault_tls_validator.py::test_production_tls_validator_rejects_encrypted_private_key_without_prompt \
  tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_dual_root_trust_pool \
  tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_noncanonical_caller_root \
  tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_symlinked_canonical_root
```

Transcript-retention limitation: context-mode auto-indexed the 171-line RED
stream and returned search excerpts rather than the complete separated stdout,
stderr, or an explicit process exit status. Those missing fields cannot be
recovered exactly and are not reconstructed here. The exact retained short
summary was:

```text
=========================== short test summary info ============================
FAILED tests/test_production_vault_tls_validator.py::test_production_tls_validator_rejects_missing_openssl_capabilities
FAILED tests/test_production_vault_tls_validator.py::test_production_tls_validator_rejects_encrypted_private_key_without_prompt
FAILED tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_dual_root_trust_pool
FAILED tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_noncanonical_caller_root
FAILED tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_symlinked_canonical_root
```

The retained assertion excerpts show `assert 0 == 65` and the existing success
output. After the minimal production changes, admission was 42% free memory,
load averages 5.41/4.89/5.12, with no model. The exact command above was rerun.
The retained GREEN stdout was:

```text
.....                                                                    [100%]
```

The original GREEN transcript likewise did not retain separately labeled
stderr or an explicit numeric exit status; only the successful tool completion
and stdout above are available.

### Independent-review FIFO cycle

Two samples rejected admission before RED: 41% free/load1 11.55/no model and
41% free/load1 10.88/no model. No test or production edit ran under either
rejected sample. A first evidence-wrapper attempt after admission used zsh's
read-only `status` variable and did not preserve the test stream; it was treated
as a harness error and no production edit followed it.

The valid RED sample was 43% free memory, load averages 9.39/7.84/6.40, and no
model resident.

Exact RED command:

```bash
uv run --locked pytest -q tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_fifo_caller_root_promptly
```

Exit status: `1`

Exact stdout:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
__ test_production_mcp_client_tls_validator_rejects_fifo_caller_root_promptly __

tmp_path = PosixPath('/private/var/folders/c9/0hq50vks4fj_mr_5zfqkgj380000gn/T/.ctx-mode-NfTiow/pytest-of-admin/pytest-0/test_production_mcp_client_tls0')

    def test_production_mcp_client_tls_validator_rejects_fifo_caller_root_promptly(
        tmp_path: Path,
    ) -> None:
        root, bundle, key = _fixture(
            tmp_path,
            hostname="mcp-client.mnemo.local",
            extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
            stem="mcp-client",
        )
        fifo_root = tmp_path / "caller-root.fifo"
        os.mkfifo(fifo_root)

>       proc = _run(
            fifo_root,
            bundle,
            key,
            validator=MCP_VALIDATOR,
            env=_mcp_env(tmp_path, root),
            timeout=1,
        )

tests/test_production_vault_tls_validator.py:547:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tests/test_production_vault_tls_validator.py:138: in _run
    stdout, stderr = process.communicate(stdin, timeout=timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/lib/python3.12/subprocess.py:1209: in communicate
    stdout, stderr = self._communicate(input, endtime, timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/lib/python3.12/subprocess.py:2116: in _communicate
    self._check_timeout(endtime, orig_timeout, stdout, stderr)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <Popen: returncode: -9 args: ['/Users/admin/Mnemosyne/infra/validate/validat...>
endtime = 1098658.644048291, orig_timeout = 1, stdout_seq = [], stderr_seq = []
skip_check_and_raise = False

    def _check_timeout(self, endtime, orig_timeout, stdout_seq, stderr_seq,
                       skip_check_and_raise=False):
        """Convenience for checking if a timeout has expired."""
        if endtime is None:
            return
        if skip_check_and_raise or _time() > endtime:
>           raise TimeoutExpired(
                    self.args, orig_timeout,
                    output=b''.join(stdout_seq) if stdout_seq else None,
                    stderr=b''.join(stderr_seq) if stderr_seq else None)
E           subprocess.TimeoutExpired: Command '['/Users/admin/Mnemosyne/infra/validate/validate-production-mcp-client-tls.sh', '/private/var/folders/c9/0hq50vks4fj_mr_5zfqkgj380000gn/T/.ctx-mode-NfTiow/pytest-of-admin/pytest-0/test_production_mcp_client_tls0/caller-root.fifo', '/private/var/folders/c9/0hq50vks4fj_mr_5zfqkgj380000gn/T/.ctx-mode-NfTiow/pytest-of-admin/pytest-0/test_production_mcp_client_tls0/mcp-client.crt', '/private/var/folders/c9/0hq50vks4fj_mr_5zfqkgj380000gn/T/.ctx-mode-NfTiow/pytest-of-admin/pytest-0/test_production_mcp_client_tls0/mcp-client.key']' timed out after 1 seconds

../.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/lib/python3.12/subprocess.py:1253: TimeoutExpired
=========================== short test summary info ============================
FAILED tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_fifo_caller_root_promptly
```

Exact stderr: empty.

The minimal production fix was a regular/non-symlink `$1` guard immediately
before `cmp`. Admission before GREEN was 40% free memory, load averages
7.94/7.60/6.35, and no model.

Exact GREEN command:

```bash
uv run --locked pytest -q tests/test_production_vault_tls_validator.py::test_production_mcp_client_tls_validator_rejects_fifo_caller_root_promptly
```

Exit status: `0`

Exact stdout:

```text
.                                                                        [100%]
```

Exact stderr: empty.

### REFACTOR

No production refactor was needed. The implementation remains the minimum
shared code: shell type guards, `case`, `awk`, and `cmp`, plus one empty
`-passin` source on the existing OpenSSL key-read command. Test process-group
cleanup was made explicit so a failed timeout regression cannot leave a FIFO
reader behind.

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
requires the caller-supplied root to be a regular non-symlink file before
requiring byte identity via `cmp -s`. This prevents FIFOs and other special
files from reaching a blocking comparison and rejects the broader two-root
compatibility bundle even when it can validate the submitted leaf.

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
three seconds with empty stdout and one exact sanitized stderr line. It also
checks the passphrase and every PEM payload line independently for absence.

## Final authorized verification

Admission immediately before the final post-review group was 41% free memory,
load averages 6.45/7.31/6.29, and no Ollama model resident.

Exact executed verification body:

```bash
set -e
bash -n \
  infra/validate/validate-production-vault-tls.sh \
  infra/validate/validate-production-mcp-client-tls.sh \
  infra/validate/validate-production-tls.sh
printf 'bash-n: PASS\n'
shellcheck \
  infra/validate/validate-production-vault-tls.sh \
  infra/validate/validate-production-mcp-client-tls.sh \
  infra/validate/validate-production-tls.sh
printf 'shellcheck: PASS\n'
uv run --locked ruff check tests/test_production_vault_tls_validator.py
uv run --locked ruff format --check tests/test_production_vault_tls_validator.py
printf 'ruff-and-format: PASS\n'
uv run --locked pytest -q \
  tests/test_production_vault_tls_validator.py \
  tests/test_prod_bootstrap_tls_staging.py
git diff --check
printf 'git-diff-check: PASS\n'
```

Exit status: `0`

Exact stdout:

```text
bash-n: PASS
shellcheck: PASS
All checks passed!
1 file already formatted
ruff-and-format: PASS
....................                                                     [100%]
git-diff-check: PASS
```

Exact stderr: empty.

The focused pytest result is 20/20 passed.

The focused suite covers the required FIFO/nonregular caller root, true
dual-root caller bundle, multi-certificate canonical root, noncanonical caller
root, canonical-root symlink, OpenSSL capability, encrypted-key, private-key
symlink, and private-key permission behaviors, along with the existing Vault,
MCP purpose/hostname, key-match, and expiry rails.

## Documentation and evidence boundary

- The production README now names exact trust-pool identity, required OpenSSL
  features, and encrypted keys among the fail-closed rails.
- State and grounded-QA evidence now report 20 focused TLS/bootstrap cases and
  distinguish pre-hardening live evidence from post-hardening checks.
- The pre-existing live Vault/MCP evidence was preserved. No post-hardening
  live production validation was rerun in this focused stream; live validation
  remained optional under the brief and no secret-bearing path or value was
  printed.
- No candidate, exact-scale, held-out, or protected attempt was consumed.

## Pre-stage security sweep

The initial exact nine-file increment and the review fix's exact five changed
files were scanned by filename and content for private-key headers, common
production credential prefixes, JWT-shaped values, risky secret-file names,
and oversized files. Both sweeps returned no credential-signature match; the
review-fix files were all below 64 KiB (largest: 63,526 bytes). `git diff
--check` passed. The passphrase in the encrypted-key regression is an explicit
synthetic fixture value only.

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
