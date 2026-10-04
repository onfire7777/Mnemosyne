# Answering ORT sidecar skeleton

`answering-ort` is a bounded, local-only Rust sidecar skeleton for future ONNX
embed, rerank, and grounded-read inference. The default server has no configured
model session and fails closed with `runtime_unavailable`. An optional native
span-tensor execution layer is described below; it is not yet a served reader.

## Build and validate

Run from the repository root:

```sh
cargo build --manifest-path services/answering-ort/Cargo.toml
cargo fmt --check --manifest-path services/answering-ort/Cargo.toml
cargo test --manifest-path services/answering-ort/Cargo.toml
cargo clippy --manifest-path services/answering-ort/Cargo.toml --all-targets -- -D warnings
```

## Run

Start the fail-closed placeholder on its default loopback TCP address:

```sh
cargo run --manifest-path services/answering-ort/Cargo.toml
```

Set `ANSWERING_ORT_TCP_ADDR=127.0.0.1:9295` to select another loopback socket.
On Unix, `ANSWERING_ORT_UNIX_SOCKET=/run/user/$(id -u)/answering-ort.sock`
selects a Unix socket instead and takes precedence over the TCP setting.

## Configuration

- `ANSWERING_ORT_TCP_ADDR` selects an exact TCP socket address and defaults to
  `127.0.0.1:9294`. Non-loopback addresses are rejected before `bind`.
- On Unix, `ANSWERING_ORT_UNIX_SOCKET` selects a Unix-domain socket instead of
  TCP. A refused stale socket is replaced; a live socket or non-socket path is
  preserved. The created socket mode is `0600`.
- `ANSWERING_ORT_MODEL_PATH` is the optional local model path seam. The skeleton
  never downloads a model.
- `ANSWERING_ORT_INTRA_OP_THREADS` requests one or two intra-op threads; values
  are clamped to the lower of two or detected physical cores. Inter-op threads
  are fixed at one, the CPU arena seam is disabled, and the model-memory seam is
  configured for mapping.
- The production custody identity is loaded from the six
  `ANSWERING_ORT_CUSTODY_*` fields: `PROVIDER`, `PROVIDER_SHA256`, `ARTIFACT`,
  `ARTIFACT_SHA256`, `CONFIGURATION`, and `CONFIGURATION_SHA256`. Leaving all
  six unset keeps the local development identity; setting any custody field
  requires a complete valid identity or requests fail closed.

## Protocol

Each connection carries one UTF-8 JSON request terminated by a newline and
receives one newline-terminated JSON response. The operations are:

```json
{"operation":"embed","query":"..."}
{"operation":"rerank","query":"...","evidence":[{"id":"1","text":"..."}],"rank_width":8}
{"operation":"read","query":"...","evidence":[{"id":"1","text":"..."}]}
```

Successful responses use `{"ok":true,"result":{...}}`. Embed results contain
an embedding, rerank results contain ordered evidence IDs, and read results are
structural only: answer type (`span`, `yes`, `no`, or `null`), evidence ID,
half-open UTF-8 byte offsets on character boundaries, and supporting evidence
IDs. The model never returns answer text; the host must reconstruct authorized
evidence substrings. The sidecar rejects non-finite or oversized embeddings,
operation-mismatched results, unknown or duplicate evidence IDs, and invalid
span boundaries before a successful response can leave the process.

Failures use `{"ok":false,"error":{"code":"...","message":"..."}}`. Stable
codes are `malformed_request`, `request_too_large`, `limit_exceeded`,
`unsupported_operation`, `request_timed_out`, `runtime_unavailable`,
`runtime_busy`, `identity_mismatch`, and `inference_failed`. This placeholder
returns `runtime_unavailable` for valid requests because it does not load a
session.

The boundary rejects request bodies over 64 KiB, queries over 2,000 characters,
more than 20 evidence rows, more than 24,000 evidence characters, and rerank
widths outside 1 through 8. Evidence IDs must be non-empty and unique. One
inference request may run at a time; transport admission allows at most that
active request plus one queued connection. Framing plus inference share a hard
30-second deadline. A timeout response returns at the deadline even if an
inference implementation fails to cooperate, while the runtime remains busy
until that inference exits so a second inference cannot overlap it.

## Security and status boundaries

TCP is loopback-only. Unix sockets are owner-readable and owner-writable only.
The protocol rejects unknown fields and unsupported operations, does not invoke
Python, does not fetch models or data, and does not silently fall back when the
runtime is unavailable. A Unix socket should still be placed in a directory
owned by the service account so another local user cannot replace its path.

This crate is a transport, protocol, and resource-configuration placeholder.
The validation commands above test those properties only; they do not provide
measured quality, memory, latency, model parity, or production-readiness evidence.

## Optional native span-tensor execution

The `onnx` Cargo feature adds `onnx_span::OnnxSpanSession`, using pinned
`ort = 2.0.0-rc.13` and an explicitly installed ONNX Runtime 1.28 library. Default
builds still have no ONNX dependency and the server remains unconfigured. This
is the tensor-execution step of W5, not a promoted `GroundedReader` backend.

The adapter verifies the supplied graph's SHA-256 before loading, allows at most
1 GiB of model bytes, and enforces batch one with 1–512 tokens. Its graph ABI is
INT64 `input_ids` and `attention_mask`, optional INT64 `token_type_ids`, and exactly
two FLOAT32 outputs: `start_logits` and `end_logits`, both shaped `[1, tokens]`.
It rejects invalid masks, unexpected inputs/outputs, incorrect shapes and NaN/Inf.
CPU arena allocation, memory patterns and parallel graph execution are disabled;
intra-op threads use the existing physical-core clamp (maximum two), inter-op one.

The tensor adapter accepts already tokenized inputs. The experimental reader
below now adds tokenizer/window/offset mapping. Answer-type and supporting-fact
heads, calibrated no-answer thresholds, real model selection, authenticated
serving integration, and physical resource admission remain unfinished. Model loading is from bytes, **not memory-mapped**. The byte
limit is not a peak-RSS guarantee. Deadline checks reject expired requests and
late results; native cancellation is not implemented here. Integration must use
the existing outer `Runtime` timeout/capacity boundary. Never advertise this
low-level method alone as a hard-interrupt deadline.

A 314-byte synthetic graph exercises real native execution without learned
weights. To reproduce in an isolated Python environment (no Python-core extras):

```sh
uv venv --python 3.11 /path/to/parity-venv
uv pip install --python /path/to/parity-venv/bin/python onnx==1.18.0 onnxruntime==1.28.0
/path/to/parity-venv/bin/python eval/compact_answering/onnx_span_parity.py /path/to/new-fixture
ORT_DYLIB_PATH=/absolute/path/to/libonnxruntime \
MNEMOSYNE_ONNX_PARITY_FIXTURE=/path/to/new-fixture \
cargo test --manifest-path services/answering-ort/Cargo.toml --features onnx \
  --test onnx_span -- --include-ignored
```

Use the actual platform library filename installed by the pinned runtime, e.g.
`libonnxruntime.1.28.0.dylib` on this Mac. No runtime/model download is performed
by the Rust adapter. Without explicit integration prerequisites the real test is
ignored, not passed. Reference cases cover lengths 1/64/128/384/512 and padding;
additional graphs exercise segment IDs, extra outputs, short outputs and NaN/Inf.
This is exact tensor parity only, not decoded-answer parity or measured QA quality.
The earlier 1.22.1 / rc.10 trial matched tensors but aborted during native teardown;
that configuration is not the supported development pin.


## Experimental decoded span reader

`onnx_reader::OnnxSpanReader` implements the existing `InferenceSession` trait
for read requests. It combines the native tensor session with a digest-checked
local tokenizer (tokenizers 0.22.1, no HTTP feature). It is not installed into the
default server or the frozen candidate-v19 configuration. Hosts must continue
using the existing Runtime identity, capacity, output-validation and deadline
boundary; tokenizer work and native inference are not independently interruptible.

The baseline uses the explicit `window-null-margin-v1` policy:

- windows have at most 512 tokens including the question and special tokens;
  context starts advance by 128 tokens, with question-dependent overlap;
- serialized truncation/padding is replaced by that policy, and the union of
  window token IDs/offsets must match the full untruncated context sequence;
- the question is limited to 256 tokens; at most 128 windows are processed per
  request, within the unchanged protocol's row/character limits;
- only attended context tokens with valid monotonic UTF-8 byte offsets can
  start or end an answer; questions, padding and processor special tokens cannot;
- the configured null token must occur exactly once as a processor special
  token in each window; stochastic BPE dropout is rejected;
- each candidate's score is start-logit plus end-logit minus that window's null
  start/end score; only a margin strictly above the configured threshold answers;
- ties use document input order, then earliest start/end byte offsets; the
  configured maximum answer-token length is enforced; and
- output is one exact source span and its evidence ID, or canonical null.

This span-only baseline supplies no learned yes/no or multi-hop supporting-fact
head. Its one supporting ID identifies the selected source, not an independently
predicted explanation. Thresholds, null-token ID and answer length must be frozen
in future candidate custody; the constructor has no quality-tuned defaults.
Full model/tokenizer/configuration/runtime manifest admission remains unfinished.

To extend the synthetic check to exact decoded-output parity, install
`tokenizers==0.22.1` in the isolated parity environment and run
`eval/compact_answering/onnx_reader_parity.py /path/to/new-fixture` after the
existing tensor fixture generator. Then run all native checks:

```sh
ORT_DYLIB_PATH=/absolute/path/to/libonnxruntime \
MNEMOSYNE_ONNX_PARITY_FIXTURE=/path/to/new-fixture \
cargo test --manifest-path services/answering-ort/Cargo.toml --features onnx \
  -- --include-ignored
```

Ten Python-reference cases cover composed/decomposed Unicode, CJK, repeated
answers, multi-document ordering, later-window answers, null and empty evidence.
They use a generated WordLevel tokenizer and the same 314-byte arithmetic graph;
no learned model, training corpus or protected test data is involved. Passing
these fixtures establishes neither QA quality nor arbitrary-model parity.
