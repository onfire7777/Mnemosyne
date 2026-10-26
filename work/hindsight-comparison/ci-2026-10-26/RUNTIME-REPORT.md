# CI failure investigation and runtime completion fix

The investigated CI run is [40400787108](https://github.com/onfire7777/Mnemosyne/actions/runs/40400787108), at ancestor commit `b63b34616f65e31457f3bc243b158d479f734e68`. The local checkout was `97091695` before these fixes. This is not a claim that the later CI run passed. No workflow rerun was dispatched.

## Observed failures

- [Postgres integration](https://github.com/onfire7777/Mnemosyne/actions/runs/40400787108/job/121845744435) stopped in `postgres-role-check`, before live tests. The report found `documents` outside the app DELETE allowlist; all eight other role checks passed. `infra/postgres/roles.sql` explicitly grants DELETE on `documents` for table-owner branch cascades, and `sql/schema.sql` defines its branch foreign key with `ON DELETE CASCADE`. The validator still listed only four older exceptions. This is a validator/schema mismatch, not a reason to widen role grants. The root agent owns its narrow CLI/test correction. Exact output: [postgres-role-check.log](postgres-role-check.log).
- [Compact ONNX tensor parity](https://github.com/onfire7777/Mnemosyne/actions/runs/40400787108/job/121845744505) installed its pinned dependencies and compiled successfully. Its library suite stopped at 47 passed / 1 failed: `synthetic_components_share_protocol_runtime_and_preserve_identity` expected a span but `read.result` was `None`. The assertion did not print the error code. Exact output: [onnx-runtime-failure.log](onnx-runtime-failure.log).

Both affected code paths were unchanged between the failing ancestor and the reviewed head, apart from unrelated book CLI additions. The failures cannot be dismissed as obsolete checkout results or package-install failures.

## Runtime defect and correction

The inference worker sent its result while still holding the single-in-flight permit. A receiver could consume the result, immediately submit the next request, and receive `RuntimeBusy` before the prior worker dropped its permit. The synthetic test's immediate embed → rerank → read sequence exposed a failure consistent with this race. The original CI log alone does not prove which error code produced its missing result.

The worker now computes the result while owning the permit, then calls a small publication boundary that drops the permit before exposing success or failure. The local permit binding preserves unwind ordering when inference panics. Running inference continues to own admission after a caller times out; the change does not admit overlapping inference.

The deterministic regression invokes publication while checking that a new permit can already be acquired. With the original publish-before-release order, it failed immediately: [runtime-completion-before.log](runtime-completion-before.log). It passes after the ordering change for both success and error results. A second regression verifies that an inference panic releases admission before the disconnected-result response is visible, including an immediate second request.

## Verification

Environment: macOS arm64, installed Rust/Cargo 1.98.1, process-local `SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk`. All Cargo commands used cached dependencies with `--offline --locked`; no package installation, external provider, benchmark, or ONNX model execution occurred.

```sh
cargo test --offline --locked --manifest-path services/answering-ort/Cargo.toml --features onnx --lib runtime::tests::
cargo test --offline --locked --manifest-path services/answering-ort/Cargo.toml --features onnx
cargo clippy --offline --locked --manifest-path services/answering-ort/Cargo.toml --all-targets --features onnx -- -D warnings
cargo fmt --check --manifest-path services/answering-ort/Cargo.toml
```

- Runtime tests: **17 passed**, including completion ordering, panic, timeout/busy, identity, and the original synthetic component sequence. [Log](runtime-onnx-feature-tests.log).
- Complete crate: **51 passed**, **2 ignored**, zero failures. This comprises 50 library tests and one input-validation integration test. The two native ONNX fixture execution tests remain intentionally ignored. [Log](answering-ort-tests.log).
- Clippy with the ONNX feature and all targets: passed with warnings denied. [Log](answering-ort-clippy.log).
- Cargo format and diff whitespace checks: passed.

Frozen `services/answering-ort/src/runtime.rs` SHA-256: `94baec07be5a1bb2822a851659e2bcc2e046815b176128bf5cf9ef8861c34bbf`.

These local results establish the synthetic runtime fix and compilation/lint coverage. They do not replace execution of the ignored native parity fixtures or successful completion of GitHub's full CI matrix.

## PostgreSQL validator correction completed

The default allowlist now includes the already-granted `documents` cascade
permission. The regression derives narrow DELETE grants from `roles.sql` and
checks them against the expected set and CLI default. It failed before the fix
and all 16 role-check tests passed afterward. The live probe against the existing
disposable database passed all 9 checks with `app_user` and `consolidator_user`,
neither superuser nor RLS-bypassing. No database grants changed; app evidence/audit
deletion and all app TRUNCATE permissions remain disallowed by the check.

Evidence: [before](pg-role-default-before.log), [tests](pg-role-default-after.xml),
and [live restricted-role probe](pg-role-default-live.json).
