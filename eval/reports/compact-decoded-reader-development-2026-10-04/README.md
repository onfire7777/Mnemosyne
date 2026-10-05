# Compact decoded-reader development evidence

Clean source: `fe753290ee31a4d822d00d625d9d1541095b0045`.
Platform: macOS ARM64; ONNX Runtime 1.28.0, Rust ort rc.13,
tokenizers 0.22.1. This is synthetic integration evidence, not learned QA quality.

The 314-byte arithmetic graph and generated tokenizer produced matching Rust
and independent Python decoded outputs for ten cases. These cover composed and
decomposed Unicode, CJK, repeated answers, multiple documents, later windows,
empty evidence, and null outputs. Native integration also checks segment IDs,
invalid tensors, deadlines, source custody, tokenizer limits and deterministic
window coverage. See the exact fixture and raw native log for assertion scope.

All commands in `validation.json` exited successfully: 51 native Rust tests,
46 default-feature Rust tests, 23 Python BurnOS/provider compatibility tests,
Clippy and formatting. Logs and generated fixture bytes are retained verbatim.
Run commands use operator-local environment paths; portable reproduction steps
are in `services/answering-ort/README.md`. The runtime library is identified by
hash but is not bundled. The source revision is the implementation revision,
not this later evidence commit.

No learned model or protected data was loaded. Full multi-task heads, real
model selection and quality evaluation, complete serving artifact/configuration
custody, physical 8 GiB acceptance, Linux CI execution and publication remain
open. The production reader configuration is unchanged. Timings are local
verification durations with cached compilation, not inference benchmarks.
