# Compact ONNX native execution development check

Source: clean `5cce12c6fae7a9eb0d9aa5c85aa3673747800a91` on macOS ARM64.
This is source/runtime integration evidence, not a memory benchmark score.

The optional native adapter executed a 314-byte synthetic graph with Python
ONNX Runtime 1.28.0 and Rust ort 2.0.0-rc.13. Five cases at sequence lengths
1/64/128/384/512 matched every FLOAT32 output bit. Extra-output, short-output,
non-finite, segment-ID and expired-deadline checks passed. The complete native
suite passed 48 tests and exited successfully. Clippy, formatting and 23 Python
BurnOS/compact-provider tests passed. Raw command results and hashes are in
`verified/validation.json`; the exact generated graphs and Python outputs are
in `fixture/`. Reproduction is documented in `services/answering-ort/README.md`.
The new Linux CI job is prepared but has not yet run on this source.

## Failures retained

The initial ort rc.10 / ONNX Runtime 1.22.1 experiment matched tensors but its
test process terminated with SIGABRT during native environment destruction.
This operator note is a summary of that tool-observed failure, not a raw log.
The macOS crash frames named `onnxruntime::Environment::~Environment()` and
`__cxa_finalize_ranges`. The current binding contains environment shutdown
handling; the replacement was tested including process exit. See the related
[upstream macOS shutdown report](https://github.com/microsoft/onnxruntime/issues/24579).
No crash suppression, forced successful exit, or leaked session was added.

A later clean-source full-suite invocation launched via Apple's system Python
failed to link because its injected `SDKROOT` selected MacOSX27.0.sdk and the
linker rejected that SDK's arm64e.x1 architecture. The complete failed log and
receipt are preserved in `failed-sdk-invocation/`. Repeating via the existing
verified project Python environment, with no injected SDKROOT, succeeded; code
was identical and the successful receipt records that environment difference.

## Remaining scope

The default server still has no configured learned reader. Tokenizer and raw
source offsets, complete multi-task/no-answer decoding, actual model selection,
memory-mapped loading, authenticated serving integration and end-to-end parity
remain open. No learned weights or protected data were loaded. The model byte
cap is not measured peak RSS; no 8 GiB, admission, quality or superiority claim
is established. Historical failed attempts remain failures.
