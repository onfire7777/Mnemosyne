"""Apple Silicon MPS/CoreML local embedding daemon (Unix socket) & offline re-embed helper.

Provides:
- Zero-egress local embeddings over a private 0600 Unix domain socket
  (``~/.local/state/mnemosyne/embedding.sock``) with optional loopback HTTP.
- Support for ``Qwen/Qwen3-Embedding-0.6B`` (MRL-1024 FP16),
  ``google/embeddinggemma-300m`` (768-d MRL), and offline-cached
  ``BAAI/bge-small-en-v1.5`` (384-d FP16 MPS, ~12 ms single-query, <1s re-embed).
- Strict per-model vector-space separation (never mixes vectors across models/dims
  without explicit opt-in ``reembed --confirm-reembed``).
- Optional MRL-1024 remote OpenRouter ``retrieval_config.py`` renderer preserving
  full backward compatibility with the live 4096-dim ``qwen/qwen3-embedding-8b`` store.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import shutil
import socketserver
import sys
import threading
import time
from typing import Any

ROOT = Path(os.environ.get("MNEMOSYNE_HOST_ROOT", Path.home() / ".local/share/mnemosyne"))
STATE = Path(os.environ.get("MNEMOSYNE_HOST_STATE", Path.home() / ".local/state/mnemosyne"))
DEFAULT_SOCKET = STATE / "embedding.sock"
MAX_REQUEST_BYTES = 4 << 20
MAX_BATCH = 128

MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3-Embedding-0.6B": {
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "dims": 1024,
        "native_dims": 1024,
        "mrl_dims": (1024, 512, 256),
        "query_prefix": "Instruct: Given a query, retrieve relevant passages that answer the query\nQuery: ",
        "max_chars": 8000,
    },
    "google/embeddinggemma-300m": {
        "model": "google/embeddinggemma-300m",
        "dims": 768,
        "native_dims": 768,
        "mrl_dims": (768, 512, 256, 128),
        "query_prefix": "task: search result | query: ",
        "max_chars": 6000,
    },
    "BAAI/bge-small-en-v1.5": {
        "model": "BAAI/bge-small-en-v1.5",
        "dims": 384,
        "native_dims": 384,
        "mrl_dims": (384,),
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "max_chars": 4000,
    },
}

DEFAULT_MODEL_PRIORITY = (
    "Qwen/Qwen3-Embedding-0.6B",
    "google/embeddinggemma-300m",
    "BAAI/bge-small-en-v1.5",
)


def _hf_hub_dir(hf_hub_dir: Path | None = None) -> Path:
    if hf_hub_dir is not None:
        return Path(hf_hub_dir)
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]).expanduser() / "hub"
    return Path.home() / ".cache/huggingface/hub"


def _repo_cache_name(model_id: str) -> str:
    return "models--" + model_id.replace("/", "--")


def discover_cached_local_models(hf_hub_dir: Path | None = None) -> list[str]:
    """Return supported preset model IDs already cached offline on this machine."""
    hub = _hf_hub_dir(hf_hub_dir)
    if not hub.is_dir():
        return []
    found: list[str] = []
    for model_id in DEFAULT_MODEL_PRIORITY:
        model_dir = hub / _repo_cache_name(model_id)
        snapshots = model_dir / "snapshots"
        if snapshots.is_dir() and any(snapshots.iterdir()):
            found.append(model_id)
    return found


def resolve_local_model(
    requested: str | None = None,
    dims: int | None = None,
    *,
    hf_hub_dir: Path | None = None,
) -> dict[str, Any]:
    """Resolve model preset and validate requested MRL dimensions offline."""
    chosen = (requested or os.environ.get("MNEMOSYNE_LOCAL_EMBEDDING_MODEL", "")).strip()
    if not chosen:
        cached = discover_cached_local_models(hf_hub_dir)
        chosen = cached[0] if cached else "BAAI/bge-small-en-v1.5"
    if chosen in MODEL_PRESETS:
        preset = dict(MODEL_PRESETS[chosen])
    else:
        native = dims if (type(dims) is int and dims > 0) else 1024
        preset = {
            "model": chosen,
            "dims": native,
            "native_dims": native,
            "mrl_dims": (native,),
            "query_prefix": "",
            "max_chars": 4000,
        }
    target_dims = preset["dims"] if dims is None else int(dims)
    if target_dims <= 0 or target_dims > int(preset["native_dims"]):
        raise ValueError(
            f"Requested dims={target_dims} out of range for {chosen} (1..{preset['native_dims']})"
        )
    preset["dims"] = target_dims
    return preset


def _fit_and_normalize(raw: Any, target_dims: int) -> list[float]:
    if len(raw) < target_dims:
        raise ValueError(f"Model produced {len(raw)} dims, fewer than target {target_dims}")
    vec = [float(raw[i]) for i in range(target_dims)]
    if any(not math.isfinite(v) for v in vec):
        raise ValueError("Embedding backend produced non-finite values")
    norm = math.sqrt(math.fsum(v * v for v in vec))
    if norm <= 0.0:
        raise ValueError("Embedding backend produced an all-zero vector")
    return [v / norm for v in vec]


class DeterministicTestBackend:
    """Pure-Python deterministic backend strictly for offline unit/contract tests."""

    backend_name = "deterministic"

    def __init__(self, model: str, dims: int, query_prefix: str = "") -> None:
        self.model = model
        self.dims = int(dims)
        self.native_dims = self.dims
        self.query_prefix = query_prefix
        self.device = "cpu"
        self.dtype_name = "float32"

    def encode(self, texts: list[str], target_dims: int | None = None) -> list[list[float]]:
        dims = self.dims if target_dims is None else int(target_dims)
        if dims <= 0 or dims > self.native_dims:
            raise ValueError(f"dimensions must be between 1 and {self.native_dims}")
        out: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(f"{self.model}:{text}".encode("utf-8")).digest()
            raw = []
            for idx in range(dims):
                digest = hashlib.sha256(seed + idx.to_bytes(4, "little")).digest()
                val = (int.from_bytes(digest[:4], "little") % 2001) / 1000.0 - 1.0
                raw.append(val)
            out.append(_fit_and_normalize(raw, dims))
        return out


class SentenceTransformerLocalBackend:
    """Thread-safe Apple Silicon MPS FP16 (or CPU FP32) SentenceTransformer backend."""

    backend_name = "sentence-transformers"

    def __init__(
        self,
        model_id: str,
        *,
        dims: int | None = None,
        max_chars: int = 4000,
        query_prefix: str = "",
    ) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(4)
        self._torch = torch
        self.model = model_id
        self.max_chars = int(max_chars)
        self.query_prefix = query_prefix
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        use_fp16 = self.device == "mps" and os.environ.get("MNEMOSYNE_EMBEDDING_FP32", "0") != "1"
        self.dtype_name = "float16" if use_fp16 else "float32"
        loaded = SentenceTransformer(
            model_id,
            device=self.device,
            local_files_only=True,
            trust_remote_code=False,
        )
        if use_fp16:
            loaded = loaded.to(dtype=torch.float16)
        loaded.eval()
        self._model = loaded
        dim_fn = getattr(loaded, "get_embedding_dimension", None) or getattr(
            loaded, "get_sentence_embedding_dimension", None
        )
        native = int(dim_fn()) if callable(dim_fn) else int(dims or 384)
        self.native_dims = native
        self.dims = native if dims is None else int(dims)
        if self.dims <= 0 or self.dims > self.native_dims:
            raise ValueError(
                f"Configured dims={self.dims} incompatible with {model_id} native dims={self.native_dims}"
            )
        self._lock = threading.Lock()
        self._warmup()

    def _warmup(self) -> None:
        """Pre-compile Metal/MPS kernels across short, medium, and batched shapes."""
        with self._lock, self._torch.inference_mode():
            for sample in (
                ["warmup query"],
                ["warmup " * 32],
                ["warmup " * 128],
                ["warmup doc"] * 8,
            ):
                self._model.encode(sample, normalize_embeddings=False, show_progress_bar=False)
            if self.device == "mps":
                self._torch.mps.synchronize()

    def encode(self, texts: list[str], target_dims: int | None = None) -> list[list[float]]:
        dims = self.dims if target_dims is None else int(target_dims)
        if dims <= 0 or dims > self.native_dims:
            raise ValueError(f"dimensions must be between 1 and {self.native_dims}")
        clipped = [text[: self.max_chars] for text in texts]
        with self._lock, self._torch.inference_mode():
            matrix = self._model.encode(
                clipped,
                batch_size=32,
                normalize_embeddings=False,
                show_progress_bar=False,
            )
            if self.device == "mps":
                self._torch.mps.synchronize()
        return [_fit_and_normalize(row.tolist(), dims) for row in matrix]


class OnnxCoreMLLocalBackend:
    """Opt-in ONNX Runtime CoreML/CPU local embedding backend for exported ONNX dirs."""

    backend_name = "onnx-coreml"

    def __init__(
        self,
        model_id: str,
        onnx_dir: str | Path,
        *,
        dims: int | None = None,
        max_chars: int = 4000,
        query_prefix: str = "",
    ) -> None:
        import numpy as np
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self._np = np
        self.model = model_id
        self.max_chars = int(max_chars)
        self.query_prefix = query_prefix
        onnx_path = Path(onnx_dir).expanduser()
        model_file = onnx_path / "model.onnx" if onnx_path.is_dir() else onnx_path
        if not model_file.is_file():
            raise FileNotFoundError(f"ONNX embedding model file not found: {model_file}")
        available = set(ort.get_available_providers())
        providers = [p for p in ("CoreMLExecutionProvider", "CPUExecutionProvider") if p in available]
        if not providers:
            providers = ["CPUExecutionProvider"]
        self.device = "coreml" if "CoreMLExecutionProvider" in providers else "cpu"
        self.dtype_name = "float32"
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(model_file.parent), local_files_only=True, trust_remote_code=False
        )
        self._session = ort.InferenceSession(str(model_file), providers=providers)
        self._input_names = {inp.name for inp in self._session.get_inputs()}
        self._lock = threading.Lock()
        probe = self._run_raw(["warmup"])[0]
        self.native_dims = len(probe)
        self.dims = self.native_dims if dims is None else int(dims)
        if self.dims <= 0 or self.dims > self.native_dims:
            raise ValueError(
                f"Configured dims={self.dims} incompatible with ONNX native dims={self.native_dims}"
            )

    def _run_raw(self, texts: list[str]) -> list[list[float]]:
        np = self._np
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
        feeds = {name: encoded[name] for name in self._input_names if name in encoded}
        if "token_type_ids" in self._input_names and "token_type_ids" not in feeds:
            feeds["token_type_ids"] = np.zeros_like(encoded["input_ids"])
        outputs = self._session.run(None, feeds)
        token_embeddings = outputs[0]
        if token_embeddings.ndim == 2:
            pooled = token_embeddings
        else:
            mask = encoded["attention_mask"][..., None].astype(np.float32)
            pooled = (token_embeddings * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
        return pooled.tolist()

    def encode(self, texts: list[str], target_dims: int | None = None) -> list[list[float]]:
        dims = self.dims if target_dims is None else int(target_dims)
        if dims <= 0 or dims > self.native_dims:
            raise ValueError(f"dimensions must be between 1 and {self.native_dims}")
        clipped = [text[: self.max_chars] for text in texts]
        with self._lock:
            raw_rows = self._run_raw(clipped)
        return [_fit_and_normalize(row, dims) for row in raw_rows]


def build_backend(
    *,
    model: str | None = None,
    dims: int | None = None,
    backend_kind: str | None = None,
) -> Any:
    preset = resolve_local_model(model, dims)
    kind = (backend_kind or os.environ.get("MNEMOSYNE_LOCAL_EMBEDDING_BACKEND", "auto")).strip().lower()
    if kind == "deterministic":
        return DeterministicTestBackend(
            preset["model"], preset["dims"], query_prefix=preset["query_prefix"]
        )
    onnx_dir = os.environ.get("MNEMOSYNE_LOCAL_EMBEDDING_ONNX_DIR", "").strip()
    if kind in {"onnx", "coreml"} or (kind == "auto" and onnx_dir):
        if not onnx_dir:
            raise ValueError("MNEMOSYNE_LOCAL_EMBEDDING_ONNX_DIR must be set for ONNX/CoreML backend")
        return OnnxCoreMLLocalBackend(
            preset["model"],
            onnx_dir,
            dims=preset["dims"],
            max_chars=preset["max_chars"],
            query_prefix=preset["query_prefix"],
        )
    return SentenceTransformerLocalBackend(
        preset["model"],
        dims=preset["dims"],
        max_chars=preset["max_chars"],
        query_prefix=preset["query_prefix"],
    )


def handle_rpc_request(backend: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Process one sanitized Unix-socket or HTTP embedding request (never echoes input)."""
    if not isinstance(request, dict):
        return {"error": "invalid_request"}
    op = request.get("op", "embed" if "input" in request else "health")
    if op == "health":
        return {
            "status": "ok",
            "model": backend.model,
            "dimensions": backend.dims,
            "native_dimensions": backend.native_dims,
            "vector_space_id": f"{backend.model}@{backend.dims}",
            "backend": backend.backend_name,
            "device": backend.device,
            "dtype": backend.dtype_name,
            "query_prefix": backend.query_prefix,
        }
    if op != "embed":
        return {"error": "unsupported_operation"}
    req_model = request.get("model")
    if isinstance(req_model, str) and req_model.strip() and req_model.strip() != backend.model:
        return {"error": "vector_space_mismatch"}
    req_dims = request.get("dimensions")
    if req_dims is None:
        target_dims = backend.dims
    elif type(req_dims) is int and 1 <= req_dims <= backend.native_dims:
        target_dims = req_dims
    else:
        return {"error": "invalid_dimensions"}
    raw_input = request.get("input")
    if isinstance(raw_input, str):
        if not raw_input:
            return {"error": "empty_input"}
        vec = backend.encode([raw_input], target_dims=target_dims)[0]
        return {
            "embedding": vec,
            "model": backend.model,
            "dimensions": target_dims,
            "vector_space_id": f"{backend.model}@{target_dims}",
        }
    if isinstance(raw_input, list):
        if not raw_input:
            return {"error": "empty_input"}
        if len(raw_input) > MAX_BATCH:
            return {"error": "batch_too_large"}
        if any(not isinstance(item, str) or not item for item in raw_input):
            return {"error": "invalid_batch_item"}
        vectors = backend.encode(raw_input, target_dims=target_dims)
        return {
            "object": "list",
            "model": backend.model,
            "dimensions": target_dims,
            "vector_space_id": f"{backend.model}@{target_dims}",
            "data": [
                {"object": "embedding", "index": index, "embedding": vector}
                for index, vector in enumerate(vectors)
            ],
        }
    return {"error": "invalid_input"}


class _UnixEmbeddingHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(MAX_REQUEST_BYTES)
            if not raw:
                return
            request = json.loads(raw)
            reply = handle_rpc_request(self.server.backend, request)
        except Exception as error:
            reply = {"error": type(error).__name__}
        try:
            self.wfile.write((json.dumps(reply, allow_nan=False) + "\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class EmbeddingUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: str | Path, backend: Any) -> None:
        self.backend = backend
        sock = Path(socket_path)
        sock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(sock.parent, 0o700)
        sock.unlink(missing_ok=True)
        old_umask = os.umask(0o177)
        try:
            super().__init__(str(sock), _UnixEmbeddingHandler)
        finally:
            os.umask(old_umask)
        self.socket_file = sock

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            self.socket_file.unlink(missing_ok=True)


def _start_loopback_http(backend: Any, *, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("local embedding HTTP server must bind to a loopback address")

    class _HttpHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return  # Never log request lines or payloads.

        def _write_json(self, status: int, body: dict[str, Any]) -> None:
            encoded = json.dumps(body, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._write_json(404, {"error": "not_found"})
                return
            self._write_json(200, handle_rpc_request(backend, {"op": "health"}))

        def do_POST(self) -> None:
            if self.path not in {"/embed", "/v1/embeddings"}:
                self._write_json(404, {"error": "not_found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._write_json(400, {"error": "invalid_content_length"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                self._write_json(400, {"error": "invalid_json"})
                return
            if isinstance(payload, dict):
                payload = {**payload, "op": "embed"}
            reply = handle_rpc_request(backend, payload)
            status = 400 if "error" in reply else 200
            self._write_json(status, reply)

    httpd = ThreadingHTTPServer((host, port), _HttpHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="local-embed-http").start()
    return httpd


def _collect_reembed_targets(engine: Any, tenant_id: str, branch: str = "main") -> dict[str, list[dict[str, Any]]]:
    """Collect all active, non-erased, embeddable rows across all 5 tables."""
    from mnemosyne.access_policy import may_embed_item

    targets: dict[str, list[dict[str, Any]]] = {
        "evidence": [],
        "assertions": [],
        "observations": [],
        "preferences": [],
        "knowledge_pages": [],
    }

    if hasattr(engine, "_connect"):
        conn = engine._connect(tenant_id)
        lock = getattr(engine, "_lock", None)

        def _fetch(sql: str, params: tuple[Any, ...]) -> list[Any]:
            if lock is not None:
                with lock:
                    return conn.execute(sql, params).fetchall()
            return conn.execute(sql, params).fetchall()

        for row in _fetch(
            "SELECT cid, branch, content, sensitivity, access_policy, erased "
            "FROM evidence WHERE tenant_id = ? AND branch = ? "
            "AND erased = 0 AND retired_at IS NULL AND modality = 'text' "
            "AND source_type != 'learning_tool_result' AND content != ''",
            (tenant_id, branch),
        ):
            policy = json.loads(row[4]) if isinstance(row[4], str) and row[4] else {}
            if not may_embed_item(sensitivity=int(row[3]), access_policy=policy, erased=bool(row[5])):
                continue
            targets["evidence"].append({"id": row[0], "branch": row[1], "text": row[2]})

        for row in _fetch(
            "SELECT id, branch, subject, predicate, object, sensitivity, access_policy "
            "FROM assertions WHERE tenant_id = ? AND branch = ? "
            "AND status IN ('active', 'contested')",
            (tenant_id, branch),
        ):
            policy = json.loads(row[6]) if isinstance(row[6], str) and row[6] else {}
            if not may_embed_item(sensitivity=int(row[5]), access_policy=policy, erased=False):
                continue
            text = f"{row[2]} {row[3]} {row[4]}".strip()
            if text:
                targets["assertions"].append({"id": row[0], "branch": row[1], "text": text})

        for row in _fetch(
            "SELECT observation_id, branch, subject, topic, content, sensitivity, access_policy "
            "FROM observations WHERE tenant_id = ? AND branch = ? AND status = 'active'",
            (tenant_id, branch),
        ):
            policy = json.loads(row[6]) if isinstance(row[6], str) and row[6] else {}
            if not may_embed_item(sensitivity=int(row[5]), access_policy=policy, erased=False):
                continue
            text = f"{row[2]} ({row[3]}): {row[4]}".strip() if row[3] else f"{row[2]}: {row[4]}".strip()
            if text:
                targets["observations"].append({"id": row[0], "branch": row[1], "text": text})

        for row in _fetch(
            "SELECT id, record FROM preferences WHERE tenant_id = ?",
            (tenant_id,),
        ):
            rec = json.loads(row[1]) if isinstance(row[1], str) and row[1] else {}
            if rec.get("status", "active") != "active":
                continue
            policy = rec.get("access_policy") if isinstance(rec.get("access_policy"), dict) else {}
            if not may_embed_item(sensitivity=0, access_policy=policy, erased=False):
                continue
            cat = str(rec.get("category") or "").strip()
            stmt = str(rec.get("statement") or "").strip()
            text = f"{cat}: {stmt}".strip() if cat else stmt
            if text:
                targets["preferences"].append({"id": row[0], "branch": branch, "text": text})

        for row in _fetch(
            "SELECT page_id, branch, title, content_markdown, sensitivity, access_policy "
            "FROM knowledge_pages WHERE tenant_id = ? AND branch = ? AND status = 'active'",
            (tenant_id, branch),
        ):
            policy = json.loads(row[5]) if isinstance(row[5], str) and row[5] else {}
            if not may_embed_item(sensitivity=int(row[4]), access_policy=policy, erased=False):
                continue
            text = f"{row[2]}\n{row[3]}".strip() if row[2] else str(row[3]).strip()
            if text:
                targets["knowledge_pages"].append({"id": row[0], "branch": row[1], "text": text})
    else:
        exported = engine.export_tenant(tenant_id)
        for row in exported.get("evidence", []):
            if row.get("branch", "main") != branch or row.get("erased") or row.get("retired_at"):
                continue
            if row.get("source_type") == "learning_tool_result" or not row.get("content"):
                continue
            if not may_embed_item(
                sensitivity=int(row.get("sensitivity", 0)),
                access_policy=row.get("access_policy") or {},
                erased=False,
            ):
                continue
            targets["evidence"].append(
                {"id": row["cid"], "branch": row.get("branch", "main"), "text": row["content"]}
            )
    return targets


def reembed_store(
    engine: Any,
    tenant_id: str,
    provider: Any,
    *,
    model: str,
    dims: int,
    branch: str = "main",
    batch_size: int = 32,
    dry_run: bool = False,
    confirm_reembed: bool = False,
    backup_path: str | Path | None = None,
) -> dict[str, Any]:
    """Two-phase, fail-closed offline re-embed across evidence/assertions/observations/prefs/pages.

    Computes and validates every vector BEFORE mutating a single row in the store so an
    interrupted or failing provider call can never leave a mixed-dimension vector space.
    """
    from mnemosyne.hosts.query_embedding import VectorSpaceIdentity, inspect_store_vector_space

    if not dry_run and not confirm_reembed:
        raise ValueError(
            "Refusing to overwrite existing embeddings without explicit confirm_reembed=True "
            "(or pass dry_run=True to inspect)."
        )
    target_space = VectorSpaceIdentity(model=model, dims=int(dims))
    before_space = inspect_store_vector_space(engine, tenant_id, branch=branch)
    targets = _collect_reembed_targets(engine, tenant_id, branch=branch)
    counts = {table: len(rows) for table, rows in targets.items()}
    if dry_run:
        return {
            "dry_run": True,
            "tenant_id": tenant_id,
            "branch": branch,
            "before_space": before_space,
            "target_space": {
                "model": target_space.model,
                "dimensions": target_space.dims,
                "vector_space_id": target_space.space_id,
            },
            "planned_counts": counts,
            "planned_total": sum(counts.values()),
        }

    if backup_path is not None and hasattr(engine, "_tenant_db_path"):
        src_db = Path(engine._tenant_db_path(tenant_id))
        if src_db.exists():
            dst = Path(backup_path)
            dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(src_db, dst)
            os.chmod(dst, 0o600)

    t0 = time.monotonic()
    # Phase 1: embed every row and validate exact dimensions before any write.
    computed: dict[str, list[tuple[dict[str, Any], list[float]]]] = {}
    evidence_hashes = {
        (row["branch"], row["id"]): hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        for row in targets["evidence"]
    }
    step = max(1, int(batch_size))
    for table, rows in targets.items():
        paired: list[tuple[dict[str, Any], list[float]]] = []
        for start in range(0, len(rows), step):
            chunk = rows[start : start + step]
            texts = [row["text"] for row in chunk]
            if hasattr(provider, "embed_many"):
                vectors = provider.embed_many(texts)
            elif hasattr(provider, "encode"):
                vectors = provider.encode(texts, target_dims=target_space.dims)
            else:
                vectors = [provider.embed(text) for text in texts]
            if len(vectors) != len(chunk):
                raise RuntimeError(f"Embedding provider returned mismatched batch size for {table}")
            for row, vec in zip(chunk, vectors, strict=True):
                normed = _fit_and_normalize(vec, target_space.dims)
                paired.append((row, normed))
        computed[table] = paired

    # Phase 2: persist all vectors atomically per target and clear stale SQLite embedding_cache.
    embedded_counts = {table: 0 for table in targets}
    for row, vec in computed["evidence"]:
        ok = engine.set_evidence_embedding(
            tenant_id, row["id"], vec, row["branch"], source=target_space.model, only_if_missing=False
        )
        if not ok:
            raise RuntimeError("An evidence record became unavailable during re-embedding")
        embedded_counts["evidence"] += 1

    if hasattr(engine, "set_assertion_embedding"):
        for row, vec in computed["assertions"]:
            if engine.set_assertion_embedding(
                tenant_id, row["id"], vec, row["branch"], source=target_space.model, only_if_missing=False
            ):
                embedded_counts["assertions"] += 1

    if hasattr(engine, "set_observation_embedding"):
        for row, vec in computed["observations"]:
            if engine.set_observation_embedding(
                tenant_id, row["id"], vec, row["branch"], source=target_space.model, only_if_missing=False
            ):
                embedded_counts["observations"] += 1

    if hasattr(engine, "set_preference_embedding"):
        for row, vec in computed["preferences"]:
            if engine.set_preference_embedding(
                tenant_id, row["id"], vec, source=target_space.model, only_if_missing=False
            ):
                embedded_counts["preferences"] += 1

    if hasattr(engine, "set_knowledge_page_embedding"):
        for row, vec in computed["knowledge_pages"]:
            if engine.set_knowledge_page_embedding(
                tenant_id, row["id"], vec, row["branch"], source=target_space.model, only_if_missing=False
            ):
                embedded_counts["knowledge_pages"] += 1

    if hasattr(engine, "_connect"):
        conn = engine._connect(tenant_id)
        lock = getattr(engine, "_lock", None)
        if lock is not None:
            with lock, conn:
                conn.execute("DELETE FROM embedding_cache WHERE tenant_id = ?", (tenant_id,))
        else:
            with conn:
                conn.execute("DELETE FROM embedding_cache WHERE tenant_id = ?", (tenant_id,))

    # Phase 3: readback verification of evidence content & dimensions.
    for row, _vec in computed["evidence"]:
        saved = engine.get_evidence(tenant_id, row["id"], row["branch"])
        if (
            saved is None
            or not saved.embedding
            or len(saved.embedding) != target_space.dims
            or hashlib.sha256(saved.content.encode("utf-8")).hexdigest()
            != evidence_hashes[(row["branch"], row["id"])]
        ):
            raise RuntimeError("Re-embedding readback verification failed")

    after_space = inspect_store_vector_space(engine, tenant_id, branch=branch)
    elapsed = round(time.monotonic() - t0, 3)
    return {
        "dry_run": False,
        "tenant_id": tenant_id,
        "branch": branch,
        "model": target_space.model,
        "dimensions": target_space.dims,
        "vector_space_id": target_space.space_id,
        "before_space": before_space,
        "after_space": after_space,
        "embedded_counts": embedded_counts,
        "total_embedded": sum(embedded_counts.values()),
        "elapsed_seconds": elapsed,
        "source_content_verified": True,
    }


def render_retrieval_config(
    *,
    mode: str = "openrouter",
    model: str | None = None,
    dims: int | None = None,
    root: Path | None = None,
    state: Path | None = None,
    tenant_id: str = "personal",
) -> str:
    """Render a drop-in retrieval_config.py for OpenRouter (4096 or MRL-1024) or local Unix socket."""
    host_root = str(root or ROOT)
    host_state = str(state or STATE)
    if mode == "openrouter":
        chosen_model = model or "qwen/qwen3-embedding-8b"
        chosen_dims = 4096 if dims is None else int(dims)
        from mnemosyne.hosts.query_embedding import OPENROUTER_QWEN3_MRL_DIMS, VectorSpaceIdentity

        if chosen_model == "qwen/qwen3-embedding-8b" and chosen_dims not in OPENROUTER_QWEN3_MRL_DIMS:
            raise ValueError(f"Unsupported Qwen3-8B MRL dims: {chosen_dims}")
        space = VectorSpaceIdentity(model=chosen_model, dims=chosen_dims, provider_kind="openrouter")
        extra = {"provider": {"order": ["SiliconFlow", "Nebius"], "allow_fallbacks": True}}
        if chosen_dims != 4096:
            extra["dimensions"] = chosen_dims
        extra_json = json.dumps(extra, separators=(",", ":"))
        cache_name = (
            "qwen-embedding-cache.sqlite"
            if chosen_dims == 4096
            else f"qwen-embedding-cache-{chosen_dims}.sqlite"
        )
        cache_scope = space.cache_scope(tenant_id)
        return (
            '"""Shared remote Qwen embedding configuration for every local host path."""\n'
            "import os\n"
            "from pathlib import Path\n\n"
            "from mnemosyne.retrieval import HttpEmbeddingProvider\n\n"
            f"ROOT = Path({host_root!r})\n"
            f"MODEL = {chosen_model!r}\n"
            "URL = 'https://openrouter.ai/api/v1/embeddings'\n"
            f"DIMENSIONS = {chosen_dims}\n"
            f"VECTOR_SPACE_ID = {space.space_id!r}\n"
            "QUERY_PREFIX = 'Instruct: Given a query, retrieve relevant passages that answer the query\\nQuery: '\n"
            f"EXTRA_BODY_JSON = {extra_json!r}\n"
            f"CACHE_PATH = str(ROOT / {cache_name!r})\n"
            f"CACHE_SCOPE = {cache_scope!r}\n\n\n"
            "def api_key():\n"
            "    key = (ROOT / 'codex/openrouter-api-key').read_text().strip()\n"
            "    if not key:\n"
            "        raise ValueError('The OpenRouter embedding credential is empty.')\n"
            "    return key\n\n\n"
            "def embedding_provider():\n"
            "    return HttpEmbeddingProvider(\n"
            "        URL, model=MODEL, api_key=api_key(), dims=DIMENSIONS,\n"
            "        query_prefix=QUERY_PREFIX, timeout_seconds=60,\n"
            "        cache_path=CACHE_PATH,\n"
            "        cache_scope=CACHE_SCOPE,\n"
            "        extra_body_json=EXTRA_BODY_JSON,\n"
            "    )\n\n\n"
            "def configure_environment():\n"
            "    values = {\n"
            "        'MNEMOSYNE_EMBEDDING_PROVIDER': 'http',\n"
            "        'MNEMOSYNE_EMBEDDING_URL': URL,\n"
            "        'MNEMOSYNE_EMBEDDING_MODEL': MODEL,\n"
            "        'MNEMOSYNE_EMBEDDING_DIMS': str(DIMENSIONS),\n"
            "        'MNEMOSYNE_EMBEDDING_API_KEY': api_key(),\n"
            "        'MNEMOSYNE_EMBEDDING_CACHE_PATH': CACHE_PATH,\n"
            "        'MNEMOSYNE_EMBEDDING_CACHE_SCOPE': CACHE_SCOPE,\n"
            "        'MNEMOSYNE_EMBEDDING_EXTRA_BODY_JSON': EXTRA_BODY_JSON,\n"
            "        'MNEMOSYNE_RERANKER_PROVIDER': 'http',\n"
            "        'MNEMOSYNE_RERANKER_URL': 'http://127.0.0.1:8766/rerank',\n"
            "        'MNEMOSYNE_RERANKER_MODEL': 'cross-encoder/ms-marco-MiniLM-L-6-v2',\n"
            "    }\n"
            "    os.environ.update(values)\n"
        )
    if mode == "local":
        preset = resolve_local_model(model, dims)
        chosen_model = preset["model"]
        chosen_dims = preset["dims"]
        query_prefix = preset["query_prefix"]
        space_id = f"{chosen_model}@{chosen_dims}"
        return (
            '"""Local-first Apple Silicon MPS/CoreML Unix-socket embedding configuration."""\n'
            "import os\n"
            "from pathlib import Path\n\n"
            "from mnemosyne.hosts.query_embedding import UnixSocketEmbeddingProvider\n\n"
            f"ROOT = Path({host_root!r})\n"
            f"STATE = Path({host_state!r})\n"
            "SOCKET = STATE / 'embedding.sock'\n"
            f"MODEL = {chosen_model!r}\n"
            f"DIMENSIONS = {chosen_dims}\n"
            f"VECTOR_SPACE_ID = {space_id!r}\n"
            f"QUERY_PREFIX = {query_prefix!r}\n\n\n"
            "def embedding_provider():\n"
            "    return UnixSocketEmbeddingProvider(\n"
            "        socket_path=str(SOCKET),\n"
            "        model=MODEL,\n"
            "        dims=DIMENSIONS,\n"
            "        query_prefix=QUERY_PREFIX,\n"
            "        timeout_seconds=5.0,\n"
            "    )\n\n\n"
            "def configure_environment():\n"
            "    values = {\n"
            "        'MNEMOSYNE_EMBEDDING_PROVIDER': 'local_unix',\n"
            "        'MNEMOSYNE_EMBEDDING_SOCKET': str(SOCKET),\n"
            "        'MNEMOSYNE_EMBEDDING_MODEL': MODEL,\n"
            "        'MNEMOSYNE_EMBEDDING_DIMS': str(DIMENSIONS),\n"
            "        'MNEMOSYNE_RERANKER_PROVIDER': 'http',\n"
            "        'MNEMOSYNE_RERANKER_URL': 'http://127.0.0.1:8766/rerank',\n"
            "        'MNEMOSYNE_RERANKER_MODEL': 'cross-encoder/ms-marco-MiniLM-L-6-v2',\n"
            "    }\n"
            "    os.environ.update(values)\n"
        )
    raise ValueError(f"Unsupported retrieval_config mode: {mode!r} (expected 'openrouter' or 'local')")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Apple Silicon MPS/CoreML embedding daemon & re-embed tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the private 0600 Unix-socket embedding daemon")
    p_serve.add_argument("--socket", type=Path, default=DEFAULT_SOCKET)
    p_serve.add_argument("--model", type=str, default=None)
    p_serve.add_argument("--dims", type=int, default=None)
    p_serve.add_argument("--backend", type=str, default=None, choices=["auto", "sentence-transformers", "onnx", "coreml", "deterministic"])
    p_serve.add_argument("--http-port", type=int, default=0, help="Optional loopback-only HTTP port (e.g. 8765)")

    p_inspect = sub.add_parser("inspect", help="Inspect store vector space and cached local HF models")
    p_inspect.add_argument("--store", type=Path, default=ROOT / "codex-memory")
    p_inspect.add_argument("--tenant", type=str, default=os.environ.get("MNEMOSYNE_TENANT", "personal"))
    p_inspect.add_argument("--branch", type=str, default="main")

    p_reembed = sub.add_parser("reembed", help="Explicit opt-in offline re-embed into a target vector space")
    p_reembed.add_argument("--store", type=Path, default=ROOT / "codex-memory")
    p_reembed.add_argument("--tenant", type=str, default=os.environ.get("MNEMOSYNE_TENANT", "personal"))
    p_reembed.add_argument("--branch", type=str, default="main")
    p_reembed.add_argument("--provider", choices=["local", "openrouter"], default="local")
    p_reembed.add_argument("--model", type=str, default=None)
    p_reembed.add_argument("--dims", type=int, default=None)
    p_reembed.add_argument("--socket", type=Path, default=None, help="Use a running Unix socket daemon instead of in-process load")
    p_reembed.add_argument("--batch-size", type=int, default=32)
    p_reembed.add_argument("--backup", type=Path, default=None)
    p_reembed.add_argument("--dry-run", action="store_true")
    p_reembed.add_argument("--confirm-reembed", action="store_true")

    p_render = sub.add_parser("render-config", help="Render a drop-in retrieval_config.py")
    p_render.add_argument("--mode", choices=["openrouter", "local"], default="openrouter")
    p_render.add_argument("--model", type=str, default=None)
    p_render.add_argument("--dims", type=int, default=None)
    p_render.add_argument("--root", type=Path, default=ROOT)
    p_render.add_argument("--state", type=Path, default=STATE)
    p_render.add_argument("--tenant", type=str, default="personal")

    args = parser.parse_args(argv)
    if args.command == "serve":
        backend = build_backend(model=args.model, dims=args.dims, backend_kind=args.backend)
        httpd = _start_loopback_http(backend, port=args.http_port) if args.http_port else None
        server = EmbeddingUnixServer(args.socket, backend)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
        return 0

    if args.command == "inspect":
        from mnemosyne.hosts.query_embedding import inspect_store_vector_space
        from mnemosyne.sqlite_engine import SqliteEngine

        engine = SqliteEngine(args.store)
        try:
            report = {
                "store": inspect_store_vector_space(engine, args.tenant, branch=args.branch),
                "cached_local_models": discover_cached_local_models(),
            }
        finally:
            engine.close()
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "reembed":
        from mnemosyne.hosts.query_embedding import (
            UnixSocketEmbeddingProvider,
            build_openrouter_mrl_provider,
        )
        from mnemosyne.sqlite_engine import SqliteEngine

        if args.provider == "local":
            preset = resolve_local_model(args.model, args.dims)
            target_model, target_dims = preset["model"], preset["dims"]
            if args.dry_run:
                provider = None
            elif args.socket is not None:
                provider = UnixSocketEmbeddingProvider(
                    socket_path=str(args.socket),
                    model=target_model,
                    dims=target_dims,
                    query_prefix=preset["query_prefix"],
                )
                provider.health()
            else:
                provider = build_backend(model=target_model, dims=target_dims)
        else:
            target_model = args.model or "qwen/qwen3-embedding-8b"
            target_dims = 4096 if args.dims is None else int(args.dims)
            if args.dry_run:
                provider = None
            else:
                key_path = ROOT / "codex/openrouter-api-key"
                api_key = os.environ.get("OPENROUTER_API_KEY") or (
                    key_path.read_text().strip() if key_path.exists() else ""
                )
                if not api_key:
                    raise ValueError("OPENROUTER_API_KEY or openrouter-api-key file required for openrouter reembed")
                provider, _space = build_openrouter_mrl_provider(
                    api_key=api_key,
                    dims=target_dims,
                    model=target_model,
                    tenant_id=args.tenant,
                )
        engine = SqliteEngine(args.store)
        try:
            report = reembed_store(
                engine,
                args.tenant,
                provider,
                model=target_model,
                dims=target_dims,
                branch=args.branch,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                confirm_reembed=args.confirm_reembed,
                backup_path=args.backup,
            )
        finally:
            engine.close()
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "render-config":
        print(
            render_retrieval_config(
                mode=args.mode,
                model=args.model,
                dims=args.dims,
                root=args.root,
                state=args.state,
                tenant_id=args.tenant,
            ),
            end="",
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
