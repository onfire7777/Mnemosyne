#!/usr/bin/env python3
"""Command-backed media embedding provider (``CommandMediaEmbeddingProvider``).

Mnemosyne invokes this as ``<this> <tmp-media-path>`` with a JSON request on
stdin (``{"path","media_type","modality","metadata"}``) and expects
``{"embedding": [...]}`` on stdout. It derives the media's genuinely-embedded
text (same stdlib extractor as the text-extractor provider) and POSTs it to the
real self-hosted bge embedder, returning the genuine vector — no fabricated
numbers. Env: ``MNEMOSYNE_EMBEDDING_URL`` (or ``MNEMOSYNE_MEDIA_EMBEDDING_URL``),
``MNEMOSYNE_EMBEDDING_MODEL``, ``MNEMOSYNE_MEDIA_EMBEDDING_DIMS``, and the
retrieval internal-host allowlist for the embedder host.
"""

from __future__ import annotations

import json
import os
import sys

from mnemosyne.media_embedded_text import extract_embedded_text
from mnemosyne.retrieval import HttpEmbeddingProvider


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({"error": "missing media path argument"}), file=sys.stderr)
        return 2
    path = argv[-1]
    raw = sys.stdin.read() or "{}"
    try:
        request = json.loads(raw)
        if not isinstance(request, dict):
            request = {}
    except json.JSONDecodeError:
        request = {}
    modality = str(request.get("modality") or "").strip()
    media_type = str(request.get("media_type") or "").strip()
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        print(json.dumps({"error": f"could not read media: {exc}"}), file=sys.stderr)
        return 1

    text, _sources = extract_embedded_text(data, media_type=media_type)
    if not text.strip():
        # No embedded text: embed a stable structural descriptor so the asset
        # still receives a genuine (non-fabricated) vector rather than nothing.
        text = f"{modality} media asset".strip() or "media asset"

    url = os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_URL") or os.environ.get("MNEMOSYNE_EMBEDDING_URL")
    if not url:
        print(json.dumps({"error": "MNEMOSYNE_EMBEDDING_URL is required"}), file=sys.stderr)
        return 1
    model = os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_MODEL") or os.environ.get("MNEMOSYNE_EMBEDDING_MODEL")
    dims = int(os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_DIMS", os.environ.get("MNEMOSYNE_EMBEDDING_DIMS", "1024")))
    timeout = float(os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_TIMEOUT", "30"))
    provider = HttpEmbeddingProvider(url=url, model=model, dims=dims, timeout_seconds=timeout)
    try:
        vector = provider.embed(text)
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the caller.
        print(json.dumps({"error": f"embedding failed: {exc}"}), file=sys.stderr)
        return 1
    print(json.dumps({"embedding": vector}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
