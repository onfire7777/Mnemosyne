"""Tests for Incremental O(1) PassageGraph and PassageIndex maintenance."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from mnemosyne.models import Hit
from mnemosyne.passages import (
    PassageGraph,
    PassageIndex,
    PassageRecord,
    rank_passages,
)


def test_passage_record_creation_and_defaults():
    rec = PassageRecord(
        passage_id="p1",
        text="The quick brown fox jumps over the lazy dog.",
        tenant_id="tenant-a",
        branch="main",
        metadata={"session_id": "s1"},
        sensitivity=0,
        disclosable=True,
    )
    assert rec.passage_id == "p1"
    assert rec.text == "The quick brown fox jumps over the lazy dog."
    assert rec.tenant_id == "tenant-a"
    assert rec.branch == "main"
    assert rec.disclosable is True
    assert rec.metadata["session_id"] == "s1"


def test_passage_index_incremental_add_text_ranking_parity():
    """Verify bit-for-bit identical ranking and BM25 scores between full rebuild and add_text."""
    initial_texts = (
        "Alice loves baking artisanal sourdough bread with rye flour.",
        "Bob drives an electric vehicle to work every day.",
        "Charlie enjoys mountain hiking and landscape photography in Colorado.",
        "Diana plays classical piano and violin in a local chamber orchestra.",
    )
    new_texts = (
        "Evan studies quantum mechanics and computational linear algebra.",
        "Fiona cultivates organic heirloom tomatoes and basil in her garden.",
    )
    all_texts = initial_texts + new_texts

    # Cold full build
    cold_index = PassageIndex(all_texts)

    # Incremental build
    incremental_index = PassageIndex(initial_texts)
    for t in new_texts:
        incremental_index.add_text(t)

    assert len(incremental_index.texts) == len(cold_index.texts)
    assert incremental_index.texts == cold_index.texts
    assert incremental_index.lengths == cold_index.lengths
    assert abs(incremental_index.average_length - cold_index.average_length) < 1e-9

    test_queries = [
        "sourdough bread baking",
        "quantum physics and algebra",
        "gardening heirloom tomatoes",
        "classical orchestra piano",
        "electric car daily commute",
    ]

    for q in test_queries:
        cold_scores = cold_index.scores(q)
        inc_scores = incremental_index.scores(q)
        assert set(cold_scores.keys()) == set(inc_scores.keys())
        for idx in cold_scores:
            assert abs(cold_scores[idx] - inc_scores[idx]) < 1e-9, (
                f"Score mismatch for query '{q}' at index {idx}: cold={cold_scores[idx]} vs inc={inc_scores[idx]}"
            )


def test_passage_index_incremental_add_text_speedup():
    """Verify O(L) amortized time: adding one passage is orders of magnitude faster than full corpus rebuild."""
    base_corpus = tuple(f"User episodic log entry number {i} discussing diverse topics and tasks." for i in range(500))
    index = PassageIndex(base_corpus)

    new_doc = "Fresh newly appended passage about astronomy and telescope calibration."

    # Time incremental add
    t0 = time.perf_counter()
    index.add_text(new_doc)
    t_inc = time.perf_counter() - t0

    # Time full cold rebuild of 501 items
    t1 = time.perf_counter()
    _ = PassageIndex(base_corpus + (new_doc,))
    t_cold = time.perf_counter() - t1

    assert t_inc < t_cold
    assert len(index.texts) == 501


def test_passage_graph_add_remove_and_compaction():
    """Test PassageGraph maintenance, live IDF tracking, and dynamic drift compaction."""
    graph = PassageGraph()
    assert graph._total_passages == 0

    p1 = PassageRecord(
        passage_id="p1",
        text="Apples and oranges are delicious fresh fruits.",
        tenant_id="t1",
        branch="main",
    )
    p2 = PassageRecord(
        passage_id="p2",
        text="Oranges contain high amounts of vitamin C.",
        tenant_id="t1",
        branch="main",
    )
    p3 = PassageRecord(
        passage_id="p3",
        text="Bananas and apples make a healthy morning breakfast smoothie.",
        tenant_id="t1",
        branch="main",
    )

    graph.add_passage(p1)
    graph.add_passage(p2)
    graph.add_passage(p3)

    assert graph._total_passages == 3
    # Live IDF: 'oranges' appears in 2 of 3 docs, 'apples' in 2 of 3, 'smoothie' in 1 of 3
    idf_oranges = graph.get_live_idf("oranges")
    idf_smoothie = graph.get_live_idf("smoothie")
    assert idf_smoothie > idf_oranges, "Rare term 'smoothie' should have higher IDF than 'oranges'"

    # Compaction check: mutations = 3, total = 3 -> drift = 1.0 >= 0.25
    compacted = graph.check_and_compact(drift_threshold=0.25)
    assert compacted is True
    assert graph._mutations_since_compaction == 0

    # Below threshold
    compacted_again = graph.check_and_compact(drift_threshold=0.25)
    assert compacted_again is False

    # Remove passage
    graph.remove_passage("p2")
    assert graph._total_passages == 2
    assert "p2" not in graph._passage_records
    # Invalidation
    graph.invalidate_for_mutation("t1", "main")
    assert graph._branch_watermarks[("t1", "main")] > 0


def test_rank_passages_reuses_cached_index_incrementally():
    """Verify rank_passages reuses owner's PassageIndex and appends texts incrementally."""
    class DummyOwner:
        pass

    owner = DummyOwner()
    dt1 = datetime(2023, 5, 1, 12, 0, tzinfo=timezone.utc)
    dt2 = datetime(2023, 5, 2, 12, 0, tzinfo=timezone.utc)
    dt3 = datetime(2023, 5, 3, 12, 0, tzinfo=timezone.utc)

    cands_initial = [
        Hit(
            id="c1",
            kind="evidence",
            text="First session discussing project architecture and microservices.",
            score=1.0,
            tenant_id="t",
            branch="main",
            channel="test",
            metadata={"created_at": dt1},
        ),
        Hit(
            id="c2",
            kind="evidence",
            text="Second session configuring Docker containers and continuous integration.",
            score=1.0,
            tenant_id="t",
            branch="main",
            channel="test",
            metadata={"created_at": dt2},
        ),
    ]

    ranked1 = rank_passages(owner, "project architecture", cands_initial, k=5)
    assert len(ranked1) == 1
    cached_idx = getattr(owner, "_passage_bm25_index", None)
    assert cached_idx is not None
    assert len(cached_idx.texts) == 2

    # Append a 3rd candidate
    cands_extended = list(cands_initial) + [
        Hit(
            id="c3",
            kind="evidence",
            text="Third session on Kubernetes orchestration and cloud deployments.",
            score=1.0,
            tenant_id="t",
            branch="main",
            channel="test",
            metadata={"created_at": dt3},
        )
    ]

    ranked2 = rank_passages(owner, "Kubernetes orchestration", cands_extended, k=5)
    assert len(ranked2) == 1
    # Check that owner index was incrementally grown, not re-allocated
    assert getattr(owner, "_passage_bm25_index") is cached_idx
    assert len(cached_idx.texts) == 3
    assert isinstance(cached_idx._texts, list)
    assert getattr(owner, "_passage_graph") is cached_idx.passage_graph
    assert cached_idx.passage_graph._total_passages == 3


def test_passage_graph_add_duplicate_passage_id_replacement():
    """Verify that adding a passage with an existing passage_id cleanly replaces it without inflating counts."""
    g = PassageGraph()
    p1 = PassageRecord("p-duplicate", "initial distinct alpha beta words", tenant_id="tenant-x", branch="main")
    g.add_passage(p1)

    assert g._total_passages == 1
    assert len(g._passage_records) == 1
    assert g._doc_frequencies["alpha"] == 1
    assert g._doc_frequencies["beta"] == 1

    # Re-add with same ID but different text
    p2 = PassageRecord("p-duplicate", "updated gamma delta words", tenant_id="tenant-x", branch="main")
    g.add_passage(p2)

    assert g._total_passages == 1
    assert len(g._passage_records) == 1
    assert g._passage_records["p-duplicate"].text == "updated gamma delta words"
    # Old unique tokens must be cleaned up
    assert "alpha" not in g._doc_frequencies
    assert "beta" not in g._doc_frequencies
    # New unique tokens must be tracked
    assert g._doc_frequencies["gamma"] == 1
    assert g._doc_frequencies["delta"] == 1
    # Shared token count must remain 1, not 2
    assert g._doc_frequencies["words"] == 1

    # Remove passage
    g.remove_passage("p-duplicate")
    assert g._total_passages == 0
    assert len(g._passage_records) == 0
    assert len(g._doc_frequencies) == 0

    # Redundant remove must be a no-op, not decrement below 0
    g.remove_passage("p-duplicate")
    assert g._total_passages == 0
    assert len(g._passage_records) == 0

