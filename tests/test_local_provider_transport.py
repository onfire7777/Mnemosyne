"""Exercise discovered adapters over owned sockets, never personal services."""

from __future__ import annotations

import json
import os
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from mnemosyne.cli import build_parser, load_retrieval_adapters
from mnemosyne.models import Hit
from mnemosyne.retrieval import HttpEmbeddingProvider, HttpReranker


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("MNEMOSYNE_") or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name)


@pytest.fixture
def service_factory():
    servers = []

    def start(*, tls_context=None):
        state = SimpleNamespace(requests=[], redirect=None, redirect_status=302, batch_status=200)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                pass

            def respond(self, payload, status=200, redirect=None):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if redirect:
                    self.send_header("Location", redirect)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                state.requests.append(("GET", self.path, None))
                self.respond({
                    "status": "ok",
                    "embedding": {"model": "fixture-embedding", "dimensions": 3,
                                  "backend": "sentence-transformers"},
                    "reranker": {"model": "fixture-reranker", "backend": "cross-encoder"},
                })

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                state.requests.append(("POST", self.path, payload))
                if state.redirect:
                    self.respond({}, state.redirect_status, state.redirect)
                elif urlsplit(self.path).path == "/v1/embeddings":
                    if isinstance(payload["input"], list):
                        self.respond({"data": [
                            {"index": i, "embedding": [1.0, 0.0, 0.0]}
                            for i, _ in enumerate(payload["input"])
                        ]}, state.batch_status)
                    else:
                        self.respond({"embedding": [1.0, 0.0, 0.0]})
                else:
                    self.respond({"results": [{"index": 0, "score": 4.0}]})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if tls_context is not None:
            server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        servers.append((server, thread))
        scheme = "https" if tls_context is not None else "http"
        state.url = f"{scheme}://127.0.0.1:{server.server_address[1]}"
        return state

    try:
        yield start
    finally:
        for server, thread in reversed(servers):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def cli_adapters(service, monkeypatch, tmp_path, *, read_only=False, host="127.0.0.1", kind="auto"):
    url = service.url.replace("127.0.0.1", host)
    monkeypatch.setenv("MNEMOSYNE_LOCAL_EMBEDDING_URL", url + "/v1/embeddings")
    monkeypatch.setenv("MNEMOSYNE_LOCAL_RERANKER_URL", url + "/rerank")
    args = build_parser().parse_args([
        "--embedding-provider", kind, "--reranker-provider", kind,
        "--embedding-url", url + "/v1/embeddings", "--reranker-url", url + "/rerank",
        "--embedding-dims", "3", "--embedding-cache-size", "7",
        "--embedding-cache-path", str(tmp_path / "embedding-cache.sqlite"),
        "--embedding-cache-scope", str(tmp_path), "--retrieval-timeout", "2",
        "search", "--tenant", "fixture", "--query", "fixture",
    ])
    args.evaluation_read_only = read_only
    adapters = load_retrieval_adapters(args)
    assert isinstance(adapters.embedding, HttpEmbeddingProvider)
    assert isinstance(adapters.reranker, HttpReranker)
    assert adapters.embedding.cache_size == (0 if read_only else 7)
    assert adapters.embedding.cache_path == (None if read_only else str(tmp_path / "embedding-cache.sqlite"))
    return adapters


def infer(adapters, operation):
    if operation == "rerank":
        hit = Hit(id="fixture", kind="evidence", tenant_id="fixture", branch="main",
                  text="private fixture document", score=0.1, channel="dense")
        ranked = adapters.reranker.rerank("private fixture query", [hit], k=1)
        assert [item.id for item in ranked] == ["fixture"]
    elif operation == "embed_many":
        assert adapters.embedding.embed_many(["private fixture one", "private fixture two"]) == [
            [1.0, 0.0, 0.0], [1.0, 0.0, 0.0],
        ]
    else:
        assert getattr(adapters.embedding, operation)("private fixture text") == [1.0, 0.0, 0.0]


@pytest.mark.parametrize("operation", ["embed", "embed_sensitive", "embed_many", "rerank"])
@pytest.mark.parametrize("read_only", [False, True])
def test_cli_auto_inference_bypasses_environment_proxy(service_factory, monkeypatch, tmp_path, operation, read_only):
    service, proxy = service_factory(), service_factory()
    monkeypatch.setenv("http_proxy", proxy.url)
    monkeypatch.setenv("no_proxy", "")
    before = dict(os.environ)
    adapters = cli_adapters(service, monkeypatch, tmp_path, read_only=read_only)
    assert service.requests == [("GET", "/health", None)] * 2
    infer(adapters, operation)
    assert proxy.requests == [], "inference leaked fixture text to an unprobed proxy"
    assert service.requests[-1][0] == "POST"
    # The runtime must not mutate proxy policy to make local inference work.
    assert {key: os.environ[key] for key in ("http_proxy", "no_proxy")} == {
        key: before[key] for key in ("http_proxy", "no_proxy")
    }


@pytest.mark.parametrize("operation", ["embed", "embed_sensitive", "embed_many", "rerank"])
@pytest.mark.parametrize("addresses", [("8.8.8.8",), ("192.168.1.10",), ("127.0.0.1", "8.8.8.8")])
def test_cli_auto_rejects_nonloopback_dns_after_discovery(service_factory, monkeypatch, tmp_path, operation, addresses):
    service = service_factory()
    original = socket.getaddrinfo
    resolved = ["127.0.0.1"]

    def lookup(host, port, *args, **kwargs):
        if host == "localhost":
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)) for ip in resolved]
        assert host == "127.0.0.1", "unexpected DNS lookup"
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    adapters = cli_adapters(service, monkeypatch, tmp_path, host="localhost")
    assert service.requests == [("GET", "/health", None)] * 2
    # Operator allowlists for explicit HTTP must not widen an auto adapter.
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_ALLOWED_INTERNAL_HOSTS", "localhost")
    resolved[:] = addresses

    def no_connect(*args, **kwargs):
        pytest.fail("rebound inference reached a socket; no remote connection was made")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    with pytest.raises(ValueError, match="loopback"):
        infer(adapters, operation)
    assert service.requests == [("GET", "/health", None)] * 2


@pytest.mark.parametrize("operation", ["embed", "embed_sensitive", "embed_many", "rerank"])
def test_explicit_http_keeps_environment_proxy_behavior(service_factory, monkeypatch, tmp_path, operation):
    service, proxy = service_factory(), service_factory()
    monkeypatch.setenv("http_proxy", proxy.url)
    monkeypatch.setenv("no_proxy", "")
    adapters = cli_adapters(service, monkeypatch, tmp_path, kind="http")
    assert isinstance(adapters.embedding, HttpEmbeddingProvider)
    assert isinstance(adapters.reranker, HttpReranker)
    assert not adapters.embedding.loopback_only
    assert not adapters.reranker.loopback_only
    infer(adapters, operation)
    assert service.requests == []
    assert len(proxy.requests) == 1
    assert proxy.requests[0][0] == "POST"
    assert proxy.requests[0][1].startswith(service.url + "/")


@pytest.mark.parametrize("operation", ["embed", "embed_sensitive", "embed_many", "rerank"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("target", ["same-origin", "other-service", "external"])
def test_auto_inference_never_follows_redirects(service_factory, monkeypatch, tmp_path, operation, status, target):
    service, other = service_factory(), service_factory()
    adapters = cli_adapters(service, monkeypatch, tmp_path)
    service.redirect = {
        "same-origin": service.url + "/redirected",
        "other-service": other.url + "/redirected",
        "external": "https://must-not-resolve.invalid/redirected",
    }[target]
    service.redirect_status = status
    original = socket.getaddrinfo

    def only_fixture(host, *args, **kwargs):
        assert host == "127.0.0.1", "redirect target reached DNS"
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", only_fixture)
    with pytest.raises(ValueError, match=f"provider returned HTTP {status}"):
        infer(adapters, operation)
    assert other.requests == []
    assert [path for method, path, _ in service.requests if method == "POST"] == [
        "/rerank" if operation == "rerank" else "/v1/embeddings"
    ]
    assert [path for method, path, _ in service.requests if method == "GET"] == ["/health"] * 2


def test_auto_batch_fallback_keeps_local_transport(service_factory, monkeypatch, tmp_path):
    service, proxy = service_factory(), service_factory()
    service.batch_status = 400
    monkeypatch.setenv("HTTP_PROXY", proxy.url)
    monkeypatch.setenv("NO_PROXY", "")
    adapters = cli_adapters(service, monkeypatch, tmp_path)
    infer(adapters, "embed_many")
    assert proxy.requests == []
    assert [payload["input"] for method, _, payload in service.requests if method == "POST"] == [
        ["private fixture one", "private fixture two"], "private fixture one", "private fixture two",
    ]


@pytest.mark.parametrize("operation", ["embed", "embed_sensitive", "embed_many", "rerank"])
def test_inference_pins_checked_localhost_address(service_factory, monkeypatch, tmp_path, operation):
    service = service_factory()
    adapters = cli_adapters(service, monkeypatch, tmp_path, host="localhost", read_only=True)
    original_lookup, original_connect = socket.getaddrinfo, socket.socket.connect
    lookups = []
    connections = []

    def rebind_after_validation(host, port, *args, **kwargs):
        if host == "localhost":
            lookups.append(host)
            address = "127.0.0.1" if len(lookups) == 1 else "8.8.8.8"
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]
        assert host == "127.0.0.1", "inference tried to resolve an unvalidated address"
        return original_lookup(host, port, *args, **kwargs)

    def only_service(sock, address):
        assert address == ("127.0.0.1", urlsplit(service.url).port)
        connections.append(address)
        return original_connect(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", rebind_after_validation)
    monkeypatch.setattr(socket.socket, "connect", only_service)
    infer(adapters, operation)
    assert lookups == ["localhost"]
    assert len(connections) == 1
    # The next POST must resolve again, then reject the rebound address before I/O.
    with pytest.raises(ValueError, match="loopback"):
        infer(adapters, operation)
    assert len(connections) == 1


def test_env_factory_inference_keeps_local_transport(service_factory, monkeypatch):
    from mnemosyne.retrieval import retrieval_adapters_from_env

    service, proxy = service_factory(), service_factory()
    monkeypatch.setenv("MNEMOSYNE_EMBEDDING_PROVIDER", "auto")
    monkeypatch.setenv("MNEMOSYNE_RERANKER_PROVIDER", "auto")
    monkeypatch.setenv("MNEMOSYNE_LOCAL_EMBEDDING_URL", service.url + "/v1/embeddings")
    monkeypatch.setenv("MNEMOSYNE_LOCAL_RERANKER_URL", service.url + "/rerank")
    monkeypatch.setenv("http_proxy", proxy.url)
    monkeypatch.setenv("no_proxy", "")
    adapters = retrieval_adapters_from_env()
    infer(adapters, "embed_sensitive")
    infer(adapters, "rerank")
    assert proxy.requests == []
    assert [method for method, _, _ in service.requests] == ["GET", "GET", "POST", "POST"]


@pytest.fixture
def tls_service(service_factory, monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta
    from ipaddress import ip_address

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"), x509.IPAddress(ip_address("127.0.0.1")),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "fixture-cert.pem", tmp_path / "fixture-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(cert_path))
    return service_factory(tls_context=context)


@pytest.mark.parametrize("operation", ["embed", "embed_sensitive", "embed_many", "rerank"])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_https_auto_inference_bypasses_proxy(tls_service, service_factory, monkeypatch, tmp_path, operation, host):
    proxy = service_factory()
    monkeypatch.setenv("https_proxy", proxy.url)
    monkeypatch.setenv("no_proxy", "")
    adapters = cli_adapters(tls_service, monkeypatch, tmp_path, host=host)
    infer(adapters, operation)
    assert proxy.requests == []
    assert [method for method, _, _ in tls_service.requests] == ["GET", "GET", "POST"]


@pytest.mark.parametrize("operation", ["embed_sensitive", "rerank"])
def test_https_inference_still_verifies_certificate(tls_service, monkeypatch, tmp_path, operation):
    adapters = cli_adapters(tls_service, monkeypatch, tmp_path, host="localhost")
    monkeypatch.delenv("SSL_CERT_FILE")
    with pytest.raises(ValueError, match="CERTIFICATE_VERIFY_FAILED"):
        infer(adapters, operation)
    assert tls_service.requests == [("GET", "/health", None)] * 2
