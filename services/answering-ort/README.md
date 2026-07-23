# Answering ORT sidecar skeleton

`answering-ort` is a bounded, local-only Rust sidecar skeleton for future ONNX
embed, rerank, and grounded-read inference. It does not yet load an ONNX model,
produce model outputs, or establish parity with another runtime. Requests
therefore fail closed with `runtime_unavailable`.

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
`runtime_busy`, and `inference_failed`. This placeholder returns
`runtime_unavailable` for valid requests because it does not load a session.

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
