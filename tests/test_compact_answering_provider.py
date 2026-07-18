"""Synthetic contract checks for the compact answering provider seam."""

from __future__ import annotations

import hashlib
import json

import pytest

from mnemosyne.models import Hit
from mnemosyne.providers.compact_answering import (
    CompactAnsweringProvider,
    CompactProviderIdentity,
    CompactProtocolError,
)


IDENTITY = CompactProviderIdentity(
    provider="answering-ort",
    provider_sha256="1" * 64,
    artifact="compact-int8.onnx",
    artifact_sha256="2" * 64,
    configuration="compact-config-v1",
    configuration_sha256="3" * 64,
)


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class _FixtureTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def __call__(
        self,
        _endpoint: str,
        body: bytes,
        _headers: dict[str, str],
        _timeout: float,
        _max_response_bytes: int,
    ) -> bytes:
        request = json.loads(body)
        self.requests.append(request)
        payload = request["payload"]
        operation = request["operation"]
        if operation == "embed" and isinstance(payload["input"], str):
            result = {"embedding": [3.0, 4.0]}
        elif operation == "embed":
            result = {
                "data": [
                    {"index": index, "embedding": [float(index + 1), 1.0]}
                    for index, _item in enumerate(payload["input"])
                ]
            }
        elif operation == "rerank":
            result = {"results": [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.2}]}
        else:
            result = {
                "spans": [{"cid": "e1", "start": 0, "end": 5}],
                "unresolved": False,
            }
        response = {
            "operation": operation,
            "request_sha256": request["request_sha256"],
            "identity": request["identity"],
            "capabilities": request["capabilities"],
            "result": result,
        }
        return json.dumps(response, separators=(",", ":")).encode()


def _provider(transport: _FixtureTransport) -> CompactAnsweringProvider:
    return CompactAnsweringProvider(
        "http://127.0.0.1:18181/compact",
        IDENTITY,
        dims=2,
        bearer_token="fixture-token",
        require_bearer_auth=True,
        transport=transport,
    )


def test_synthetic_embed_rerank_and_read_preserve_existing_shapes() -> None:
    transport = _FixtureTransport()
    provider = _provider(transport)
    assert provider.embed("hello") == pytest.approx([0.6, 0.8])
    vectors = provider.embed_many(["one", "two"])
    assert vectors[0] == pytest.approx([0.70710678, 0.70710678])
    assert vectors[1] == pytest.approx([0.89442719, 0.4472136])
    hits = [
        Hit("a", "evidence", "tenant", "main", "first", 0.1, "lexical"),
        Hit("b", "evidence", "tenant", "main", "second", 0.2, "lexical"),
    ]
    ranked = provider.rerank("question", hits, 2)
    assert [hit.id for hit in ranked] == ["b", "a"]
    assert ranked[0].channel == "lexical+rerank"
    assert provider.read(
        {
            "question": "What?",
            "evidence": [{"cid": "e1", "content": "Paris is sunny."}],
        }
    ) == {
        "claims": [{"spans": [{"cid": "e1", "quote": "Paris"}]}],
        "unresolved": False,
    }
    assert [request["operation"] for request in transport.requests] == [
        "embed",
        "embed",
        "rerank",
        "read",
    ]


def test_identity_and_request_digest_are_custody_bound() -> None:
    transport = _FixtureTransport()
    provider = _provider(transport)
    provider.embed("stable")
    request = transport.requests[0]
    assert request["request_sha256"] == _digest(request["payload"])
    assert provider.disclosure["artifact_sha256"] == "2" * 64

    class DriftTransport(_FixtureTransport):
        def __call__(self, *args: object) -> bytes:
            response = json.loads(super().__call__(*args))
            response["identity"]["artifact_sha256"] = "4" * 64
            return json.dumps(response).encode()

    with pytest.raises(CompactProtocolError, match="identity"):
        _provider(DriftTransport()).embed("drift")
