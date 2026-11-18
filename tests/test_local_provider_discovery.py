"""Opt-in local discovery contracts; every HTTP call uses an owned test server."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from mnemosyne.quantized_vectors import discover_local_embedding_provider, discover_local_reranker
from mnemosyne.retrieval import (
    HashingEmbeddingProvider,
    HttpEmbeddingProvider,
    HttpReranker,
    LocalSimilarityReranker,
)


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    # Never inherit a developer's models, endpoints, cache paths, or credentials.
    for name in tuple(os.environ):
        if name.startswith("MNEMOSYNE_") or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name)


@pytest.fixture
def local_service(monkeypatch):
    state = SimpleNamespace(
        health={
            "status": "ok",
            "embedding": {
                "model": "fixture-embedding",
                "dimensions": 3,
                "backend": "sentence-transformers",
            },
            "reranker": {"model": "fixture-reranker", "backend": "cross-encoder"},
        },
        status=200,
        content_type="application/json",
        redirect=None,
        raw_body=None,
        requests=[],
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            pass

        def do_GET(self):
            state.requests.append(("GET", self.path, None))
            body = state.raw_body if state.raw_body is not None else json.dumps(state.health).encode()
            redirect = state.redirect if self.path == "/health" else None
            self.send_response(302 if redirect else state.status)
            if redirect:
                self.send_header("Location", redirect)
            self.send_header("Content-Type", state.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append(("POST", self.path, payload))
            if self.path == "/v1/embeddings":
                response = {"embedding": [1.0, 0.0, 0.0]}
            else:
                response = {"results": [{"index": 0, "score": 4.0}]}
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("MNEMOSYNE_LOCAL_EMBEDDING_URL", state.url + "/v1/embeddings")
    monkeypatch.setenv("MNEMOSYNE_LOCAL_RERANKER_URL", state.url + "/rerank")
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_embedding_uses_health_dimensions_and_model_without_padding(local_service, monkeypatch):
    monkeypatch.setenv("MNEMOSYNE_EMBEDDING_DIMS", "1024")
    monkeypatch.setenv("MNEMOSYNE_EMBEDDING_MODEL", "unrelated-environment-model")
    provider = discover_local_embedding_provider(allow_inprocess_onnx=False)
    assert isinstance(provider, HttpEmbeddingProvider)
    assert provider.dims == 3
    assert provider.model == "fixture-embedding"
    # Discovery itself sends no text to the service.
    assert local_service.requests == [("GET", "/health", None)]
    monkeypatch.setenv("MNEMOSYNE_ALLOWED_INTERNAL_HOSTS", "127.0.0.1")
    assert provider.embed_sensitive("owned fixture text") == [1.0, 0.0, 0.0]
    assert local_service.requests[-1] == (
        "POST", "/v1/embeddings", {"input": "owned fixture text", "model": "fixture-embedding"}
    )


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
@pytest.mark.parametrize(
    "metadata",
    [None, {}, "healthy", {"model": "fixture", "backend": "fallback", "dimensions": 3},
     {"model": "fixture", "backend": "uninitialized", "dimensions": 3},
     {"model": "fixture", "backend": "unknown", "dimensions": 3},
     {"model": "fixture", "dimensions": 3}],
)
def test_only_explicit_semantic_capabilities_are_discovered(local_service, kind, metadata):
    local_service.health = {"status": "ok", kind: metadata}
    if kind == "embedding":
        provider = discover_local_embedding_provider(default_dims=7, allow_inprocess_onnx=False)
        assert isinstance(provider, HashingEmbeddingProvider)
        assert provider.dims == 7
    else:
        embedding = HashingEmbeddingProvider(dims=7)
        provider = discover_local_reranker(fallback_embedding=embedding)
        assert isinstance(provider, LocalSimilarityReranker)
        assert provider.embedding_provider is embedding


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
@pytest.mark.parametrize("model", [None, "", "   ", 17, True, [], {}])
def test_model_identity_must_be_a_nonempty_string(local_service, kind, model):
    local_service.health[kind]["model"] = model
    if kind == "embedding":
        provider = discover_local_embedding_provider(allow_inprocess_onnx=False)
        assert isinstance(provider, HashingEmbeddingProvider)
    else:
        assert isinstance(discover_local_reranker(), LocalSimilarityReranker)


@pytest.mark.parametrize("dimensions", [None, 0, -1, True, "3", "nonsense", 3.5, [], {}])
def test_invalid_dimensions_fall_back_without_coercion(local_service, monkeypatch, dimensions):
    local_service.health["embedding"]["dimensions"] = dimensions
    # An unrelated explicit-http configuration must not mask invalid health data.
    monkeypatch.setenv("MNEMOSYNE_EMBEDDING_DIMS", "1024")
    provider = discover_local_embedding_provider(default_dims=7, allow_inprocess_onnx=False)
    assert isinstance(provider, HashingEmbeddingProvider)
    assert provider.dims == 7


def test_conflicting_dimension_aliases_are_rejected(local_service):
    local_service.health["embedding"]["dims"] = 5
    assert isinstance(
        discover_local_embedding_provider(allow_inprocess_onnx=False), HashingEmbeddingProvider
    )


@pytest.mark.parametrize("off_host", [False, True])
def test_health_redirects_are_never_followed(local_service, off_host):
    target = local_service.url.replace("127.0.0.1", "localhost") if off_host else local_service.url
    local_service.redirect = target + "/redirected"
    assert isinstance(
        discover_local_embedding_provider(allow_inprocess_onnx=False), HashingEmbeddingProvider
    )
    assert isinstance(discover_local_reranker(), LocalSimilarityReranker)
    assert local_service.requests == [("GET", "/health", None)] * 2


@pytest.mark.parametrize("failure", ["oversized", "html", "bad-json", "not-object", "unhealthy", "http-error"])
def test_unusable_health_responses_fall_back(local_service, failure):
    if failure == "oversized":
        local_service.health["padding"] = "x" * 65536
    elif failure == "html":
        local_service.content_type = "text/html"
    elif failure == "bad-json":
        local_service.raw_body = b"not json"
    elif failure == "not-object":
        local_service.health = []
    elif failure == "unhealthy":
        local_service.health["status"] = "loading"
    else:
        local_service.status = 503
    assert isinstance(
        discover_local_embedding_provider(allow_inprocess_onnx=False), HashingEmbeddingProvider
    )
    assert isinstance(discover_local_reranker(), LocalSimilarityReranker)


@pytest.mark.parametrize("url", [
    "http://[invalid", "http://127.0.0.1:99999/embed", "http://127.0.0.1:abc/embed",
    "http://127.0.0.1:0/embed", "http://user:pass@127.0.0.1/embed",
    "https://public.invalid/embed", "http://192.168.1.1/embed", "file:///health", "",
])
def test_invalid_or_nonloopback_urls_fail_closed_without_io(monkeypatch, url):
    import socket

    def no_dns(*args, **kwargs):
        pytest.fail("invalid discovery endpoint reached DNS/network")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    monkeypatch.setenv("MNEMOSYNE_LOCAL_EMBEDDING_URL", url)
    monkeypatch.setenv("MNEMOSYNE_LOCAL_RERANKER_URL", url)
    assert isinstance(
        discover_local_embedding_provider(allow_inprocess_onnx=False), HashingEmbeddingProvider
    )
    assert isinstance(discover_local_reranker(), LocalSimilarityReranker)


def test_endpoint_is_validated_before_health_path_is_derived(local_service, monkeypatch):
    for suffix in ("#fragment", "\n", "\t"):
        monkeypatch.setenv("MNEMOSYNE_LOCAL_EMBEDDING_URL", local_service.url + "/embed" + suffix)
        assert isinstance(
            discover_local_embedding_provider(allow_inprocess_onnx=False), HashingEmbeddingProvider
        )
    assert local_service.requests == []


def test_discovered_model_identity_changes_with_model(local_service):
    first = discover_local_embedding_provider(allow_inprocess_onnx=False)
    local_service.health["embedding"]["model"] = "different-fixture-model"
    second = discover_local_embedding_provider(allow_inprocess_onnx=False)
    assert first.name != second.name
    assert first.model == "fixture-embedding"
    assert second.model == "different-fixture-model"


def test_discovery_bypasses_environment_proxy(local_service, monkeypatch):
    monkeypatch.setenv("http_proxy", local_service.url)
    monkeypatch.setenv("no_proxy", "")
    provider = discover_local_embedding_provider(allow_inprocess_onnx=False)
    assert isinstance(provider, HttpEmbeddingProvider)
    assert local_service.requests == [("GET", "/health", None)]


def test_legacy_dims_health_field_is_supported(local_service):
    metadata = local_service.health["embedding"]
    metadata["dims"] = metadata.pop("dimensions")
    provider = discover_local_embedding_provider(allow_inprocess_onnx=False)
    assert isinstance(provider, HttpEmbeddingProvider)
    assert provider.dims == 3


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_probe_timeout_never_reaches_network(local_service, monkeypatch, timeout):
    def no_dns(*args, **kwargs):
        pytest.fail("invalid timeout reached network")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    assert isinstance(discover_local_embedding_provider(
        allow_inprocess_onnx=False, probe_timeout_seconds=timeout
    ), HashingEmbeddingProvider)
    assert isinstance(discover_local_reranker(probe_timeout_seconds=timeout), LocalSimilarityReranker)


@pytest.mark.parametrize("sample", [[], [0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0], [[1.0]]])
def test_invalid_cached_model_probe_falls_back_without_downloads(monkeypatch, sample):
    calls = []

    class CachedModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed(self, texts):
            assert texts == ["probe"]
            return [sample]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=CachedModel))
    monkeypatch.setenv("MNEMOSYNE_FASTEMBED_MODEL", "fixture-cached-model")
    provider = discover_local_embedding_provider(default_dims=7, allow_loopback_http=False)
    assert isinstance(provider, HashingEmbeddingProvider)
    assert provider.dims == 7
    assert calls == [{"model_name": "fixture-cached-model", "local_files_only": True}]


def test_nonloopback_resolution_of_localhost_is_rejected(local_service, monkeypatch):
    def resolved_elsewhere(host, port, *args, **kwargs):
        assert host == "localhost"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))]

    def no_connect(*args, **kwargs):
        pytest.fail("discovery attempted a nonloopback connection")

    monkeypatch.setenv("MNEMOSYNE_LOCAL_EMBEDDING_URL", local_service.url.replace("127.0.0.1", "localhost"))
    monkeypatch.setattr(socket, "getaddrinfo", resolved_elsewhere)
    monkeypatch.setattr(socket, "create_connection", no_connect)
    assert isinstance(discover_local_embedding_provider(allow_inprocess_onnx=False), HashingEmbeddingProvider)
    assert local_service.requests == []


def test_redirect_to_external_hostname_is_not_even_resolved(local_service, monkeypatch):
    original = socket.getaddrinfo

    def only_fixture(host, *args, **kwargs):
        assert host == "127.0.0.1", "redirect escaped the original loopback endpoint"
        return original(host, *args, **kwargs)

    local_service.redirect = "https://must-not-resolve.invalid/health"
    monkeypatch.setattr(socket, "getaddrinfo", only_fixture)
    assert isinstance(discover_local_embedding_provider(allow_inprocess_onnx=False), HashingEmbeddingProvider)
    assert local_service.requests == [("GET", "/health", None)]


def test_cached_fastembed_model_is_local_only_and_takes_precedence(local_service, monkeypatch):
    from mnemosyne.quantized_vectors import FastEmbedLocalProvider

    calls = []

    class CachedModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=CachedModel))
    monkeypatch.setenv("MNEMOSYNE_FASTEMBED_MODEL", "fixture-cached-model")
    provider = discover_local_embedding_provider()
    assert isinstance(provider, FastEmbedLocalProvider)
    assert provider.dims == 2
    assert provider.name == "fastembed:fixture-cached-model"
    assert provider.embed("owned fixture") == [1.0, 0.0]
    assert calls == [{"model_name": "fixture-cached-model", "local_files_only": True}]
    assert local_service.requests == []


def test_missing_cached_model_falls_through_without_retrying_download(local_service, monkeypatch):
    calls = []

    def unavailable(**kwargs):
        calls.append(kwargs)
        raise FileNotFoundError("fixture model is not cached")

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=unavailable))
    monkeypatch.setenv("MNEMOSYNE_FASTEMBED_MODEL", "fixture-not-cached")
    provider = discover_local_embedding_provider()
    assert isinstance(provider, HttpEmbeddingProvider)
    assert calls == [{"model_name": "fixture-not-cached", "local_files_only": True}]
    assert local_service.requests == [("GET", "/health", None)]


def test_discovery_does_not_widen_normal_http_provider_policy(local_service, monkeypatch):
    before = dict(os.environ)
    assert isinstance(discover_local_embedding_provider(allow_inprocess_onnx=False), HttpEmbeddingProvider)
    assert dict(os.environ) == before
    with pytest.raises(ValueError, match="requires https"):
        HttpEmbeddingProvider(url="http://169.254.169.254/embeddings").embed_sensitive("must-not-leave")
    assert local_service.requests == [("GET", "/health", None)]


def _cli_args(*flags):
    from mnemosyne.cli import build_parser

    return build_parser().parse_args([*flags, "search", "--tenant", "fixture", "--query", "fixture"])


@pytest.mark.parametrize("flag", ["--embedding-provider", "--reranker-provider"])
def test_cli_accepts_explicit_auto_flags(flag):
    args = _cli_args(flag, "auto")
    assert getattr(args, flag.removeprefix("--").replace("-", "_")) == "auto"


def test_default_factories_stay_offline_even_with_discoverable_service(local_service, monkeypatch):
    from mnemosyne.cli import load_retrieval_adapters
    from mnemosyne.retrieval import retrieval_adapters_from_env

    class ForbiddenModel:
        def __init__(self, **kwargs):
            pytest.fail("default local provider attempted to load a semantic model")

    monkeypatch.setenv("MNEMOSYNE_FASTEMBED_MODEL", "must-not-load-without-auto")
    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=ForbiddenModel))
    args = _cli_args()
    assert args.embedding_provider == args.reranker_provider == "local"
    for adapters in (load_retrieval_adapters(args), retrieval_adapters_from_env()):
        assert isinstance(adapters.embedding, HashingEmbeddingProvider)
        assert adapters.embedding.dims == 1024
        assert isinstance(adapters.reranker, LocalSimilarityReranker)
        assert adapters.reranker.embedding_provider is adapters.embedding
        assert adapters.embedding.embed("fixture") == HashingEmbeddingProvider(dims=1024).embed("fixture")
    assert local_service.requests == []


@pytest.mark.parametrize("factory", ["cli", "env"])
@pytest.mark.parametrize("embedding_kind,reranker_kind", [("auto", "auto"), ("auto", "local"), ("local", "auto")])
def test_auto_selection_reaches_actual_factory(local_service, monkeypatch, factory, embedding_kind, reranker_kind):
    from mnemosyne.cli import load_retrieval_adapters
    from mnemosyne.models import Hit
    from mnemosyne.retrieval import retrieval_adapters_from_env

    if factory == "cli":
        args = _cli_args("--embedding-provider", embedding_kind, "--reranker-provider", reranker_kind)
        adapters = load_retrieval_adapters(args)
    else:
        monkeypatch.setenv("MNEMOSYNE_EMBEDDING_PROVIDER", embedding_kind)
        monkeypatch.setenv("MNEMOSYNE_RERANKER_PROVIDER", reranker_kind)
        adapters = retrieval_adapters_from_env()
    if embedding_kind == "auto":
        assert isinstance(adapters.embedding, HttpEmbeddingProvider)
        assert adapters.embedding.dims == 3
        assert adapters.embedding.model == "fixture-embedding"
        assert adapters.embedding.embed_sensitive("fixture") == [1.0, 0.0, 0.0]
    else:
        assert isinstance(adapters.embedding, HashingEmbeddingProvider)
        assert adapters.embedding.dims == 1024
    if reranker_kind == "auto":
        assert isinstance(adapters.reranker, HttpReranker)
        assert adapters.reranker.model == "fixture-reranker"
        hit = Hit(id="fixture", kind="evidence", tenant_id="fixture", branch="main",
                  text="fixture", score=0.1, channel="dense")
        ranked = adapters.reranker.rerank("fixture query", [hit], k=1)
        assert 0.98 < ranked[0].score < 0.99
        assert local_service.requests[-1][2]["query"] == "fixture query"
    else:
        assert isinstance(adapters.reranker, LocalSimilarityReranker)
        assert adapters.reranker.embedding_provider is adapters.embedding


def test_mcp_environment_auto_reaches_engine_without_personal_stores(local_service, monkeypatch, tmp_path):
    from mnemosyne.mcp_server import MnemosyneMcpServer

    monkeypatch.setenv("MNEMOSYNE_EMBEDDING_PROVIDER", "auto")
    monkeypatch.setenv("MNEMOSYNE_RERANKER_PROVIDER", "auto")
    with MnemosyneMcpServer(store_path=tmp_path / "memory.json", object_store=tmp_path / "objects") as server:
        assert isinstance(server.engine.adapters.embedding, HttpEmbeddingProvider)
        assert server.engine.adapters.embedding.dims == 3
        assert isinstance(server.engine.adapters.reranker, HttpReranker)
    assert local_service.requests == [("GET", "/health", None)] * 2


@pytest.mark.parametrize("read_only", [False, True])
def test_cli_auto_preserves_explicit_cache_privacy_policy(local_service, tmp_path, read_only):
    from mnemosyne.cli import load_retrieval_adapters

    cache_path = tmp_path / "unused-embedding-cache.sqlite"
    args = _cli_args(
        "--embedding-provider", "auto", "--reranker-provider", "auto",
        "--embedding-cache-path", str(cache_path), "--embedding-cache-size", "7",
        "--embedding-cache-scope", "isolated-fixture", "--retrieval-timeout", "2",
    )
    args.evaluation_read_only = read_only
    adapters = load_retrieval_adapters(args)
    assert isinstance(adapters.embedding, HttpEmbeddingProvider)
    assert adapters.embedding.cache_size == (0 if read_only else 7)
    assert adapters.embedding.cache_path == (None if read_only else str(cache_path))
    assert adapters.embedding.cache_scope == "isolated-fixture"
    assert adapters.embedding.timeout_seconds == adapters.reranker.timeout_seconds == 2
    # Health discovery never writes a query cache or sends user content.
    assert not cache_path.exists()
    assert all(method == "GET" for method, _, _ in local_service.requests)


def test_local_discovery_does_not_require_optional_vector_accelerator():
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", """
import sys
sys.modules['numpy'] = None
from mnemosyne.quantized_vectors import discover_local_embedding_provider, discover_local_reranker
from mnemosyne.retrieval import HashingEmbeddingProvider, LocalSimilarityReranker
embedding = discover_local_embedding_provider(allow_loopback_http=False, allow_inprocess_onnx=False)
assert isinstance(embedding, HashingEmbeddingProvider)
assert isinstance(discover_local_reranker(fallback_embedding=embedding, allow_loopback_http=False), LocalSimilarityReranker)
from mnemosyne.quantized_vectors import QuantizedVectorIndex
for operation in (lambda: QuantizedVectorIndex(2), lambda: QuantizedVectorIndex.from_vectors(['x'], [[1., 0.]])):
    try:
        operation()
    except ImportError as error:
        assert 'numpy' in str(error)
    else:
        raise AssertionError('missing accelerator must be explicit')
"""],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
