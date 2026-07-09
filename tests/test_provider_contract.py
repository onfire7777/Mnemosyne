from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from mnemosyne.models import Hit
from mnemosyne.retrieval import HttpEmbeddingProvider, HttpReranker

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests" / "fixtures" / "provider_contract.json"
SERVICE_PATH = ROOT / "services" / "embedding" / "app.py"


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _load_embedding_service() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mnemosyne_embedding_contract_app", SERVICE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def embedding_service(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    service = _load_embedding_service()
    contract = _contract()
    monkeypatch.setattr(service, "FORCE_FALLBACK", True)
    monkeypatch.setattr(
        service,
        "BACKEND",
        service.Backend(
            embed_model_name=contract["embedding"]["model"],
            rerank_model_name=contract["rerank"]["model"],
            dims=contract["embedding"]["dimensions"],
        ),
    )
    return service


def test_python_embedding_service_satisfies_shared_contract(embedding_service: ModuleType) -> None:
    contract = _contract()
    dims = contract["embedding"]["dimensions"]

    single = embedding_service.handle_embed(contract["embedding"]["single"]["request"])
    assert single["model"] == contract["embedding"]["model"]
    assert single["dimensions"] == dims
    assert len(single["embedding"]) == dims
    assert any(abs(value) > 0 for value in single["embedding"])

    batch = embedding_service.handle_embed(contract["embedding"]["batch"]["request"])
    assert batch["object"] == "list"
    assert batch["model"] == contract["embedding"]["model"]
    assert batch["dimensions"] == dims
    assert [row["index"] for row in batch["data"]] == [0, 1]
    assert all(len(row["embedding"]) == dims for row in batch["data"])


def test_python_reranker_service_satisfies_shared_contract(embedding_service: ModuleType) -> None:
    contract = _contract()

    response = embedding_service.handle_rerank(contract["rerank"]["request"])

    assert response["model"] == contract["rerank"]["model"]
    assert response["results"][0]["index"] == contract["rerank"]["expected_top_index"]
    assert all({"index", "score"} <= set(row) for row in response["results"])


def test_http_adapters_satisfy_shared_provider_contract(
    embedding_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _contract()
    requests: list[tuple[str, dict[str, object]]] = []

    def _post_json(
        url: str,
        payload: dict[str, object],
        _api_key: str | None,
        _timeout: float,
    ) -> dict[str, object]:
        requests.append((url, payload))
        if url.endswith("/embed"):
            return embedding_service.handle_embed(payload)
        if url.endswith("/rerank"):
            return embedding_service.handle_rerank(payload)
        raise AssertionError(f"unexpected provider URL: {url}")

    monkeypatch.setattr("mnemosyne.retrieval._post_json", _post_json)

    embedding = HttpEmbeddingProvider(
        url="https://provider.test/embed",
        dims=contract["embedding"]["dimensions"],
        model=contract["embedding"]["model"],
    )
    single_vector = embedding.embed(contract["embedding"]["single"]["request"]["input"])
    batch_vectors = embedding.embed_many(contract["embedding"]["batch"]["request"]["input"])

    hits = [
        Hit(
            id=f"doc-{index}",
            kind="evidence",
            tenant_id="contract",
            branch="main",
            text=document,
            score=0.1,
            channel="contract",
        )
        for index, document in enumerate(contract["rerank"]["request"]["documents"])
    ]
    ranked = HttpReranker(
        url="https://provider.test/rerank",
        model=contract["rerank"]["model"],
    ).rerank("provider health", hits, k=contract["rerank"]["request"]["top_n"])

    assert len(single_vector) == contract["embedding"]["dimensions"]
    assert len(batch_vectors) == 2
    assert [len(vector) for vector in batch_vectors] == [contract["embedding"]["dimensions"]] * 2
    assert ranked[0].id == f"doc-{contract['rerank']['expected_top_index']}"
    assert requests == [
        ("https://provider.test/embed", contract["embedding"]["single"]["request"]),
        ("https://provider.test/embed", contract["embedding"]["batch"]["request"]),
        ("https://provider.test/rerank", contract["rerank"]["request"]),
    ]
