#!/usr/bin/env python3
"""Instrumented launcher for the embedding service (diagnostics only).

Wraps the production FastAPI app from ``app.py`` with a request-counting
middleware so we can PROVE, from outside, whether the Mnemosyne CLI's retrieval
path actually calls ``/embed`` and ``/rerank`` over HTTP. It does not change the
service contract or behavior — it only counts requests and exposes the tallies at
``GET /_counters`` (and writes them to ``EMBEDDING_COUNTER_FILE`` on each call).

Run exactly like ``app.py``:
    EMBEDDING_SERVICE_PORT=8000 python services/embedding/serve_instrumented.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as svc  # noqa: E402  the production service module

COUNTER_FILE = os.environ.get("EMBEDDING_COUNTER_FILE", "/tmp/embedding_counters.json")
HOST = os.environ.get("EMBEDDING_SERVICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("EMBEDDING_SERVICE_PORT", "8000"))

_counts: Counter = Counter()


def _flush() -> None:
    try:
        Path(COUNTER_FILE).write_text(json.dumps(dict(_counts)))
    except OSError:
        pass


def main() -> None:
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware

    app = svc.build_fastapi_app()

    class CountMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path.rstrip("/") or "/"
            _counts[f"{request.method} {path}"] += 1
            _flush()
            return await call_next(request)

    app.add_middleware(CountMiddleware)

    @app.get("/_counters")
    async def _counters() -> dict:
        return dict(_counts)

    _flush()
    print(
        f"[embedding-service:instrumented] FastAPI/uvicorn on http://{HOST}:{PORT} "
        f"(counters -> {COUNTER_FILE})",
        flush=True,
    )
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
