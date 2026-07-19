from __future__ import annotations

import asyncio
import base64
import datetime as dt
import ipaddress
import inspect
import json
import shlex
import socket
import ssl
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import Any
from urllib import error as urlerror, request as urlrequest

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import mnemosyne.mcp_server as mcp_server
from mnemosyne.mcp_server import (
    MnemosyneMcpServer,
    build_http_server,
    build_sdk_server,
    build_sdk_streamable_http_app,
    run_self_test,
)
from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import Intention, LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.models import Assertion, Evidence, Hit, Relation
from mnemosyne.postgres_engine import PostgresEngine, _bytes_to_cid, _cid_to_bytes, _stable_uuid, _uuid_or_none, _vector_literal
from mnemosyne.retrieval import (
    CommandMediaEmbeddingProvider,
    HttpEmbeddingProvider,
    HttpReranker,
    LocalSimilarityReranker,
    semantic_entropy,
)
from mnemosyne.security import SessionIdentity, SessionTokenVerifier


TENANT = "tenant-runtime"
USER = "user-runtime"
PARAMETRIC_AUTH = {"role": "operator", "source_trust_tier": 0}
MCP_SESSION_SECRET = "mnemosyne-mcp-session-secret"
IDP_ISSUER = "https://idp.example.test/"
IDP_AUDIENCE = "mnemosyne-production"
MFA_ACR = "urn:mnemosyne:mfa"
MFA_RULE = {
    "required_acr": MFA_ACR,
    "required_amr": "mfa",
    "max_auth_age_seconds": 300,
}


def seed_grounded_gate_evidence(
    engine: LocalMemoryEngine,
    content: str,
    *,
    tenant_id: str = TENANT,
    user_id: str = USER,
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id=user_id,
            actor="user",
            source_type="grounded-gate-fixture",
            content=content,
            metadata={"reality_class": "grounded"},
            trust_tier=0,
            access_policy={"tenant": tenant_id},
        )
    )


def mcp_call(server: MnemosyneMcpServer, name: str, arguments: dict[str, object]) -> dict:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response["result"]["isError"] is False, response["result"]["content"][0]["text"]
    return response["result"]["structuredContent"]


def mcp_session_token(
    *,
    tenant_id: str = TENANT,
    user_id: str = USER,
    role: str = "operator",
    source_trust_tier: int = 0,
    session_id: str = "mcp-test-session",
    agent_id: str | None = None,
) -> str:
    return SessionTokenVerifier(MCP_SESSION_SECRET).sign(
        SessionIdentity(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,  # type: ignore[arg-type]
            source_trust_tier=source_trust_tier,
            session_id=session_id,
            agent_id=agent_id,
        )
    )


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_oidc_token(payload: dict[str, object], *, kid: str = "idp-key-1") -> tuple[dict[str, object], str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "alg": "RS256",
                "use": "sig",
                "n": b64url(public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")),
                "e": b64url(public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")),
            }
        ]
    }
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    header_b64 = b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    payload_b64 = b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return jwks, f"{header_b64}.{payload_b64}.{b64url(signature)}"


def oidc_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "iss": IDP_ISSUER,
        "aud": IDP_AUDIENCE,
        "sub": USER,
        "tenant_id": TENANT,
        "mnemosyne_role": "operator",
        "mnemosyne_source_trust_tier": 0,
        "exp": 2_000_000_000,
        "auth_time": int(time.time()) - 30,
        "acr": MFA_ACR,
        "amr": ["pwd", "mfa"],
        "jti": "mcp-idp-session",
    }
    payload.update(overrides)
    return payload


def make_tls_material(tmp_path: Path) -> dict[str, Path]:
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mnemosyne test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    def signed_cert(
        common_name: str,
        *,
        usage_oid: ExtendedKeyUsageOID,
        subject_alt_names: list[x509.GeneralName] | None = None,
    ) -> tuple[object, x509.Certificate]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.ExtendedKeyUsage([usage_oid]), critical=False)
        )
        if subject_alt_names:
            builder = builder.add_extension(x509.SubjectAlternativeName(subject_alt_names), critical=False)
        return key, builder.sign(ca_key, hashes.SHA256())

    server_key, server_cert = signed_cert(
        "localhost",
        usage_oid=ExtendedKeyUsageOID.SERVER_AUTH,
        subject_alt_names=[
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ],
    )
    client_key, client_cert = signed_cert("mnemosyne-test-client", usage_oid=ExtendedKeyUsageOID.CLIENT_AUTH)

    paths = {
        "ca_cert": tmp_path / "ca.pem",
        "server_cert": tmp_path / "server.pem",
        "server_key": tmp_path / "server-key.pem",
        "client_cert": tmp_path / "client.pem",
        "client_key": tmp_path / "client-key.pem",
    }
    paths["ca_cert"].write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    paths["server_cert"].write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    paths["client_cert"].write_bytes(client_cert.public_bytes(serialization.Encoding.PEM))
    for key_name, key in (("server_key", server_key), ("client_key", client_key)):
        paths[key_name].write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    return paths


def start_mcp_http_server(**kwargs: object) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = build_http_server(host="127.0.0.1", port=0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def fake_session_secret_command(tmp_path: Path, response: dict[str, object], *, name: str = "fake-session-secret") -> str:
    response_file = tmp_path / f"{name}.json"
    response_file.write_text(json.dumps(response, sort_keys=True), encoding="utf-8")
    script = tmp_path / f"{name}.py"
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json, sys",
                "from pathlib import Path",
                "response = Path(sys.argv[1])",
                "action = sys.argv[2]",
                "request = json.load(sys.stdin)",
                "if action != 'get_session_secret' or request.get('action') != 'get_session_secret':",
                "    print('bad action', file=sys.stderr)",
                "    raise SystemExit(2)",
                "print(response.read_text(encoding='utf-8'))",
            ]
        ),
        encoding="utf-8",
    )
    return " ".join(shlex.quote(item) for item in (sys.executable, str(script), str(response_file)))


def stop_mcp_http_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def http_json(
    method: str,
    url: str,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    context: ssl.SSLContext | None = None,
) -> tuple[int, dict[str, object] | None]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urlrequest.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urlrequest.urlopen(request, timeout=5, context=context) as response:  # noqa: S310 - test-local server.
            body = response.read()
            return response.status, None if not body else json.loads(body.decode("utf-8"))
    except urlerror.HTTPError as exc:
        body = exc.read()
        return exc.code, None if not body else json.loads(body.decode("utf-8"))


def http_post_raw(url: str, body: bytes) -> tuple[int, dict[str, object] | None]:
    request = urlrequest.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlrequest.urlopen(request, timeout=5) as response:  # noqa: S310 - test-local server.
            response_body = response.read()
            return response.status, None if not response_body else json.loads(response_body.decode("utf-8"))
    except urlerror.HTTPError as exc:
        response_body = exc.read()
        return exc.code, None if not response_body else json.loads(response_body.decode("utf-8"))


def fake_kms_command(tmp_path: Path) -> tuple[str, Path]:
    state = tmp_path / "kms-state.json"
    script = tmp_path / "fake-kms.py"
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import base64, hashlib, json, sys",
                "from pathlib import Path",
                "state = Path(sys.argv[1])",
                "action = sys.argv[2]",
                "request = json.load(sys.stdin)",
                "data = json.loads(state.read_text()) if state.exists() else {'keys': {}}",
                "keys = data.setdefault('keys', {})",
                "key_id = request['key_id']",
                "def save(): state.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')",
                "if action == 'get_or_create_key':",
                "    keys.setdefault(key_id, base64.urlsafe_b64encode(hashlib.sha256(key_id.encode()).digest()).decode('ascii'))",
                "    save()",
                "    print(json.dumps({'key': keys[key_id]}))",
                "elif action == 'get_key':",
                "    if key_id not in keys:",
                "        print('missing key', file=sys.stderr)",
                "        raise SystemExit(4)",
                "    print(json.dumps({'key': keys[key_id]}))",
                "elif action == 'has_key':",
                "    print(json.dumps({'exists': key_id in keys}))",
                "elif action == 'shred_key':",
                "    shredded = keys.pop(key_id, None) is not None",
                "    save()",
                "    print(json.dumps({'shredded': shredded}))",
                "else:",
                "    print('bad action', file=sys.stderr)",
                "    raise SystemExit(2)",
            ]
        ),
        encoding="utf-8",
    )
    command = " ".join(shlex.quote(item) for item in (sys.executable, str(script), str(state)))
    return command, state


def fake_parametric_command(tmp_path: Path) -> tuple[str, Path]:
    state = tmp_path / "parametric-state.json"
    script = tmp_path / "fake-parametric.py"
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json, sys",
                "from pathlib import Path",
                "state = Path(sys.argv[1])",
                "action = sys.argv[2]",
                "request = json.load(sys.stdin)",
                "data = json.loads(state.read_text()) if state.exists() else {'calls': []}",
                "data.setdefault('calls', []).append({'action': action, 'tenant_id': request.get('tenant_id'), 'source_ids': request.get('source_ids'), 'protected_suite': request.get('protected_suite'), 'protected_cases': [case.get('id') for case in request.get('protected_cases', [])]})",
                "state.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')",
                "if action == 'propose':",
                "    print(json.dumps({'adapter_kind': 'test-time-command-adapter', 'artifact_ref': 'provider://' + request['tenant_id'] + '/adapter', 'metrics': {'source_count': len(request['source_ids']), 'rail_count': len(request['immutable_rails'])}, 'metadata': {'lesson_count': len(request['lessons']), 'procedure_count': len(request['procedures'])}}))",
                "elif action == 'rollback':",
                "    print(json.dumps({'rollback_ref': 'provider-rollback-' + request['artifact']['id'], 'metrics': {'provider_rolled_back': 1}}))",
                "else:",
                "    print('bad action', file=sys.stderr)",
                "    raise SystemExit(2)",
            ]
        ),
        encoding="utf-8",
    )
    command = " ".join(shlex.quote(item) for item in (sys.executable, str(script), str(state)))
    return command, state


def test_semantic_entropy_distinguishes_identical_and_divergent_answers() -> None:
    assert semantic_entropy(["Postgres is the store", "Postgres is the store"]) == 0.0
    assert semantic_entropy(["Postgres is the store", "SQLite is the store"]) > 0.5


def test_local_similarity_reranker_prefers_query_relevant_hits() -> None:
    reranker = LocalSimilarityReranker()
    hits = [
        Hit(
            id="unrelated",
            kind="evidence",
            tenant_id=TENANT,
            branch="main",
            text="The UI color palette should avoid one-note gradients.",
            score=0.1,
            channel="candidate",
        ),
        Hit(
            id="postgres",
            kind="evidence",
            tenant_id=TENANT,
            branch="main",
            text="The memory system stores durable evidence in local-first Postgres.",
            score=0.1,
            channel="candidate",
        ),
    ]

    ranked = reranker.rerank("Postgres durable evidence store", hits, k=2)

    assert [hit.id for hit in ranked] == ["postgres", "unrelated"]
    assert ranked[0].metadata["reranker"] == "local-similarity"


def test_http_embedding_and_reranker_adapters_use_json_provider_contract() -> None:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append({"path": self.path, "payload": payload, "auth": self.headers.get("Authorization")})
            if self.path == "/embed":
                body = {"data": [{"embedding": [3.0, 4.0, 0.0, 99.0]}]}
            else:
                body = {"results": [{"index": 1, "relevance_score": 0.91}, {"index": 0, "relevance_score": 0.2}]}
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature.
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        embedding = HttpEmbeddingProvider(f"{base}/embed", model="embed-model", api_key="secret", dims=3)
        vector = embedding.embed("hello")
        reranker = HttpReranker(f"{base}/rerank", model="rank-model")
        ranked = reranker.rerank(
            "query",
            [
                Hit("a", "evidence", TENANT, "main", "first", 0.1, "candidate"),
                Hit("b", "evidence", TENANT, "main", "second", 0.1, "candidate"),
            ],
            k=2,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert vector == [0.6, 0.8, 0.0]
    assert [hit.id for hit in ranked] == ["b", "a"]
    assert requests[0]["auth"] == "Bearer secret"
    assert requests[0]["payload"] == {"input": "hello", "model": "embed-model"}
    assert requests[1]["payload"]["model"] == "rank-model"


def test_http_embedding_provider_caches_single_and_batch_calls() -> None:
    requests: list[dict[str, object]] = []

    def vector_for(text: str) -> list[float]:
        if text == "alpha":
            return [3.0, 4.0, 0.0]
        if text == "beta":
            return [0.0, 5.0, 0.0]
        return [8.0, 6.0, 0.0]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append({"payload": payload})
            value = payload["input"]
            if isinstance(value, list):
                body = {
                    "data": [
                        {"index": index, "embedding": vector_for(str(item))}
                        for index, item in enumerate(value)
                    ]
                }
            else:
                body = {"data": [{"embedding": vector_for(str(value))}]}
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature.
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        embedding = HttpEmbeddingProvider(f"{base}/embed", model="embed-model", dims=3, cache_size=16)
        assert embedding.embed("alpha") == [0.6, 0.8, 0.0]
        assert embedding.embed("alpha") == [0.6, 0.8, 0.0]
        assert embedding.embed_many(["alpha", "beta"]) == [[0.6, 0.8, 0.0], [0.0, 1.0, 0.0]]
        assert embedding.embed_many(["beta", "gamma"]) == [[0.0, 1.0, 0.0], [0.8, 0.6, 0.0]]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert [request["payload"]["input"] for request in requests] == ["alpha", "beta", "gamma"]


def test_http_retrieval_adapters_fail_closed_on_malformed_provider_responses() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
            if self.path == "/embed-zero":
                body = {"embedding": [0.0, 0.0, 0.0]}
            elif self.path == "/rerank-empty":
                body = {"results": []}
            else:
                body = {"results": [{"index": 9, "score": 0.9}]}
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature.
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(ValueError, match="non-zero vector"):
            HttpEmbeddingProvider(f"{base}/embed-zero", dims=3).embed("hello")
        with pytest.raises(ValueError, match="at least one scored result"):
            HttpReranker(f"{base}/rerank-empty").rerank(
                "query",
                [Hit("a", "evidence", TENANT, "main", "first", 0.1, "candidate")],
                k=1,
            )
        with pytest.raises(ValueError, match="out of range"):
            HttpReranker(f"{base}/rerank-oob").rerank(
                "query",
                [Hit("a", "evidence", TENANT, "main", "first", 0.1, "candidate")],
                k=1,
            )
        with pytest.raises(ValueError, match="must be http\\(s\\) with a hostname"):
            HttpEmbeddingProvider("file:///tmp/embed", dims=3).embed("hello")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_hosted_json_probe_rejects_unsafe_fetch_url_without_network() -> None:
    from mnemosyne import cli as mneme_cli

    probe = mneme_cli._http_json_probe(
        url="http://provider.example.test/healthz",
        method="GET",
        headers={},
        timeout_seconds=1.0,
    )

    assert probe["ok"] is False
    assert probe["status"] is None
    assert "requires https unless insecure localhost is explicitly allowed" in probe["error"]


def test_hosted_sse_probe_rejects_userinfo_without_network() -> None:
    from mnemosyne import cli as mneme_cli

    probe = mneme_cli._sse_probe(
        url="https://user:secret@provider.example.test/sse",
        headers={},
        timeout_seconds=1.0,
        max_bytes=1024,
        max_events=1,
        expected_event=None,
    )

    assert probe["ok"] is False
    assert probe["status"] is None
    assert "must not contain userinfo credentials" in probe["error"]


def test_command_media_embedding_provider_validates_json_contract(tmp_path: Path) -> None:
    embedder = tmp_path / "embedder.py"
    embedder.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "request = json.loads(sys.stdin.read())",
                "assert pathlib.Path(sys.argv[1]).read_bytes() == b'media-bytes'",
                "assert request['media_type'] == 'image/png'",
                "print(json.dumps({'embedding': [3.0, 4.0, 0.0, 99.0]}))",
            ]
        ),
        encoding="utf-8",
    )
    embedder.chmod(0o755)

    vector = CommandMediaEmbeddingProvider(str(embedder), dims=3).embed_media(
        b"media-bytes",
        media_type="image/png",
        modality="image",
        metadata={"source": "unit"},
    )

    assert vector == [0.6, 0.8, 0.0]


def test_memory_tools_direct_confirm_promotes_proposal_branch() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="direct-confirm",
            content="Direct confirm promotes a proposal branch into main.",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        )
    )

    proposal = tools.propose(
        TENANT,
        USER,
        "Direct confirm",
        "promotes",
        "proposal branch",
        source_evidence_cids=[cid],
        confidence=0.91,
        trust_tier=1,
    )
    confirmed = tools.confirm(
        proposal["id"],
        role="operator",
        source_trust_tier=0,
        tenant_id=TENANT,
    )
    exported = engine.export_tenant(TENANT)
    main_assertion = next(
        item
        for item in exported["assertions"]
        if item["id"] == proposal["id"] and item["branch"] == "main"
    )

    assert confirmed["id"] == proposal["id"]
    assert confirmed["branch"] == proposal["branch"]
    assert confirmed["into"] == "main"
    assert confirmed["security"]["allowed"] is True
    assert confirmed["merge"]["from_branch"] == proposal["branch"]
    assert confirmed["merge"]["into_branch"] == "main"
    assert confirmed["merge"]["assertions_added"] >= 1
    assert main_assertion["subject"] == "Direct confirm"
    assert main_assertion["object"] == "proposal branch"
    assert main_assertion["source_evidence_cids"] == [cid]


def test_memory_tools_direct_branch_merge_discard_facades() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    initial_audit_count = len(engine.audit_log)

    with pytest.raises(PermissionError, match="branch writes require normal-or-stronger source trust"):
        tools.branch("denied-direct-branch", role="agent", source_trust_tier=4, tenant_id=TENANT)
    denied_export = engine.export_all()
    assert "denied-direct-branch" not in engine.branches
    assert not any(item["name"] == "denied-direct-branch" for item in denied_export["branches"])
    assert not any(
        item.get("branch") == "denied-direct-branch"
        for section in ("evidence", "assertions", "relations")
        for item in denied_export[section]
    )
    denied_auth_audits = engine.audit_log[initial_audit_count:]
    assert len(denied_auth_audits) == 1
    assert denied_auth_audits[0]["op"] == "authorize_write"
    assert denied_auth_audits[0]["actor"] == "agent"
    assert denied_auth_audits[0]["source"] == "mcp_tools"
    assert denied_auth_audits[0]["trust_tier"] == 4
    assert denied_auth_audits[0]["capability_tags"] == ["authz", "denied"]
    assert denied_auth_audits[0]["diff"]["operation"] == "branch"
    assert denied_auth_audits[0]["diff"]["allowed"] is False
    assert denied_auth_audits[0]["diff"]["reason"] == "branch writes require normal-or-stronger source trust"
    with pytest.raises(PermissionError, match="branch promotion requires operator/consolidator authority"):
        tools.merge("denied-direct-merge", role="reader", source_trust_tier=0, tenant_id=TENANT)
    with pytest.raises(PermissionError, match="branch promotion requires operator/consolidator authority"):
        tools.discard("denied-direct-discard", role="reader", source_trust_tier=0, tenant_id=TENANT)
    denied_auth_audits = engine.audit_log[initial_audit_count:]
    assert [item["diff"]["operation"] for item in denied_auth_audits] == ["branch", "merge", "discard"]
    assert all(item["diff"]["allowed"] is False for item in denied_auth_audits)

    tools.branch(
        "low-trust-promotion-branch",
        role="operator",
        source_trust_tier=0,
        tenant_id=TENANT,
    )
    low_trust_cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="direct-low-trust-branch",
            content="Low-trust branch promotion denial must not mutate main or branch state.",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        ),
        branch="low-trust-promotion-branch",
    )
    low_trust_audit_count = len(engine.audit_log)
    with pytest.raises(PermissionError, match="branch promotion requires operator/consolidator authority"):
        tools.merge("low-trust-promotion-branch", role="operator", source_trust_tier=3, tenant_id=TENANT)
    assert engine.get_evidence(TENANT, low_trust_cid, branch="main") is None
    assert engine.get_evidence(TENANT, low_trust_cid, branch="low-trust-promotion-branch") is not None
    assert "low-trust-promotion-branch" in engine.branches
    low_trust_auth_audits = engine.audit_log[low_trust_audit_count:]
    assert [item["diff"]["operation"] for item in low_trust_auth_audits] == ["merge"]
    assert low_trust_auth_audits[0]["diff"]["allowed"] is False
    with pytest.raises(PermissionError, match="branch promotion requires operator/consolidator authority"):
        tools.discard("low-trust-promotion-branch", role="operator", source_trust_tier=3, tenant_id=TENANT)
    assert engine.get_evidence(TENANT, low_trust_cid, branch="low-trust-promotion-branch") is not None
    assert "low-trust-promotion-branch" in engine.branches
    low_trust_auth_audits = engine.audit_log[low_trust_audit_count:]
    assert [item["diff"]["operation"] for item in low_trust_auth_audits] == ["merge", "discard"]
    assert all(item["diff"]["allowed"] is False for item in low_trust_auth_audits)

    branched = tools.branch(
        "direct-merge-branch",
        role="operator",
        source_trust_tier=0,
        kind="proposal",
        tenant_id=TENANT,
    )
    branch_cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="direct-branch",
            content="Direct branch facade evidence moves to main.",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        ),
        branch="direct-merge-branch",
    )
    merged = tools.merge(
        "direct-merge-branch",
        role="operator",
        source_trust_tier=0,
        tenant_id=TENANT,
    )

    discard_branch = tools.branch(
        "direct-discard-branch",
        role="operator",
        source_trust_tier=0,
        tenant_id=TENANT,
    )
    discard_cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="direct-discard",
            content="Direct discard facade evidence stays off main.",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        ),
        branch="direct-discard-branch",
    )
    discarded = tools.discard(
        "direct-discard-branch",
        role="operator",
        source_trust_tier=0,
        tenant_id=TENANT,
    )

    assert branched["branch"] == "direct-merge-branch"
    assert branched["from"] == "main"
    assert branched["kind"] == "proposal"
    assert branched["security"]["allowed"] is True
    assert merged["from_branch"] == "direct-merge-branch"
    assert merged["into_branch"] == "main"
    assert merged["evidence_added"] >= 1
    assert merged["security"]["allowed"] is True
    assert engine.get_evidence(TENANT, branch_cid, branch="main") is not None
    assert discard_branch["branch"] == "direct-discard-branch"
    assert discarded["discarded"] == "direct-discard-branch"
    assert discarded["tenant_id"] == TENANT
    assert discarded["security"]["allowed"] is True
    assert engine.get_evidence(TENANT, discard_cid, branch="direct-discard-branch") is None
    assert engine.get_evidence(TENANT, discard_cid, branch="main") is None
    assert "direct-discard-branch" not in engine.branches
    assert not any(item["name"] == "direct-discard-branch" for item in engine.export_all()["branches"])


def test_memory_tools_denied_auth_decision_persists_audit_only_event(tmp_path: Path) -> None:
    store_path = tmp_path / "memory-store.json"
    engine = LocalMemoryEngine(store_path=store_path)
    tools = MemoryTools(engine)

    with pytest.raises(PermissionError, match="branch writes require normal-or-stronger source trust"):
        tools.branch("denied-persistent-branch", role="agent", source_trust_tier=4, tenant_id=TENANT)

    engine.close()
    reloaded = LocalMemoryEngine(store_path=store_path, read_only=True)
    audit = [
        item
        for item in reloaded.audit_log
        if item["op"] == "authorize_write" and item["diff"].get("operation") == "branch"
    ]
    assert len(audit) == 1
    assert audit[0]["source"] == "mcp_tools"
    assert audit[0]["capability_tags"] == ["authz", "denied"]
    assert audit[0]["diff"]["allowed"] is False


def test_local_engine_close_is_idempotent_and_hands_off_sequential_ownership(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    engine = LocalMemoryEngine(store_path=store)
    first_cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="Writer lifecycle evidence before handoff.",
            trust_tier=3,
            access_policy={"tenant": TENANT},
        )
    )
    engine.close()
    engine.close()

    with pytest.raises(RuntimeError, match="does not own its writable store"):
        engine.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id=USER,
                actor="user",
                source_type="chat",
                content="Write after close must fail.",
                trust_tier=3,
                access_policy={"tenant": TENANT},
            )
        )

    with LocalMemoryEngine(store_path=store) as successor:
        assert f"{TENANT}:main:{first_cid}" in successor.evidence
        successor_cid = successor.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id=USER,
                actor="user",
                source_type="chat",
                content="Successor writes after sequential handoff.",
                trust_tier=3,
                access_policy={"tenant": TENANT},
            )
        )

    observer = LocalMemoryEngine(store_path=store, read_only=True)
    assert {f"{TENANT}:main:{first_cid}", f"{TENANT}:main:{successor_cid}"} <= set(observer.evidence)


def test_memory_tools_direct_assert_fact_and_preference_write_paths() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="direct-write-facade",
            content="Direct write facade coverage preserves source evidence.",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        )
    )

    asserted = tools.assert_fact(
        TENANT,
        "Direct write facade",
        "covers",
        "fact wrapper",
        [cid],
        user_id=USER,
        confidence=0.93,
        trust_tier=1,
        role="operator",
        source_trust_tier=0,
    )
    preferred = tools.preference(
        TENANT,
        USER,
        "workflow",
        "Prefer direct facade tests for low-count wrappers.",
        explicit=True,
        confidence=0.88,
        source_evidence_cids=[cid],
        role="operator",
        source_trust_tier=0,
    )
    with pytest.raises(PermissionError, match="belief writes require normal-or-stronger source trust"):
        tools.assert_fact(
            TENANT,
            "Low trust direct write",
            "cannot",
            "write fact",
            [cid],
            trust_tier=4,
            source_trust_tier=4,
        )
    with pytest.raises(PermissionError, match="preference writes require user-authored or stronger evidence"):
        tools.preference(
            TENANT,
            USER,
            "workflow",
            "Low trust inferred preference cannot write.",
            explicit=False,
            source_evidence_cids=[cid],
        )
    exported = engine.export_tenant(TENANT)
    assertion = next(item for item in exported["assertions"] if item["id"] == asserted["id"])
    preference = next(item for item in exported["preferences"] if item["id"] == preferred["id"])

    assert asserted["branch"] == "main"
    assert asserted["security"]["allowed"] is True
    assert assertion["subject"] == "Direct write facade"
    assert assertion["predicate"] == "covers"
    assert assertion["object"] == "fact wrapper"
    assert assertion["source_evidence_cids"] == [cid]
    assert assertion["trust_tier"] == 1
    assert preferred["security"]["allowed"] is True
    assert preference["category"] == "workflow"
    assert preference["statement"] == "Prefer direct facade tests for low-count wrappers."
    assert preference["explicit"] is True
    assert preference["source_evidence_cids"] == [cid]


def test_memory_tools_direct_correct_and_prefetch_facades() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    prefetch_cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="direct-prefetch",
            content="Direct prefetch warms correction context before the next task.",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        )
    )

    corrected = tools.correct(
        TENANT,
        USER,
        "Direct correction",
        "updates",
        "corrected wrapper state",
        "Direct correction evidence from user-authored input.",
    )
    with pytest.raises(PermissionError, match="belief corrections require user-authored or stronger evidence"):
        tools.correct(
            TENANT,
            USER,
            "Low trust direct correction",
            "cannot",
            "write correction",
            "Low-trust correction evidence.",
            source_trust_tier=3,
        )
    prefetch = tools.prefetch(
        TENANT,
        [
            {
                "query": "prefetch warms correction context",
                "probability": 0.91,
                "reason": "next task prediction",
                "metadata": {"surface": "direct-facade"},
            },
            {
                "query": "unsafe network prefetch",
                "probability": 0.99,
                "reason": "requires network",
                "metadata": {"requires_network": True},
            },
            {"query": "weak prefetch", "probability": 0.2, "reason": "weak signal"},
        ],
    )
    exported = engine.export_tenant(TENANT)
    assertion = next(item for item in exported["assertions"] if item["id"] == corrected["id"])
    correction_evidence = next(
        item
        for item in exported["evidence"]
        if item["source_type"] == "correction" and item["content"] == "Direct correction evidence from user-authored input."
    )
    prefetch_results = prefetch["results"]

    assert corrected["branch"] == "main"
    assert corrected["security"]["allowed"] is True
    assert assertion["subject"] == "Direct correction"
    assert assertion["object"] == "corrected wrapper state"
    assert assertion["source_evidence_cids"] == [correction_evidence["cid"]]
    assert [item["executed"] for item in prefetch_results] == [True, False, False]
    assert prefetch_results[0]["candidate"]["metadata"] == {"surface": "direct-facade"}
    assert any(hit["id"] == prefetch_cid for hit in prefetch_results[0]["retrieval"]["hits"])
    assert prefetch_results[1]["reason"] == "prefetch cannot perform network side effects"
    assert prefetch_results[2]["reason"] == "candidate below predictability threshold"
    assert tools.prefetcher.get_warmed(TENANT, "prefetch warms correction context") is not None


def test_memory_tools_direct_profile_graph_learning_facade_methods() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="direct-facade",
            content="Direct facade coverage links profile, graph, and learning.",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="Direct facade",
            predicate="covers",
            object="wrapper behavior",
            confidence=0.92,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        )
    )
    superseded_source_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="Direct facade supersede",
            predicate="tracks",
            object="old wrapper behavior",
            confidence=0.75,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=1,
            access_policy={"tenant": TENANT},
        )
    )
    engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source="Direct facade",
            predicate="related_to",
            target="Wrapper behavior",
            confidence=0.88,
            source_evidence_cids=[cid],
            access_policy={"tenant": TENANT},
        )
    )

    recorded = tools.profile_record_explicit(
        TENANT,
        USER,
        "Prefer direct facade regression tests.",
        scope={"surface": "mcp-tools"},
    )
    inferred = tools.profile_propose_inference(
        TENANT,
        USER,
        "Likely values wrapper-level tests.",
        context={"surface": "mcp-tools"},
    )
    corrected = tools.profile_correct(
        TENANT,
        USER,
        recorded["id"],
        "Prefer direct facade and transport tests together.",
        context={"surface": "mcp-tools"},
    )
    profile = tools.profile_get_relevant(TENANT, USER, {"surface": "mcp-tools"})
    profile_context = tools.profile_context(TENANT, USER, {"surface": "mcp-tools"})
    superseded = tools.supersede(
        TENANT,
        USER,
        superseded_source_id,
        {"object": "new wrapper behavior", "source_evidence_cids": [cid]},
        role="operator",
        source_trust_tier=0,
    )
    neighbors = tools.graph_neighbors(TENANT, ["direct"], k=4)
    graph_query = tools.graph_query(TENANT, ["direct"], hops=2, k=4)
    timeline = tools.graph_timeline(TENANT, "Direct facade")
    graph_as_of = tools.graph_as_of(
        TENANT,
        "Direct facade",
        "covers",
        "2999-01-01T00:00:00Z",
    )
    trajectory = tools.trajectory_log(
        TENANT,
        USER,
        "direct-facade-session",
        "direct facade coverage",
        [{"status": "failed", "error": "wrapper drift"}],
        "failure",
        -1.0,
        "direct-facade-v1",
    )
    alias_trajectory = tools.trajectory_record(
        TENANT,
        USER,
        "direct-facade-alias-session",
        "direct facade alias coverage",
        [{"status": "failed", "error": "alias drift"}],
        "failure",
        -1.0,
        "direct-facade-v2",
    )
    attribution = tools.trajectory_attribute(trajectory["id"])
    lesson = tools.lesson_induce(trajectory["id"])
    procedure = tools.procedure_induce(lesson["id"])
    alias_lesson = tools.lesson_propose(alias_trajectory["id"])
    alias_procedure = tools.procedure_propose(alias_lesson["id"])
    seed_grounded_gate_evidence(engine, "alias drift verify with tools")
    promoted_lesson = tools.lesson_promote(
        alias_lesson["id"],
        cases=[
            {
                "id": "direct-facade-alias-lesson",
                "signature": "direct facade alias coverage",
                "query": "alias drift verify with tools",
                "expected_substring": "verify with tools",
                "protected": True,
            }
        ],
        role="operator",
        source_trust_tier=0,
    )
    lesson_lookup = tools.lesson_search("alias drift", tenant_id=TENANT, status="active")
    procedure_lookup = tools.procedure_search("alias-drift", tenant_id=TENANT)
    validated = tools.procedure_validate(
        procedure["id"],
        role="operator",
        source_trust_tier=0,
    )
    promoted = tools.procedure_promote(
        procedure["id"],
        role="operator",
        source_trust_tier=0,
    )
    rolled_back = tools.procedure_rollback(
        procedure["id"],
        role="operator",
        source_trust_tier=0,
    )
    outcome = tools.outcome_evaluate(trajectory_id=trajectory["id"])
    replay = tools.outcome_evaluate(before_successes=1, after_successes=3, total_cases=4)

    assert recorded["security"]["allowed"] is True
    assert inferred["security"]["allowed"] is True
    assert corrected["corrects"] == recorded["id"]
    assert any("facade" in item["statement"] for item in profile["authoritative"])
    assert profile_context["authoritative"] == profile["authoritative"]
    assert superseded["supersedes"] == superseded_source_id
    assert superseded["security"]["allowed"] is True
    assert neighbors["hits"]
    assert graph_query["hops"] == 2
    assert {event["kind"] for event in timeline["events"]} == {"assertion", "relation"}
    assert graph_as_of["assertions"][0]["object"] == "wrapper behavior"
    assert attribution["trajectory_id"] == trajectory["id"]
    assert lesson["failure_signature"] == attribution["signature"]
    assert procedure["signature"]["failure_signature"] == lesson["failure_signature"]
    assert alias_lesson["failure_signature"].endswith("alias-drift")
    assert alias_procedure["signature"]["failure_signature"] == alias_lesson["failure_signature"]
    assert promoted_lesson["promoted"] is True
    assert promoted_lesson["security"]["allowed"] is True
    assert lesson_lookup["lessons"][0]["id"] == alias_lesson["id"]
    assert procedure_lookup["procedures"][0]["id"] == alias_procedure["id"]
    assert validated["status"] == "validated"
    assert promoted["status"] == "promoted"
    assert rolled_back["status"] == "rolled_back"
    assert outcome["outcome"] == "failure"
    assert replay["counterfactual_replay_score"] > 0


def test_memory_tools_direct_source_sync_applies_committed_markdown_git_assertion(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(source_repo), *args],
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()

    git("init")
    git("config", "user.email", "mnemosyne@example.test")
    git("config", "user.name", "Mnemosyne Test")
    (source_repo / "memory.md").write_text(
        """# Direct Source

```mnemosyne-assertion
id = "direct-source-truth"
subject = "Direct source sync"
predicate = "anchors"
object = "MemoryTools facade"
confidence = 0.98
valid_from = "2026-06-20T00:00:00Z"

[metadata]
reviewed_by = "human"
```
""",
        encoding="utf-8",
    )
    git("add", "memory.md")
    git("commit", "-m", "add direct source truth")
    head = git("rev-parse", "HEAD")
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)

    synced = tools.source_sync(
        TENANT,
        USER,
        str(source_repo),
        apply=True,
        role="operator",
        source_trust_tier=0,
    )
    exported = engine.export_tenant(TENANT)
    synced_evidence = next(item for item in exported["evidence"] if item["cid"] == synced["evidence_cids"][0])
    active = [
        item
        for item in exported["assertions"]
        if item["subject"] == "Direct source sync" and item["predicate"] == "anchors"
    ]

    assert synced["security"]["allowed"] is True
    assert synced["discovered"] == 1
    assert synced["applied"] == 1
    assert synced["blocks"][0]["source_identity"] == f"git:memory.md@{head}#direct-source-truth"
    assert active[0]["object"] == "MemoryTools facade"
    assert active[0]["source_evidence_cids"] == [synced_evidence["cid"]]
    assert synced_evidence["source_type"] == "markdown_git"
    assert synced_evidence["trust_tier"] == 0
    assert "human-source-truth" in synced_evidence["capability_tags"]
    assert synced_evidence["metadata"]["source_truth"]["git_sha"] == head


def test_mcp_server_initializes_lists_tools_and_calls_capture_search(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    capture = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "chat",
                    "content": "Runtime MCP captures memory evidence.",
                    "trust_tier": 3,
                },
            },
        }
    )
    search = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"tenant_id": TENANT, "query": "MCP memory evidence"},
            },
        }
    )

    assert init["result"]["serverInfo"]["name"] == "mnemosyne-memory"
    assert {tool["name"] for tool in listed["result"]["tools"]} >= {
        "capture",
        "ingest",
        "assert_fact",
        "relation",
        "preference",
        "search",
        "branch",
        "prefetch",
        "profile_add",
        "profile_context",
        "profile_record_mistake",
        "profile_retire_support_strategy",
        "graph_neighbors",
        "trajectory_log",
        "lesson_induce",
        "procedure_induce",
        "lesson_promote",
        "procedure_validate",
        "parametric_propose",
        "parametric_evaluate",
        "parametric_rollback",
        "forget",
        "export",
    }
    tools_by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert set(tools_by_name) == {item["name"] for item in TOOL_SPEC}
    capture_schema = tools_by_name["capture"]["inputSchema"]
    assert capture_schema["properties"]["trust_tier"]["type"] == "integer"
    assert "trust_tier" not in capture_schema["required"]
    assert capture_schema["additionalProperties"] is False
    assert {"type": "null"} in tools_by_name["search"]["inputSchema"]["properties"]["max_sensitivity"]["anyOf"]
    graph_schema = tools_by_name["graph_query"]["inputSchema"]
    assert graph_schema["properties"]["seeds"] == {"type": "array", "items": {"type": "string"}}
    assert graph_schema["properties"]["hops"]["type"] == "integer"
    assert "hops" not in graph_schema["required"]
    mistake_schema = tools_by_name["profile_record_mistake"]["inputSchema"]
    assert {"type": "object", "additionalProperties": True} in mistake_schema["properties"]["scope"]["anyOf"]
    assert {"type": "null"} in mistake_schema["properties"]["scope"]["anyOf"]
    assert "scope" not in mistake_schema["required"]
    retire_schema = tools_by_name["profile_retire_support_strategy"]["inputSchema"]
    assert retire_schema["properties"]["strategy_id"]["type"] == "string"
    assert "role" not in retire_schema["required"]
    supersede_schema = tools_by_name["supersede"]["inputSchema"]
    assert supersede_schema["properties"]["new"]["type"] == "object"
    assert "branch" not in supersede_schema["required"]
    assert capture["result"]["isError"] is False
    assert search["result"]["isError"] is False
    capture_content = capture["result"]["structuredContent"]
    search_content = search["result"]["structuredContent"]
    assert capture_content["cid"]
    assert search_content["hits"]
    assert search_content["hits"][0]["provenance"] == [capture_content["cid"]]


def test_mcp_server_calls_profile_graph_source_and_learning_aliases(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(source_repo), *args],
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()

    git("init")
    git("config", "user.email", "mnemosyne@example.test")
    git("config", "user.name", "Mnemosyne Test")
    (source_repo / "memory.md").write_text(
        """# MCP Source Truth

```mnemosyne-assertion
id = "mcp-source-truth"
subject = "MCP source truth"
predicate = "prefers"
object = "Markdown git"
confidence = 0.99
valid_from = "2026-06-20T00:00:00Z"
```
""",
        encoding="utf-8",
    )
    git("add", "memory.md")
    git("commit", "-m", "add mcp source truth")

    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    synced = mcp_call(
        server,
        "source_sync",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "root": str(source_repo),
            "apply": True,
            **PARAMETRIC_AUTH,
        },
    )
    mcp_call(
        server,
        "relation",
        {
            "tenant_id": TENANT,
            "source": "MCP source truth",
            "predicate": "links",
            "target": "Markdown git",
            "source_evidence_cids": synced["evidence_cids"],
            **PARAMETRIC_AUTH,
        },
    )
    timeline = mcp_call(server, "graph_timeline", {"tenant_id": TENANT, "entity": "MCP source truth"})
    as_of = mcp_call(
        server,
        "graph_as_of",
        {
            "tenant_id": TENANT,
            "subject": "MCP source truth",
            "predicate": "prefers",
            "time": "2026-06-21T00:00:00Z",
        },
    )

    assert synced["discovered"] == 1
    assert synced["applied"] == 1
    assert synced["security"]["allowed"] is True
    assert {event["kind"] for event in timeline["events"]} == {"assertion", "relation"}
    assert as_of["assertions"][0]["object"] == "Markdown git"

    scope = {"surface": "mcp", "project": "mnemosyne"}
    explicit = mcp_call(
        server,
        "profile_record_explicit",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "statement": "Prefer direct MCP alias coverage.",
            "scope": scope,
            "confidence": 0.82,
            "source_evidence_cids": synced["evidence_cids"],
        },
    )
    inferred = mcp_call(
        server,
        "profile_propose_inference",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "statement": "Prefer inferred MCP alias coverage only.",
            "context": scope,
            "confidence": 0.51,
        },
    )
    corrected = mcp_call(
        server,
        "profile_correct",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "id": inferred["id"],
            "statement": "Prefer verified MCP alias coverage.",
            "context": scope,
            "confidence": 0.96,
        },
    )
    relevant = mcp_call(
        server,
        "profile_get_relevant",
        {"tenant_id": TENANT, "user_id": USER, "context": scope},
    )

    assert explicit["security"]["allowed"] is True
    assert corrected["corrects"] == inferred["id"]
    assert any(item["id"] == explicit["id"] for item in relevant["authoritative"])
    assert any(item["statement"] == "Prefer verified MCP alias coverage." for item in relevant["authoritative"])

    trajectory = mcp_call(
        server,
        "trajectory_log",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "session_id": "session-mcp-aliases",
            "task": "MCP alias parity",
            "steps": [{"name": "verify", "status": "failed", "error": "alias gap"}],
            "outcome": "failure",
            "reward": -1.0,
            "memory_version": "v1",
        },
    )
    attribution = mcp_call(server, "trajectory_attribute", {"trajectory_id": trajectory["id"]})
    lesson = mcp_call(server, "lesson_induce", {"trajectory_id": trajectory["id"]})
    procedure = mcp_call(server, "procedure_induce", {"lesson_id": lesson["id"]})
    lesson_search = mcp_call(server, "lesson_search", {"tenant_id": TENANT, "signature": "alias-gap"})
    procedure_search = mcp_call(server, "procedure_search", {"tenant_id": TENANT, "query": "alias-gap"})
    outcome = mcp_call(server, "outcome_evaluate", {"trajectory_id": trajectory["id"]})

    assert attribution["cause"] == "alias gap"
    assert lesson_search["lessons"][0]["id"] == lesson["id"]
    assert procedure_search["procedures"][0]["id"] == procedure["id"]
    assert outcome["trajectory_id"] == trajectory["id"]
    assert outcome["passed"] is False


def test_official_mcp_sdk_adapter_lists_tools_and_calls_capture_search(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp import types

    server = build_sdk_server(store_path=tmp_path / "sdk-store.json", auth_token="token")

    async def exercise() -> None:
        list_handler = server.request_handlers[types.ListToolsRequest]
        call_handler = server.request_handlers[types.CallToolRequest]
        listed = await list_handler(types.ListToolsRequest())
        tools_by_name = {tool.name: tool for tool in listed.root.tools}

        denied = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Unauthorized SDK call should fail closed.",
                    },
                }
            )
        )
        invalid = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "auth_token": "token",
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Invalid SDK call should fail schema validation.",
                        "unexpected": True,
                    },
                }
            )
        )
        captured = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "auth_token": "token",
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Official MCP SDK captures Mnemosyne memory.",
                        "trust_tier": 3,
                    },
                }
            )
        )
        searched = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "search",
                    "arguments": {
                        "auth_token": "token",
                        "tenant_id": TENANT,
                        "query": "SDK Mnemosyne memory",
                    },
                }
            )
        )

        assert set(tools_by_name) == {item["name"] for item in TOOL_SPEC}
        assert tools_by_name["capture"].inputSchema["additionalProperties"] is False
        assert denied.root.isError is True
        assert "unauthorized" in denied.root.content[0].text
        assert invalid.root.isError is True
        assert "Input validation error" in invalid.root.content[0].text
        assert captured.root.isError is False
        assert captured.root.structuredContent["cid"]
        assert searched.root.isError is False
        assert searched.root.structuredContent["hits"]

    asyncio.run(exercise())


def test_official_mcp_sdk_streamable_http_adapter_lists_tools_and_calls_capture_search(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    httpx = pytest.importorskip("httpx")
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    app = build_sdk_streamable_http_app(store_path=tmp_path / "streamable-sdk-store.json")

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with app.state.mnemosyne_streamable_http_manager.run():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                health = await client.get("/healthz")
                assert health.status_code == 200
                assert health.json()["transport"] == "mcp-sdk-streamable-http"
                async with streamable_http_client(
                    "http://testserver/mcp",
                    http_client=client,
                    terminate_on_close=False,
                ) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        result = await session.call_tool("residency_policy", {})
                        captured = await session.call_tool(
                            "capture",
                            {
                                "tenant_id": TENANT,
                                "user_id": USER,
                                "actor": "user",
                                "source_type": "streamable-http",
                                "content": "Official StreamableHTTP MCP captures Mnemosyne memory.",
                                "trust_tier": 3,
                            },
                        )
                        searched = await session.call_tool(
                            "search",
                            {
                                "tenant_id": TENANT,
                                "query": "StreamableHTTP MCP captures Mnemosyne memory",
                            },
                        )

        assert len(tools.tools) == len(TOOL_SPEC)
        assert any(tool.name == "capture" for tool in tools.tools)
        assert result.isError is False
        assert captured.isError is False
        assert captured.structuredContent["cid"]
        assert searched.isError is False
        assert searched.structuredContent["hits"][0]["provenance"] == [captured.structuredContent["cid"]]

    asyncio.run(exercise())


def test_mcp_server_honors_object_encryption_and_residency_config(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        object_store=objects,
        object_store_encryption="aesgcm",
        object_key_store=tmp_path / "keys.json",
        allowed_residencies=("local", "eu"),
    )
    ingested = mcp_call(
        server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "data": base64.b64encode(b"mcp private payload bytes").decode("ascii"),
            "modality": "binary",
            "media_type": "application/octet-stream",
            "metadata": {"residency": "eu", "description": "MCP encrypted private payload."},
            "trust_tier": 0,
        },
    )
    raw_objects = [path.read_bytes() for path in objects.rglob("*") if path.is_file()]
    exported = mcp_call(server, "export", {"tenant_id": TENANT})
    evidence = next(item for item in exported["evidence"] if item["cid"] == ingested["cid"])
    rejected = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "ingest",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "mcp-upload",
                    "content": "disallowed residency",
                    "metadata": {"residency": "us"},
                    "trust_tier": 0,
                },
            },
        }
    )
    forgotten = mcp_call(
        server,
        "forget",
        {"tenant_id": TENANT, "cid": ingested["cid"], "erasure_mode": "hard_delete_legal"},
    )

    assert raw_objects
    assert all(b"mcp private payload bytes" not in raw for raw in raw_objects)
    assert evidence["metadata"]["privacy"]["residency"] == "eu"
    assert "residency:eu" in evidence["capability_tags"]
    assert rejected["result"]["isError"] is True
    assert "not allowed by this runtime" in rejected["result"]["content"][0]["text"]
    assert forgotten["object_shred"]["crypto_shredded"] is True


def test_mcp_server_enforces_cross_region_residency_transfers(tmp_path: Path) -> None:
    denied_server = MnemosyneMcpServer(
        store_path=tmp_path / "denied.json",
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
    )
    denied = denied_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ingest",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "mcp-upload",
                    "content": "EU data cannot process in US without explicit transfer.",
                    "metadata": {"residency": "eu"},
                    "trust_tier": 0,
                },
            },
        }
    )
    allowed_server = MnemosyneMcpServer(
        store_path=tmp_path / "allowed.json",
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
        allowed_residency_transfers=("eu->us",),
    )
    accepted = mcp_call(
        allowed_server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "content": "EU data can process in US with explicit transfer.",
            "metadata": {"residency": "eu"},
            "trust_tier": 0,
        },
    )
    exported = mcp_call(allowed_server, "export", {"tenant_id": TENANT})
    evidence = next(item for item in exported["evidence"] if item["cid"] == accepted["cid"])

    assert denied["result"]["isError"] is True
    assert "cross-region residency transfer" in denied["result"]["content"][0]["text"]
    assert evidence["metadata"]["privacy"]["runtime_residency"] == "us"
    assert evidence["metadata"]["privacy"]["cross_region_transfer"] is True


def test_mcp_server_requires_runtime_residency_when_configured(tmp_path: Path) -> None:
    denied_server = MnemosyneMcpServer(
        store_path=tmp_path / "denied.json",
        allowed_residencies=("eu",),
        require_runtime_residency=True,
    )
    denied = denied_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ingest",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "mcp-upload",
                    "content": "Runtime residency cannot be omitted in strict mode.",
                    "metadata": {"residency": "eu"},
                    "trust_tier": 0,
                },
            },
        }
    )
    allowed_server = MnemosyneMcpServer(
        store_path=tmp_path / "allowed.json",
        allowed_residencies=("eu",),
        runtime_residency="eu",
        require_runtime_residency=True,
    )
    accepted = mcp_call(
        allowed_server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "content": "Runtime residency is configured in strict mode.",
            "metadata": {"residency": "eu"},
            "trust_tier": 0,
        },
    )
    exported = mcp_call(allowed_server, "export", {"tenant_id": TENANT})
    evidence = next(item for item in exported["evidence"] if item["cid"] == accepted["cid"])

    assert denied["result"]["isError"] is True
    assert "runtime residency is required" in denied["result"]["content"][0]["text"]
    assert evidence["metadata"]["privacy"]["runtime_residency"] == "eu"
    assert evidence["metadata"]["privacy"]["cross_region_transfer"] is False


def test_mcp_server_reports_residency_policy(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
        allowed_residency_transfers=("eu->us",),
        require_runtime_residency=True,
    )
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    policy = mcp_call(server, "residency_policy", {})

    tool_names = {item["name"] for item in tools["result"]["tools"]}
    assert "residency_policy" in tool_names
    assert policy["allowed_residencies"] == ["eu", "us"]
    assert policy["runtime_residency"] == "us"
    assert policy["require_runtime_residency"] is True
    assert policy["allowed_residency_transfers"] == ["eu->us"]
    assert policy["warnings"] == []


def test_cli_and_mcp_runtime_env_defaults_are_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mnemosyne import cli as mneme_cli

    object_store = tmp_path / "env-objects"
    object_key_store = tmp_path / "env-keys.json"
    monkeypatch.setenv("MNEMOSYNE_OBJECT_STORE", str(object_store))
    monkeypatch.setenv("MNEMOSYNE_OBJECT_STORE_ENCRYPTION", "aesgcm")
    monkeypatch.setenv("MNEMOSYNE_OBJECT_KEY_STORE", str(object_key_store))
    monkeypatch.delenv("MNEMOSYNE_OBJECT_KEY_PROVIDER", raising=False)
    monkeypatch.setenv("MNEMOSYNE_OBJECT_KEY_COMMAND", "fake-key-command --json")
    monkeypatch.setenv("MNEMOSYNE_OBJECT_KEY_TIMEOUT", "12.5")
    monkeypatch.setenv("MNEMOSYNE_ALLOWED_RESIDENCIES", " local, eu ,us,, ")
    monkeypatch.setenv("MNEMOSYNE_RUNTIME_RESIDENCY", "eu")
    monkeypatch.setenv("MNEMOSYNE_ALLOWED_RESIDENCY_TRANSFERS", "local->eu, eu->us ,")
    monkeypatch.setenv("MNEMOSYNE_REQUIRE_RUNTIME_RESIDENCY", "yes")

    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    policy = server.tools.residency_policy()

    assert mneme_cli.default_object_store() == str(object_store)
    assert mneme_cli.default_object_store_encryption() == "aesgcm"
    assert mneme_cli.default_object_key_store() == str(object_key_store)
    assert mneme_cli.default_object_key_provider() == "command"
    assert mneme_cli.default_object_key_command() == "fake-key-command --json"
    assert mneme_cli.default_allowed_residencies() == ["local", "eu", "us"]
    assert mneme_cli.default_allowed_residency_transfers() == ["local->eu", "eu->us"]
    assert server.object_store == str(object_store)
    assert server.object_store_encryption == "aesgcm"
    assert server.object_key_store == str(object_key_store)
    assert server.object_key_provider == "command"
    assert server.object_key_command == "fake-key-command --json"
    assert server.object_key_timeout == 12.5
    assert server.allowed_residencies == ("local", "eu", "us")
    assert server.runtime_residency == "eu"
    assert server.allowed_residency_transfers == ("local->eu", "eu->us")
    assert server.require_runtime_residency is True
    assert policy["allowed_residencies"] == ["local", "eu", "us"]
    assert policy["runtime_residency"] == "eu"
    assert policy["require_runtime_residency"] is True
    assert policy["request_runtime_residency_required"] is False
    assert policy["allowed_residency_transfers"] == ["local->eu", "eu->us"]
    assert policy["warnings"] == []


def test_mcp_production_profile_fails_closed_on_unsafe_defaults(tmp_path: Path) -> None:
    base = {
        "store_path": tmp_path / "store.json",
        "production_profile": True,
        "object_store_encryption": "aesgcm",
        "object_key_provider": "command",
        "object_key_command": "vault-object-key",
        "stateless": True,
    }

    with pytest.raises(ValueError, match="requires MNEMOSYNE_MCP_REQUIRE_SESSION=1"):
        MnemosyneMcpServer(**base)
    with pytest.raises(ValueError, match="signed-session verifier custody"):
        MnemosyneMcpServer(**base, require_session=True)
    with pytest.raises(ValueError, match="MNEMOSYNE_OBJECT_STORE_ENCRYPTION=aesgcm"):
        MnemosyneMcpServer(
            **{**base, "object_store_encryption": "none"},
            require_session=True,
            session_secret=MCP_SESSION_SECRET,
        )
    with pytest.raises(ValueError, match="command-backed object key custody"):
        MnemosyneMcpServer(
            **{**base, "object_key_provider": "json", "object_key_command": None},
            require_session=True,
            session_secret=MCP_SESSION_SECRET,
        )

    server = MnemosyneMcpServer(
        **base,
        require_session=True,
        session_secret=MCP_SESSION_SECRET,
    )
    assert server.production_profile is True
    assert server.require_session is True
    assert server.object_store_encryption == "aesgcm"
    assert server.object_key_provider == "command"


def test_mcp_server_main_dispatches_serving_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.delenv("MNEMOSYNE_MCP_SDK_STREAMABLE_HTTP", raising=False)

    def record(name: str):
        def _inner(**kwargs: object) -> None:
            calls.append((name, dict(kwargs)))

        return _inner

    class DummyServer:
        def __init__(self, **kwargs: object) -> None:
            calls.append(("stdio_init", dict(kwargs)))

        def __enter__(self) -> DummyServer:
            return self

        def __exit__(self, *_exc_info: object) -> None:
            calls.append(("stdio_close", {}))

        def serve(self) -> None:
            calls.append(("stdio_serve", {}))

    monkeypatch.setattr(mcp_server, "serve_sdk_stdio", record("sdk_stdio"))
    monkeypatch.setattr(mcp_server, "serve_sdk_streamable_http", record("sdk_streamable_http"))
    monkeypatch.setattr(mcp_server, "serve_http", record("http"))
    monkeypatch.setattr(mcp_server, "MnemosyneMcpServer", DummyServer)

    def base_args(name: str) -> list[str]:
        return [
            "--store",
            str(tmp_path / f"{name}.json"),
            "--auth-token",
            "entrypoint-token",
            "--session-secret",
            "entrypoint-secret",
            "--require-session",
            "--stateless",
            "--object-store",
            str(tmp_path / f"{name}-objects"),
            "--parametric-artifact-store",
            str(tmp_path / f"{name}-parametric"),
            "--allowed-residency",
            "local",
            "--runtime-residency",
            "local",
            "--allowed-residency-transfer",
            "local->local",
        ]

    mcp_server.main(base_args("stdio"))
    mcp_server.main(["--sdk", *base_args("sdk")])
    mcp_server.main(
        [
            "--sdk-streamable-http",
            "--http-host",
            "0.0.0.0",
            "--http-port",
            "9876",
            "--sdk-streamable-http-path",
            "/sdk-mcp",
            "--sdk-streamable-health-path",
            "/sdk-health",
            "--sdk-streamable-stateful",
            *base_args("sdk-streamable"),
        ]
    )
    mcp_server.main(
        [
            "--http",
            "--http-host",
            "127.0.0.2",
            "--http-port",
            "9877",
            "--http-rpc-path",
            "/jsonrpc",
            "--http-health-path",
            "/live",
            "--http-session-exchange-path",
            "/exchange",
            "--http-max-body-bytes",
            "4096",
            *base_args("http"),
        ]
    )

    calls_by_name = {name: kwargs for name, kwargs in calls if name != "stdio_serve"}
    assert calls[0][0] == "stdio_init"
    assert calls[1] == ("stdio_serve", {})
    assert calls[2] == ("stdio_close", {})
    assert calls_by_name["stdio_init"]["store_path"] == str(tmp_path / "stdio.json")
    assert calls_by_name["stdio_init"]["auth_token"] == "entrypoint-token"
    assert calls_by_name["stdio_init"]["require_session"] is True
    assert calls_by_name["stdio_init"]["stateless"] is True
    assert calls_by_name["stdio_init"]["allowed_residencies"][-1] == "local"
    assert calls_by_name["stdio_init"]["allowed_residency_transfers"][-1] == "local->local"
    assert calls_by_name["sdk_stdio"]["store_path"] == str(tmp_path / "sdk.json")
    assert calls_by_name["sdk_stdio"]["stateless"] is True
    assert calls_by_name["sdk_streamable_http"]["host"] == "0.0.0.0"
    assert calls_by_name["sdk_streamable_http"]["port"] == 9876
    assert calls_by_name["sdk_streamable_http"]["streamable_http_path"] == "/sdk-mcp"
    assert calls_by_name["sdk_streamable_http"]["health_path"] == "/sdk-health"
    assert calls_by_name["sdk_streamable_http"]["transport_stateless"] is False
    assert calls_by_name["sdk_streamable_http"]["stateless"] is True
    assert calls_by_name["sdk_streamable_http"]["store_path"] == str(tmp_path / "sdk-streamable.json")
    assert calls_by_name["http"]["host"] == "127.0.0.2"
    assert calls_by_name["http"]["port"] == 9877
    assert calls_by_name["http"]["rpc_path"] == "/jsonrpc"
    assert calls_by_name["http"]["health_path"] == "/live"
    assert calls_by_name["http"]["session_exchange_path"] == "/exchange"
    assert calls_by_name["http"]["max_body_bytes"] == 4096
    assert calls_by_name["http"]["store_path"] == str(tmp_path / "http.json")


def test_mcp_server_main_rejects_combined_serving_modes(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        mcp_server.main(["--store", str(tmp_path / "store.json"), "--http", "--sdk"])

    assert exc.value.code == 2


def test_sdk_streamable_builder_preserves_facade_stateless_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def module(name: str) -> object:
        return type(sys)(name)

    fastmcp_server = module("mcp.server.fastmcp.server")
    streamable_manager = module("mcp.server.streamable_http_manager")
    mcp_module = module("mcp")
    mcp_server_module = module("mcp.server")
    mcp_fastmcp_module = module("mcp.server.fastmcp")
    starlette_module = module("starlette")
    starlette_applications = module("starlette.applications")
    starlette_responses = module("starlette.responses")
    starlette_routing = module("starlette.routing")

    class FakeStreamableHTTPASGIApp:
        def __init__(self, manager: object) -> None:
            captured["streamable_app_manager"] = manager

    class FakeStreamableHTTPSessionManager:
        def __init__(
            self,
            *,
            app: object,
            event_store: object,
            json_response: bool,
            stateless: bool,
            security_settings: object,
        ) -> None:
            captured["manager_app"] = app
            captured["manager_stateless"] = stateless

        def run(self) -> None:
            return None

    class FakeJSONResponse:
        def __init__(self, body: object) -> None:
            self.body = body

    class FakeRoute:
        def __init__(self, path: str, endpoint: object, methods: list[str] | None = None) -> None:
            self.path = path
            self.endpoint = endpoint
            self.methods = methods

    class FakeStarlette:
        def __init__(self, *, routes: list[object], lifespan: object) -> None:
            self.routes = routes
            self.lifespan = lifespan
            self.state = type("State", (), {})()

    setattr(fastmcp_server, "StreamableHTTPASGIApp", FakeStreamableHTTPASGIApp)
    setattr(streamable_manager, "StreamableHTTPSessionManager", FakeStreamableHTTPSessionManager)
    setattr(starlette_applications, "Starlette", FakeStarlette)
    setattr(starlette_responses, "JSONResponse", FakeJSONResponse)
    setattr(starlette_routing, "Route", FakeRoute)
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", mcp_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", mcp_fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.server", fastmcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.streamable_http_manager", streamable_manager)
    monkeypatch.setitem(sys.modules, "starlette", starlette_module)
    monkeypatch.setitem(sys.modules, "starlette.applications", starlette_applications)
    monkeypatch.setitem(sys.modules, "starlette.responses", starlette_responses)
    monkeypatch.setitem(sys.modules, "starlette.routing", starlette_routing)

    class FakeFacade:
        def close(self) -> None:
            captured["facade_closed"] = True

    class FakeSdkServer:
        mnemosyne_mcp_facade = FakeFacade()

    fake_sdk_server = FakeSdkServer()

    def fake_build_sdk_server(**kwargs: object) -> object:
        captured["sdk_kwargs"] = dict(kwargs)
        return fake_sdk_server

    monkeypatch.setattr(mcp_server, "build_sdk_server", fake_build_sdk_server)

    app = build_sdk_streamable_http_app(stateless=True, store_path=tmp_path / "store.json")

    assert captured["sdk_kwargs"] == {"store_path": tmp_path / "store.json", "stateless": True}
    assert captured["manager_app"] is fake_sdk_server
    assert captured["manager_stateless"] is True
    assert getattr(app.state, "mnemosyne_streamable_http_manager")
    assert app.state.mnemosyne_mcp_facade is fake_sdk_server.mnemosyne_mcp_facade
    assert "facade_closed" not in captured


def test_mcp_server_can_use_command_key_provider_for_encrypted_objects(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    command, kms_state = fake_kms_command(tmp_path)
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        object_store=objects,
        object_store_encryption="aesgcm",
        object_key_provider="command",
        object_key_command=command,
    )
    ingested = mcp_call(
        server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "data": base64.b64encode(b"mcp kms private payload").decode("ascii"),
            "modality": "binary",
            "media_type": "application/octet-stream",
            "metadata": {"description": "MCP command-KMS private payload."},
            "trust_tier": 0,
        },
    )
    raw_objects = [path.read_bytes() for path in objects.rglob("*") if path.is_file()]
    before_shred = json.loads(kms_state.read_text(encoding="utf-8"))
    forgotten = mcp_call(
        server,
        "forget",
        {"tenant_id": TENANT, "cid": ingested["cid"], "erasure_mode": "hard_delete_legal"},
    )
    after_shred = json.loads(kms_state.read_text(encoding="utf-8"))

    assert raw_objects
    assert all(b"mcp kms private payload" not in raw for raw in raw_objects)
    assert len(before_shred["keys"]) == 1
    assert after_shred["keys"] == {}
    assert not (objects / ".keys.json").exists()
    assert forgotten["object_shred"]["crypto_shredded"] is True


def test_mcp_search_surfaces_gist_only_abstention(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    captured = mcp_call(
        server,
        "capture",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp",
            "content": "MCP search abstention source should only support answers through generated gist metadata.",
            "trust_tier": 0,
        },
    )
    summary_run = ConsolidationWorker(server.engine, gate_cases=[]).run_queue_payload(
        {
            "tenant_id": TENANT,
            "branch": "main",
            "source_evidence_cids": [captured["cid"]],
            "passes": ["summarizer"],
        }
    )
    summary = next(item for item in summary_run.pass_results if item["name"] == "summarizer")["details"]

    searched = mcp_call(server, "search", {"tenant_id": TENANT, "query": captured["cid"]})

    assert searched["abstained"] is True
    assert searched["uncertainty_note"] == "Only gist-tier memory support was retrieved; inspect source evidence before answering."
    assert searched["hits"][0]["id"] == summary["summary_cid"]
    assert searched["hits"][0]["metadata"]["summary"]["kind"] == "abstractive_gist"
    assert searched["explain"]["gist_support"]["applied"] is True
    assert searched["explain"]["gist_support"]["gist_hit_ids"] == [summary["summary_cid"]]


def test_mcp_deep_search_suppresses_gist_derived_graph_without_source(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    source_key = "mcp-deep-gist-source"
    summary_cid = server.engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="system",
            source_type="consolidation-summary",
            source_identity="consolidation-summary:mcp-deep-gist",
            content="MCP deep search generated summary support requires source inspection.",
            metadata={
                "summary": {
                    "kind": "abstractive_gist",
                    "source_evidence_cids": [source_key],
                    "confabulation_risk": True,
                }
            },
            trust_tier=2,
            capability_tags=["consolidation-gist", "derived-summary"],
            access_policy={"tenant": TENANT},
        )
    )
    server.engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source=source_key,
            predicate="summary-derived-gist",
            target=summary_cid,
            source_evidence_cids=[source_key],
            access_policy={"tenant": TENANT},
        )
    )

    deep_searched = mcp_call(server, "deep_search", {"tenant_id": TENANT, "query": source_key})
    explained = mcp_call(server, "explain", {"tenant_id": TENANT, "query": source_key})

    for result in (deep_searched, explained):
        relation_hits = [hit for hit in result["hits"] if hit["kind"] == "relation"]
        assert result["abstained"] is True
        assert (
            result["uncertainty_note"]
            == "Retrieved evidence did not cover enough query terms; abstaining until stronger support is available."
        )
        assert result["hits"] == []
        assert relation_hits == []
        assert result["explain"]["gist_support"]["applied"] is False
        assert result["explain"]["gist_support"]["gist_hit_ids"] == []


def test_mcp_server_rejects_non_object_tool_arguments(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search", "arguments": ["not", "an", "object"]},
        }
    )

    assert response["result"]["isError"] is True
    assert "Tool arguments must be a JSON object" in response["result"]["content"][0]["text"]


def test_mcp_server_rejects_schema_invalid_json_rpc_tool_arguments(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")

    invalid_type = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "tenant_id": TENANT,
                    "query": "schema invalid request",
                    "max_sensitivity": "high",
                },
            },
        }
    )
    unexpected_property = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "tenant_id": TENANT,
                    "query": "schema invalid request",
                    "unexpected": True,
                },
            },
        }
    )
    explicit_null = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "tenant_id": TENANT,
                    "query": "schema valid nullable request",
                    "max_sensitivity": None,
                },
            },
        }
    )

    assert invalid_type["result"]["isError"] is True
    assert "Input validation error" in invalid_type["result"]["content"][0]["text"]
    assert unexpected_property["result"]["isError"] is True
    assert "unexpected" in unexpected_property["result"]["content"][0]["text"]
    assert explicit_null["result"]["isError"] is False


def test_mcp_prepare_tool_arguments_strips_metadata_and_binds_session(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(session_id="prepare-tool-arguments-session")

    prepared_capture = server.prepare_tool_arguments(
        "capture",
        {"_meta": {"session_token": token}},
        {
            "_meta": {"auth_token": "transport-only"},
            "auth_token": "transport-only",
            "tenant_id": "",
            "user_id": USER,
            "actor": "user",
            "source_type": "prepare-tool-arguments",
            "content": "Session-bound prepare_tool_arguments input.",
            "trust_tier": 5,
        },
    )
    prepared_assert = server.prepare_tool_arguments(
        "assert_fact",
        {"session_token": token},
        {
            "tenant_id": TENANT,
            "user_id": "",
            "subject": "prepare_tool_arguments",
            "predicate": "binds",
            "object_value": "session claims",
            "source_evidence_cids": [],
            "trust_tier": 5,
            "role": "reader",
            "source_trust_tier": 5,
        },
    )

    assert "_meta" not in prepared_capture
    assert "auth_token" not in prepared_capture
    assert "session_token" not in prepared_capture
    assert prepared_capture["tenant_id"] == TENANT
    assert prepared_capture["user_id"] == USER
    assert prepared_capture["trust_tier"] == 0
    assert prepared_capture["source_identity"] == "prepare-tool-arguments-session"
    assert prepared_assert["user_id"] == USER
    assert prepared_assert["role"] == "operator"
    assert prepared_assert["source_trust_tier"] == 0
    assert prepared_assert["trust_tier"] == 0

    with pytest.raises(PermissionError, match="session token required"):
        server.prepare_tool_arguments("search", {}, {"tenant_id": TENANT, "query": "session required"})
    with pytest.raises(PermissionError, match="session tenant mismatch"):
        server.prepare_tool_arguments(
            "capture",
            {},
            {
                "session_token": token,
                "tenant_id": "other-tenant",
                "user_id": USER,
                "actor": "user",
                "source_type": "prepare-tool-arguments",
                "content": "Mismatched tenant should fail closed.",
            },
        )


def test_mcp_self_test_validates_auth_session_and_schema(tmp_path: Path) -> None:
    auth_token = "mcp-self-test-auth-token"
    report = run_self_test(
        store_path=tmp_path / "store.json",
        auth_token=auth_token,
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    checks = {check["name"]: check for check in report["checks"]}
    encoded = json.dumps(report)

    assert report["ok"] is True
    assert report["auth_token_required"] is True
    assert report["session_required"] is True
    assert checks["initialize"]["ok"] is True
    assert checks["tools_list"]["ok"] is True
    assert checks["tools_list"]["tool_count"] == len(TOOL_SPEC)
    assert checks["auth_token_rejects_missing_token"]["ok"] is True
    assert checks["session_rejects_missing_token"]["ok"] is True
    assert checks["session_signing_configured"]["ok"] is True
    assert checks["schema_rejects_invalid_arguments"]["ok"] is True
    assert checks["read_only_tool_call"]["ok"] is True
    assert auth_token not in encoded
    assert MCP_SESSION_SECRET not in encoded
    assert "session_token" not in encoded


def test_mcp_self_test_fails_when_session_required_without_verifier(tmp_path: Path) -> None:
    report = run_self_test(store_path=tmp_path / "store.json", require_session=True)
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is False
    assert checks["session_signing_configured"]["ok"] is False
    assert checks["read_only_tool_call"]["ok"] is False


def test_mcp_self_test_records_sdk_build_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sdk_calls: list[dict[str, object]] = []
    facade_close_calls: list[int] = []

    class FakeSdkFacade:
        def close(self) -> None:
            facade_close_calls.append(1)

    class FakeSdkServer:
        def __init__(self) -> None:
            self.mnemosyne_mcp_facade = FakeSdkFacade()

    def sdk_success(**kwargs: object) -> object:
        sdk_calls.append(dict(kwargs))
        return FakeSdkServer()

    monkeypatch.setattr(mcp_server, "build_sdk_server", sdk_success)
    report = run_self_test(store_path=tmp_path / "sdk-ok.json", sdk=True, stateless=True)
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is True
    assert report["stateless"] is True
    assert checks["sdk_build"]["ok"] is True
    assert facade_close_calls == [1]
    assert sdk_calls[0]["store_path"] == tmp_path / "sdk-ok.json"
    assert sdk_calls[0]["stateless"] is True

    dsn = "postgresql://mnemosyne:p%40ss@127.0.0.1:54329/mnemosyne?sslpassword=q%40pass"

    def sdk_failure(**_kwargs: object) -> object:
        raise RuntimeError(
            f"sdk extra unavailable for sdk-self-test-token using {dsn}; password=p%40ss; decoded=p@ss; query=q@pass"
        )

    monkeypatch.setattr(mcp_server, "build_sdk_server", sdk_failure)
    failed = run_self_test(
        store_path=tmp_path / "sdk-fail.json",
        auth_token="sdk-self-test-token",
        postgres_dsn=dsn,
        sdk=True,
    )
    failed_checks = {check["name"]: check for check in failed["checks"]}
    encoded = json.dumps(failed)

    assert failed["ok"] is False
    assert failed_checks["sdk_build"]["ok"] is False
    assert (
        failed_checks["sdk_build"]["error"]
        == "sdk extra unavailable for <redacted> using <redacted>; password=<redacted>; decoded=<redacted>; query=<redacted>"
    )
    assert "sdk-self-test-token" not in encoded
    assert "p%40ss" not in encoded
    assert "p@ss" not in encoded
    assert "q%40pass" not in encoded
    assert "q@pass" not in encoded
    assert dsn not in encoded


def test_mcp_cli_self_test_reports_deployment_health(tmp_path: Path) -> None:
    auth_token = "mcp-cli-self-test-auth-token"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mnemosyne.mcp_server",
            "--store",
            str(tmp_path / "store.json"),
            "--self-test",
            "--auth-token",
            auth_token,
            "--session-secret",
            MCP_SESSION_SECRET,
            "--require-session",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    encoded = json.dumps(report)

    assert report["ok"] is True
    assert report["backend"] == "local"
    assert report["stateless"] is False
    assert auth_token not in encoded
    assert MCP_SESSION_SECRET not in encoded


def test_mcp_http_transport_health_lists_and_calls_capture_search(tmp_path: Path) -> None:
    server, thread, base = start_mcp_http_server(store_path=tmp_path / "store.json")
    try:
        health_status, health = http_json("GET", f"{base}/healthz")
        init_status, initialized = http_json("POST", f"{base}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        list_status, listed = http_json("POST", f"{base}/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        capture_status, captured = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "chat",
                        "content": "Hosted MCP HTTP transport captures evidence.",
                        "trust_tier": 3,
                    },
                },
            },
        )
        search_status, searched = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "search",
                    "arguments": {"tenant_id": TENANT, "query": "Hosted MCP HTTP transport"},
                },
            },
        )
        notification_status, notification = http_json(
            "POST",
            f"{base}/mcp",
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
    finally:
        stop_mcp_http_server(server, thread)

    assert health_status == 200
    assert health is not None
    assert health["ok"] is True
    assert health["transport"] == "http-json-rpc"
    assert health["rpc_path"] == "/mcp"
    assert health["auth_token_required"] is False
    assert init_status == 200
    assert initialized is not None
    assert initialized["result"]["protocolVersion"] == "2024-11-05"  # type: ignore[index]
    assert list_status == 200
    assert listed is not None
    first_tool = listed["result"]["tools"][0]  # type: ignore[index]
    assert first_tool["inputSchema"]["additionalProperties"] is False
    assert capture_status == 200
    assert captured is not None
    captured_content = captured["result"]["structuredContent"]  # type: ignore[index]
    assert search_status == 200
    assert searched is not None
    hits = searched["result"]["structuredContent"]["hits"]  # type: ignore[index]
    assert hits[0]["provenance"] == [captured_content["cid"]]
    assert notification_status == 204
    assert notification is None


def test_mcp_http_transport_surfaces_gist_only_abstention(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server, thread, base = start_mcp_http_server(store_path=store)
    try:
        capture_status, captured = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "mcp",
                        "content": (
                            "Hosted MCP HTTP search abstention source should only support answers "
                            "through generated gist metadata."
                        ),
                        "trust_tier": 0,
                    },
                },
            },
        )
    finally:
        stop_mcp_http_server(server, thread)

    assert capture_status == 200
    assert captured is not None
    captured_content = captured["result"]["structuredContent"]  # type: ignore[index]
    with LocalMemoryEngine(store_path=store) as consolidation_engine:
        summary_run = ConsolidationWorker(consolidation_engine, gate_cases=[]).run_queue_payload(
            {
                "tenant_id": TENANT,
                "branch": "main",
                "source_evidence_cids": [captured_content["cid"]],
                "passes": ["summarizer"],
            }
        )
    summary = next(item for item in summary_run.pass_results if item["name"] == "summarizer")["details"]

    server, thread, base = start_mcp_http_server(store_path=store)
    try:
        search_status, searched = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search",
                    "arguments": {"tenant_id": TENANT, "query": captured_content["cid"]},
                },
            },
        )
    finally:
        stop_mcp_http_server(server, thread)

    assert search_status == 200
    assert searched is not None
    body = searched["result"]["structuredContent"]  # type: ignore[index]
    assert body["abstained"] is True
    assert body["uncertainty_note"] == "Only gist-tier memory support was retrieved; inspect source evidence before answering."
    assert body["hits"][0]["id"] == summary["summary_cid"]
    assert body["hits"][0]["metadata"]["summary"]["kind"] == "abstractive_gist"
    assert body["explain"]["gist_support"]["applied"] is True
    assert body["explain"]["gist_support"]["gist_hit_ids"] == [summary["summary_cid"]]


def test_mcp_http_transport_suppresses_gist_derived_graph_without_source(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    source_key = "hosted-http-deep-gist-source"
    with LocalMemoryEngine(store_path=store) as engine:
        summary_cid = engine.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id=USER,
                actor="system",
                source_type="consolidation-summary",
                source_identity="consolidation-summary:http-deep-gist",
                content="Hosted MCP HTTP deep search generated summary support requires source inspection.",
                metadata={
                    "summary": {
                        "kind": "abstractive_gist",
                        "source_evidence_cids": [source_key],
                        "confabulation_risk": True,
                    }
                },
                trust_tier=2,
                capability_tags=["consolidation-gist", "derived-summary"],
                access_policy={"tenant": TENANT},
            )
        )
        engine.add_relation(
            Relation(
                tenant_id=TENANT,
                source=source_key,
                predicate="summary-derived-gist",
                target=summary_cid,
                source_evidence_cids=[source_key],
                access_policy={"tenant": TENANT},
            )
        )

    server, thread, base = start_mcp_http_server(store_path=store)
    try:
        deep_status, deep_searched = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "deep_search",
                    "arguments": {"tenant_id": TENANT, "query": source_key},
                },
            },
        )
        explain_status, explained = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "explain",
                    "arguments": {"tenant_id": TENANT, "query": source_key},
                },
            },
        )
    finally:
        stop_mcp_http_server(server, thread)

    assert deep_status == 200
    assert explain_status == 200
    assert deep_searched is not None
    assert explained is not None
    for response in (deep_searched, explained):
        body = response["result"]["structuredContent"]  # type: ignore[index]
        relation_hits = [hit for hit in body["hits"] if hit["kind"] == "relation"]
        assert body["abstained"] is True
        assert (
            body["uncertainty_note"]
            == "Retrieved evidence did not cover enough query terms; abstaining until stronger support is available."
        )
        assert body["hits"] == []
        assert relation_hits == []
        assert body["explain"]["gist_support"]["applied"] is False
        assert body["explain"]["gist_support"]["gist_hit_ids"] == []


def test_mcp_http_transport_serves_tls_health(tmp_path: Path) -> None:
    tls = make_tls_material(tmp_path)
    server, thread, _ = start_mcp_http_server(
        store_path=tmp_path / "store.json",
        tls_cert_file=str(tls["server_cert"]),
        tls_key_file=str(tls["server_key"]),
    )
    base = f"https://127.0.0.1:{server.server_port}"
    context = ssl.create_default_context(cafile=str(tls["ca_cert"]))
    try:
        health_status, health = http_json("GET", f"{base}/healthz", context=context)
    finally:
        stop_mcp_http_server(server, thread)

    assert health_status == 200
    assert health is not None
    assert health["ok"] is True
    assert health["transport"] == "http-json-rpc"
    assert health["tls_enabled"] is True
    assert health["tls_client_cert_required"] is False


def test_mcp_http_transport_requires_client_certificate(tmp_path: Path) -> None:
    tls = make_tls_material(tmp_path)
    server, thread, _ = start_mcp_http_server(
        store_path=tmp_path / "store.json",
        tls_cert_file=str(tls["server_cert"]),
        tls_key_file=str(tls["server_key"]),
        tls_client_ca_file=str(tls["ca_cert"]),
        tls_require_client_cert=True,
    )
    base = f"https://127.0.0.1:{server.server_port}"
    server_trust_context = ssl.create_default_context(cafile=str(tls["ca_cert"]))
    client_identity_context = ssl.create_default_context(cafile=str(tls["ca_cert"]))
    client_identity_context.load_cert_chain(str(tls["client_cert"]), str(tls["client_key"]))
    try:
        with pytest.raises((ssl.SSLError, urlerror.URLError, ConnectionError, OSError)):
            http_json("GET", f"{base}/healthz", context=server_trust_context)
        health_status, health = http_json("GET", f"{base}/healthz", context=client_identity_context)
    finally:
        stop_mcp_http_server(server, thread)

    assert health_status == 200
    assert health is not None
    assert health["ok"] is True
    assert health["tls_enabled"] is True
    assert health["tls_client_cert_required"] is True


def test_mcp_http_transport_rejects_incomplete_tls_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    close_calls: list[int] = []
    original_close = MnemosyneMcpServer.close

    def counting_close(self: MnemosyneMcpServer) -> None:
        close_calls.append(1)
        original_close(self)

    monkeypatch.setattr(MnemosyneMcpServer, "close", counting_close)
    tls = make_tls_material(tmp_path)
    with pytest.raises(ValueError, match="both tls_cert_file and tls_key_file"):
        build_http_server(host="127.0.0.1", port=0, tls_cert_file=str(tls["server_cert"]))
    assert close_calls == [1]
    with pytest.raises(ValueError, match="client certificate enforcement requires tls_client_ca_file"):
        build_http_server(
            host="127.0.0.1",
            port=0,
            tls_cert_file=str(tls["server_cert"]),
            tls_key_file=str(tls["server_key"]),
            tls_require_client_cert=True,
        )
    assert close_calls == [1, 1]


def test_mcp_http_transport_enforces_auth_session_and_schema(tmp_path: Path) -> None:
    auth_token = "http-mcp-auth-token"
    server, thread, base = start_mcp_http_server(
        store_path=tmp_path / "store.json",
        auth_token=auth_token,
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    try:
        _, health = http_json("GET", f"{base}/healthz")
        _, missing_auth = http_json(
            "POST",
            f"{base}/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "residency_policy", "arguments": {}}},
        )
        _, wrong_auth = http_json(
            "POST",
            f"{base}/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "residency_policy", "arguments": {}}},
            headers={"Authorization": "Bearer wrong-token"},
        )
        _, missing_session = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "residency_policy", "arguments": {}},
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        session_token = mcp_session_token()
        _, tampered_session = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "residency_policy", "arguments": {}},
            },
            headers={"Authorization": f"Bearer {auth_token}", "X-Mnemosyne-Session-Token": f"{session_token}tampered"},
        )
        tenant_mismatch_token = mcp_session_token(tenant_id="other-tenant")
        _, tenant_mismatch = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "chat",
                        "content": "Tenant mismatch should fail.",
                        "trust_tier": 0,
                    },
                },
            },
            headers={"Authorization": f"Bearer {auth_token}", "X-Mnemosyne-Session-Token": tenant_mismatch_token},
        )
        _, schema_error = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "residency_policy",
                    "arguments": {"unexpected": True},
                },
            },
            headers={"Authorization": f"Bearer {auth_token}", "X-Mnemosyne-Session-Token": session_token},
        )
        _, ok = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "residency_policy",
                    "arguments": {},
                },
            },
            headers={"Authorization": f"Bearer {auth_token}", "X-Mnemosyne-Session-Token": session_token},
        )
    finally:
        stop_mcp_http_server(server, thread)

    encoded = json.dumps([health, missing_auth, wrong_auth, missing_session, tampered_session, tenant_mismatch, schema_error, ok])
    assert health is not None
    assert health["auth_token_required"] is True
    assert health["session_required"] is True
    assert missing_auth is not None
    assert missing_auth["result"]["isError"] is True  # type: ignore[index]
    assert "auth token" in missing_auth["result"]["content"][0]["text"]  # type: ignore[index]
    assert wrong_auth is not None
    assert wrong_auth["result"]["isError"] is True  # type: ignore[index]
    assert "auth token" in wrong_auth["result"]["content"][0]["text"]  # type: ignore[index]
    assert missing_session is not None
    assert missing_session["result"]["isError"] is True  # type: ignore[index]
    assert "session token required" in missing_session["result"]["content"][0]["text"]  # type: ignore[index]
    assert tampered_session is not None
    assert tampered_session["result"]["isError"] is True  # type: ignore[index]
    assert "session token denied" in tampered_session["result"]["content"][0]["text"]  # type: ignore[index]
    assert tenant_mismatch is not None
    assert tenant_mismatch["result"]["isError"] is True  # type: ignore[index]
    assert "session tenant mismatch" in tenant_mismatch["result"]["content"][0]["text"]  # type: ignore[index]
    assert schema_error is not None
    assert schema_error["result"]["isError"] is True  # type: ignore[index]
    assert "unexpected" in schema_error["result"]["content"][0]["text"]  # type: ignore[index]
    assert ok is not None
    assert ok["result"]["isError"] is False  # type: ignore[index]
    assert auth_token not in encoded
    assert MCP_SESSION_SECRET not in encoded
    assert session_token not in encoded


def test_mcp_http_transport_uses_session_secret_command(tmp_path: Path) -> None:
    auth_token = "http-mcp-auth-token"
    command_secret = "command-mcp-session-secret"
    command = fake_session_secret_command(tmp_path, {"secret": command_secret})
    session_token = SessionTokenVerifier(command_secret).sign(
        SessionIdentity(tenant_id=TENANT, user_id=USER, role="operator", source_trust_tier=0)
    )
    server, thread, base = start_mcp_http_server(
        store_path=tmp_path / "store.json",
        auth_token=auth_token,
        session_secret_command=command,
        require_session=True,
    )
    try:
        status, response = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "residency_policy", "arguments": {}},
            },
            headers={"Authorization": f"Bearer {auth_token}", "X-Mnemosyne-Session-Token": session_token},
        )
    finally:
        stop_mcp_http_server(server, thread)

    encoded = json.dumps(response)
    assert status == 200
    assert response is not None
    assert response["result"]["isError"] is False  # type: ignore[index]
    assert command_secret not in encoded
    assert session_token not in encoded
    assert auth_token not in encoded


def test_mcp_http_session_exchange_validates_idp_and_issues_usable_session(tmp_path: Path) -> None:
    auth_token = "http-session-exchange-auth"
    jwks, idp_token = make_oidc_token(oidc_payload())
    server, thread, base = start_mcp_http_server(
        store_path=tmp_path / "store.json",
        auth_token=auth_token,
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
        idp_jwks=json.dumps(jwks),
        idp_issuer=IDP_ISSUER,
        idp_audience=IDP_AUDIENCE,
        session_max_ttl_seconds=600,
    )
    try:
        _, health = http_json("GET", f"{base}/healthz")
        unauthorized_status, unauthorized = http_json(
            "POST",
            f"{base}/session/exchange",
            {"idp_token": idp_token},
        )
        exchange_status, exchanged = http_json(
            "POST",
            f"{base}/session/exchange",
            {"idp_token": idp_token},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        bad_status, bad_exchange = http_json(
            "POST",
            f"{base}/session/exchange",
            {"idp_token": f"{idp_token}tampered"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        session_token = exchanged["session_token"] if exchanged else ""
        call_status, call = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "residency_policy",
                    "arguments": {},
                },
            },
            headers={"Authorization": f"Bearer {auth_token}", "X-Mnemosyne-Session-Token": str(session_token)},
        )
    finally:
        stop_mcp_http_server(server, thread)

    encoded = json.dumps([health, unauthorized, exchanged, bad_exchange, call])
    assert health is not None
    assert health["session_exchange_configured"] is True
    assert health["session_exchange_jwks_cache_ttl_seconds"] == 300
    assert health["session_exchange_refresh_on_unknown_kid"] is True
    assert unauthorized_status == 401
    assert unauthorized == {"error": "unauthorized", "ok": False}
    assert exchange_status == 200
    assert exchanged is not None
    verified = SessionTokenVerifier(MCP_SESSION_SECRET).verify(exchanged["session_token"])
    assert verified.tenant_id == TENANT
    assert verified.user_id == USER
    assert verified.role == "operator"
    assert verified.source_trust_tier == 0
    assert verified.session_id == "mcp-idp-session"
    assert bad_status == 401
    assert bad_exchange == {"error": "session exchange denied", "ok": False}
    assert call_status == 200
    assert call is not None
    assert call["result"]["isError"] is False  # type: ignore[index]
    assert idp_token not in encoded
    assert MCP_SESSION_SECRET not in encoded
    assert auth_token not in encoded


def test_mcp_http_session_exchange_refreshes_file_jwks_rotation_on_unknown_kid(tmp_path: Path) -> None:
    auth_token = "http-session-exchange-rotation-auth"
    old_jwks, old_idp_token = make_oidc_token(oidc_payload(jti="old-idp-session"), kid="old-idp-key")
    new_jwks, new_idp_token = make_oidc_token(oidc_payload(jti="new-idp-session"), kid="new-idp-key")
    jwks_file = tmp_path / "idp-jwks.json"
    jwks_file.write_text(json.dumps(old_jwks), encoding="utf-8")
    server, thread, base = start_mcp_http_server(
        store_path=tmp_path / "store.json",
        auth_token=auth_token,
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
        idp_jwks_file=str(jwks_file),
        idp_issuer=IDP_ISSUER,
        idp_audience=IDP_AUDIENCE,
        idp_jwks_cache_ttl_seconds=300,
    )
    try:
        old_status, old_exchange = http_json(
            "POST",
            f"{base}/session/exchange",
            {"idp_token": old_idp_token},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        jwks_file.write_text(json.dumps(new_jwks), encoding="utf-8")
        new_status, new_exchange = http_json(
            "POST",
            f"{base}/session/exchange",
            {"idp_token": new_idp_token},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
    finally:
        stop_mcp_http_server(server, thread)

    encoded = json.dumps([old_exchange, new_exchange])
    assert old_status == 200
    assert old_exchange is not None
    assert SessionTokenVerifier(MCP_SESSION_SECRET).verify(old_exchange["session_token"]).session_id == "old-idp-session"
    assert new_status == 200
    assert new_exchange is not None
    assert SessionTokenVerifier(MCP_SESSION_SECRET).verify(new_exchange["session_token"]).session_id == "new-idp-session"
    assert old_idp_token not in encoded
    assert new_idp_token not in encoded
    assert MCP_SESSION_SECRET not in encoded
    assert auth_token not in encoded


def test_mcp_http_session_exchange_maps_claims_through_authz_policy(tmp_path: Path) -> None:
    auth_token = "http-session-exchange-policy-auth"
    payload = oidc_payload(groups=["mnemosyne-operators"], scope="openid mnemosyne.write", azp="mcp-client")
    payload.pop("mnemosyne_role")
    payload.pop("mnemosyne_source_trust_tier")
    jwks, idp_token = make_oidc_token(payload)
    bad_payload = oidc_payload(groups=["mnemosyne-readers"], scope="openid", azp="mcp-client")
    bad_jwks, bad_idp_token = make_oidc_token(bad_payload, kid="bad-policy-key")
    jwks["keys"].extend(bad_jwks["keys"])
    policy_file = tmp_path / "authz-policy.json"
    policy_file.write_text(
        json.dumps(
            {
                "allowed_client_ids": ["mcp-client"],
                "rules": [
                    {
                        "tenant_ids": [TENANT],
                        "claim_contains": {
                            "groups": "mnemosyne-operators",
                            "scope": "mnemosyne.write",
                        },
                        "role": "operator",
                        "source_trust_tier": 0,
                        **MFA_RULE,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    server, thread, base = start_mcp_http_server(
        store_path=tmp_path / "store.json",
        auth_token=auth_token,
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
        idp_jwks=json.dumps(jwks),
        idp_authz_policy_file=str(policy_file),
        idp_issuer=IDP_ISSUER,
        idp_audience=IDP_AUDIENCE,
    )
    try:
        _, health = http_json("GET", f"{base}/healthz")
        exchange_status, exchanged = http_json(
            "POST",
            f"{base}/session/exchange",
            {"idp_token": idp_token},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        bad_status, bad_exchange = http_json(
            "POST",
            f"{base}/session/exchange",
            {"idp_token": bad_idp_token},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        session_token = exchanged["session_token"] if exchanged else ""
        call_status, call = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "residency_policy", "arguments": {}},
            },
            headers={"Authorization": f"Bearer {auth_token}", "X-Mnemosyne-Session-Token": str(session_token)},
        )
    finally:
        stop_mcp_http_server(server, thread)

    encoded = json.dumps([health, exchanged, bad_exchange, call])
    assert health is not None
    assert health["session_exchange_authz_policy_configured"] is True
    assert exchange_status == 200
    assert exchanged is not None
    verified = SessionTokenVerifier(MCP_SESSION_SECRET).verify(exchanged["session_token"])
    assert verified.tenant_id == TENANT
    assert verified.user_id == USER
    assert verified.role == "operator"
    assert verified.source_trust_tier == 0
    assert bad_status == 401
    assert bad_exchange == {"error": "session exchange denied", "ok": False}
    assert call_status == 200
    assert call is not None
    assert call["result"]["isError"] is False  # type: ignore[index]
    assert idp_token not in encoded
    assert bad_idp_token not in encoded
    assert MCP_SESSION_SECRET not in encoded
    assert auth_token not in encoded


def test_mcp_http_transport_rejects_malformed_and_oversized_payloads(tmp_path: Path) -> None:
    server, thread, base = start_mcp_http_server(store_path=tmp_path / "store.json", max_body_bytes=128)
    try:
        malformed_status, malformed = http_post_raw(f"{base}/mcp", b"{bad-json")
        non_object_status, non_object = http_post_raw(f"{base}/mcp", b"[]")
        unsupported_status, unsupported = http_json(
            "POST",
            f"{base}/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "unknown/method"},
        )
        oversized_status, oversized = http_post_raw(
            f"{base}/mcp",
            b'{"jsonrpc":"2.0","id":1,"method":"initialize","padding":"' + (b"a" * 160) + b'"}',
        )
        missing_status, missing = http_json("GET", f"{base}/missing")
    finally:
        stop_mcp_http_server(server, thread)

    assert malformed_status == 400
    assert malformed is not None
    assert malformed["error"]["code"] == -32700  # type: ignore[index]
    assert non_object_status == 400
    assert non_object is not None
    assert non_object["error"]["message"] == "JSON-RPC request must be an object"  # type: ignore[index]
    assert unsupported_status == 200
    assert unsupported is not None
    assert unsupported["error"]["code"] == -32601  # type: ignore[index]
    assert oversized_status == 413
    assert oversized is not None
    assert oversized["error"]["message"] == "Request body too large"  # type: ignore[index]
    assert missing_status == 404
    assert missing == {"error": "not found", "ok": False}


def test_mcp_http_transport_stateless_mode_reloads_durable_state(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server, thread, base = start_mcp_http_server(store_path=store, stateless=True)
    try:
        _, captured = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "chat",
                        "content": "Hosted stateless MCP reloads durable state.",
                        "trust_tier": 3,
                    },
                },
            },
        )
    finally:
        stop_mcp_http_server(server, thread)

    server, thread, base = start_mcp_http_server(store_path=store, stateless=True)
    try:
        _, searched = http_json(
            "POST",
            f"{base}/mcp",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search",
                    "arguments": {"tenant_id": TENANT, "query": "Hosted stateless MCP"},
                },
            },
        )
    finally:
        stop_mcp_http_server(server, thread)

    assert captured is not None
    assert searched is not None
    captured_content = captured["result"]["structuredContent"]  # type: ignore[index]
    hits = searched["result"]["structuredContent"]["hits"]  # type: ignore[index]
    assert hits[0]["provenance"] == [captured_content["cid"]]


def test_mcp_http_server_close_releases_facade_and_is_idempotent(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server, thread, base = start_mcp_http_server(store_path=store)
    try:
        with pytest.raises(RuntimeError, match="already has a writer"):
            LocalMemoryEngine(store_path=store)
    finally:
        stop_mcp_http_server(server, thread)
    server.server_close()
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_server_stateless_mode_reloads_durable_engine_and_runtime_state(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    writer = MnemosyneMcpServer(store_path=store, stateless=True)
    captured = mcp_call(
        writer,
        "capture",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "chat",
            "content": "Stateless MCP reloads durable evidence.",
            "trust_tier": 3,
        },
    )
    mcp_call(
        writer,
        "profile_add",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "kind": "explicit_preference",
            "statement": "Prefer stateless MCP calls backed by durable state.",
        },
    )
    first_slip = mcp_call(
        writer,
        "profile_record_mistake",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "pattern": "date_math",
            "description": "User accepted an off-by-one deployment date.",
            "scope": {"surface": "mcp"},
            "suggestion": "Offer to double-check deployment date math.",
            "source_trust_tier": 0,
        },
    )
    second_slip = mcp_call(
        writer,
        "profile_record_mistake",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "pattern": "date_math",
            "description": "User repeated the same deployment date slip.",
            "scope": {"surface": "mcp"},
            "suggestion": "Offer to double-check deployment date math.",
            "source_trust_tier": 0,
        },
    )
    writer.close()
    reader = MnemosyneMcpServer(store_path=store, stateless=True)

    search = mcp_call(reader, "search", {"tenant_id": TENANT, "query": "stateless durable evidence"})
    profile = mcp_call(reader, "profile_context", {"tenant_id": TENANT, "user_id": USER, "scope": {"surface": "mcp"}})

    assert first_slip["promoted"] is False
    assert first_slip["strategy_id"] is None
    assert second_slip["promoted"] is True
    assert second_slip["strategy_id"]
    assert search["hits"][0]["provenance"] == [captured["cid"]]
    assert profile["authoritative"][0]["statement"] == "Prefer stateless MCP calls backed by durable state."
    assert profile["support_strategies"][0]["id"] == second_slip["strategy_id"]
    assert profile["support_strategies"][0]["suggestion"] == "Offer to double-check deployment date math."

    denied_retire = reader.handle(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "profile_retire_support_strategy",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": "other-user",
                    "strategy_id": second_slip["strategy_id"],
                    "role": "operator",
                    "source_trust_tier": 0,
                },
            },
        }
    )
    retired = mcp_call(
        reader,
        "profile_retire_support_strategy",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "strategy_id": second_slip["strategy_id"],
            "role": "operator",
            "source_trust_tier": 0,
        },
    )
    reader.close()
    with MnemosyneMcpServer(store_path=store, stateless=True) as observer:
        after_retire = mcp_call(
            observer,
            "profile_context",
            {"tenant_id": TENANT, "user_id": USER, "scope": {"surface": "mcp"}},
        )

    assert denied_retire["result"]["isError"] is True
    assert "outside the requested tenant/user scope" in denied_retire["result"]["content"][0]["text"]
    assert retired["retired"] is True
    assert after_retire["support_strategies"] == []


def test_mcp_server_stateless_mode_reuses_warm_tools_for_same_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store.json"
    server = MnemosyneMcpServer(store_path=store, stateless=True)
    original_build_tools = server._build_tools
    build_calls: list[str | None] = []

    def counted_build_tools(queue_tenant: str | None = None):
        build_calls.append(queue_tenant)
        return original_build_tools(queue_tenant)

    monkeypatch.setattr(server, "_build_tools", counted_build_tools)

    first = mcp_call(server, "profile_context", {"tenant_id": TENANT, "user_id": USER})
    second = mcp_call(server, "profile_context", {"tenant_id": TENANT, "user_id": USER})
    mcp_call(server, "profile_context", {"tenant_id": "tenant-other", "user_id": USER})

    assert first == second
    assert build_calls == [TENANT, "tenant-other"]


def test_mcp_server_stateless_reader_rebuilds_after_close_and_sees_external_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store.json"
    reader = MnemosyneMcpServer(store_path=store, stateless=True)
    original_build_tools = reader._build_tools
    build_calls = 0

    def counted_build_tools(queue_tenant: str | None = None):
        nonlocal build_calls
        build_calls += 1
        return original_build_tools(queue_tenant)

    monkeypatch.setattr(reader, "_build_tools", counted_build_tools)

    query = {"tenant_id": TENANT, "query": "externally written warm bundle evidence"}
    assert mcp_call(reader, "search", query)["hits"] == []
    reader.close()
    with MnemosyneMcpServer(store_path=store, stateless=True) as external_writer:
        captured = mcp_call(
            external_writer,
            "capture",
            {
                "tenant_id": TENANT,
                "user_id": USER,
                "actor": "user",
                "source_type": "chat",
                "content": "Externally written warm bundle evidence.",
                "trust_tier": 3,
            },
        )
    refreshed = mcp_call(reader, "search", query)

    assert build_calls == 2
    assert refreshed["hits"][0]["provenance"] == [captured["cid"]]


def test_mcp_server_close_releases_cached_stateless_bundles_exactly_once(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server = MnemosyneMcpServer(store_path=store, stateless=True)
    mcp_call(
        server,
        "capture",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "chat",
            "content": "Warm bundle closed exactly once on facade close.",
            "trust_tier": 3,
        },
    )
    ((_stamp, bundle),) = server._stateless_tools_cache.values()
    engine = bundle[0]
    close_calls: list[int] = []
    original_close = engine.close

    def counting_close() -> None:
        close_calls.append(1)
        original_close()

    engine.close = counting_close
    server.close()
    server.close()

    assert close_calls == [1]
    assert server._stateless_tools_cache == {}
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.evidence


def test_mcp_server_stateful_close_is_idempotent_and_closes_engine_exactly_once(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server = MnemosyneMcpServer(store_path=store)
    close_calls: list[int] = []
    original_close = server.engine.close

    def counting_close() -> None:
        close_calls.append(1)
        original_close()

    server.engine.close = counting_close
    server.close()
    server.close()

    assert close_calls == [1]
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_close_bundle_releases_every_resource_when_one_closer_fails() -> None:
    closed: list[str] = []

    class FailingEngine:
        def close(self) -> None:
            closed.append("engine")
            raise RuntimeError("engine close failed")

    class ClosableQueue:
        def close(self) -> None:
            closed.append("queue")

    class ConnectionsOnlyRuntimeState:
        def close_connections(self) -> None:
            closed.append("runtime_state")

    with pytest.raises(RuntimeError, match="engine close failed"):
        MnemosyneMcpServer._close_bundle(
            (FailingEngine(), ClosableQueue(), ConnectionsOnlyRuntimeState(), None)
        )

    assert closed == ["engine", "queue", "runtime_state"]


def test_mcp_server_close_waits_for_in_flight_stateless_transaction(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server = MnemosyneMcpServer(store_path=store, stateless=True)
    mcp_call(server, "profile_context", {"tenant_id": TENANT, "user_id": USER})

    closer = threading.Thread(target=server.close)
    with server._stateless_transaction_lock:
        closer.start()
        closer.join(timeout=0.2)
        assert closer.is_alive(), "close() must wait for the in-flight stateless transaction"
    closer.join(timeout=5)
    assert not closer.is_alive()
    assert server._stateless_tools_cache == {}
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_http_server_build_failure_closes_facade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    close_calls: list[int] = []
    original_close = MnemosyneMcpServer.close

    def counting_close(self: MnemosyneMcpServer) -> None:
        close_calls.append(1)
        original_close(self)

    monkeypatch.setattr(MnemosyneMcpServer, "close", counting_close)
    blocker = socket.socket()
    try:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        with pytest.raises(OSError):
            build_http_server(
                host="127.0.0.1",
                port=blocker.getsockname()[1],
                store_path=tmp_path / "store.json",
            )
    finally:
        blocker.close()

    assert close_calls == [1]


def test_mcp_sdk_streamable_http_lifespan_closes_facade_on_exit(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    store = tmp_path / "streamable-lifespan-store.json"
    app = build_sdk_streamable_http_app(store_path=store, stateless=False)

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            with pytest.raises(RuntimeError, match="already has a writer"):
                LocalMemoryEngine(store_path=store)

    asyncio.run(exercise())
    # The app (and thus the SDK facade) is still referenced, so only the
    # lifespan's deterministic close can have released the writer.
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_http_server_close_bounded_despite_idle_connection(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    httpd = build_http_server(host="127.0.0.1", port=0, store_path=store)
    assert httpd.RequestHandlerClass.timeout is not None
    httpd.RequestHandlerClass.timeout = 1  # keep the bounded-join check fast
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    idle = socket.create_connection(("127.0.0.1", httpd.server_port))
    try:
        time.sleep(0.2)  # let a non-daemon handler thread block on the idle socket
        httpd.shutdown()
        thread.join(timeout=5)
        closer = threading.Thread(target=httpd.server_close, daemon=True)
        closer.start()
        closer.join(timeout=5)
        assert not closer.is_alive(), "server_close must not hang on an idle connection"
    finally:
        idle.close()
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_sdk_streamable_http_build_failure_closes_facade(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    store = tmp_path / "streamable-build-failure-store.json"
    with pytest.raises(ValueError, match="path must be non-empty"):
        build_sdk_streamable_http_app(streamable_http_path="", stateless=False, store_path=store)
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_server_build_tools_failure_releases_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MNEMOSYNE_POSTGRES_DSN", raising=False)
    store = tmp_path / "store.json"
    with pytest.raises(ValueError, match="queue backend requires"):
        MnemosyneMcpServer(store_path=store, queue_backend="postgres")
    # The engine claimed the writer before queue construction failed; the
    # partial bundle must be released without waiting for GC.
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_server_stateless_scope_replacement_closes_previous_bundle(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    with MnemosyneMcpServer(store_path=store, stateless=True) as server:
        mcp_call(server, "profile_context", {"tenant_id": TENANT, "user_id": USER})
        ((_stamp, first_bundle),) = server._stateless_tools_cache.values()
        first_engine = first_bundle[0]

        mcp_call(server, "profile_context", {"tenant_id": "tenant-other", "user_id": USER})

        assert len(server._stateless_tools_cache) == 1
        with pytest.raises(RuntimeError, match="does not own its writable store"):
            first_engine.append_evidence(
                Evidence(
                    tenant_id=TENANT,
                    user_id=USER,
                    actor="user",
                    source_type="chat",
                    content="Evicted bundle must not write the shared store.",
                    trust_tier=3,
                    access_policy={"tenant": TENANT},
                )
            )
        with pytest.raises(RuntimeError, match="already has a writer"):
            LocalMemoryEngine(store_path=store)
    with LocalMemoryEngine(store_path=store) as successor:
        assert successor.store_path == store


def test_mcp_server_persists_parametric_artifacts_and_rolls_back(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server = MnemosyneMcpServer(store_path=store)
    seed_grounded_gate_evidence(server.engine, "regression verify tools durable memory verify with tools")
    trajectory = mcp_call(
        server,
        "trajectory_record",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "session_id": "session-mcp",
            "task": "MCP parametric rollback",
            "steps": [{"name": "train", "status": "failed", "error": "regression"}],
            "outcome": "failure",
            "reward": -1.0,
            "memory_version": "v1",
        },
    )
    lesson = mcp_call(server, "lesson_propose", {"trajectory_id": trajectory["id"]})
    procedure = mcp_call(server, "procedure_propose", {"lesson_id": lesson["id"]})
    mcp_call(server, "procedure_validate", {"procedure_id": procedure["id"], **PARAMETRIC_AUTH})
    mcp_call(
        server,
        "lesson_promote",
        {
            "lesson_id": lesson["id"],
            "cases": [
                    {
                        "id": "mcp-parametric-case",
                        "signature": "MCP parametric rollback",
                        "query": "regression verify tools durable memory",
                        "expected_substring": "verify with tools",
                        "protected": True,
                    }
            ],
            **PARAMETRIC_AUTH,
        },
    )
    assert server.runtime_state is not None
    server.runtime_state.save_gate_cases(
        [
            RegressionCase(
                id="mcp-parametric-case",
                signature="MCP parametric rollback",
                query="regression verify tools durable memory",
                expected_substring="verify with tools",
                tier="core",
                protected=True,
                origin="curated",
            )
        ]
    )

    artifact = mcp_call(server, "parametric_propose", {"tenant_id": TENANT, **PARAMETRIC_AUTH})
    artifact_path = store.with_suffix(store.suffix + ".parametric") / TENANT / f"{artifact['id']}.json"
    proposal_record = json.loads(artifact_path.read_text(encoding="utf-8"))
    evaluated = mcp_call(
        server,
        "parametric_evaluate",
        {"artifact_uri": artifact["artifact_uri"], **PARAMETRIC_AUTH},
    )
    rolled_back = mcp_call(
        server,
        "parametric_rollback",
        {
            "artifact_uri": artifact["artifact_uri"],
            "reason": "protected regression after MCP proposal",
            **PARAMETRIC_AUTH,
        },
    )
    rollback_record = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert set(artifact["source_ids"]) == {lesson["id"], procedure["id"]}
    assert artifact["artifact_uri"].startswith("local-parametric://")
    assert proposal_record["payload"]["phase"] == "proposal"
    assert evaluated["artifact"]["id"] == artifact["id"]
    assert evaluated["promoted"] is True
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["rollback_ref"].startswith("rollback-")
    assert rollback_record["payload"]["phase"] == "rolled_back"


def test_mcp_server_parametric_tier_can_use_command_provider(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    command, provider_state = fake_parametric_command(tmp_path)
    server = MnemosyneMcpServer(
        store_path=store,
        parametric_provider="command",
        parametric_command=command,
        parametric_adapter_kind="test-time-command-adapter",
    )
    seed_grounded_gate_evidence(server.engine, "verify with tools durable memory")
    trajectory = mcp_call(
        server,
        "trajectory_record",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "session_id": "session-mcp-parametric-provider",
            "task": "MCP parametric provider",
            "steps": [{"name": "train", "status": "failed", "error": "provider"}],
            "outcome": "failure",
            "reward": -1.0,
            "memory_version": "v1",
        },
    )
    lesson = mcp_call(server, "lesson_propose", {"trajectory_id": trajectory["id"]})
    procedure = mcp_call(server, "procedure_propose", {"lesson_id": lesson["id"]})
    mcp_call(server, "procedure_validate", {"procedure_id": procedure["id"], **PARAMETRIC_AUTH})
    mcp_call(
        server,
        "lesson_promote",
        {
            "lesson_id": lesson["id"],
            "cases": [
                {
                    "id": "mcp-parametric-provider-case",
                    "signature": "MCP parametric provider",
                    "query": "verify with tools durable memory",
                    "expected_substring": "verify with tools",
                    "protected": True,
                }
            ],
            **PARAMETRIC_AUTH,
        },
    )

    artifact = mcp_call(server, "parametric_propose", {"tenant_id": TENANT, **PARAMETRIC_AUTH})
    artifact_path = store.with_suffix(store.suffix + ".parametric") / TENANT / f"{artifact['id']}.json"
    proposal_record = json.loads(artifact_path.read_text(encoding="utf-8"))
    rolled_back = mcp_call(
        server,
        "parametric_rollback",
        {"artifact_uri": artifact["artifact_uri"], "reason": "provider rollback smoke", **PARAMETRIC_AUTH},
    )
    rollback_record = json.loads(artifact_path.read_text(encoding="utf-8"))
    calls = json.loads(provider_state.read_text(encoding="utf-8"))["calls"]

    assert artifact["adapter_kind"] == "test-time-command-adapter"
    assert artifact["metrics"]["provider_invoked"] == 1.0
    assert artifact["metrics"]["source_count"] == 2.0
    assert proposal_record["payload"]["provider"]["artifact_ref"] == f"provider://{TENANT}/adapter"
    assert rolled_back["rollback_ref"] == f"provider-rollback-{artifact['id']}"
    assert rolled_back["metrics"]["provider_rolled_back"] == 1.0
    assert rolled_back["protected_suite"]["source"] == "synthetic"
    assert rolled_back["protected_suite"]["gating"] is False
    assert rolled_back["protected_suite"]["protected_case_ids"] == ["parametric-protected-0"]
    assert rolled_back["rollback"]["rollback_verified"] is False
    assert rolled_back["rollback"]["protected_suite_passed"] is False
    assert rollback_record["payload"]["provider"]["rollback_ref"] == f"provider-rollback-{artifact['id']}"
    assert rollback_record["payload"]["protected_suite"]["protected_case_ids"] == ["parametric-protected-0"]
    assert [call["action"] for call in calls] == ["propose", "rollback"]
    assert calls[-1]["protected_cases"] == ["parametric-protected-0"]
    assert calls[-1]["protected_suite"]["protected_case_count"] == 1


def test_mcp_parametric_provider_requires_operator_authority(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "mcp-store.json")

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "parametric_propose",
                "arguments": {"tenant_id": TENANT, "role": "agent", "source_trust_tier": 5},
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "policy and safety rails require operator authority" in response["result"]["content"][0]["text"]


def test_mcp_learning_activation_requires_mediated_authority(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "mcp-store.json")
    trajectory = mcp_call(
        server,
        "trajectory_record",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "session_id": "session-learning-authz",
            "task": "learning promotion authz",
            "steps": [{"name": "promote", "status": "failed", "error": "untrusted"}],
            "outcome": "failure",
            "reward": -1.0,
            "memory_version": "v1",
        },
    )
    lesson = mcp_call(server, "lesson_propose", {"trajectory_id": trajectory["id"]})
    procedure = mcp_call(server, "procedure_propose", {"lesson_id": lesson["id"]})
    low_trust = {"role": "agent", "source_trust_tier": 5}

    denied_calls = [
        (
            "lesson_promote",
            {
                "lesson_id": lesson["id"],
                "cases": [
                    {
                        "id": "case-learning-authz",
                        "signature": "learning promotion authz",
                        "query": "learning promotion authz",
                        "expected_substring": "verify with tools",
                        "protected": True,
                    }
                ],
                **low_trust,
            },
        ),
        ("procedure_validate", {"procedure_id": procedure["id"], **low_trust}),
        ("procedure_promote", {"procedure_id": procedure["id"], **low_trust}),
        ("procedure_rollback", {"procedure_id": procedure["id"], **low_trust}),
    ]

    for name, arguments in denied_calls:
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )

        assert response["result"]["isError"] is True
        assert "branch promotion requires operator/consolidator authority" in response["result"]["content"][0]["text"]

    assert server.tools.learning.lessons[lesson["id"]].status == "candidate"
    assert server.tools.learning.procedures[procedure["id"]].status == "candidate"


def test_mcp_server_requires_configured_auth_token_for_tool_calls(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json", auth_token="secret-token")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "capture",
            "arguments": {
                "tenant_id": TENANT,
                "user_id": USER,
                "actor": "user",
                "source_type": "chat",
                "content": "Authenticated MCP writes are accepted.",
            },
        },
    }

    denied = server.handle(request)
    request["params"]["_meta"] = {"auth_token": "secret-token"}
    allowed = server.handle(request)

    assert denied["result"]["isError"] is True
    assert "auth token required" in denied["result"]["content"][0]["text"]
    assert allowed["result"]["isError"] is False
    assert allowed["result"]["structuredContent"]["cid"]


def test_mcp_server_requires_signed_session_when_configured(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "chat",
                    "content": "Unsigned MCP writes must fail closed.",
                },
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "session token required" in response["result"]["content"][0]["text"]


def test_mcp_server_binds_signed_session_and_rejects_tenant_mismatch(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(role="agent", source_trust_tier=3)

    mismatch = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "session_token": token,
                    "tenant_id": "other-tenant",
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "chat",
                    "content": "Tenant mismatch must not be accepted.",
                },
            },
        }
    )
    captured = mcp_call(
        server,
        "capture",
        {
            "session_token": token,
            "actor": "user",
            "source_type": "chat",
            "content": "Signed sessions bind tenant and user for capture.",
        },
    )
    searched = mcp_call(server, "search", {"session_token": token, "query": "bind tenant and user"})

    assert mismatch["result"]["isError"] is True
    assert "session tenant mismatch" in mismatch["result"]["content"][0]["text"]
    assert captured["cid"]
    assert searched["hits"][0]["provenance"] == [captured["cid"]]


def test_mcp_cancel_binding_accepts_only_authenticated_user_or_agent(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json", session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(agent_id="owning-agent")

    def cancel(**overrides: Any) -> dict[str, Any]:
        arguments: dict[str, Any] = {"session_token": token, "intention_id": "missing-intention"}
        arguments.update(overrides)
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "cancel_intention", "arguments": arguments}})

    accepted_cases = (
        cancel(),
        cancel(cancelled_by=USER),
        cancel(cancelled_by="owning-agent"),
        cancel(cancelled_by=None),
        cancel(cancelled_by=""),
    )
    for accepted in accepted_cases:
        assert accepted["result"]["isError"] is True
        # An accepted principal must reach the engine and fail only on the
        # missing intention, proving no binding or principal denial fired.
        assert "missing-intention" in accepted["result"]["content"][0]["text"]
    foreign = cancel(cancelled_by="foreign-agent")
    assert "session cancellation principal mismatch" in foreign["result"]["content"][0]["text"]


def test_memory_tools_cancel_authorizes_user_owner_then_selected_agent() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    evidence_id = seed_grounded_gate_evidence(engine, "Cancel through owning agent.")
    due = dt.datetime(2026, 7, 18, 12, tzinfo=dt.timezone.utc)
    engine.schedule_intention(Intention(
        intention_id="agent-cancellable", tenant_id=TENANT, user_id=USER,
        agent_id="owning-agent", trigger_type="exact_time",
        trigger_expression={"at": due.isoformat()},
        action={"type": "remind", "message": "Agent cancellation."}, due_at=due,
        evidence_ids=[evidence_id], session_id="mcp-test-session",
    ))
    identity = SessionIdentity(
        tenant_id=TENANT, user_id=USER, agent_id="owning-agent", role="operator",
        source_trust_tier=0, session_id="mcp-test-session",
    )
    with pytest.raises(PermissionError, match="not authenticated"):
        tools.cancel_intention(TENANT, "agent-cancellable", "foreign-agent", session_identity=identity)
    cancelled = tools.cancel_intention(
        TENANT, "agent-cancellable", "owning-agent", session_identity=identity,
    )
    assert cancelled["cancellation_state"] == {"cancelled_by": "owning-agent"}


def test_memory_tools_cancel_agent_principal_cannot_reach_other_users() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    evidence_id = seed_grounded_gate_evidence(
        engine, "Agent principal stays user-scoped.", user_id="other-user"
    )
    due = dt.datetime(2026, 7, 18, 12, tzinfo=dt.timezone.utc)
    engine.schedule_intention(Intention(
        intention_id="other-users-intention", tenant_id=TENANT, user_id="other-user",
        agent_id="owning-agent", trigger_type="exact_time",
        trigger_expression={"at": due.isoformat()},
        action={"type": "remind", "message": "Other user's reminder."}, due_at=due,
        evidence_ids=[evidence_id],
    ))
    identity = SessionIdentity(
        tenant_id=TENANT, user_id=USER, agent_id="owning-agent", role="operator",
        source_trust_tier=0, session_id="mcp-test-session",
    )
    with pytest.raises(PermissionError, match="authenticated user's intentions"):
        tools.cancel_intention(
            TENANT, "other-users-intention", "owning-agent", session_identity=identity,
        )
    stored = next(
        intention for intention in engine.list_intentions(TENANT)
        if intention.intention_id == "other-users-intention"
    )
    assert stored.status == "scheduled"
    assert stored.session_id is None


def test_mcp_server_accepts_keyring_sessions_and_rejects_revoked_session_ids(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_keyring=json.dumps({"current": MCP_SESSION_SECRET}),
        session_key_id="current",
        session_revoked_ids="revoked-session",
        require_session=True,
    )
    allowed_token = SessionTokenVerifier({"current": MCP_SESSION_SECRET}, active_key_id="current").sign(
        SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=0,
            session_id="active-session",
        )
    )
    revoked_token = SessionTokenVerifier({"current": MCP_SESSION_SECRET}, active_key_id="current").sign(
        SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=0,
            session_id="revoked-session",
        )
    )

    allowed = mcp_call(
        server,
        "capture",
        {
            "session_token": allowed_token,
            "actor": "user",
            "source_type": "chat",
            "content": "Keyring MCP sessions authorize capture.",
        },
    )
    denied = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "session_token": revoked_token,
                    "actor": "user",
                    "source_type": "chat",
                    "content": "Revoked MCP sessions must fail.",
                },
            },
        }
    )

    assert allowed["cid"]
    assert denied["result"]["isError"] is True
    assert "session id is revoked" in denied["result"]["content"][0]["text"]


def test_mcp_server_session_overrides_self_asserted_authority(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(role="agent", source_trust_tier=5)

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "parametric_propose",
                "arguments": {
                    "session_token": token,
                    "tenant_id": TENANT,
                    "role": "operator",
                    "source_trust_tier": 0,
                },
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "policy and safety rails require operator authority" in response["result"]["content"][0]["text"]


def test_official_mcp_sdk_adapter_binds_signed_session_like_json_rpc(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp import types

    server = build_sdk_server(
        store_path=tmp_path / "sdk-session-store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(role="agent", source_trust_tier=3)

    async def exercise() -> None:
        call_handler = server.request_handlers[types.CallToolRequest]
        denied = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Unsigned SDK session call must fail.",
                    },
                }
            )
        )
        mismatch = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "session_token": token,
                        "tenant_id": "other-tenant",
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "SDK tenant mismatch must fail.",
                    },
                }
            )
        )
        captured = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "session_token": token,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "SDK signed sessions bind Mnemosyne memory.",
                    },
                }
            )
        )
        searched = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "search",
                    "arguments": {
                        "session_token": token,
                        "query": "SDK signed sessions",
                    },
                }
            )
        )

        assert denied.root.isError is True
        assert "session token required" in denied.root.content[0].text
        assert mismatch.root.isError is True
        assert "session tenant mismatch" in mismatch.root.content[0].text
        assert captured.root.isError is False
        assert captured.root.structuredContent["cid"]
        assert searched.root.isError is False
        assert searched.root.structuredContent["hits"][0]["provenance"] == [captured.root.structuredContent["cid"]]

    asyncio.run(exercise())


def test_caller_context_without_leakage_across_json_rpc_and_sdk(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp import types

    query = "transport-caller-context-needle"
    protected = f"{query} raw-secret-payload"
    agent_token = mcp_session_token(role="agent", source_trust_tier=0)
    reader_token = mcp_session_token(role="reader", source_trust_tier=0)
    server = MnemosyneMcpServer(
        store_path=tmp_path / "json-rpc-context.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    captured = mcp_call(
        server,
        "ingest",
        {
            "session_token": agent_token,
            "actor": "user",
            "source_type": "json-rpc-context",
            "content": protected,
            "sensitivity": 2,
        },
    )
    cid = captured["cid"]

    for name in ("search", "deep_search", "explain"):
        allowed = mcp_call(
            server,
            name,
            {"session_token": agent_token, "query": query, "max_sensitivity": 2},
        )
        assert any(hit["id"] == cid for hit in allowed["hits"])
        denied = mcp_call(server, name, {"session_token": reader_token, "query": query})
        encoded = json.dumps(denied, sort_keys=True)
        assert denied["hits"] == []
        assert protected not in encoded
        assert cid not in encoded
        assert denied["explain"]["gist_support"]["gist_hit_ids"] == []
        assert "denial" not in encoded
        assert "hidden" not in encoded

    mismatch = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "deep_search",
                "arguments": {
                    "session_token": agent_token,
                    "query": query,
                    "user_id": "other-user",
                },
            },
        }
    )
    assert mismatch["result"]["isError"] is True
    assert "session user mismatch" in mismatch["result"]["content"][0]["text"]

    sdk = build_sdk_server(
        store_path=tmp_path / "sdk-context.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )

    async def exercise() -> None:
        call = sdk.request_handlers[types.CallToolRequest]
        capture_result = await call(
            types.CallToolRequest(
                params={
                    "name": "ingest",
                    "arguments": {
                        "session_token": agent_token,
                        "actor": "user",
                        "source_type": "sdk-context",
                        "content": protected,
                        "sensitivity": 2,
                    },
                }
            )
        )
        sdk_cid = capture_result.root.structuredContent["cid"]
        for name in ("search", "deep_search", "explain"):
            allowed = await call(
                types.CallToolRequest(
                    params={
                        "name": name,
                        "arguments": {
                            "session_token": agent_token,
                            "query": query,
                            "max_sensitivity": 2,
                        },
                    }
                )
            )
            assert any(hit["id"] == sdk_cid for hit in allowed.root.structuredContent["hits"])
            denied = await call(
                types.CallToolRequest(
                    params={"name": name, "arguments": {"session_token": reader_token, "query": query}}
                )
            )
            encoded = json.dumps(denied.root.structuredContent, sort_keys=True)
            assert denied.root.isError is False
            assert denied.root.structuredContent["hits"] == []
            assert protected not in encoded
            assert sdk_cid not in encoded
            assert denied.root.structuredContent["explain"]["gist_support"]["gist_hit_ids"] == []
            assert "denial" not in encoded
            assert "hidden" not in encoded

    asyncio.run(exercise())


def test_mcp_server_postgres_backend_requires_dsn(monkeypatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_POSTGRES_DSN", raising=False)

    try:
        MnemosyneMcpServer(backend="postgres")
    except ValueError as exc:
        assert "Postgres MCP backend requires" in str(exc)
    else:  # pragma: no cover - defensive assertion clarity.
        raise AssertionError("postgres MCP backend should require a DSN")


def test_mcp_server_suppresses_initialized_notification_and_frames_stdio(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    incoming = StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"missing","arguments":{}}}\n'
    )
    outgoing = StringIO()

    server.serve(incoming, outgoing)
    lines = [line for line in outgoing.getvalue().splitlines() if line.strip()]

    assert len(lines) == 2
    assert '"id":1' in lines[0]
    assert '"id":2' in lines[1]
    assert '"isError":true' in lines[1]


def test_pyproject_exposes_mcp_script_and_postgres_extra() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["mneme-mcp"] == "mnemosyne.mcp_server:main"
    assert "psycopg[binary]>=3.2" in project["project"]["optional-dependencies"]["postgres"]


def test_worker_run_heartbeat_mount_is_public_runtime_scoped() -> None:
    import mnemosyne.cli as cli

    source = inspect.getsource(cli.cmd_worker_run)
    assert "_runtime_workspace_service" in source
    assert "workspace_heartbeat" in source
    assert "cmd_worker_run" not in inspect.getsource(MnemosyneMcpServer)


def test_postgres_cid_helpers_and_audit_uuid_guard() -> None:
    cid = "28e581ee79af77abbdfc97e1d9c9c65a7970bbb7bc06858280303c01c70847de"

    assert _bytes_to_cid(_cid_to_bytes(cid)) == cid
    assert _uuid_or_none("019ee1ba-9d93-7ca1-bde5-0afa93e73e98") == "019ee1ba-9d93-7ca1-bde5-0afa93e73e98"
    assert _uuid_or_none(cid) is None
    assert _stable_uuid("tenant", "tenant-a") == _stable_uuid("tenant", "tenant-a")
    assert _stable_uuid("tenant", "tenant-a") != _stable_uuid("tenant", "tenant-b")
    assert _vector_literal([0.25, -0.5, 1.0]) == "[0.25,-0.5,1]"


def test_postgres_adapter_uses_sql_retrieval_backends() -> None:
    source = inspect.getsource(PostgresEngine)

    assert "plainto_tsquery('english'" in source
    assert "embedding <=> %s::vector" in source
    assert "postgres_graph_ppr" in source
    assert "return []" not in inspect.getsource(PostgresEngine.vector_search)
    assert "del seeds" not in inspect.getsource(PostgresEngine.graph_ppr)
    assert "FROM relations" in inspect.getsource(PostgresEngine.graph_ppr)


def test_postgres_adapter_sets_rls_tenant_context() -> None:
    source = inspect.getsource(PostgresEngine)

    assert "set_config('mnemosyne.tenant_id'" in source
    assert "PostgresEngine.branch requires tenant_id" in source
    assert "PostgresEngine.merge requires tenant_id" in source
    assert "PostgresEngine.discard requires tenant_id" in source


def test_postgres_merge_replays_clones_without_moving_source_rows() -> None:
    source = inspect.getsource(PostgresEngine.merge)

    assert "UPDATE assertions src" not in source
    assert "UPDATE relations SET branch" not in source
    assert "_upsert_assertion_with_cursor" in source
    assert "INSERT INTO relations" in source
    assert "gen_random_uuid()" in source
    assert "_merge_clone_assertion_id" in source
    assert "actual_assertion_ids" in source


def test_postgres_engine_exposes_memory_tools_runtime_surface() -> None:
    required = {
        "retrieve",
        "deep_search",
        "explain",
        "correct",
        "forget",
        "export_tenant",
        "branch",
        "merge",
        "discard",
    }

    assert required <= set(dir(PostgresEngine))
