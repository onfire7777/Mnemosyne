"""Self-test: start the service and assert it satisfies Mnemosyne's adapter contract.

This boots the embedding/reranker service on a free port (stdlib path, so it runs
offline with no torch/models) and verifies BOTH:

1. The raw HTTP response shapes match what ``HttpEmbeddingProvider`` /
   ``HttpReranker`` parse (``/embed`` -> ``{"embedding": [...]}``;
   ``/rerank`` -> ``{"results": [{"index", "score"}]}``); and

2. The *actual Mnemosyne adapters* from ``src/mnemosyne/retrieval.py`` consume the
   live service end-to-end and reproduce the ``provider-check`` behavior:
     * ``HttpEmbeddingProvider(dims=1024).embed(text)`` returns a normalized
       1024-vector (non-zero requirement satisfied);
     * ``HttpReranker.rerank(query, [irrelevant, relevant], k=2)`` ranks the
       relevant document first.

If ``mnemosyne`` is importable (it is, from this repo's ``src/``), the test runs
the strong adapter-level assertions. If it is not importable for any reason, the
test falls back to validating the raw JSON shapes directly so it still proves the
contract offline. Exit code 0 == contract satisfied.

Run:  python services/embedding/selftest.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent  # .../Mnemosyne-completion
SRC = REPO_ROOT / "src"

# Make both the service module and the mnemosyne package importable.
sys.path.insert(0, str(HERE))
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

# Force the deterministic fallback so the test is hermetic/offline.
os.environ.setdefault("EMBEDDING_SERVICE_FORCE_FALLBACK", "1")

import app as service  # noqa: E402  (after sys.path setup)

EXPECTED_DIMS = 1024


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _start_stdlib_server(port: int):
    from http.server import ThreadingHTTPServer

    handler = service._make_stdlib_handler()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    # Wait for readiness.
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            _get(f"{base}/health")
            return httpd, base
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("service did not become ready")


def _check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        raise AssertionError(name)


def main() -> int:
    port = _free_port()
    httpd, base = _start_stdlib_server(port)
    print(f"[selftest] service up at {base} (deterministic fallback path)")
    try:
        # --- /health --------------------------------------------------- #
        health = _get(f"{base}/health")
        _check("health.status == ok", health.get("status") == "ok", json.dumps(health.get("embedding", {})))

        # --- raw /embed shape ----------------------------------------- #
        emb = _post(f"{base}/embed", {"input": "preferred database is postgres"})
        _check("embed response has `embedding`", isinstance(emb.get("embedding"), list))
        vec = emb["embedding"]
        _check(
            f"embed vector length == {EXPECTED_DIMS}",
            len(vec) == EXPECTED_DIMS,
            f"len={len(vec)}",
        )
        _check("embed vector is non-zero", any(abs(x) > 0 for x in vec))
        _check("embed vector values are finite floats", all(isinstance(x, float) for x in vec))

        # --- raw batch /embed shape (OpenAI-style) -------------------- #
        batch = _post(f"{base}/embed", {"input": ["alpha text", "beta text"]})
        _check("batch embed has data list", isinstance(batch.get("data"), list) and len(batch["data"]) == 2)
        _check(
            "batch data[0].embedding is 1024-dim",
            len(batch["data"][0]["embedding"]) == EXPECTED_DIMS,
        )

        # --- raw /rerank shape ---------------------------------------- #
        rr = _post(
            f"{base}/rerank",
            {
                "query": "preferred database",
                "documents": ["the sky is blue today", "my preferred database is postgres"],
                "top_n": 2,
            },
        )
        _check("rerank response has `results`", isinstance(rr.get("results"), list))
        results = rr["results"]
        _check("rerank returned 2 results", len(results) == 2)
        _check("rerank rows have int index", all(isinstance(r["index"], int) for r in results))
        _check("rerank rows have numeric score", all(isinstance(r["score"], (int, float)) for r in results))
        _check(
            "rerank ranks relevant doc (index 1) first",
            results[0]["index"] == 1,
            f"top={results[0]}",
        )

        # --- strong: drive the REAL Mnemosyne adapters ----------------- #
        try:
            from mnemosyne.models import Hit  # type: ignore
            from mnemosyne.retrieval import HttpEmbeddingProvider, HttpReranker  # type: ignore
        except Exception as exc:  # pragma: no cover - only if src not importable
            print(f"[selftest] mnemosyne adapters not importable ({exc}); raw-shape checks already passed.")
            print("[selftest] ALL CONTRACT CHECKS PASSED (raw mode)")
            return 0

        provider = HttpEmbeddingProvider(url=f"{base}/embed", dims=EXPECTED_DIMS, timeout_seconds=10.0)
        # This is exactly what `provider-check` calls.
        adapter_vec = provider.embed("Mnemosyne provider health check")
        _check(
            f"HttpEmbeddingProvider.embed -> {EXPECTED_DIMS} dims",
            len(adapter_vec) == EXPECTED_DIMS,
            f"len={len(adapter_vec)}",
        )
        norm = sum(x * x for x in adapter_vec) ** 0.5
        _check("adapter vector is L2-normalized & non-zero", abs(norm - 1.0) < 1e-6, f"norm={norm:.6f}")

        reranker = HttpReranker(url=f"{base}/rerank", timeout_seconds=10.0)
        hits = [
            Hit(id="a", kind="evidence", tenant_id="health", branch="main",
                text="irrelevant text", score=0.1, channel="health"),
            Hit(id="b", kind="evidence", tenant_id="health", branch="main",
                text="provider health check", score=0.1, channel="health"),
        ]
        ranked = reranker.rerank("provider health", hits, k=2)
        _check("HttpReranker.rerank returned hits", len(ranked) > 0, f"n={len(ranked)}")
        _check(
            "HttpReranker ranks relevant hit (id=b) first",
            ranked[0].id == "b",
            f"top_id={ranked[0].id} score={ranked[0].score:.4f}",
        )
        _check(
            "reranked hit channel marked +rerank",
            ranked[0].channel.endswith("+rerank"),
            ranked[0].channel,
        )

        print("[selftest] ALL CONTRACT CHECKS PASSED (mnemosyne adapter mode)")
        return 0
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
