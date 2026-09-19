"""Contract tests for the Phase 15 S4 / 15-03-03 100k scale harness.

Harness-only: synthetic/dev fixtures. These tests lock identity, isolation,
retrieval hooks, and receipt ABI. They do not admit a measured CAP-006 number.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.harness.metrics import ndcg_at_k, recall_at_k
from eval.scale.bench_100k import (
    CLAIM_STATUS,
    ITEM_COUNT,
    PHASE15_S4_100K_REPORT,
    RECEIPT_CLASS,
    RECEIPT_SCHEMA,
    WORKLOAD_ID,
    account_embeddings,
    corpus_digest,
    erase_items,
    fallback_candidates,
    generate_corpus,
    generate_queryset,
    index_identity,
    isolate_items,
    ndcg_hook,
    production_backfill_gate,
    query_cached,
    queryset_digest,
    recall_hook,
    run_synthetic_harness,
)
from mnemosyne.postgres_engine import _null_embedding_fallback_limit

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_RECEIPT = REPO_ROOT / "eval" / "scale" / "reports" / "phase15-s4-100k.json"


def _assert_unofficial_scale_receipt(receipt: dict) -> None:
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["receipt_class"] == RECEIPT_CLASS == "synthetic-development"
    assert receipt["official_claim"] is False
    assert receipt["admitted_measurement"] is False
    assert receipt["claim_status"] == CLAIM_STATUS == "harness-ready-blocked"
    assert receipt["harness_ready"] is True
    assert "cap006_remains_open" in receipt["blockers"]
    assert receipt.get("cap006", {}).get("measured_100k") is False


def test_exact_item_count() -> None:
    corpus = generate_corpus()
    assert ITEM_COUNT == 100_000
    assert len(corpus) == ITEM_COUNT
    assert len({item["item_id"] for item in corpus}) == ITEM_COUNT


def test_generation_is_deterministic() -> None:
    first = generate_corpus()
    second = generate_corpus()
    assert first == second
    assert corpus_digest(first) == corpus_digest(second)
    assert corpus_digest(first).startswith("sha256:")


def test_tenant_and_branch_isolation() -> None:
    corpus = generate_corpus()
    primary = isolate_items(corpus, tenant_id="scale-tenant-a", branch="main")
    other_tenant = isolate_items(corpus, tenant_id="scale-tenant-b", branch="main")
    other_branch = isolate_items(corpus, tenant_id="scale-tenant-a", branch="dev")

    assert primary
    assert other_tenant
    assert other_branch
    assert {item["tenant_id"] for item in primary} == {"scale-tenant-a"}
    assert {item["branch"] for item in primary} == {"main"}
    assert {item["tenant_id"] for item in other_tenant} == {"scale-tenant-b"}
    assert {item["branch"] for item in other_branch} == {"dev"}
    assert {item["item_id"] for item in primary}.isdisjoint({item["item_id"] for item in other_tenant})
    assert {item["item_id"] for item in primary}.isdisjoint({item["item_id"] for item in other_branch})
    assert len(primary) + len(other_tenant) + len(other_branch) == ITEM_COUNT


def test_index_identity_is_stable_and_bound() -> None:
    first = index_identity()
    second = index_identity()
    assert first == second
    assert first["digest"].startswith("sha256:")
    assert first["indexes"]
    assert first["indexes"] == sorted(first["indexes"])
    assert "evidence_embedding_public_hnsw" in first["indexes"]
    assert "evidence_null_embedding_fallback_idx" in first["indexes"]


def test_queryset_digest_is_deterministic() -> None:
    corpus = generate_corpus()
    first = generate_queryset(corpus)
    second = generate_queryset(corpus)
    assert first == second
    digest = queryset_digest(first)
    assert digest == queryset_digest(second)
    assert digest.startswith("sha256:")
    assert first
    assert all("query_id" in query and "text" in query and "relevant_ids" in query for query in first)


def test_recall_and_ndcg_hooks_reuse_eval_metrics() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = ["b", "e"]
    assert recall_hook(retrieved, relevant, 3) == recall_at_k(retrieved, relevant, 3)
    assert ndcg_hook(retrieved, relevant, 3) == ndcg_at_k(retrieved, relevant, 3)
    assert recall_hook(retrieved, relevant, 3) == 0.5


def test_latency_and_resource_distribution_fields_are_unofficial() -> None:
    receipt = run_synthetic_harness()
    _assert_unofficial_scale_receipt(receipt)
    rows = receipt["distributions"]
    assert rows
    for row in rows:
        for field in ("name", "sample_count", "p50_ms", "p95_ms", "p99_ms", "official_claim", "asserted"):
            assert field in row, f"distribution missing {field}"
        assert row["official_claim"] is False
        assert row["asserted"] is False
    resources = receipt["resources"]
    for sample_name in ("before", "after"):
        sample = resources[sample_name]
        for field in (
            "total_memory_bytes",
            "free_memory_bytes",
            "available_memory_bytes",
            "swap_bytes",
            "process_rss_bytes",
            "process_pss_or_working_set_bytes",
            "vram_bytes",
            "disk_bytes",
            "network_bytes",
            "load_averages",
            "cpu_seconds",
        ):
            assert field in sample, f"resource {sample_name} missing {field}"
    assert resources["during"]
    assert "memory_pressure" in resources
    assert "swap_pagefile_delta" in resources
    assert "disk_index_growth" in resources
    assert "first_abort" in resources


def test_erasure_removes_live_items_and_blocks_replay() -> None:
    corpus = generate_corpus()
    target = isolate_items(corpus, tenant_id="scale-tenant-a", branch="main")[0]
    erased = erase_items(corpus, [target["item_id"]])
    assert erased["erased_count"] == 1
    live = isolate_items(corpus, tenant_id=target["tenant_id"], branch=target["branch"])
    assert target["item_id"] not in {item["item_id"] for item in live}
    replay = erase_items(corpus, [target["item_id"]])
    assert replay["erased_count"] == 0
    assert replay["already_erased"] == 1


def test_cache_invalidates_after_erasure() -> None:
    corpus = generate_corpus()
    query = generate_queryset(corpus)[0]
    first = query_cached(corpus, query)
    assert first["cache_hit"] is False
    second = query_cached(corpus, query)
    assert second["cache_hit"] is True
    assert second["hits"] == first["hits"]
    if first["hits"]:
        erase_items(corpus, [first["hits"][0]])
    else:
        erase_items(corpus, [query["relevant_ids"][0]])
    third = query_cached(corpus, query)
    assert third["cache_hit"] is False
    assert third["hits"] != first["hits"]


def test_fallback_uses_shared_postgres_cap() -> None:
    corpus = generate_corpus()
    k = 5
    result = fallback_candidates(corpus, k)
    assert result["limit"] == _null_embedding_fallback_limit(k)
    assert result["observed"] >= 0
    assert result["returned"] <= result["limit"]
    assert result["truncated"] is (result["observed"] > result["limit"])
    assert result["control"] == "_null_embedding_fallback_limit"


def test_zero_unaccounted_null_embeddings() -> None:
    corpus = generate_corpus()
    accounting = account_embeddings(corpus)
    assert accounting["live_rows"] + accounting["erased_rows"] == ITEM_COUNT
    assert accounting["stored_vectors"] + accounting["embeddable_null_embeddings"] + accounting[
        "none_partition_rows"
    ] + accounting["erased_rows"] == ITEM_COUNT
    assert accounting["unaccounted_null_embeddings"] == 0
    assert accounting["embeddable_null_embeddings"] == accounting["accounted_null_embeddings"]


def test_setup_index_backfill_are_separated_from_query_time() -> None:
    receipt = run_synthetic_harness()
    phases = receipt["phases"]
    for name in ("setup", "index", "backfill"):
        assert phases[name]["excluded_from_query_time"] is True
        assert phases[name]["duration_ms"] >= 0
    assert phases["query"]["excluded_from_query_time"] is False
    query_time = receipt["query_time"]
    assert query_time["includes_setup"] is False
    assert query_time["includes_index"] is False
    assert query_time["includes_backfill"] is False
    assert query_time["duration_ms"] == phases["query"]["duration_ms"]


def test_before_after_counts_and_rollback_noop_proof() -> None:
    receipt = run_synthetic_harness()
    before = receipt["counts"]["before"]
    after = receipt["counts"]["after"]
    for side in (before, after):
        for field in (
            "live_rows",
            "embeddable_null_embeddings",
            "stored_vectors",
            "none_partition_rows",
            "erased_rows",
        ):
            assert field in side
    assert before["live_rows"] == ITEM_COUNT
    backfill = receipt["backfill"]
    assert backfill["control"] == "vector_backfill_apply"
    assert backfill["second_path"] is False
    assert backfill["production_authorized"] is False
    assert backfill["applied"] is False
    assert backfill["no_op"] is True
    assert backfill["rollback_proof"] is True
    gate = production_backfill_gate(operator_authorized=False)
    assert gate["allowed"] is False
    assert gate["reason"] == "operator_window_required"


def test_committed_receipt_is_harness_ready_stub_not_measured_cap006() -> None:
    assert COMMITTED_RECEIPT == PHASE15_S4_100K_REPORT
    payload = json.loads(COMMITTED_RECEIPT.read_text(encoding="utf-8"))
    _assert_unofficial_scale_receipt(payload)
    identity = payload["identity"]
    assert identity["workload"] == WORKLOAD_ID
    assert identity["item_count"] == ITEM_COUNT
    assert identity["based_on_sha"] == "e32e1cb7ceb455ffbfd06ddc6c0bd2d526bfe4d4"
    assert "admitted_100k_measurement_missing" in payload["blockers"]
    assert "production_backfill_operator_window_missing" in payload["blockers"]
    distributions = payload.get("distributions") or []
    for row in distributions:
        assert row.get("official_claim") is False
        assert row.get("asserted") is False
        assert row.get("p95_ms") is None
