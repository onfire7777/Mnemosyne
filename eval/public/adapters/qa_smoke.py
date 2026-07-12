"""Redistributable QA schema/custody fixture; it does not execute role commands."""

from __future__ import annotations

import hashlib

from typing import Any

from eval.public.scoring import score_profile
from mnemosyne.providers.extractive_decomposer import disclosure
from mnemosyne.providers.grounded_protocol import (
    GENERATION_SPEC,
    MODEL_CONTENT_SHA256,
    MODEL_SELECTOR,
    role_digests,
)


def run(benchmark: dict[str, Any], _cli: object) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    record = benchmark["corpus"][0]
    capture = record["capture"]
    captured = _cli.capture(
        capture["tenant_id"], capture["user_id"], capture["content"],
        actor=capture["actor"], source_type=capture["source_type"], source_identity=capture["source_identity"],
    )
    if captured["cid"] != record["doc_id"]:
        raise ValueError("public CLI capture CID does not match QA benchmark custody")
    trace = {
        "abstained": False,
        "answer": "red fox",
        "authorized_evidence_fingerprint": _fingerprint([record["doc_id"]]),
        "authorized_retrieval_hops": [{"hop": 0, "rows": [{"capture": capture, "cid": captured["cid"]}]}],
        "claims": [{
            "evidence_cids": [record["doc_id"]],
            "spans": [{
                "cid": record["doc_id"], "start": 0, "end": 7,
                "slice_sha256": hashlib.sha256(b"red fox").hexdigest(),
            }],
            "text": "red fox",
        }],
        "question_id": "qa-smoke-1",
        "reader": {
            "query_decomposer": disclosure(),
            "grounded_reader": {
                "role": "grounded_reader",
                "model": MODEL_SELECTOR,
                "model_content_digest": MODEL_CONTENT_SHA256,
                **role_digests("grounded_reader"),
                "decoding_options": GENERATION_SPEC,
            },
        },
        "scoring_family": "qa",
    }
    labels = [{"answers": ["red fox"], "question_id": "qa-smoke-1"}]
    return [trace], score_profile("qa-em-f1-v1", labels, [trace])


def _fingerprint(cids: list[str]) -> str:
    import hashlib
    import json

    raw = (json.dumps(sorted(cids), separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()
