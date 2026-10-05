# Dependency advisory repair

A public OSV query of the current Python/Rust lockfiles found three patched
vulnerability advisories and one maintenance advisory. `before.json` and
`after.json` retain the query results; `lock-identities.json` binds the scanned
lockfiles. The package count drops from 424 to 423 because both Rust components
now share the same crossbeam-epoch version already used by the ONNX service.

| Dependency | Previous | Updated | Advisory |
| --- | --- | --- | --- |
| crossbeam-epoch | 0.9.18 | 0.9.21 | [RUSTSEC-2026-0204](https://rustsec.org/advisories/RUSTSEC-2026-0204.html) |
| h2 | 0.4.15 | 0.4.16 | [RUSTSEC-2026-0258](https://rustsec.org/advisories/RUSTSEC-2026-0258.html) |
| rustls | 0.23.41 | 0.23.45 | [RUSTSEC-2026-0285](https://rustsec.org/advisories/RUSTSEC-2026-0285.html) |

Cargo also updates rustls-webpki from 0.103.13 to 0.103.15 to satisfy the patched
rustls dependency. Updates are limited to the two affected Cargo lockfiles.
There are no protocol, authorization, model or dataset changes.

The remaining [paste advisory](https://rustsec.org/advisories/RUSTSEC-2024-0436.html)
is an unmaintained-crate notice, with no patched version. It remains visible;
no advisory is suppressed. A clean version-based vulnerability query is not a
proof of exploitability, complete security, or runtime behavior.

GitHub separately reported a critical alert on default-branch push. Its private
alert page was unavailable in the signed-out browser session, so these fixes
must not be described as verified resolution of that particular alert. The
current development locks, not the default branch, were queried here.

## Validation

On macOS ARM64 with two Cargo build jobs: the native crate passed six tests
(`cargo test --locked --manifest-path rust/mnemosyne-native/Cargo.toml --no-default-features`;
PYO3_PYTHON pointed to the existing verified project Python). The provider crate
passed sixteen tests (`cargo test --locked --manifest-path rust/mneme-providers/Cargo.toml`).
The optional model-enabled dependency path compiled successfully with
`cargo check --locked --manifest-path rust/mneme-providers/Cargo.toml --features models`.
This last check compiles the actual updated TLS/HTTP dependencies but does not
load models or establish end-to-end learned inference quality.

Twenty-three Python BurnOS/compact-provider compatibility checks passed;
repository Ruff and diff checks passed. This is a summary of observed command
results, not retained raw test output. Remote CI for these changes remains
pending. Existing in-progress CI belongs to the earlier development commit.
