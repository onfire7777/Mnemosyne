"""Quantized two-stage vector prefiltering and local dense/reranker auto-discovery.

Provides:
1. ``QuantizedVectorIndex``:
   - 1-bit packed binary codes (Hamming similarity via 256-entry LUT popcount, 32x smaller than fp32)
   - Symmetric ``int8`` scalar quantization (4x smaller than fp32)
   - Exact ``float32`` L2-normalized rescoring over the coarse shortlist, preserving >99% Recall@k
   - Deterministic binary serialization (``to_bytes`` / ``from_bytes``) and erasure-safe ``remove_ids``
2. Local adapter auto-discovery (``discover_local_embedding_provider``,
   ``discover_local_reranker``, ``auto_local_retrieval_adapters``):
   - Discovers explicitly named cached ``fastembed`` models with ``local_files_only``
     or loopback-only local daemons (e.g. ``127.0.0.1:8766`` cross-encoder, ``127.0.0.1:8765`` embedding)
     and falls back deterministically to ``HashingEmbeddingProvider`` / ``LocalSimilarityReranker``.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import struct
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import numpy as np
else:
    try:
        import numpy as np
    except ImportError:  # Base installs may discover HTTP models without NumPy.
        np = None

from mnemosyne import text as text_kernels
from mnemosyne.network_safety import (
    safe_urlopen,
    validate_fetch_url,
)
from mnemosyne.retrieval import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    HttpEmbeddingProvider,
    HttpReranker,
    LocalSimilarityReranker,
    Reranker,
    RetrievalAdapters,
)

QuantizedMode = Literal["auto", "exact", "int8_rescore", "binary_int8_rescore"]

# Precomputed 8-bit popcount lookup table for fast vectorized Hamming distance.
_POPCOUNT_LUT = (
    np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
    if np is not None else None
)
_SERIAL_MAGIC = b"MNQ1"


def _l2_normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    safe_norms = np.where(norms > 1e-12, norms, 1.0)
    out = mat / safe_norms
    out = np.where(norms > 1e-12, out, 0.0)
    return out.astype(np.float32, copy=False)


def _l2_normalize_vec(vec: Sequence[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-12 or not math.isfinite(norm):
        return np.zeros_like(arr, dtype=np.float32)
    return (arr / norm).astype(np.float32, copy=False)


def _quantize_int8_rows(unit_f32: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if unit_f32.size == 0:
        return (
            np.empty(unit_f32.shape, dtype=np.int8),
            np.empty((unit_f32.shape[0],), dtype=np.float32),
        )
    max_abs = np.max(np.abs(unit_f32), axis=1)
    scales = np.where(max_abs > 1e-8, max_abs / 127.0, 1.0 / 127.0).astype(np.float32)
    q = np.clip(np.rint(unit_f32 / scales[:, None]), -127.0, 127.0).astype(np.int8)
    return q, scales


def _pack_binary_rows(unit_f32: np.ndarray) -> np.ndarray:
    if unit_f32.size == 0:
        packed_width = (unit_f32.shape[1] + 7) // 8 if unit_f32.ndim == 2 else 0
        return np.empty((unit_f32.shape[0], packed_width), dtype=np.uint8)
    bits = (unit_f32 > 0.0).astype(np.uint8)
    return np.packbits(bits, axis=1)


class QuantizedVectorIndex:
    """Two-/three-stage quantized vector index with exact float32 rescoring.

    Maintains aligned arrays for ``ids``, 1-bit packed sign bits, symmetric per-row
    ``int8`` codes + scales, and exact L2-normalized ``float32`` vectors (optional on
    deserialization when operating purely from int8 reconstruction).
    """

    def __init__(
        self,
        dims: int,
        *,
        int8_oversample: int = 4,
        int8_min_candidates: int = 64,
        binary_oversample: int = 16,
        binary_min_candidates: int = 256,
    ) -> None:
        if np is None:
            raise ImportError("QuantizedVectorIndex requires the optional numpy dependency")
        if dims <= 0:
            raise ValueError("dims must be positive")
        self.dims = int(dims)
        self.int8_oversample = max(1, int(int8_oversample))
        self.int8_min_candidates = max(8, int(int8_min_candidates))
        self.binary_oversample = max(2, int(binary_oversample))
        self.binary_min_candidates = max(32, int(binary_min_candidates))

        self._ids: list[str] = []
        self._id_to_pos: dict[str, int] = {}
        self._f32 = np.empty((0, self.dims), dtype=np.float32)
        self._int8 = np.empty((0, self.dims), dtype=np.int8)
        self._scales = np.empty((0,), dtype=np.float32)
        self._binary = np.empty((0, (self.dims + 7) // 8), dtype=np.uint8)
        self._native: Any = None
        self._native_dirty: bool = True

    def _ensure_native(self) -> Any:
        native_mod = text_kernels.NATIVE
        native_cls = (
            getattr(native_mod, "NativeQuantizedIndex", None)
            if native_mod is not None
            else None
        )
        if native_cls is None or not self._ids:
            return None
        if self._native is None or self._native_dirty:
            self._native = native_cls.from_packed_buffers(
                self.dims,
                len(self._ids),
                np.ascontiguousarray(self._binary, dtype=np.uint8).tobytes(),
                np.ascontiguousarray(self._int8, dtype=np.int8).tobytes(),
                np.ascontiguousarray(self._scales, dtype="<f4").tobytes(),
                np.ascontiguousarray(self._f32, dtype="<f4").tobytes(),
            )
            self._native_dirty = False
        return self._native

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._ids)

    def memory_bytes(self) -> dict[str, int]:
        """Report byte footprint per representation tier."""
        return {
            "binary_bytes": int(self._binary.nbytes),
            "int8_bytes": int(self._int8.nbytes + self._scales.nbytes),
            "float32_bytes": int(self._f32.nbytes),
        }

    @classmethod
    def from_vectors(
        cls,
        ids: Sequence[str],
        vectors: Sequence[Sequence[float]] | np.ndarray,
        **kwargs: Any,
    ) -> QuantizedVectorIndex:
        if np is None:
            raise ImportError("QuantizedVectorIndex requires the optional numpy dependency")
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[0] != len(ids):
            raise ValueError("vectors must be a 2D array aligned with ids")
        idx = cls(dims=int(arr.shape[1]), **kwargs)
        idx.add_many(ids, arr)
        return idx

    def add_many(
        self,
        ids: Sequence[str],
        vectors: Sequence[Sequence[float]] | np.ndarray,
    ) -> None:
        """Insert or update vectors by ID, preserving deterministic order."""
        if not ids:
            return
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[0] != len(ids) or arr.shape[1] != self.dims:
            raise ValueError(
                f"expected shape ({len(ids)}, {self.dims}), got {arr.shape}"
            )
        unit = _l2_normalize_rows(arr)
        q_i8, scales = _quantize_int8_rows(unit)
        b_u8 = _pack_binary_rows(unit)

        # Deduplicate within input batch (last write wins) and split updates vs appends
        dedup_map: dict[str, int] = {}
        for row_idx, item_id in enumerate(ids):
            dedup_map[str(item_id)] = row_idx

        new_ids: list[str] = []
        new_rows: list[int] = []
        for item_id, row_idx in dedup_map.items():
            existing = self._id_to_pos.get(item_id)
            if existing is not None:
                self._f32[existing] = unit[row_idx]
                self._int8[existing] = q_i8[row_idx]
                self._scales[existing] = scales[row_idx]
                self._binary[existing] = b_u8[row_idx]
            else:
                new_ids.append(item_id)
                new_rows.append(row_idx)

        if new_rows:
            base = len(self._ids)
            for offset, item_id in enumerate(new_ids):
                self._id_to_pos[item_id] = base + offset
            self._ids.extend(new_ids)
            sel = np.asarray(new_rows, dtype=np.intp)
            self._f32 = (
                unit[sel].copy()
                if self._f32.shape[0] == 0
                else np.vstack([self._f32, unit[sel]])
            )
            self._int8 = (
                q_i8[sel].copy()
                if self._int8.shape[0] == 0
                else np.vstack([self._int8, q_i8[sel]])
            )
            self._scales = (
                scales[sel].copy()
                if self._scales.shape[0] == 0
                else np.concatenate([self._scales, scales[sel]])
            )
            self._binary = (
                b_u8[sel].copy()
                if self._binary.shape[0] == 0
                else np.vstack([self._binary, b_u8[sel]])
            )
        self._native_dirty = True

    def remove_ids(self, ids_to_remove: Sequence[str] | set[str]) -> int:
        """Physically purge vector rows for erased/redacted items."""
        remove_set = {str(x) for x in ids_to_remove} & self._id_to_pos.keys()
        if not remove_set:
            return 0
        keep_mask = np.array(
            [item_id not in remove_set for item_id in self._ids], dtype=bool
        )
        self._ids = [item_id for item_id in self._ids if item_id not in remove_set]
        self._id_to_pos = {item_id: i for i, item_id in enumerate(self._ids)}
        self._f32 = self._f32[keep_mask]
        self._int8 = self._int8[keep_mask]
        self._scales = self._scales[keep_mask]
        self._binary = self._binary[keep_mask]
        self._native_dirty = True
        return len(remove_set)

    def search(
        self,
        query_vec: Sequence[float] | np.ndarray,
        k: int = 10,
        *,
        mode: QuantizedMode = "auto",
        allowed_ids: set[str] | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Return ``(id, exact_cosine_score)`` pairs sorted descending."""
        n = len(self._ids)
        if k <= 0 or n == 0:
            return []
        q_f32 = _l2_normalize_vec(query_vec)
        if q_f32.shape[0] != self.dims:
            raise ValueError(
                f"query vector dims {q_f32.shape[0]} != index dims {self.dims}"
            )
        if not np.any(q_f32):
            return []

        if allowed_ids is not None:
            candidate_idx = np.array(
                [self._id_to_pos[i] for i in allowed_ids if i in self._id_to_pos],
                dtype=np.intp,
            )
            if candidate_idx.size == 0:
                return []
            candidate_idx.sort()
        else:
            candidate_idx = None

        active_n = int(candidate_idx.size) if candidate_idx is not None else n
        chosen_mode = mode
        if chosen_mode == "auto":
            if active_n >= max(1024, self.binary_min_candidates * 2):
                chosen_mode = "binary_int8_rescore"
            elif active_n >= max(64, self.int8_min_candidates):
                chosen_mode = "int8_rescore"
            else:
                chosen_mode = "exact"

        native_idx = self._ensure_native()
        if native_idx is not None:
            bin_budget = max(self.binary_oversample * k, self.binary_min_candidates)
            i8_budget = max(self.int8_oversample * k, self.int8_min_candidates)
            raw_pairs = native_idx.search(
                np.ascontiguousarray(q_f32, dtype="<f4").tobytes(),
                int(k),
                str(chosen_mode),
                candidate_idx.tolist() if candidate_idx is not None else None,
                float(min_score),
                int(bin_budget),
                int(i8_budget),
            )
            scored_pairs = [(self._ids[pos], float(val)) for pos, val in raw_pairs]
            scored_pairs.sort(key=lambda pair: (-pair[1], pair[0]))
            return scored_pairs[:k]

        pool_idx = candidate_idx

        # Stage 1: 1-bit Binary Hamming prefilter
        if chosen_mode == "binary_int8_rescore":
            bin_budget = min(
                active_n, max(self.binary_oversample * k, self.binary_min_candidates)
            )
            if bin_budget < active_n:
                q_bin = np.packbits((q_f32 > 0.0).astype(np.uint8))
                sub_bin = self._binary if pool_idx is None else self._binary[pool_idx]
                xor_bytes = np.bitwise_xor(sub_bin, q_bin[None, :])
                hamming_dist = _POPCOUNT_LUT[xor_bytes].sum(axis=1, dtype=np.int32)
                # Keep smallest Hamming distances (ties broken by row index)
                top_local = np.argpartition(hamming_dist, bin_budget - 1)[:bin_budget]
                pool_idx = top_local if pool_idx is None else pool_idx[top_local]
                active_n = int(pool_idx.size)

        # Stage 2: Symmetric int8 dot-product shortlist
        if chosen_mode in {"int8_rescore", "binary_int8_rescore"}:
            i8_budget = min(
                active_n, max(self.int8_oversample * k, self.int8_min_candidates)
            )
            if i8_budget < active_n:
                q_max = float(np.max(np.abs(q_f32)))
                q_scale = q_max / 127.0 if q_max > 1e-8 else 1.0 / 127.0
                q_i8 = np.clip(np.rint(q_f32 / q_scale), -127.0, 127.0).astype(np.int32)
                sub_i8 = self._int8 if pool_idx is None else self._int8[pool_idx]
                sub_scales = (
                    self._scales if pool_idx is None else self._scales[pool_idx]
                )
                raw_dots = sub_i8.astype(np.int32) @ q_i8
                approx_scores = raw_dots.astype(np.float32) * (sub_scales * q_scale)
                top_local = np.argpartition(-approx_scores, i8_budget - 1)[:i8_budget]
                pool_idx = top_local if pool_idx is None else pool_idx[top_local]

        # Stage 3: Exact float32 cosine rescoring over shortlist
        sub_f32 = self._f32 if pool_idx is None else self._f32[pool_idx]
        exact_scores = sub_f32 @ q_f32
        if pool_idx is None:
            row_indices = np.arange(n, dtype=np.intp)
        else:
            row_indices = pool_idx

        # Deterministic sort by (-score, id)
        scored_pairs: list[tuple[str, float]] = []
        for idx_pos, val in zip(row_indices.tolist(), exact_scores.tolist()):
            score = float(val)
            if score > min_score:
                scored_pairs.append((self._ids[idx_pos], score))
        scored_pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored_pairs[:k]

    def to_bytes(self, *, include_float32: bool = True) -> bytes:
        """Serialize quantized index to compact deterministic bytes."""
        header = json.dumps(
            {
                "dims": self.dims,
                "count": len(self._ids),
                "include_float32": bool(include_float32),
                "int8_oversample": self.int8_oversample,
                "int8_min_candidates": self.int8_min_candidates,
                "binary_oversample": self.binary_oversample,
                "binary_min_candidates": self.binary_min_candidates,
                "ids": self._ids,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        parts = [
            _SERIAL_MAGIC,
            struct.pack("<I", len(header)),
            header,
            self._binary.tobytes(order="C"),
            self._int8.tobytes(order="C"),
            self._scales.astype("<f4").tobytes(order="C"),
        ]
        if include_float32:
            parts.append(self._f32.astype("<f4").tobytes(order="C"))
        return b"".join(parts)

    @classmethod
    def from_bytes(cls, payload: bytes) -> QuantizedVectorIndex:
        """Restore ``QuantizedVectorIndex`` from ``to_bytes()`` output."""
        if len(payload) < 8 or payload[:4] != _SERIAL_MAGIC:
            raise ValueError("invalid quantized vector index magic header")
        header_len = struct.unpack("<I", payload[4:8])[0]
        offset = 8 + header_len
        if len(payload) < offset:
            raise ValueError("truncated quantized vector index header")
        meta = json.loads(payload[8:offset].decode("utf-8"))
        dims = int(meta["dims"])
        count = int(meta["count"])
        include_f32 = bool(meta.get("include_float32", True))
        idx = cls(
            dims=dims,
            int8_oversample=int(meta.get("int8_oversample", 4)),
            int8_min_candidates=int(meta.get("int8_min_candidates", 64)),
            binary_oversample=int(meta.get("binary_oversample", 16)),
            binary_min_candidates=int(meta.get("binary_min_candidates", 256)),
        )
        idx._ids = [str(x) for x in meta["ids"]]
        if len(idx._ids) != count:
            raise ValueError("quantized vector index id count mismatch")
        idx._id_to_pos = {item_id: i for i, item_id in enumerate(idx._ids)}

        bin_width = (dims + 7) // 8
        bin_bytes = count * bin_width
        i8_bytes = count * dims
        scale_bytes = count * 4
        f32_bytes = count * dims * 4 if include_f32 else 0
        expected_total = offset + bin_bytes + i8_bytes + scale_bytes + f32_bytes
        if len(payload) != expected_total:
            raise ValueError("quantized vector index payload size mismatch")

        idx._binary = (
            np.frombuffer(payload, dtype=np.uint8, count=bin_bytes, offset=offset)
            .reshape((count, bin_width))
            .copy()
        )
        offset += bin_bytes
        idx._int8 = (
            np.frombuffer(payload, dtype=np.int8, count=i8_bytes, offset=offset)
            .reshape((count, dims))
            .copy()
        )
        offset += i8_bytes
        idx._scales = (
            np.frombuffer(payload, dtype="<f4", count=count, offset=offset)
            .astype(np.float32)
            .copy()
        )
        offset += scale_bytes
        if include_f32:
            idx._f32 = (
                np.frombuffer(payload, dtype="<f4", count=count * dims, offset=offset)
                .reshape((count, dims))
                .astype(np.float32)
                .copy()
            )
        else:
            # Reconstruct L2-normalized float32 approximation from int8 + scales
            dequant = idx._int8.astype(np.float32) * idx._scales[:, None]
            idx._f32 = _l2_normalize_rows(dequant)
        idx._native = None
        idx._native_dirty = True
        return idx


def dense_scan_f32_packed(
    query_vec: Sequence[float] | np.ndarray,
    rows_f32: bytes,
    dims: int,
    row_mask: bytes,
) -> list[float | None]:
    """SIMD/NEON packed float32 dot-product scan with pure-NumPy fallback."""
    native_mod = text_kernels.NATIVE
    native_fn = (
        getattr(native_mod, "dense_scan_f32_packed", None)
        if native_mod is not None
        else None
    )
    if np is not None:
        q_bytes = np.ascontiguousarray(query_vec, dtype="<f4").tobytes()
    else:
        q_bytes = struct.pack(f"<{dims}f", *(float(v) for v in query_vec))
    if native_fn is not None:
        return list(native_fn(q_bytes, rows_f32, int(dims), row_mask))
    if np is None:
        raise ImportError("dense_scan_f32_packed requires mnemosyne_native or numpy")
    q_arr = np.frombuffer(q_bytes, dtype="<f4")
    n = len(row_mask)
    if n == 0:
        return []
    mat = np.frombuffer(rows_f32, dtype="<f4").reshape((n, int(dims)))
    dots = (mat @ q_arr).tolist()
    return [float(dots[i]) if row_mask[i] else None for i in range(n)]


def dense_scan_f16_packed(
    query_vec: Sequence[float] | np.ndarray,
    rows_f16: bytes,
    dims: int,
    row_mask: bytes,
) -> list[float | None]:
    """SIMD/NEON packed float16 dot-product scan with pure-NumPy fallback."""
    native_mod = text_kernels.NATIVE
    native_fn = (
        getattr(native_mod, "dense_scan_f16_packed", None)
        if native_mod is not None
        else None
    )
    if np is not None:
        q_bytes = np.ascontiguousarray(query_vec, dtype="<f4").tobytes()
    else:
        q_bytes = struct.pack(f"<{dims}f", *(float(v) for v in query_vec))
    if native_fn is not None:
        return list(native_fn(q_bytes, rows_f16, int(dims), row_mask))
    if np is None:
        raise ImportError("dense_scan_f16_packed requires mnemosyne_native or numpy")
    q_arr = np.frombuffer(q_bytes, dtype="<f4")
    n = len(row_mask)
    if n == 0:
        return []
    mat = np.frombuffer(rows_f16, dtype="<f2").reshape((n, int(dims))).astype(np.float32)
    dots = (mat @ q_arr).tolist()
    return [float(dots[i]) if row_mask[i] else None for i in range(n)]


@dataclass(frozen=True, slots=True)
class FastEmbedLocalProvider:
    """In-process local ONNX embedding adapter via ``fastembed`` when installed."""

    _model: Any
    dims: int
    name: str = "local-fastembed"

    def embed(self, text: str) -> list[float]:
        vecs = list(self._model.embed([text]))
        if not vecs:
            return [0.0] * self.dims
        return _l2_normalize_vec(vecs[0]).tolist()

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = list(self._model.embed(list(texts)))
        return [_l2_normalize_vec(v).tolist() for v in vecs]


def _is_loopback_url(url: str) -> bool:
    # Validate the original endpoint before urljoin can discard unsafe parts.
    if not url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and (parsed.port is None or 0 < parsed.port <= 65535)
        )
    except ValueError:
        return False


def _probe_loopback_json(url: str, timeout_seconds: float = 0.25) -> dict[str, Any] | None:
    if not _is_loopback_url(url) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        return None
    try:
        validated = validate_fetch_url(
            url,
            allow_insecure_localhost=True,
            purpose="local retrieval discovery",
            loopback_only=True,
        )
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        with safe_urlopen(req, validated=validated, timeout=timeout_seconds) as resp:
            if resp.status != 200 or resp.headers.get_content_type() != "application/json":
                return None
            payload = resp.read(65537)
            if len(payload) > 65536:
                return None
            data = json.loads(payload.decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        return None


def _probe_endpoint_health(endpoint: str, timeout_seconds: float) -> dict[str, Any] | None:
    if not _is_loopback_url(endpoint):
        return None
    return _probe_loopback_json(urllib.parse.urljoin(endpoint, "/health"), timeout_seconds)


def _semantic_health_metadata(
    health: dict[str, Any] | None, capability: str, *, backends: set[str]
) -> dict[str, Any] | None:
    """A healthy web server is not evidence of a loaded semantic model."""
    if not health or health.get("status") != "ok":
        return None
    metadata = health.get(capability)
    if not isinstance(metadata, dict):
        return None
    model = metadata.get("model")
    backend = metadata.get("backend")
    if not isinstance(model, str) or not model.strip():
        return None
    if not isinstance(backend, str) or backend not in backends:
        return None
    return metadata


def _embedding_health_dims(metadata: dict[str, Any]) -> int | None:
    widths = [metadata[key] for key in ("dimensions", "dims") if key in metadata]
    if not widths or any(type(width) is not int or width <= 0 for width in widths):
        return None
    if len(set(widths)) != 1:
        return None
    return widths[0]


def discover_local_embedding_provider(
    *,
    default_dims: int = 256,
    probe_timeout_seconds: float = 0.25,
    allow_loopback_http: bool = True,
    allow_inprocess_onnx: bool = True,
) -> EmbeddingProvider:
    """Auto-discover a safe local dense embedding provider, falling back to hashing."""
    if allow_inprocess_onnx and np is not None:
        model_name = os.environ.get("MNEMOSYNE_FASTEMBED_MODEL", "").strip()
        if model_name:
            try:
                from fastembed import TextEmbedding  # type: ignore[import-not-found]

                fe_model = TextEmbedding(model_name=model_name, local_files_only=True)
                sample = np.asarray(list(fe_model.embed(["probe"]))[0], dtype=np.float32)
                if sample.ndim != 1 or not sample.size or not np.isfinite(sample).all() or not np.any(sample):
                    raise ValueError("cached embedding model returned an invalid probe vector")
                return FastEmbedLocalProvider(
                    _model=fe_model,
                    dims=int(len(sample)),
                    name=f"fastembed:{model_name}",
                )
            except Exception:
                pass

    if allow_loopback_http:
        explicit_url = os.environ.get(
            "MNEMOSYNE_LOCAL_EMBEDDING_URL", "http://127.0.0.1:8765/v1/embeddings"
        )
        health = _probe_endpoint_health(explicit_url, probe_timeout_seconds)
        emb_meta = _semantic_health_metadata(
            health, "embedding", backends={"sentence-transformers", "fastembed"}
        )
        detected_dims = _embedding_health_dims(emb_meta) if emb_meta is not None else None
        if emb_meta is not None and detected_dims is not None:
            return HttpEmbeddingProvider(
                url=explicit_url,
                model=emb_meta["model"],
                dims=detected_dims,
                timeout_seconds=10.0,
                name=f"local-http-embedding:{emb_meta['model']}",
                loopback_only=True,
            )

    return HashingEmbeddingProvider(dims=default_dims)


def discover_local_reranker(
    *,
    fallback_embedding: EmbeddingProvider | None = None,
    probe_timeout_seconds: float = 0.25,
    allow_loopback_http: bool = True,
) -> Reranker:
    """Auto-discover a loopback cross-encoder reranker, falling back to LocalSimilarityReranker."""
    if allow_loopback_http:
        rerank_url = os.environ.get(
            "MNEMOSYNE_LOCAL_RERANKER_URL", "http://127.0.0.1:8766/rerank"
        )
        health = _probe_endpoint_health(rerank_url, probe_timeout_seconds)
        rk_meta = _semantic_health_metadata(health, "reranker", backends={"cross-encoder"})
        if rk_meta is not None:
            model_name = rk_meta["model"]
            return HttpReranker(
                url=rerank_url,
                model=model_name,
                timeout_seconds=10.0,
                name=f"local-cross-encoder:{model_name}",
                query_prefix="",
                score_kind="logit",
                loopback_only=True,
            )

    emb = fallback_embedding or HashingEmbeddingProvider()
    return LocalSimilarityReranker(embedding_provider=emb)


def auto_local_retrieval_adapters(
    *,
    default_dims: int = 256,
    probe_timeout_seconds: float = 0.25,
    allow_loopback_http: bool = True,
    allow_inprocess_onnx: bool = True,
) -> RetrievalAdapters:
    """Build ``RetrievalAdapters`` using local dense/cross-encoder discovery with safe fallback."""
    embedding = discover_local_embedding_provider(
        default_dims=default_dims,
        probe_timeout_seconds=probe_timeout_seconds,
        allow_loopback_http=allow_loopback_http,
        allow_inprocess_onnx=allow_inprocess_onnx,
    )
    reranker = discover_local_reranker(
        fallback_embedding=embedding,
        probe_timeout_seconds=probe_timeout_seconds,
        allow_loopback_http=allow_loopback_http,
    )
    return RetrievalAdapters(
        embedding=embedding,
        reranker=reranker,
    )
