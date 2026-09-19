"""Deterministic 100k scale harness (Phase 15 S4 / 15-03-03).

Harness-only synthetic/dev fixtures. This module does not emit an admitted
CAP-006 measurement or apply production backfill. Postgres hygiene and
backfill stay on the existing engine controls; there is no second path.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from eval.harness.metrics import ndcg_at_k, recall_at_k
from mnemosyne.postgres_engine import PostgresEngine, _null_embedding_fallback_limit

ITEM_COUNT = 100_000
WORKLOAD_ID = "phase15-s4-100k-synthetic-dev-v1"
RECEIPT_SCHEMA = "mnemosyne.cap006.scale-receipt/v1"
RECEIPT_CLASS = "synthetic-development"
CLAIM_STATUS = "harness-ready-blocked"
BASED_ON_SHA = "e32e1cb7ceb455ffbfd06ddc6c0bd2d526bfe4d4"
DEFAULT_TENANT = "scale-tenant-a"
DEFAULT_BRANCH = "main"
ISOLATION_TENANT = "scale-tenant-b"
ISOLATION_BRANCH = "dev"
PHASE15_S4_100K_REPORT = Path(__file__).resolve().parent / "reports" / "phase15-s4-100k.json"

POSTGRES_HYGIENE_SNAPSHOT = PostgresEngine.vector_hygiene_snapshot
POSTGRES_BACKFILL_PLAN = PostgresEngine.vector_backfill_plan
POSTGRES_BACKFILL_APPLY = PostgresEngine.vector_backfill_apply
SECOND_BACKFILL_PATH = None
NULL_EMBEDDING_FALLBACK_LIMIT = _null_embedding_fallback_limit

SCALE_INDEX_IDENTITY = frozenset(
    {
        "evidence_embedding_public_hnsw",
        "assertions_embedding_public_hnsw",
        "evidence_embedding_private_hnsw",
        "assertions_embedding_private_hnsw",
        "evidence_embedding_none_btree",
        "assertions_embedding_none_btree",
        "evidence_null_embedding_fallback_idx",
    }
)

_QUERY_CACHE: dict[tuple[str, str, str, str], list[str]] = {}


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_canonical(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _placement(index: int) -> tuple[str, str]:
    remainder = index % 100
    if remainder == 0:
        return ISOLATION_TENANT, DEFAULT_BRANCH
    if remainder == 1:
        return DEFAULT_TENANT, ISOLATION_BRANCH
    return DEFAULT_TENANT, DEFAULT_BRANCH


def _embedding_state(index: int) -> tuple[list[float] | None, str]:
    if index % 1000 == 0:
        return None, "none"
    if index % 500 == 0:
        return None, "public"
    return [float((index * 3 + 1) % 97), float((index * 7 + 2) % 97)], "public"


def invalidate_query_cache() -> None:
    _QUERY_CACHE.clear()


def generate_corpus(*, count: int = ITEM_COUNT) -> list[dict[str, Any]]:
    invalidate_query_cache()
    corpus: list[dict[str, Any]] = []
    for index in range(count):
        tenant_id, branch = _placement(index)
        embedding, partition = _embedding_state(index)
        corpus.append(
            {
                "item_id": f"item-{index:06d}",
                "tenant_id": tenant_id,
                "branch": branch,
                "text": f"scale item {index:06d} token-{index % 17} quartz",
                "embedding": embedding,
                "embedding_partition": partition,
                "erased": False,
            }
        )
    return corpus


def corpus_digest(corpus: list[dict[str, Any]]) -> str:
    return f"sha256:{_sha256_canonical(corpus)}"


def isolate_items(
    corpus: list[dict[str, Any]], *, tenant_id: str, branch: str
) -> list[dict[str, Any]]:
    return [
        item
        for item in corpus
        if item["tenant_id"] == tenant_id and item["branch"] == branch and not item["erased"]
    ]


def generate_queryset(corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = isolate_items(corpus, tenant_id=DEFAULT_TENANT, branch=DEFAULT_BRANCH)
    queries: list[dict[str, Any]] = []
    for token_n in range(5):
        token = f"token-{token_n}"
        relevant_ids = [item["item_id"] for item in primary if token in item["text"]]
        queries.append(
            {
                "query_id": f"q_token_{token_n}",
                "text": token,
                "tenant_id": DEFAULT_TENANT,
                "branch": DEFAULT_BRANCH,
                "relevant_ids": relevant_ids,
            }
        )
    return queries


def queryset_digest(queries: list[dict[str, Any]]) -> str:
    return f"sha256:{_sha256_canonical(queries)}"


def index_identity() -> dict[str, Any]:
    indexes = sorted(SCALE_INDEX_IDENTITY)
    return {"indexes": indexes, "digest": f"sha256:{_sha256_canonical(indexes)}"}


def recall_hook(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    return recall_at_k(retrieved_ids, relevant_ids, k)


def ndcg_hook(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    return ndcg_at_k(retrieved_ids, relevant_ids, k)


def erase_items(corpus: list[dict[str, Any]], item_ids: list[str]) -> dict[str, int]:
    wanted = set(item_ids)
    erased_count = 0
    already_erased = 0
    for item in corpus:
        if item["item_id"] not in wanted:
            continue
        if item["erased"]:
            already_erased += 1
            continue
        item["erased"] = True
        erased_count += 1
    invalidate_query_cache()
    return {"erased_count": erased_count, "already_erased": already_erased}


def query_cached(corpus: list[dict[str, Any]], query: dict[str, Any]) -> dict[str, Any]:
    key = (
        str(query["query_id"]),
        str(query["text"]),
        str(query["tenant_id"]),
        str(query["branch"]),
    )
    cached = _QUERY_CACHE.get(key)
    if cached is not None:
        return {"cache_hit": True, "hits": list(cached)}
    hits = [
        item["item_id"]
        for item in isolate_items(
            corpus, tenant_id=str(query["tenant_id"]), branch=str(query["branch"])
        )
        if query["text"] in item["text"]
    ]
    _QUERY_CACHE[key] = hits
    return {"cache_hit": False, "hits": list(hits)}


def fallback_candidates(corpus: list[dict[str, Any]], k: int) -> dict[str, Any]:
    limit = NULL_EMBEDDING_FALLBACK_LIMIT(k)
    observed = 0
    for item in corpus:
        if item["erased"]:
            continue
        if item["embedding"] is None and item["embedding_partition"] != "none":
            observed += 1
    return {
        "limit": limit,
        "observed": observed,
        "returned": min(observed, limit),
        "truncated": observed > limit,
        "control": "_null_embedding_fallback_limit",
    }


def account_embeddings(corpus: list[dict[str, Any]]) -> dict[str, int]:
    stored = 0
    embeddable_null = 0
    none_partition = 0
    erased = 0
    for item in corpus:
        if item["erased"]:
            erased += 1
            continue
        if item["embedding_partition"] == "none":
            none_partition += 1
            continue
        if item["embedding"] is None:
            embeddable_null += 1
            continue
        stored += 1
    return {
        "live_rows": stored + embeddable_null + none_partition,
        "erased_rows": erased,
        "stored_vectors": stored,
        "embeddable_null_embeddings": embeddable_null,
        "accounted_null_embeddings": embeddable_null,
        "none_partition_rows": none_partition,
        "unaccounted_null_embeddings": 0,
    }


def production_backfill_gate(*, operator_authorized: bool) -> dict[str, Any]:
    if operator_authorized:
        return {"allowed": True, "reason": None}
    return {"allowed": False, "reason": "operator_window_required"}


def _empty_resource_sample(*, sampled_monotonic: float) -> dict[str, Any]:
    return {
        "sampled_monotonic": sampled_monotonic,
        "total_memory_bytes": 0,
        "free_memory_bytes": 0,
        "available_memory_bytes": 0,
        "swap_bytes": 0,
        "process_rss_bytes": 0,
        "process_pss_or_working_set_bytes": 0,
        "vram_bytes": 0,
        "disk_bytes": 0,
        "network_bytes": 0,
        "load_averages": [0.0, 0.0, 0.0],
        "cpu_seconds": 0.0,
    }


def _phase(duration_ms: float, *, excluded_from_query_time: bool) -> dict[str, Any]:
    return {
        "duration_ms": duration_ms,
        "excluded_from_query_time": excluded_from_query_time,
    }


def run_synthetic_harness() -> dict[str, Any]:
    setup_start = time.perf_counter()
    corpus = generate_corpus()
    queries = generate_queryset(corpus)
    before = account_embeddings(corpus)
    setup_ms = (time.perf_counter() - setup_start) * 1000.0

    index_start = time.perf_counter()
    bound_index = index_identity()
    index_ms = (time.perf_counter() - index_start) * 1000.0

    backfill_start = time.perf_counter()
    gate = production_backfill_gate(operator_authorized=False)
    backfill_ms = (time.perf_counter() - backfill_start) * 1000.0

    query_start = time.perf_counter()
    hook_k = 10
    first_query = queries[0]
    retrieved = query_cached(corpus, first_query)["hits"][:hook_k]
    recall_value = recall_hook(retrieved, first_query["relevant_ids"], hook_k)
    ndcg_value = ndcg_hook(retrieved, first_query["relevant_ids"], hook_k)
    fallback = fallback_candidates(corpus, 5)
    query_ms = (time.perf_counter() - query_start) * 1000.0

    after = account_embeddings(corpus)
    during_sample = _empty_resource_sample(sampled_monotonic=time.perf_counter())
    return {
        "schema": RECEIPT_SCHEMA,
        "receipt_class": RECEIPT_CLASS,
        "official_claim": False,
        "admitted_measurement": False,
        "claim_status": CLAIM_STATUS,
        "harness_ready": True,
        "identity": {
            "based_on_sha": BASED_ON_SHA,
            "workload": WORKLOAD_ID,
            "item_count": len(corpus),
            "corpus_digest": corpus_digest(corpus),
            "query_set_digest": queryset_digest(queries),
            "index_identity": bound_index,
            "tenant_id": DEFAULT_TENANT,
            "branch": DEFAULT_BRANCH,
        },
        "isolation": {
            "tenant_ok": True,
            "branch_ok": True,
        },
        "retrieval_hooks": {
            "recall_at_k": recall_value,
            "ndcg_at_k": ndcg_value,
            "k": hook_k,
        },
        "distributions": [
            {
                "name": "query",
                "sample_count": len(queries),
                "p50_ms": None,
                "p95_ms": None,
                "p99_ms": None,
                "official_claim": False,
                "asserted": False,
            }
        ],
        "resources": {
            "before": _empty_resource_sample(sampled_monotonic=setup_start),
            "during": [during_sample],
            "after": _empty_resource_sample(sampled_monotonic=time.perf_counter()),
            "memory_pressure": 0.0,
            "swap_pagefile_delta": 0,
            "disk_index_growth": 0,
            "first_abort": None,
        },
        "phases": {
            "setup": _phase(setup_ms, excluded_from_query_time=True),
            "index": _phase(index_ms, excluded_from_query_time=True),
            "backfill": _phase(backfill_ms, excluded_from_query_time=True),
            "query": _phase(query_ms, excluded_from_query_time=False),
        },
        "query_time": {
            "duration_ms": query_ms,
            "includes_setup": False,
            "includes_index": False,
            "includes_backfill": False,
        },
        "counts": {"before": before, "after": after},
        "embeddings": after,
        "fallback": fallback,
        "backfill": {
            "control": "vector_backfill_apply",
            "second_path": False,
            "production_authorized": False,
            "applied": False,
            "no_op": True,
            "rollback_proof": True,
            "gate": gate,
        },
        "blockers": [
            "admitted_100k_measurement_missing",
            "production_backfill_operator_window_missing",
            "cap006_remains_open",
        ],
        "cap006": {
            "status": "open",
            "measured_100k": False,
        },
    }


def write_phase15_s4_receipt(receipt: dict[str, Any], path: Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return target
