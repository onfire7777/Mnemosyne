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

## Configuration

- `ANSWERING_ORT_TCP_ADDR` selects an exact TCP socket address and defaults to
  `127.0.0.1:9294`. Non-loopback addresses are rejected before `bind`.
- On Unix, `ANSWERING_ORT_UNIX_SOCKET` selects a Unix-domain socket instead of
  TCP. A refused stale socket is replaced; a live socket or non-socket path is
  preserved. The created socket mode is `0600`.
- `ANSWERING_ORT_MODEL_PATH` is the optional local model path seam. The skeleton
  never downloads a model.
- `ANSWERING_ORT_INTRA_OP_THREADS` requests one or two intra-op threads; values
  are clamped to that range. Inter-op threads are fixed at one, the CPU arena
  seam is disabled, and the model-memory seam is configured for mapping.

## Protocol

Each connection carries one UTF-8 JSON request terminated by a newline and
receives one newline-terminated JSON response. The operations are:

```json
{"operation":"embed","query":"..."}
{"operation":"rerank","query":"...","evidence":[{"id":"1","text":"..."}],"rank_width":8}
{"operation":"read","query":"...","evidence":[{"id":"1","text":"..."}]}
```

The boundary rejects request bodies over 64 KiB, queries over 2,000 characters,
more than 20 evidence rows, more than 24,000 evidence characters, and rerank
widths outside 1 through 8. One request may run at a time, and the deadline seam
is capped at 30 seconds. Errors have stable codes and messages.

## Security and status boundaries

TCP is loopback-only. Unix sockets are owner-readable and owner-writable only.
The protocol rejects unknown fields and unsupported operations, does not invoke
Python, does not fetch models or data, and does not silently fall back when the
runtime is unavailable. A Unix socket should still be placed in a directory
owned by the service account so another local user cannot replace its path.

This crate is a transport, protocol, and resource-configuration placeholder.
The validation commands above test those properties only; they do not provide
measured quality, memory, latency, model parity, or production-readiness evidence.
