"""Synthetic contract checks for the compact answering provider seam."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading

import pytest

from mnemosyne.models import Hit
from mnemosyne.providers.compact_answering import (
    CompactAnsweringProvider,
    CompactProviderError,
    CompactProviderIdentity,
    CompactProtocolError,
    CompactServiceError,
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
        self.headers: list[dict[str, str]] = []

    def __call__(
        self,
        _endpoint: str,
        body: bytes,
        headers: dict[str, str],
        _timeout: float,
        _max_response_bytes: int,
    ) -> bytes:
        request = json.loads(body)
        self.requests.append(request)
        self.headers.append(dict(headers))
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
    assert all(
        headers["Authorization"] == "Bearer fixture-token"
        for headers in transport.headers
    )


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


def test_unicode_reader_spans_use_exact_utf8_byte_offsets() -> None:
    class UnicodeTransport(_FixtureTransport):
        def __call__(self, *args: object) -> bytes:
            response = json.loads(super().__call__(*args))
            response["result"] = {
                "spans": [{"cid": "e1", "start": 7, "end": 20}],
                "unresolved": False,
            }
            return json.dumps(response).encode()

    provider = _provider(UnicodeTransport())
    assert provider.read(
        {
            "question": "What?",
            "evidence": [{"cid": "e1", "content": "prefix naïve 東京 suffix"}],
        }
    ) == {
        "claims": [{"spans": [{"cid": "e1", "quote": "naïve 東京"}]}],
        "unresolved": False,
    }

    class SplitCodepointTransport(_FixtureTransport):
        def __call__(self, *args: object) -> bytes:
            response = json.loads(super().__call__(*args))
            response["result"] = {
                "spans": [{"cid": "e1", "start": 10, "end": 20}],
                "unresolved": False,
            }
            return json.dumps(response).encode()

    with pytest.raises(CompactProtocolError, match="UTF-8"):
        _provider(SplitCodepointTransport()).read(
            {
                "question": "What?",
                "evidence": [{"cid": "e1", "content": "prefix naïve 東京 suffix"}],
            }
        )


def test_unavailable_and_oversize_transports_fail_closed() -> None:
    def unavailable(*_args: object) -> bytes:
        raise TimeoutError("synthetic timeout")

    provider = CompactAnsweringProvider(
        "unix:///tmp/answering-ort.sock?path=/compact",
        IDENTITY,
        dims=2,
        transport=unavailable,
    )
    with pytest.raises(CompactProviderError, match="failed closed"):
        provider.embed("no fallback")

    def oversize(*_args: object) -> bytes:
        return b"x" * 129

    provider = CompactAnsweringProvider(
        "http://[::1]:18181/compact",
        IDENTITY,
        dims=2,
        max_response_bytes=128,
        transport=oversize,
    )
    with pytest.raises(CompactProviderError, match="output limit"):
        provider.embed("bounded")

    provider = CompactAnsweringProvider(
        "http://127.0.0.1:18181/compact",
        IDENTITY,
        dims=2,
        max_request_bytes=128,
        transport=_FixtureTransport(),
    )
    with pytest.raises(CompactProviderError, match="input limit"):
        provider.embed("x" * 129)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:18181/compact",
        "http://192.0.2.10:18181/compact",
        "http://user:pass@127.0.0.1:18181/compact",
        "unix://relative.sock",
        "unix:///tmp/answering.sock?path=/compact%0d%0aInjected:true",
        "http+unix://%2Ftmp%2Fanswering.sock/compact?unexpected=yes",
    ],
)
def test_endpoint_policy_rejects_nonlocal_or_ambiguous_targets(endpoint: str) -> None:
    with pytest.raises(ValueError):
        CompactAnsweringProvider(endpoint, IDENTITY)


class _RawTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def __call__(self, _endpoint: str, body: bytes, *_args: object) -> bytes:
        assert body.endswith(b"\n")
        self.requests.append(json.loads(body))
        return json.dumps(self.response, separators=(",", ":")).encode() + b"\n"


def test_raw_answering_ort_shapes_preserve_ids_order_spans_and_custody() -> None:
    transport = _RawTransport(
        {
            "ok": True,
            "result": {
                "operation": "rerank",
                "ranked_ids": ["b", "a"],
            },
        }
    )
    provider = CompactAnsweringProvider(
        "http://127.0.0.1:18181",
        IDENTITY,
        dims=2,
        wire_protocol="answering-ort",
        transport=transport,
    )
    hits = [
        Hit("a", "evidence", "tenant", "main", "first", 0.1, "lexical"),
        Hit("b", "evidence", "tenant", "main", "second", 0.2, "lexical"),
    ]
    assert [hit.id for hit in provider.rerank("question", hits, 2)] == ["b", "a"]
    assert transport.requests == [
        {
            "operation": "rerank",
            "query": "query: question",
            "evidence": [{"id": "a", "text": "first"}, {"id": "b", "text": "second"}],
            "rank_width": 2,
        }
    ]
    assert provider.disclosure["wire_protocol"] == "answering-ort"

    transport.response = {
        "ok": True,
        "result": {"operation": "embed", "embedding": [3.0, 4.0]},
    }
    assert provider.embed_many(["first", "second"]) == [pytest.approx([0.6, 0.8])] * 2
    assert transport.requests[-2:] == [
        {"operation": "embed", "query": "first"},
        {"operation": "embed", "query": "second"},
    ]

    transport.response = {
        "ok": True,
        "result": {
            "operation": "read",
            "prediction": {
                "answer_type": "span",
                "evidence_id": "e1",
                "start": 7,
                "end": 20,
                "supporting_ids": ["e1"],
            },
        },
    }
    assert provider.read(
        {"question": "What?", "evidence": [{"cid": "e1", "content": "prefix naïve 東京 suffix"}]}
    ) == {"claims": [{"spans": [{"cid": "e1", "quote": "naïve 東京"}]}], "unresolved": False}


@pytest.mark.parametrize(
    "prediction",
    [
        {"answer_type": "null", "supporting_ids": ["unknown"]},
        {
            "answer_type": "span",
            "evidence_id": "e1",
            "start": 0,
            "end": 3,
            "supporting_ids": ["e2"],
        },
    ],
)
def test_raw_answering_ort_rejects_invalid_supporting_ids(prediction: dict[str, object]) -> None:
    provider = CompactAnsweringProvider(
        "http://127.0.0.1:18181",
        IDENTITY,
        wire_protocol="answering-ort",
        transport=_RawTransport({
            "ok": True,
            "result": {"operation": "read", "prediction": prediction},
        }),
    )
    with pytest.raises(CompactProtocolError, match="supporting id"):
        provider.read({
            "question": "What?",
            "evidence": [
                {"cid": "e1", "content": "one"},
                {"cid": "e2", "content": "two"},
            ],
        })


def test_raw_transport_supports_loopback_tcp_and_absolute_unix() -> None:
    response = json.dumps({
        "ok": True,
        "result": {"operation": "embed", "embedding": [3.0, 4.0]},
    }, separators=(",", ":")).encode() + b"\n"

    def serve_once(server: socket.socket) -> threading.Thread:
        def serve() -> None:
            with server:
                connection, _address = server.accept()
                with connection:
                    assert connection.recv(4096).endswith(b"\n")
                    connection.sendall(response)

        thread = threading.Thread(target=serve)
        thread.start()
        return thread

    tcp = socket.socket()
    tcp.bind(("127.0.0.1", 0))
    tcp.listen(1)
    port = tcp.getsockname()[1]
    tcp_thread = serve_once(tcp)
    tcp_provider = CompactAnsweringProvider(
        f"http://127.0.0.1:{port}", IDENTITY, dims=2, wire_protocol="answering-ort"
    )
    assert tcp_provider.embed("tcp") == pytest.approx([0.6, 0.8])
    tcp_thread.join()

    path = f"/tmp/mnemosyne-answering-{os.getpid()}.sock"
    unix = socket.socket(socket.AF_UNIX)
    unix.bind(path)
    unix.listen(1)
    unix_thread = serve_once(unix)
    unix_provider = CompactAnsweringProvider(
        f"unix://{path}", IDENTITY, dims=2, wire_protocol="answering-ort"
    )
    assert unix_provider.embed("unix") == pytest.approx([0.6, 0.8])
    unix_thread.join()
    os.unlink(path)


@pytest.mark.parametrize("response", [
    {"ok": False, "error": {"code": "runtime_busy", "message": "busy"}},
    {"ok": True, "result": {"operation": "rerank", "ranked_ids": ["unknown"]}},
    {"ok": True, "result": {"operation": "read", "prediction": {"answer_type": "yes", "supporting_ids": ["e1"]}}},
])
def test_raw_answering_ort_failures_are_typed_and_strict(response: dict[str, object]) -> None:
    provider = CompactAnsweringProvider(
        "unix:///tmp/answering-ort.sock",
        IDENTITY,
        wire_protocol="answering-ort",
        transport=_RawTransport(response),
    )
    if response.get("ok") is False:
        with pytest.raises(CompactServiceError) as raised:
            provider.embed("question")
        assert raised.value.code == "runtime_busy"
    elif response["result"]["operation"] == "rerank":  # type: ignore[index]
        with pytest.raises(CompactProtocolError, match="ranked id"):
            provider.rerank("question", [Hit("a", "evidence", "t", "main", "x", 0.1, "lexical")], 1)
    else:
        with pytest.raises(CompactProtocolError, match="answer type"):
            provider.read({"question": "What?", "evidence": [{"cid": "e1", "content": "yes"}]})


def test_raw_answering_ort_enforces_component_bounds_before_transport() -> None:
    transport = _RawTransport({"ok": True, "result": {"operation": "read"}})
    provider = CompactAnsweringProvider(
        "http://127.0.0.1:18181",
        IDENTITY,
        wire_protocol="answering-ort",
        transport=transport,
    )
    with pytest.raises(CompactProtocolError, match="character limit"):
        provider.embed("x" * 2_001)
    with pytest.raises(CompactProtocolError, match="component limit"):
        provider.read({
            "question": "bounded",
            "evidence": [{"cid": f"e{index}", "content": "x"} for index in range(21)],
        })
    assert transport.requests == []
