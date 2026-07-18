"""Bounded, custody-checked adapter for the compact answering sidecar.

The compact service is deliberately treated as an untrusted data endpoint.  This
module owns the transport and protocol boundary only; it does not download
models, choose a fallback provider, or synthesize answer text.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import math
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from mnemosyne.models import Hit


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SUPPORTED_CAPABILITIES = frozenset({"embed", "embed_many", "rerank", "read"})
_IDENTITY_KEYS = frozenset(
    {
        "provider",
        "provider_sha256",
        "artifact",
        "artifact_sha256",
        "configuration",
        "configuration_sha256",
    }
)
_REQUEST_KEYS = frozenset(
    {"operation", "request_sha256", "identity", "capabilities", "payload"}
)
_RESPONSE_KEYS = frozenset(
    {"operation", "request_sha256", "identity", "capabilities", "result"}
)


class CompactProviderError(RuntimeError):
    """A transport or bounded-provider failure that must not fall back."""


class CompactProtocolError(ValueError):
    """A malformed, unauthorised, or parity-incompatible provider message."""


JsonTransport = Callable[[str, bytes, Mapping[str, str], float, int], bytes]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep a validated loopback request from being redirected off-host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


@dataclass(frozen=True, slots=True)
class CompactProviderIdentity:
    """Operator-configured custody identity for one compact sidecar build."""

    provider: str
    provider_sha256: str
    artifact: str
    artifact_sha256: str
    configuration: str
    configuration_sha256: str
    capabilities: tuple[str, ...] = ("embed", "embed_many", "rerank", "read")

    def __post_init__(self) -> None:
        for name in ("provider", "artifact", "configuration"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} identity must be a non-empty string")
        for name in (
            "provider_sha256",
            "artifact_sha256",
            "configuration_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        capabilities = tuple(self.capabilities)
        if not capabilities or len(set(capabilities)) != len(capabilities):
            raise ValueError("compact provider capabilities must be unique and non-empty")
        if any(
            not isinstance(capability, str) or capability not in _SUPPORTED_CAPABILITIES
            for capability in capabilities
        ):
            raise ValueError("compact provider capabilities contain an unknown operation")
        object.__setattr__(self, "capabilities", capabilities)

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "provider_sha256": self.provider_sha256,
            "artifact": self.artifact,
            "artifact_sha256": self.artifact_sha256,
            "configuration": self.configuration,
            "configuration_sha256": self.configuration_sha256,
        }


@dataclass(frozen=True, slots=True)
class _Endpoint:
    kind: str
    address: str
    path: str


def _parse_endpoint(endpoint: str) -> _Endpoint:
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 4096:
        raise ValueError("compact provider endpoint is invalid")
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme in {"http", "https"}:
        if parsed.scheme != "http" or parsed.username or parsed.password:
            raise ValueError("compact HTTP endpoint must be unauthenticated loopback HTTP")
        if parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("compact HTTP endpoint must not contain query or fragment data")
        host = parsed.hostname.casefold()
        if host != "localhost":
            try:
                if not ipaddress.ip_address(host).is_loopback:
                    raise ValueError("compact HTTP endpoint must target loopback")
            except ValueError as exc:
                raise ValueError("compact HTTP endpoint must target loopback") from exc
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("compact HTTP endpoint port is invalid") from exc
        return _Endpoint("http", endpoint, parsed.path or "/")

    if parsed.scheme not in {"unix", "http+unix"}:
        raise ValueError("compact provider endpoint must be loopback HTTP or Unix-domain")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("compact Unix endpoint contains unsupported authority data")
    if parsed.scheme == "http+unix":
        if parsed.query:
            raise ValueError("compact HTTP-over-Unix endpoint must not contain a query")
        socket_path = urllib.parse.unquote(parsed.netloc)
        request_path = parsed.path or "/"
    else:
        socket_path = urllib.parse.unquote(parsed.path)
        request_path = "/"
        if parsed.query:
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            if set(query) != {"path"} or len(query["path"]) != 1:
                raise ValueError("compact Unix endpoint query must contain one path")
            request_path = query["path"][0] or "/"
    if not socket_path.startswith("/") or "\x00" in socket_path:
        raise ValueError("compact Unix endpoint must use an absolute socket path")
    if not request_path.startswith("/") or any(
        character in request_path for character in "\x00\r\n"
    ):
        raise ValueError("compact Unix request path is invalid")
    return _Endpoint("unix", socket_path, request_path)


def _assert_data(value: object, *, label: str) -> None:
    """Allow only JSON data and reject non-finite numbers before serializing."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CompactProtocolError(f"{label} contains a non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _assert_data(item, label=label)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CompactProtocolError(f"{label} contains a non-string key")
            _assert_data(item, label=label)
        return
    raise CompactProtocolError(f"{label} contains a non-data value")


def _canonical_json(value: object, *, label: str) -> bytes:
    _assert_data(value, label=label)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CompactProtocolError(f"{label} cannot be serialized as JSON data") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CompactProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_json(raw: bytes, *, label: str) -> dict[str, object]:
    if not isinstance(raw, bytes):
        raise CompactProviderError(f"{label} response is not bytes")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                CompactProtocolError(f"{label} contains non-finite JSON: {constant}")
            ),
        )
    except CompactProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CompactProtocolError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise CompactProtocolError(f"{label} must be a JSON object")
    _assert_data(value, label=label)
    return value


def _require_keys(value: object, keys: frozenset[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise CompactProtocolError(f"{label} has unknown or missing keys")
    return value


def _optional_keys(value: object, allowed: frozenset[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not set(value) <= allowed:
        raise CompactProtocolError(f"{label} has unknown keys")
    return value


def _string(value: object, *, label: str, non_empty: bool = True) -> str:
    if not isinstance(value, str) or (non_empty and not value):
        raise CompactProtocolError(f"{label} must be a string")
    return value


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompactProtocolError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise CompactProtocolError(f"{label} must be finite")
    return result


def _with_query_prefix(text: str, prefix: str) -> str:
    if not prefix:
        return text
    marker = prefix.rstrip()
    if text.startswith(prefix) or (marker and text.startswith(marker)):
        return text
    return f"{prefix}{text}"


def _vector(value: object, *, dims: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != dims:
        raise CompactProtocolError(f"{label} has the wrong dimensions")
    vector = [_finite_number(item, label=label) for item in value]
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0.0:
        raise CompactProtocolError(f"{label} must be non-zero")
    return [item / norm for item in vector]


def _utf8_slice(value: str, start: int, end: int, *, label: str) -> str:
    """Decode one exact half-open UTF-8 byte span on character boundaries."""

    encoded = value.encode("utf-8")
    if start < 0 or start >= end or end > len(encoded):
        raise CompactProtocolError(f"{label} is outside evidence")
    try:
        return encoded[start:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CompactProtocolError(
            f"{label} does not align to UTF-8 character boundaries"
        ) from exc


def _default_transport(
    endpoint: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout: float,
    max_response_bytes: int,
) -> bytes:
    parsed = _parse_endpoint(endpoint)
    if parsed.kind == "http":
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(_NoRedirectHandler)
            with opener.open(request, timeout=timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        if int(content_length) > max_response_bytes:
                            raise CompactProviderError("compact provider response exceeds the output limit")
                    except ValueError as exc:
                        raise CompactProviderError("compact provider Content-Length is invalid") from exc
                if not 200 <= int(response.status) < 300:
                    raise CompactProviderError("compact provider returned a non-success status")
                raw = response.read(max_response_bytes + 1)
        except CompactProviderError:
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise CompactProviderError("compact provider transport failed closed") from exc
        if len(raw) > max_response_bytes:
            raise CompactProviderError("compact provider response exceeds the output limit")
        return raw

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(parsed.address)
        request = (
            f"POST {parsed.path} HTTP/1.1\r\n"
            "Host: localhost\r\n"
            f"Content-Length: {len(body)}\r\n"
            + "\r\n".join(f"{key}: {value}" for key, value in headers.items())
            + "\r\n\r\n"
        ).encode("ascii") + body
        sock.sendall(request)
        response = http.client.HTTPResponse(sock)
        response.begin()
        if not 200 <= int(response.status) < 300:
            raise CompactProviderError("compact provider returned a non-success status")
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > max_response_bytes:
                    raise CompactProviderError("compact provider response exceeds the output limit")
            except ValueError as exc:
                raise CompactProviderError("compact provider Content-Length is invalid") from exc
        raw = response.read(max_response_bytes + 1)
    except CompactProviderError:
        raise
    except (OSError, http.client.HTTPException, TimeoutError) as exc:
        raise CompactProviderError("compact provider transport failed closed") from exc
    finally:
        sock.close()
    if len(raw) > max_response_bytes:
        raise CompactProviderError("compact provider response exceeds the output limit")
    return raw


@dataclass(slots=True)
class CompactAnsweringProvider:
    """Strict embed/rerank/read adapter for a configured compact sidecar.

    The identity and all digests are operator-supplied expectations.  A response
    is accepted only when it echoes those exact values and the exact request
    digest; response metadata is never used to discover or select a model.
    """

    endpoint: str
    identity: CompactProviderIdentity
    dims: int = 1024
    timeout_seconds: float = 30.0
    max_request_bytes: int = 256 * 1024
    max_response_bytes: int = 256 * 1024
    bearer_token: str | None = field(default=None, repr=False)
    require_bearer_auth: bool = False
    query_prefix: str = "query: "
    max_read_spans: int = 20
    # Names used by the existing bounded command provider are accepted as
    # explicit aliases, while the request/response names remain canonical.
    max_input_bytes: int | None = None
    max_output_bytes: int | None = None
    transport: JsonTransport | None = field(default=None, repr=False, compare=False)
    _parsed_endpoint: _Endpoint = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompactProviderIdentity):
            raise ValueError("compact provider identity is required")
        self._parsed_endpoint = _parse_endpoint(self.endpoint)
        if self.max_input_bytes is not None:
            if self.max_request_bytes != 256 * 1024 and self.max_request_bytes != self.max_input_bytes:
                raise ValueError("compact provider input limits disagree")
            self.max_request_bytes = self.max_input_bytes
        if self.max_output_bytes is not None:
            if self.max_response_bytes != 256 * 1024 and self.max_response_bytes != self.max_output_bytes:
                raise ValueError("compact provider output limits disagree")
            self.max_response_bytes = self.max_output_bytes
        if not isinstance(self.dims, int) or isinstance(self.dims, bool) or self.dims <= 0:
            raise ValueError("compact embedding dimensions must be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("compact provider timeout must be positive")
        if (
            not isinstance(self.max_request_bytes, int)
            or isinstance(self.max_request_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or isinstance(self.max_response_bytes, bool)
            or self.max_request_bytes < 1
            or self.max_response_bytes < 1
        ):
            raise ValueError("compact provider byte limits must be positive")
        if not isinstance(self.max_read_spans, int) or isinstance(self.max_read_spans, bool) or self.max_read_spans < 1:
            raise ValueError("compact reader span limit must be positive")
        if self.require_bearer_auth and not self.bearer_token:
            raise ValueError("compact provider bearer authentication is required")
        if self.bearer_token is not None and not isinstance(self.bearer_token, str):
            raise ValueError("compact provider bearer token must be a string")
        if self.bearer_token is not None and any(
            character in self.bearer_token for character in "\r\n"
        ):
            raise ValueError("compact provider bearer token contains header control characters")
        if not isinstance(self.query_prefix, str):
            raise ValueError("compact provider query prefix must be a string")

    @property
    def name(self) -> str:
        return self.identity.provider

    @property
    def disclosure(self) -> dict[str, object]:
        """Return configured custody data without accepting provider claims."""

        return {
            **self.identity.to_dict(),
            "capabilities": list(self.identity.capabilities),
        }

    @property
    def configuration_identity(self) -> dict[str, object]:
        return dict(self.disclosure)

    def embed(self, text: str) -> list[float]:
        self._require_capability("embed")
        if not isinstance(text, str):
            raise TypeError("compact embedding input must be text")
        result = self._roundtrip("embed", {"input": text})
        payload = _require_keys(result, frozenset({"embedding"}), label="embed result")
        return _vector(payload["embedding"], dims=self.dims, label="embedding")

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        self._require_capability("embed_many")
        if any(not isinstance(text, str) for text in items):
            raise TypeError("compact batch embedding input must be text")
        result = self._roundtrip("embed", {"input": items})
        payload = _require_keys(result, frozenset({"data"}), label="batch embed result")
        rows = payload["data"]
        if not isinstance(rows, list) or len(rows) != len(items):
            raise CompactProtocolError("batch embedding result length does not match input")
        vectors: list[list[float] | None] = [None] * len(items)
        for position, row in enumerate(rows):
            fields = _optional_keys(
                row,
                frozenset({"embedding", "index"}),
                label="batch embedding row",
            )
            if "embedding" not in fields:
                raise CompactProtocolError("batch embedding row is missing embedding")
            index = fields.get("index", position)
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
                raise CompactProtocolError("batch embedding row index is invalid")
            if vectors[index] is not None:
                raise CompactProtocolError("batch embedding row index is duplicated")
            vectors[index] = _vector(
                fields["embedding"], dims=self.dims, label="batch embedding"
            )
        if any(vector is None for vector in vectors):
            raise CompactProtocolError("batch embedding result misses an input")
        return [vector for vector in vectors if vector is not None]

    def embed_query(self, query: str) -> list[float]:
        if not isinstance(query, str):
            raise TypeError("compact query embedding input must be text")
        return self.embed(_with_query_prefix(query, self.query_prefix))

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        if isinstance(k, bool) or not isinstance(k, int):
            raise TypeError("compact rerank k must be an integer")
        if k <= 0 or not hits:
            return []
        self._require_capability("rerank")
        if not isinstance(query, str):
            raise TypeError("compact rerank query must be text")
        documents: list[str] = []
        for hit in hits:
            text = getattr(hit, "text", None)
            if not isinstance(text, str):
                raise TypeError("compact rerank hits must contain text")
            documents.append(text)
        result = self._roundtrip(
            "rerank",
            {
                "query": _with_query_prefix(query, self.query_prefix),
                "documents": documents,
                "top_n": k,
            },
        )
        payload = _require_keys(result, frozenset({"results"}), label="rerank result")
        rows = payload["results"]
        if not isinstance(rows, list) or not rows or len(rows) > k:
            raise CompactProtocolError("rerank result count is invalid")
        ranked: list[Hit] = []
        seen: set[int] = set()
        for row in rows:
            fields = _optional_keys(
                row,
                frozenset({"index", "score", "relevance_score"}),
                label="rerank row",
            )
            if "index" not in fields or ("score" not in fields) == ("relevance_score" not in fields):
                raise CompactProtocolError("rerank row must contain one score and an index")
            index = fields["index"]
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(hits):
                raise CompactProtocolError("rerank row index is invalid")
            if index in seen:
                raise CompactProtocolError("rerank row index is duplicated")
            seen.add(index)
            score = _finite_number(
                fields.get("score", fields.get("relevance_score")),
                label="rerank score",
            )
            hit = hits[index]
            ranked.append(
                Hit(
                    id=hit.id,
                    kind=hit.kind,
                    tenant_id=hit.tenant_id,
                    branch=hit.branch,
                    text=hit.text,
                    score=score,
                    channel=f"{hit.channel}+rerank",
                    provenance=list(hit.provenance),
                    trust_tier=hit.trust_tier,
                    sensitivity=hit.sensitivity,
                    metadata={**hit.metadata, "reranker": self.name},
                )
            )
        return sorted(ranked, key=lambda hit: hit.score, reverse=True)

    def read(self, payload: dict[str, object]) -> dict[str, object]:
        self._require_capability("read")
        request = _require_keys(
            payload,
            frozenset({"question", "evidence"}),
            label="grounded reader input",
        )
        question = _string(request["question"], label="grounded reader question")
        raw_evidence = request["evidence"]
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise CompactProtocolError("grounded reader evidence must be non-empty")
        evidence: list[dict[str, str]] = []
        contents: dict[str, str] = {}
        for row in raw_evidence:
            fields = _require_keys(
                row,
                frozenset({"cid", "content"}),
                label="grounded reader evidence row",
            )
            cid = _string(fields["cid"], label="grounded evidence cid")
            content = _string(fields["content"], label="grounded evidence content")
            if cid in contents:
                raise CompactProtocolError("grounded reader evidence contains duplicate cid")
            contents[cid] = content
            evidence.append({"cid": cid, "content": content})
        result = self._roundtrip(
            "read",
            {"question": question, "evidence": evidence},
        )
        fields = _require_keys(
            result,
            frozenset({"spans", "unresolved"}),
            label="grounded reader result",
        )
        unresolved = fields["unresolved"]
        spans = fields["spans"]
        if not isinstance(unresolved, bool) or not isinstance(spans, list):
            raise CompactProtocolError("grounded reader result is malformed")
        if unresolved:
            if spans:
                raise CompactProtocolError("unresolved grounded reader result contains spans")
            return {"claims": [], "unresolved": True}
        if not spans or len(spans) > self.max_read_spans:
            raise CompactProtocolError("grounded reader span count is invalid")
        claims: list[dict[str, object]] = []
        occupied: dict[str, list[tuple[int, int]]] = {}
        for row in spans:
            span = _require_keys(
                row,
                frozenset({"cid", "start", "end"}),
                label="grounded reader span",
            )
            cid = _string(span["cid"], label="grounded reader span cid")
            start = span["start"]
            end = span["end"]
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or cid not in contents
            ):
                raise CompactProtocolError("grounded reader span is outside evidence")
            if any(
                start < right and left < end
                for left, right in occupied.setdefault(cid, [])
            ):
                raise CompactProtocolError("grounded reader spans overlap")
            occupied[cid].append((start, end))
            quote = _utf8_slice(
                contents[cid], start, end, label="grounded reader span"
            )
            if not quote:
                raise CompactProtocolError("grounded reader span is empty")
            claims.append({"spans": [{"cid": cid, "quote": quote}]})
        return {"claims": claims, "unresolved": False}

    def _require_capability(self, operation: str) -> None:
        if operation not in self.identity.capabilities:
            raise CompactProtocolError(f"compact provider capability is not configured: {operation}")

    def _roundtrip(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        if operation not in _SUPPORTED_CAPABILITIES:
            raise CompactProtocolError("compact provider operation is not supported")
        payload_bytes = _canonical_json(payload, label=f"{operation} request payload")
        request = {
            "operation": operation,
            "request_sha256": _sha256(payload_bytes),
            "identity": self.identity.to_dict(),
            "capabilities": list(self.identity.capabilities),
            "payload": payload,
        }
        body = _canonical_json(request, label=f"{operation} request")
        if len(body) > self.max_request_bytes:
            raise CompactProviderError("compact provider request exceeds the input limit")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        try:
            raw = (
                self.transport(
                    self.endpoint,
                    body,
                    headers,
                    self.timeout_seconds,
                    self.max_response_bytes,
                )
                if self.transport is not None
                else _default_transport(
                    self.endpoint,
                    body,
                    headers,
                    self.timeout_seconds,
                    self.max_response_bytes,
                )
            )
        except CompactProviderError:
            raise
        except (OSError, TimeoutError) as exc:
            raise CompactProviderError("compact provider transport failed closed") from exc
        if not isinstance(raw, bytes):
            raise CompactProviderError("compact provider transport returned non-bytes")
        if len(raw) > self.max_response_bytes:
            raise CompactProviderError("compact provider response exceeds the output limit")
        response = _decode_json(raw, label=f"{operation} response")
        fields = _require_keys(response, _RESPONSE_KEYS, label=f"{operation} response envelope")
        if fields["operation"] != operation:
            raise CompactProtocolError("compact provider response operation does not match request")
        request_sha256 = fields["request_sha256"]
        if (
            not isinstance(request_sha256, str)
            or not _DIGEST.fullmatch(request_sha256)
            or request_sha256 != request["request_sha256"]
        ):
            raise CompactProtocolError("compact provider request digest does not match")
        response_identity = _require_keys(
            fields["identity"], _IDENTITY_KEYS, label="compact provider response identity"
        )
        if response_identity != self.identity.to_dict():
            raise CompactProtocolError("compact provider identity does not match configured custody")
        capabilities = fields["capabilities"]
        if capabilities != list(self.identity.capabilities):
            raise CompactProtocolError("compact provider capabilities do not match configured custody")
        result = fields["result"]
        if not isinstance(result, dict):
            raise CompactProtocolError("compact provider result must be an object")
        return result


# Explicit aliases make the one custody-checked object usable at each existing
# protocol boundary without creating separate transports or fallback paths.
CompactEmbeddingProvider = CompactAnsweringProvider
CompactReranker = CompactAnsweringProvider
CompactGroundedReader = CompactAnsweringProvider


def identity_digest(value: object) -> str:
    """Return the canonical SHA-256 helper used for synthetic manifests/tests."""

    return _sha256(_canonical_json(value, label="identity digest input"))


__all__ = [
    "CompactAnsweringProvider",
    "CompactEmbeddingProvider",
    "CompactGroundedReader",
    "CompactProviderError",
    "CompactProviderIdentity",
    "CompactProtocolError",
    "CompactReranker",
    "JsonTransport",
    "identity_digest",
]
