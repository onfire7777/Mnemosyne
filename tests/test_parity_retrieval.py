"""Blueprint-parity contract tests for the CC-R retrieval/provider lane.

These tests pin down the behavior of every retrieval adapter boundary defined
in :mod:`mnemosyne.retrieval` and :mod:`mnemosyne.providers` without any network
dependency:

* deterministic local providers (hashing embedding, local-similarity reranker);
* production HTTP adapters (embedding + cross-encoder reranker) exercised via a
  faked transport so response-shape parsing, Matryoshka truncation/padding and
  vector normalization are covered;
* shell-free command adapters (lexical/BM25, specialist graph, multimodal
  embedding) exercised through a real ``sys.executable -c`` subprocess;
* the environment-driven adapter factory and its validation errors;
* the deterministic scoring helpers (semantic entropy, gist support,
  ACT-R-style activation scoring) and the low-level numeric guards.

The goal is a regression net that proves the local defaults stay byte-stable
while the production provider seams behave to contract.
"""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.benchmarks import (
    LabeledQuery,
    RetrievalQualityBenchmarkResult,
    retrieval_quality_benchmark,
)
from mnemosyne import providers as providers_pkg
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Hit
from mnemosyne.policy import OperatingPolicy
from mnemosyne.providers import (
    ProviderRegistry,
    SandboxedDreamer,
    SpecialistBudget,
    SpecialistModuleSpec,
    build_adapters_from_config,
    default_registry,
)
from mnemosyne import retrieval as retrieval_mod
from mnemosyne.retrieval import (
    CommandGraphRetriever,
    CommandLexicalRetriever,
    CommandMediaEmbeddingProvider,
    GraphSignalCache,
    HashingEmbeddingProvider,
    HttpEmbeddingProvider,
    HttpReranker,
    LocalSimilarityReranker,
    RetrievalAdapters,
    activation_explain,
    apply_activation_scores,
    build_channel_hits,
    gist_support_report,
    is_retired_summary_metadata,
    marginal_gain_cutoff,
    retrieval_adapters_from_env,
    semantic_entropy,
    validate_adapter_hit_scope,
)
from mnemosyne.retrieval import (
    _coerce_vector,
    _finite_float,
    _normalize_vector,
    _post_json,
    _spreading_activation,
    _validate_http_provider_config,
)

# A standalone interpreter snippet that drains stdin and emits a fixed JSON
# payload, used to drive the shell-free command adapters deterministically.
_PRINT_HITS = (
    "import json,sys;sys.stdin.read();"
    "print(json.dumps({'hits':["
    "{'id':'h1','text':'alpha context','kind':'evidence','score':0.9},"
    "{'id':'h2','text':'beta context','kind':'assertion','score':0.4}"
    "]}))"
)
_PRINT_EMBEDDING = (
    "import json,sys;sys.stdin.read();"
    "print(json.dumps({'embedding':[0.1,0.2,0.3,0.4]}))"
)
_PRINT_CROSS_SCOPE_HITS = (
    "import json,sys;sys.stdin.read();"
    "print(json.dumps({'hits':["
    "{'id':'h1','text':'alpha context','kind':'evidence','score':0.9,'tenant_id':'tenant-b'}"
    "]}))"
)
_PRINT_CROSS_BRANCH_HITS = (
    "import json,sys;sys.stdin.read();"
    "print(json.dumps({'hits':["
    "{'id':'h1','text':'alpha context','kind':'evidence','score':0.9,'branch':'shadow'}"
    "]}))"
)


def _hit(hit_id: str, text: str, *, score: float, channel: str = "lexical", **extra: object) -> Hit:
    """Build a minimal :class:`Hit` with sensible contract defaults."""

    return Hit(
        id=hit_id,
        kind=extra.pop("kind", "evidence"),  # type: ignore[arg-type]
        tenant_id=extra.pop("tenant_id", "tenant-a"),
        branch=extra.pop("branch", "main"),
        text=text,
        score=score,
        channel=channel,
        provenance=list(extra.pop("provenance", [])),
        trust_tier=int(extra.pop("trust_tier", 0)),
        sensitivity=int(extra.pop("sensitivity", 0)),
        metadata=dict(extra.pop("metadata", {})),
    )


# --------------------------------------------------------------------------- #
# Local deterministic providers
# --------------------------------------------------------------------------- #


def test_hashing_embedding_is_deterministic_and_dimensioned() -> None:
    provider = HashingEmbeddingProvider(dims=64)
    first = provider.embed("memory consolidation")
    second = provider.embed("memory consolidation")
    other = provider.embed("graph traversal")
    assert provider.name == "local-hashing"
    assert len(first) == 64
    assert first == second  # deterministic
    assert first != other  # content-sensitive


def test_local_similarity_reranker_orders_by_blended_signal() -> None:
    reranker = LocalSimilarityReranker()
    hits = [
        _hit("far", "completely unrelated content", score=0.5),
        _hit("near", "vector database retrieval engine", score=0.5),
    ]
    ranked = reranker.rerank("vector database retrieval", hits, k=2)
    assert [hit.id for hit in ranked] == ["near", "far"]
    assert all(hit.channel.endswith("+rerank") for hit in ranked)
    assert all(hit.metadata["reranker"] == "local-similarity" for hit in ranked)
    assert all(hit.score >= 0.0 for hit in ranked)


def test_local_similarity_reranker_respects_k() -> None:
    reranker = LocalSimilarityReranker()
    hits = [_hit(f"h{i}", f"text {i}", score=0.5) for i in range(5)]
    assert len(reranker.rerank("text", hits, k=2)) == 2


# --------------------------------------------------------------------------- #
# HTTP embedding provider (faked transport)
# --------------------------------------------------------------------------- #


def _patch_post_json(monkeypatch: pytest.MonkeyPatch, response: object) -> None:
    monkeypatch.setattr(
        "mnemosyne.retrieval._post_json",
        lambda url, payload, api_key, timeout: response,
    )


def test_http_embedding_generic_shape_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post_json(monkeypatch, {"embedding": [3.0, 4.0]})
    provider = HttpEmbeddingProvider(url="https://embed.test/v1", dims=2)
    vector = provider.embed("hello")
    assert vector == pytest.approx([0.6, 0.8])
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)


def test_http_embedding_openai_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post_json(monkeypatch, {"data": [{"embedding": [1.0, 0.0, 0.0]}]})
    provider = HttpEmbeddingProvider(url="https://embed.test/v1", dims=3)
    assert provider.embed("hello") == pytest.approx([1.0, 0.0, 0.0])


def test_http_embedding_truncates_and_pads_to_target_dims(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post_json(monkeypatch, {"embedding": [1.0, 0.0, 0.0, 0.0]})
    assert HttpEmbeddingProvider(url="https://e.test", dims=2).embed("x") == pytest.approx([1.0, 0.0])
    _patch_post_json(monkeypatch, {"embedding": [1.0]})
    padded = HttpEmbeddingProvider(url="https://e.test", dims=3).embed("x")
    assert padded == pytest.approx([1.0, 0.0, 0.0])


def test_http_embedding_rejects_zero_and_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post_json(monkeypatch, {"embedding": [0.0, 0.0]})
    with pytest.raises(ValueError, match="non-zero"):
        HttpEmbeddingProvider(url="https://e.test", dims=2).embed("x")
    _patch_post_json(monkeypatch, {"unexpected": True})
    with pytest.raises(ValueError, match="embedding response"):
        HttpEmbeddingProvider(url="https://e.test", dims=2).embed("x")


@pytest.mark.parametrize(
    ("url", "match"),
    [
        (
            "http://provider.example.test/embed",
            "requires https unless insecure localhost is explicitly allowed",
        ),
        (
            "https://user:secret@provider.example.test/embed",
            "must not contain userinfo credentials",
        ),
        (
            "file:///tmp/embed",
            "must be http\\(s\\) with a hostname",
        ),
    ],
)
def test_http_provider_config_rejects_unsafe_fetch_urls(url: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _validate_http_provider_config(url, 5.0)


def test_http_provider_config_rejects_private_https_address() -> None:
    with pytest.raises(ValueError, match="must not resolve to private"):
        _validate_http_provider_config("https://127.0.0.1/embed", 5.0)


# --------------------------------------------------------------------------- #
# HTTP cross-encoder reranker (faked transport)
# --------------------------------------------------------------------------- #


def test_http_reranker_cohere_shape_reorders(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post_json(
        monkeypatch,
        {"results": [{"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.9}]},
    )
    hits = [_hit("a", "first", score=0.5), _hit("b", "second", score=0.5)]
    ranked = HttpReranker(url="https://rr.test").rerank("q", hits, k=2)
    assert [hit.id for hit in ranked] == ["b", "a"]
    assert ranked[0].score == pytest.approx(0.9)
    assert ranked[0].channel.endswith("+rerank")
    assert ranked[0].metadata["reranker"] == "http-reranker"


def test_http_reranker_generic_score_shape_and_top_n(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post_json(
        monkeypatch,
        {"results": [{"index": 0, "score": 0.2}, {"index": 1, "score": 0.8}, {"index": 2, "score": 0.5}]},
    )
    hits = [_hit("a", "1", score=0.5), _hit("b", "2", score=0.5), _hit("c", "3", score=0.5)]
    ranked = HttpReranker(url="https://rr.test").rerank("q", hits, k=2)
    assert [hit.id for hit in ranked] == ["b", "c"]


def test_http_reranker_short_circuits_without_work(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("transport must not be called")

    monkeypatch.setattr("mnemosyne.retrieval._post_json", _boom)
    rr = HttpReranker(url="https://rr.test")
    assert rr.rerank("q", [_hit("a", "x", score=0.5)], k=0) == []
    assert rr.rerank("q", [], k=4) == []


@pytest.mark.parametrize(
    ("response", "match"),
    [
        ({"results": [{"index": 9, "score": 0.5}]}, "out of range"),
        ({"results": [{"index": 0, "score": 0.5}, {"index": 0, "score": 0.4}]}, "duplicate index"),
        ({"results": []}, "at least one scored result"),
        ({"results": [{"index": "x", "score": 0.5}]}, "index must be an integer"),
        ({"unexpected": True}, "must contain `results`"),
    ],
)
def test_http_reranker_rejects_bad_responses(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, object], match: str
) -> None:
    _patch_post_json(monkeypatch, response)
    hits = [_hit("a", "1", score=0.5), _hit("b", "2", score=0.5)]
    with pytest.raises(ValueError, match=match):
        HttpReranker(url="https://rr.test").rerank("q", hits, k=2)


# --------------------------------------------------------------------------- #
# Shell-free command adapters (real subprocess, no shell)
# --------------------------------------------------------------------------- #


def test_command_lexical_retriever_parses_and_truncates() -> None:
    retriever = CommandLexicalRetriever([sys.executable, "-c", _PRINT_HITS], backend="paradedb-bm25")
    hits = retriever.search("alpha", tenant_id="tenant-a", branch="main", k=1)
    assert len(hits) == 1
    assert hits[0].id == "h1"
    assert hits[0].channel == "command_lexical"
    assert hits[0].metadata["backend"] == "paradedb-bm25"
    assert hits[0].metadata["command_retrieval"] is True


def test_command_graph_retriever_parses_seeds() -> None:
    retriever = CommandGraphRetriever([sys.executable, "-c", _PRINT_HITS], backend="age-graph")
    hits = retriever.search(["alpha"], tenant_id="tenant-a", branch="main", k=5)
    assert [hit.id for hit in hits] == ["h1", "h2"]
    assert hits[0].channel == "command_graph_ppr"


def test_command_retriever_rejects_cross_scope_hits() -> None:
    retriever = CommandLexicalRetriever([sys.executable, "-c", _PRINT_CROSS_SCOPE_HITS])
    with pytest.raises(ValueError, match="outside requested tenant"):
        retriever.search("alpha", tenant_id="tenant-a", branch="main", k=1)


def test_command_retriever_rejects_cross_branch_hits() -> None:
    retriever = CommandLexicalRetriever([sys.executable, "-c", _PRINT_CROSS_BRANCH_HITS])
    with pytest.raises(ValueError, match="outside requested branch"):
        retriever.search("alpha", tenant_id="tenant-a", branch="main", k=1)


def test_validate_adapter_hit_scope_rejects_cross_scope_hits() -> None:
    hit = _hit("h1", "alpha context", score=0.9, tenant_id="tenant-b")
    with pytest.raises(ValueError, match="outside requested tenant"):
        validate_adapter_hit_scope(
            [hit],
            tenant_id="tenant-a",
            branch="main",
            adapter_name="lexical",
        )


def test_validate_adapter_hit_scope_rejects_cross_branch_hits() -> None:
    hit = _hit("h1", "alpha context", score=0.9, branch="shadow")
    with pytest.raises(ValueError, match="outside requested branch"):
        validate_adapter_hit_scope(
            [hit],
            tenant_id="tenant-a",
            branch="main",
            adapter_name="lexical",
        )


def test_command_media_embedding_normalizes() -> None:
    provider = CommandMediaEmbeddingProvider([sys.executable, "-c", _PRINT_EMBEDDING], dims=4)
    vector = provider.embed_media(b"\x00\x01", media_type="image/png", modality="image")
    assert len(vector) == 4
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)


def test_command_adapter_construction_validation() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        CommandLexicalRetriever([])
    with pytest.raises(ValueError, match="timeout must be positive"):
        CommandGraphRetriever([sys.executable], timeout_seconds=0)
    with pytest.raises(ValueError, match="dimensions must be positive"):
        CommandMediaEmbeddingProvider([sys.executable], dims=0)


def test_command_retriever_rejects_nonzero_exit_and_bad_payloads() -> None:
    fail = CommandLexicalRetriever([sys.executable, "-c", "import sys;sys.exit(3)"])
    with pytest.raises(ValueError, match="command failed"):
        fail.search("q", tenant_id="t", branch="main", k=1)

    empty = CommandLexicalRetriever([sys.executable, "-c", "import sys;sys.stdin.read()"])
    with pytest.raises(ValueError, match="returned no JSON"):
        empty.search("q", tenant_id="t", branch="main", k=1)

    not_json = CommandLexicalRetriever([sys.executable, "-c", "import sys;sys.stdin.read();print('nope')"])
    with pytest.raises(ValueError, match="must be valid JSON"):
        not_json.search("q", tenant_id="t", branch="main", k=1)

    no_id_script = "import json,sys;sys.stdin.read();print(json.dumps({'hits':[{'text':'x','score':1.0}]}))"
    missing_id = CommandLexicalRetriever([sys.executable, "-c", no_id_script])
    with pytest.raises(ValueError, match="requires id"):
        missing_id.search("q", tenant_id="t", branch="main", k=1)


# --------------------------------------------------------------------------- #
# Environment-driven adapter factory
# --------------------------------------------------------------------------- #


def test_adapters_from_env_defaults_to_local_and_native() -> None:
    # No PARITYR_* env vars are set, so the factory must fall back to the
    # deterministic local embedding/reranker and native (Postgres) retrievers.
    adapters = retrieval_adapters_from_env(prefix="PARITYR")
    assert isinstance(adapters, RetrievalAdapters)
    assert isinstance(adapters.embedding, HashingEmbeddingProvider)
    assert isinstance(adapters.reranker, LocalSimilarityReranker)
    assert adapters.lexical_retriever is None
    assert adapters.graph_retriever is None


def test_adapters_from_env_builds_http_and_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARITYR_EMBEDDING_PROVIDER", "http")
    monkeypatch.setenv("PARITYR_EMBEDDING_URL", "https://embed.test/v1")
    monkeypatch.setenv("PARITYR_EMBEDDING_DIMS", "32")
    monkeypatch.setenv("PARITYR_RERANKER_PROVIDER", "http")
    monkeypatch.setenv("PARITYR_RERANKER_URL", "https://rr.test/v1")
    monkeypatch.setenv("PARITYR_LEXICAL_PROVIDER", "command")
    monkeypatch.setenv("PARITYR_LEXICAL_COMMAND", "/usr/bin/true")
    monkeypatch.setenv("PARITYR_GRAPH_PROVIDER", "command")
    monkeypatch.setenv("PARITYR_GRAPH_COMMAND", "/usr/bin/true")
    adapters = retrieval_adapters_from_env(prefix="PARITYR")
    assert isinstance(adapters.embedding, HttpEmbeddingProvider)
    assert adapters.embedding.url == "https://embed.test/v1"
    assert adapters.embedding.dims == 32
    assert isinstance(adapters.reranker, HttpReranker)
    assert isinstance(adapters.lexical_retriever, CommandLexicalRetriever)
    assert isinstance(adapters.graph_retriever, CommandGraphRetriever)


@pytest.mark.parametrize(
    ("env", "match"),
    [
        ({"PARITYR_EMBEDDING_PROVIDER": "bogus"}, "unsupported embedding provider"),
        ({"PARITYR_RERANKER_PROVIDER": "bogus"}, "unsupported reranker provider"),
        ({"PARITYR_LEXICAL_PROVIDER": "bogus"}, "unsupported lexical provider"),
        ({"PARITYR_GRAPH_PROVIDER": "bogus"}, "unsupported graph provider"),
        ({"PARITYR_EMBEDDING_PROVIDER": "http"}, "EMBEDDING_URL is required"),
    ],
)
def test_adapters_from_env_rejects_bad_config(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], match: str
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=match):
        retrieval_adapters_from_env(prefix="PARITYR")


# --------------------------------------------------------------------------- #
# Deterministic scoring helpers
# --------------------------------------------------------------------------- #


def test_semantic_entropy_bounds() -> None:
    assert semantic_entropy([]) == 0.0
    assert semantic_entropy(["only one"]) == 0.0
    assert semantic_entropy(["same answer", "same answer"]) == 0.0
    assert semantic_entropy(["alpha", "beta"]) == pytest.approx(1.0)
    mixed = semantic_entropy(["alpha", "alpha", "beta"])
    assert 0.0 < mixed < 1.0


def test_gist_support_report_flags_pure_gist() -> None:
    assert gist_support_report([]) == {"applied": False, "gist_hit_ids": [], "hit_count": 0}
    gist = _hit("g1", "summary", score=0.5, metadata={"summary": {"kind": "abstractive_gist"}})
    plain = _hit("p1", "raw", score=0.5)
    assert gist_support_report([gist])["applied"] is True
    mixed = gist_support_report([gist, plain])
    assert mixed["applied"] is False
    assert mixed["gist_hit_ids"] == ["g1"]
    assert mixed["hit_count"] == 2


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"summary": {"status": "retired"}}, True),
        ({"summary": {"status": "superseded"}}, True),
        ({"summary": {"superseded_by": "x"}}, True),
        ({"summary": {"retired_at": "2026-01-01T00:00:00Z"}}, True),
        ({"summary": {"status": "active"}}, False),
        ({"summary": "not-a-dict"}, False),
        ({}, False),
        ("not-a-dict", False),
    ],
)
def test_is_retired_summary_metadata(metadata: object, expected: bool) -> None:
    assert is_retired_summary_metadata(metadata) is expected


def test_apply_activation_scores_annotates_and_sorts() -> None:
    policy = OperatingPolicy()
    now = datetime(2026, 6, 23, tzinfo=UTC)
    hits = [
        _hit(
            "fresh",
            "recently accessed important fact",
            score=0.8,
            metadata={"confidence": 0.9, "access_count": 5, "last_accessed": (now - timedelta(hours=1)).isoformat()},
            trust_tier=3,
        ),
        _hit(
            "stale",
            "rarely accessed weak fact",
            score=0.2,
            metadata={"confidence": 0.4, "access_count": 0, "last_accessed": (now - timedelta(days=90)).isoformat()},
            trust_tier=0,
        ),
    ]
    activated = apply_activation_scores(hits, policy, now=now)
    assert [hit.id for hit in activated] == ["fresh", "stale"]
    for hit in activated:
        activation = hit.metadata["activation"]
        assert 0.0 <= activation["score"] <= 1.0
        assert set(activation["components"]) == {"base_level", "semantic", "importance", "recency"}
    assert apply_activation_scores([], policy) == []


def test_apply_activation_scores_uses_actr_base_level_when_enabled() -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    hit = _hit(
        "stale",
        "frequently accessed but old memory",
        score=0.8,
        metadata={"confidence": 0.9, "access_count": 5, "last_accessed": (now - timedelta(days=90)).isoformat()},
        trust_tier=3,
    )

    legacy = apply_activation_scores([hit], OperatingPolicy(), now=now)[0]
    actr = apply_activation_scores([hit], OperatingPolicy(actr_decay=0.5), now=now)[0]

    assert actr.metadata["activation"]["components"]["base_level"] < legacy.metadata["activation"]["components"]["base_level"]


def test_activation_explain_reports_weights() -> None:
    policy = OperatingPolicy()
    hits = apply_activation_scores([_hit("a", "fact", score=0.5)], policy)
    report = activation_explain(hits, policy)
    assert report["applied"] is True
    assert report["weights"] == policy.activation_weights
    assert report["hits"][0]["id"] == "a"
    assert "activation" in report["hits"][0]


# --------------------------------------------------------------------------- #
# Low-level numeric and transport guards
# --------------------------------------------------------------------------- #


def test_normalize_vector_truncates_pads_and_guards() -> None:
    assert _normalize_vector([3.0, 4.0], 2) == pytest.approx([0.6, 0.8])
    assert _normalize_vector([1.0], 3) == pytest.approx([1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="dimensions must be positive"):
        _normalize_vector([1.0], 0)
    with pytest.raises(ValueError, match="non-zero"):
        _normalize_vector([0.0, 0.0], 2)


def test_coerce_and_finite_float_guards() -> None:
    assert _coerce_vector([1, 2.5], field="v") == [1.0, 2.5]
    with pytest.raises(ValueError, match="at least one value"):
        _coerce_vector([], field="v")
    with pytest.raises(ValueError, match="numeric"):
        _coerce_vector([True], field="v")
    with pytest.raises(ValueError, match="numeric"):
        _finite_float("x", field="v")
    with pytest.raises(ValueError, match="finite"):
        _finite_float(float("inf"), field="v")
    assert _finite_float(2, field="v") == 2.0


@pytest.mark.parametrize(
    ("url", "timeout", "ok"),
    [
        ("https://93.184.216.34/v1", 30.0, True),
        ("http://127.0.0.1", 1.0, True),
        ("http://provider.test", 1.0, False),
        ("ftp://provider.test", 30.0, False),
        ("not-a-url", 30.0, False),
        ("https://provider.test", 0.0, False),
        ("https://provider.test", float("nan"), False),
    ],
)
def test_validate_http_provider_config(url: str, timeout: float, ok: bool) -> None:
    if ok:
        _validate_http_provider_config(url, timeout)
    else:
        with pytest.raises(ValueError):
            _validate_http_provider_config(url, timeout)


def test_post_json_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.error

    class _FakeResponse(io.BytesIO):
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc: object) -> None:
            self.close()

    monkeypatch.setattr(
        "mnemosyne.retrieval.validate_fetch_url",
        lambda *_args, **_kwargs: object(),
    )

    def _ok(request: object, *, validated: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(b'{"embedding": [1.0]}')

    monkeypatch.setattr("mnemosyne.retrieval.safe_urlopen", _ok)
    assert _post_json("https://p.test", {"input": "x"}, None, 5.0) == {"embedding": [1.0]}

    def _non_dict(request: object, *, validated: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"[1, 2, 3]")

    monkeypatch.setattr("mnemosyne.retrieval.safe_urlopen", _non_dict)
    with pytest.raises(ValueError, match="must be a JSON object"):
        _post_json("https://p.test", {}, None, 5.0)

    def _bad_json(request: object, *, validated: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"not json")

    monkeypatch.setattr("mnemosyne.retrieval.safe_urlopen", _bad_json)
    with pytest.raises(ValueError, match="must be valid JSON"):
        _post_json("https://p.test", {}, None, 5.0)

    def _http_error(request: object, *, validated: object, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError("https://p.test", 503, "unavailable", {}, io.BytesIO(b"down"))

    monkeypatch.setattr("mnemosyne.retrieval.safe_urlopen", _http_error)
    with pytest.raises(ValueError, match="HTTP 503"):
        _post_json("https://p.test", {}, None, 5.0)

    def _url_error(request: object, *, validated: object, timeout: float) -> _FakeResponse:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("mnemosyne.retrieval.safe_urlopen", _url_error)
    with pytest.raises(ValueError, match="request failed"):
        _post_json("https://p.test", {}, None, 5.0)


# --------------------------------------------------------------------------- #
# Retrieval-quality benchmark (blueprint §16: recall@k / nDCG@k / precision / MRR)
# --------------------------------------------------------------------------- #


class _FakeResult:
    def __init__(self, hits: list[Hit]) -> None:
        self.hits = hits


class _RankingEngine:
    """A duck-typed engine returning a fixed ranked id list per query."""

    def __init__(self, ranking: dict[str, list[str]]) -> None:
        self._ranking = ranking

    def retrieve(self, query: str, *, tenant_id: str, branch: str, deep: bool) -> _FakeResult:
        ids = self._ranking.get(query, [])
        return _FakeResult([_hit(hid, hid, score=1.0, tenant_id=tenant_id, branch=branch) for hid in ids])


def test_retrieval_quality_metric_math_is_exact() -> None:
    engine = _RankingEngine({"q-second": ["d1", "d2", "d3", "d4"], "q-first": ["d1", "d2", "d3", "d4"]})
    result = retrieval_quality_benchmark(
        engine,  # type: ignore[arg-type]
        "tenant-a",
        [LabeledQuery("q-second", ("d2",)), LabeledQuery("q-first", ("d1",))],
        k=4,
    )
    assert result.query_count == 2
    assert result.recall_at_k == pytest.approx(1.0)
    assert result.precision_at_k == pytest.approx(0.25)
    # MRR: relevant at rank 2 (1/2) and rank 1 (1/1) -> mean 0.75
    assert result.mrr == pytest.approx(0.75)
    # nDCG: (1/log2(3) + 1/log2(2)) / 2
    expected_ndcg = ((1.0 / math.log2(3)) + 1.0) / 2
    assert result.ndcg_at_k == pytest.approx(expected_ndcg)


def test_retrieval_quality_counts_labeled_misses_but_skips_unlabeled() -> None:
    engine = _RankingEngine({"hit": ["d1"], "miss": ["d9"], "unlabeled": ["d1"]})
    result = retrieval_quality_benchmark(
        engine,  # type: ignore[arg-type]
        "tenant-a",
        [
            LabeledQuery("hit", ("d1",)),
            LabeledQuery("miss", ("d2",)),  # labeled but not retrieved -> scored 0
            LabeledQuery("unlabeled", ()),  # no labels -> skipped entirely
        ],
        k=4,
    )
    assert result.query_count == 2  # unlabeled skipped
    assert result.recall_at_k == pytest.approx(0.5)  # (1.0 + 0.0) / 2


def test_retrieval_quality_empty_and_invalid_inputs() -> None:
    engine = _RankingEngine({})
    empty = retrieval_quality_benchmark(engine, "tenant-a", [], k=4)  # type: ignore[arg-type]
    assert isinstance(empty, RetrievalQualityBenchmarkResult)
    assert empty.query_count == 0
    assert empty.recall_at_k == 0.0
    with pytest.raises(ValueError, match="k must be positive"):
        retrieval_quality_benchmark(engine, "tenant-a", [], k=0)  # type: ignore[arg-type]


def test_retrieval_quality_runs_against_real_local_engine() -> None:
    engine = LocalMemoryEngine()
    tenant = "tenant-bench"
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="user-bench",
            actor="user",
            source_type="seed",
            content="The deployment runbook lives in the operations wiki.",
            trust_tier=2,
            access_policy={"tenant": tenant},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            subject="deployment runbook",
            predicate="lives in",
            object="operations wiki",
            confidence=0.9,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=2,
            access_policy={"tenant": tenant},
        )
    )
    probe = engine.retrieve("deployment runbook", tenant_id=tenant, branch="main", deep=False)
    relevant_ids = tuple(hit.id for hit in probe.hits[:1])
    result = retrieval_quality_benchmark(
        engine,
        tenant,
        [LabeledQuery("deployment runbook", relevant_ids)],
        k=8,
    )
    assert result.query_count == 1
    for metric in (result.recall_at_k, result.precision_at_k, result.ndcg_at_k, result.mrr):
        assert 0.0 <= metric <= 1.0
    assert result.per_query[0]["query"] == "deployment runbook"
    assert result.to_dict()["k"] == 8


# --------------------------------------------------------------------------- #
# Provider package: organized surface + pluggable registry
# --------------------------------------------------------------------------- #


def test_providers_reexport_is_identical_to_retrieval() -> None:
    # The package must expose the *same* objects as the retrieval home, not copies.
    for name in (
        "EmbeddingProvider",
        "Reranker",
        "HashingEmbeddingProvider",
        "LocalSimilarityReranker",
        "HttpEmbeddingProvider",
        "HttpReranker",
        "CommandLexicalRetriever",
        "CommandGraphRetriever",
        "CommandMediaEmbeddingProvider",
        "RetrievalAdapters",
        "retrieval_adapters_from_env",
    ):
        assert getattr(providers_pkg, name) is getattr(retrieval_mod, name)


def test_registry_default_build_matches_env_builder() -> None:
    # Config-driven default construction must align with the env-driven path so
    # the two entry points never diverge in their built-in provider selection.
    from_config = build_adapters_from_config({})
    from_env = retrieval_mod.retrieval_adapters_from_env(prefix="PARITYRX")
    assert type(from_config.embedding) is type(from_env.embedding)
    assert type(from_config.reranker) is type(from_env.reranker)
    assert from_config.lexical_retriever is None and from_env.lexical_retriever is None
    assert from_config.graph_retriever is None and from_env.graph_retriever is None
    assert from_config.lexical_backend == "postgres-fts"


def test_registry_builds_http_and_command_providers() -> None:
    adapters = build_adapters_from_config(
        {
            "embedding_provider": "http",
            "embedding_url": "https://embed.test/v1",
            "embedding_dims": 16,
            "reranker_provider": "http",
            "reranker_url": "https://rr.test/v1",
            "lexical_provider": "command",
            "lexical_command": "/usr/bin/true",
            "graph_provider": "command",
            "graph_command": "/usr/bin/true",
        }
    )
    assert isinstance(adapters.embedding, providers_pkg.HttpEmbeddingProvider)
    assert adapters.embedding.dims == 16
    assert isinstance(adapters.reranker, providers_pkg.HttpReranker)
    assert isinstance(adapters.lexical_retriever, providers_pkg.CommandLexicalRetriever)
    assert isinstance(adapters.graph_retriever, providers_pkg.CommandGraphRetriever)


def test_local_reranker_binds_constructed_embedding() -> None:
    adapters = build_adapters_from_config(
        {"embedding_provider": "http", "embedding_url": "https://e.test", "reranker_provider": "local"}
    )
    assert isinstance(adapters.reranker, providers_pkg.LocalSimilarityReranker)
    assert adapters.reranker.embedding_provider is adapters.embedding


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"embedding_provider": "bogus"}, "unsupported embedding provider"),
        ({"reranker_provider": "bogus"}, "unsupported reranker provider"),
        ({"lexical_provider": "bogus"}, "unsupported lexical provider"),
        ({"graph_provider": "bogus"}, "unsupported graph provider"),
        ({"embedding_provider": "http"}, "embedding_url is required"),
        ({"lexical_provider": "command"}, "lexical_command is required"),
    ],
)
def test_registry_rejects_bad_config(config: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        build_adapters_from_config(config)


def test_registry_supports_custom_provider_registration() -> None:
    registry = default_registry()
    sentinel = providers_pkg.HashingEmbeddingProvider(dims=8)
    registry.register_embedding_provider("sentinel", lambda _config: sentinel)
    adapters = build_adapters_from_config({"embedding_provider": "sentinel"}, registry=registry)
    assert adapters.embedding is sentinel
    # A fresh default registry must NOT see the custom registration (no shared mutable state).
    assert "sentinel" not in default_registry().embedding


def test_provider_registry_is_constructible_empty() -> None:
    empty = ProviderRegistry()
    assert empty.embedding == {} and empty.reranker == {}
    with pytest.raises(ValueError, match="unsupported embedding provider"):
        build_adapters_from_config({"embedding_provider": "local"}, registry=empty)


def test_specialist_registry_exposes_typed_roles_and_budgets() -> None:
    registry = default_registry()
    manifest = {item["name"]: item for item in registry.specialist_manifest()}

    assert manifest["embedder.local"]["role"] == "embedder"
    assert manifest["embedder.local"]["budget"]["critical_path_allowed"] is True
    assert manifest["dreamer.shadow"]["role"] == "dreamer"
    assert manifest["dreamer.shadow"]["budget"]["critical_path_allowed"] is False
    assert manifest["dreamer.shadow"]["budget"]["answer_authority_allowed"] is False
    assert manifest["dreamer.shadow"]["budget"]["promotion_gate_required"] is True
    assert "shadow_only" not in manifest["dreamer.shadow"]["budget"]
    assert "low-groundedness" in manifest["dreamer.shadow"]["tags"]
    assert [spec.name for spec in registry.specialists_by_role("dreamer")] == ["dreamer.shadow"]


def test_specialist_registry_builds_modules_and_blocks_shadow_critical_path() -> None:
    registry = default_registry()

    embedder = registry.build_specialist("embedder.local", {"embedding_dims": 8}, critical_path=True)
    dreamer = registry.build_specialist("dreamer.shadow", {"dreamer_max_candidates": 2})
    capped_dreamer = registry.build_specialist(
        "dreamer.shadow",
        {"dreamer_max_candidates": 99, "dreamer_min_sources": 1},
    )

    assert isinstance(embedder, providers_pkg.HashingEmbeddingProvider)
    assert isinstance(dreamer, SandboxedDreamer)
    assert dreamer.max_candidates == 2
    assert isinstance(capped_dreamer, SandboxedDreamer)
    assert capped_dreamer.max_candidates == 3
    assert capped_dreamer.min_sources == 2
    with pytest.raises(ValueError, match="not approved for critical-path use"):
        registry.build_specialist("dreamer.shadow", critical_path=True)


def test_specialist_registry_rejects_invalid_specs_and_duplicate_names() -> None:
    with pytest.raises(ValueError, match="answer-authority specialists"):
        SpecialistBudget(answer_authority_allowed=True, critical_path_allowed=False)

    registry = ProviderRegistry()
    spec = SpecialistModuleSpec(
        name="custom.shadow",
        role="dreamer",
        factory=lambda _config: object(),
        budget=SpecialistBudget(),
        input_contract="input",
        output_contract="output",
    )
    registry.register_specialist(spec)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_specialist(spec)


# --------------------------------------------------------------------------- #
# §22.4 spreading activation · marginal-gain cutoff · §22.2 graph cache + channels
# --------------------------------------------------------------------------- #


def test_spreading_activation_signal_from_shared_cues() -> None:
    hits = [
        _hit("a", "alpha", score=0.9, provenance=["ev1"], metadata={"subject": "postgres"}),
        _hit("b", "beta", score=0.8, provenance=["ev1"], metadata={"subject": "redis"}),
        _hit("c", "gamma", score=0.7, metadata={"subject": "kafka"}),
    ]
    signals = _spreading_activation(hits)
    assert signals["a"] == pytest.approx(0.5)  # shares ev1 with b -> 1 of 2 others
    assert signals["b"] == pytest.approx(0.5)
    assert signals["c"] == 0.0  # shares nothing


def test_spreading_activation_respects_metadata_override() -> None:
    hits = [_hit("a", "x", score=0.5, metadata={"spreading_activation": 0.77})]
    assert _spreading_activation(hits)["a"] == pytest.approx(0.77)


def test_activation_default_output_has_no_spreading_component() -> None:
    # Regression guard: the default policy (the config-drift baseline) must yield
    # exactly the original four components — spreading is strictly opt-in.
    activated = apply_activation_scores([_hit("a", "fact", score=0.5)], OperatingPolicy())
    assert set(activated[0].metadata["activation"]["components"]) == {
        "base_level",
        "semantic",
        "importance",
        "recency",
    }


def test_activation_includes_spreading_when_weighted() -> None:
    policy = OperatingPolicy(
        activation_weights={
            "base_level": 0.3,
            "semantic": 0.3,
            "importance": 0.2,
            "recency": 0.1,
            "spreading": 0.1,
        }
    )
    hits = [
        _hit("a", "alpha", score=0.9, provenance=["ev1"]),
        _hit("b", "beta", score=0.8, provenance=["ev1"]),
    ]
    activated = apply_activation_scores(hits, policy)
    for hit in activated:
        components = hit.metadata["activation"]["components"]
        assert "spreading" in components
        assert components["spreading"] == pytest.approx(1.0)  # both share ev1
        assert 0.0 <= hit.metadata["activation"]["score"] <= 1.0


def test_marginal_gain_cutoff_respects_budget_and_redundancy() -> None:
    hits = [
        _hit("a", "alpha beta gamma", score=1.0),
        _hit("b", "alpha beta gamma", score=0.95),  # near-duplicate of a
        _hit("c", "totally different words here", score=0.9),
    ]
    selected, used = marginal_gain_cutoff(hits, token_budget=100, cost=0.4, redundancy_lambda=1.0)
    ids = [hit.id for hit in selected]
    assert ids[0] == "a"
    assert "b" not in ids  # redundant -> marginal gain below cost -> stop
    assert used > 0


def test_marginal_gain_cutoff_token_budget_and_validation() -> None:
    hits = [_hit("a", "one two three four five", score=1.0), _hit("b", "six seven eight", score=0.9)]
    selected, used = marginal_gain_cutoff(hits, token_budget=5, cost=0.0)
    assert [hit.id for hit in selected] == ["a"]
    assert used == 5
    assert marginal_gain_cutoff([], token_budget=10) == ([], 0)
    with pytest.raises(ValueError, match="non-negative"):
        marginal_gain_cutoff(hits, token_budget=-1)


def test_graph_signal_cache_roundtrip_and_filtering() -> None:
    cache = GraphSignalCache()
    assert cache.fast_signal("t", "main", 5) == []
    cache.put(
        "t",
        "main",
        [_hit("g1", "postgres replication", score=0.6), _hit("g2", "kafka streams", score=0.9)],
    )
    top = cache.fast_signal("t", "main", 5)
    assert [hit.id for hit in top] == ["g2", "g1"]  # sorted by score desc
    assert all(hit.metadata["graph_signal_cached"] is True for hit in top)
    assert cache.fast_signal("t", "main", 0) == []
    seeded = cache.fast_signal("t", "main", 5, seeds=["postgres"])
    assert [hit.id for hit in seeded] == ["g1"]
    cache.invalidate("t", "main")
    assert cache.fast_signal("t", "main", 5) == []


def test_build_channel_hits_tags_and_validates() -> None:
    hits = build_channel_hits(
        [
            {"id": "p1", "text": "prefers dark mode", "score": 0.7},
            {"id": "p2", "text": "uses metric units", "score": 0.9},
        ],
        channel="preference",
        tenant_id="t",
        branch="main",
    )
    assert [hit.id for hit in hits] == ["p2", "p1"]  # sorted by score
    assert all(hit.channel == "preference" for hit in hits)
    assert all(hit.metadata["channel_source"] == "preference" for hit in hits)
    with pytest.raises(ValueError, match="requires id and text"):
        build_channel_hits([{"id": "x"}], channel="lesson", tenant_id="t", branch="main")
    with pytest.raises(ValueError, match="score must be numeric"):
        build_channel_hits(
            [{"id": "x", "text": "y", "score": "nan-ish"}], channel="lesson", tenant_id="t", branch="main"
        )
    with pytest.raises(ValueError, match="must be mappings"):
        build_channel_hits(["not-a-mapping"], channel="lesson", tenant_id="t", branch="main")
