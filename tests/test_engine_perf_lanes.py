"""Lane B2 byte-parity tests for the local/SQLite engine perf work.

Covers four pure-speed changes:

* the LocalMemoryEngine candidate-scan memo (``_candidate_hits`` LRU + clone
  hand-out; kill-switch ``MNEMOSYNE_CANDIDATE_MEMO=0``);
* the SqliteEngine scan-oracle memo (``_scan_oracle`` hydration shared across
  the dense/lexical channels of one retrieve; same kill-switch);
* the ``rrf_fuse`` local-branch reconstruction that replaced
  ``copy.deepcopy`` (proven against a deepcopy reference kept here);
* the graph-PPR node->relation pair index (first-match semantics pinned);
* the default-OFF ``MNEMOSYNE_PARALLEL_CHANNELS`` channel overlap.

Each test proves the optimized path produces results deep-equal to the
previous/pure path — order, scores, and metadata included.
"""

from __future__ import annotations

import copy
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mnemosyne import pipeline as pipeline_mod
from mnemosyne.algorithms import rrf_fuse
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Hit, Preference, Relation
from mnemosyne.sqlite_engine import SqliteEngine

TENANT = "tenant-perf-b2"
USER = "user-perf-b2"
QUERY = "the delivery deadline for project helios"
FROZEN_NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


def _freeze_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin retrieve-time clocks so paired engines compute identical recency/
    read-mark values regardless of wall-clock spacing between the runs."""
    for target in (
        "mnemosyne.models.utc_now",
        "mnemosyne.engine.utc_now",
        "mnemosyne.retrieval.utc_now",
        "mnemosyne.sqlite_engine.utc_now",
    ):
        monkeypatch.setattr(target, lambda: FROZEN_NOW)


def _seed(engine: LocalMemoryEngine | SqliteEngine) -> dict[str, object]:
    cids = [
        engine.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id=USER,
                actor="user",
                source_type="seed",
                content=content,
                trust_tier=0,
                access_policy={"tenant": TENANT},
            )
        )
        for content in (
            "Project Helios has a delivery deadline of Q3 2026.",
            "Mara is assigned to project Helios.",
            "Project Aurora is budgeted at 90k for the year.",
        )
    ]
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject="project helios",
            predicate="has deadline",
            object="Q3 2026",
            source_evidence_cids=[cids[0]],
            confidence=0.9,
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    preference_id = engine.add_preference(
        Preference(
            tenant_id=TENANT,
            user_id=USER,
            category="workflow",
            statement="Track every project delivery deadline in the release plan.",
            explicit=True,
            source_evidence_cids=[cids[0]],
            access_policy={"tenant": TENANT},
        )
    )
    relation_id = engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source="helios",
            predicate="has_deadline",
            target="q3 2026",
            source_evidence_cids=[cids[0]],
            access_policy={"tenant": TENANT},
        )
    )
    return {
        "cids": cids,
        "assertion_id": assertion_id,
        "preference_id": preference_id,
        "relation_id": relation_id,
    }


def _retrieve_sequence(engine: LocalMemoryEngine | SqliteEngine) -> list[dict]:
    """Shallow, shallow-again (post read-marks), then deep — the staleness-
    sensitive sequence: read-marks mutate access counts between calls."""
    return [
        engine.retrieve(QUERY, TENANT).to_dict(),
        engine.retrieve(QUERY, TENANT).to_dict(),
        engine.retrieve(QUERY, TENANT, deep=True).to_dict(),
    ]


# --------------------------------------------------------------------------- #
# Task 1 — LocalMemoryEngine candidate-scan memo
# --------------------------------------------------------------------------- #

def test_local_candidate_memo_byte_identical_and_single_scan_per_retrieve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_time(monkeypatch)
    store = tmp_path / "store.json"
    _seed(LocalMemoryEngine(store_path=store))

    # Both engines load the identical persisted snapshot before any retrieve.
    plain = LocalMemoryEngine(store_path=store)
    memo = LocalMemoryEngine(store_path=store)

    scans = 0
    real_scan = LocalMemoryEngine._candidate_hits_uncached

    def counting_scan(self: LocalMemoryEngine, filt: dict) -> list[Hit]:
        nonlocal scans
        scans += 1
        return real_scan(self, filt)

    monkeypatch.setattr(LocalMemoryEngine, "_candidate_hits_uncached", counting_scan)

    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "0")
    plain_results = _retrieve_sequence(plain)

    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
    scans = 0
    first = memo.retrieve(QUERY, TENANT)
    # The core claim: vector + lexical shared ONE candidate scan.
    assert scans == 1
    memo_results = [
        first.to_dict(),
        memo.retrieve(QUERY, TENANT).to_dict(),
        memo.retrieve(QUERY, TENANT, deep=True).to_dict(),
    ]

    assert memo_results == plain_results


def test_local_candidate_memo_clones_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalMemoryEngine()
    _seed(engine)
    filt = {"tenant_id": TENANT, "branch": "main"}

    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "0")
    baseline = [hit.to_dict() for hit in engine._candidate_hits(filt)]

    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
    first = engine._candidate_hits(filt)
    assert [hit.to_dict() for hit in first] == baseline

    # Channel-style mutation on one caller's hits, including nested metadata.
    first[0].score = 123.0
    first[0].channel = "dense_hash"
    first[0].metadata["stored_embedding_used"] = True
    for value in first[0].metadata.values():
        if isinstance(value, dict):
            value["poisoned"] = True

    second = engine._candidate_hits(filt)
    assert [hit.to_dict() for hit in second] == baseline
    assert all(a is not b for a, b in zip(first, second, strict=True))


def test_local_candidate_memo_invalidates_on_write(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalMemoryEngine()
    _seed(engine)
    filt = {"tenant_id": TENANT, "branch": "main"}

    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
    before = engine._candidate_hits(filt)
    new_cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="seed",
            content="A freshly appended deadline note about project Helios.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    after = engine._candidate_hits(filt)
    assert len(after) == len(before) + 1
    assert new_cid in {hit.id for hit in after}

    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "0")
    uncached = [hit.to_dict() for hit in engine._candidate_hits(filt)]
    assert [hit.to_dict() for hit in after] == uncached


# --------------------------------------------------------------------------- #
# Task 1 (SQLite) — scan-oracle memo
# --------------------------------------------------------------------------- #

def _seed_sqlite_root(root: Path) -> None:
    engine = SqliteEngine(root)
    _seed(engine)
    engine.close()


def test_sqlite_scan_memo_byte_identical_and_single_hydration_per_retrieve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_time(monkeypatch)
    root_plain = tmp_path / "plain"
    _seed_sqlite_root(root_plain)
    root_memo = tmp_path / "memo"
    shutil.copytree(root_plain, root_memo)

    plain = SqliteEngine(root_plain)
    memo = SqliteEngine(root_memo)
    try:
        hydrations = 0
        real_hydrate = SqliteEngine._hydrate_scan_oracle

        def counting_hydrate(self: SqliteEngine, filt: dict):
            nonlocal hydrations
            hydrations += 1
            return real_hydrate(self, filt)

        monkeypatch.setattr(SqliteEngine, "_hydrate_scan_oracle", counting_hydrate)

        monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "0")
        plain_results = _retrieve_sequence(plain)

        monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
        hydrations = 0
        first = memo.retrieve(QUERY, TENANT)
        # The core claim: dense + lexical shared ONE SQL hydration.
        assert hydrations == 1
        memo_results = [
            first.to_dict(),
            memo.retrieve(QUERY, TENANT).to_dict(),
            memo.retrieve(QUERY, TENANT, deep=True).to_dict(),
        ]

        assert memo_results == plain_results
    finally:
        plain.close()
        memo.close()


def test_sqlite_scan_memo_invalidates_on_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    _seed_sqlite_root(root)
    engine = SqliteEngine(root)
    try:
        monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
        filt = {"tenant_id": TENANT, "branch": "main"}
        oracle_before = engine._scan_oracle(filt)
        new_cid = engine.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id=USER,
                actor="user",
                source_type="seed",
                content="A freshly appended deadline note about project Helios.",
                trust_tier=0,
                access_policy={"tenant": TENANT},
            )
        )
        oracle_after = engine._scan_oracle(filt)
        assert oracle_after is not oracle_before
        assert len(oracle_after.evidence) == len(oracle_before.evidence) + 1
        assert any(ev.cid == new_cid for ev in oracle_after.evidence.values())
    finally:
        engine.close()


# --------------------------------------------------------------------------- #
# Task 2 — graph PPR node->relation pair index (first-match semantics)
# --------------------------------------------------------------------------- #

def test_graph_ppr_pair_index_preserves_first_match_semantics() -> None:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="seed",
            content="Graph seed evidence grounding the alpha beta gamma relations.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )

    def relation(source: str, target: str) -> str:
        return engine.add_relation(
            Relation(
                tenant_id=TENANT,
                source=source,
                predicate="linked_to",
                target=target,
                source_evidence_cids=[cid],
                access_policy={"tenant": TENANT},
            )
        )

    r1 = relation("alpha", "beta")
    r2 = relation("beta", "gamma")
    r3 = relation("alpha", "gamma")

    hits = engine.graph_ppr(["alpha"], k=10, tenant_id=TENANT, branch="main")
    hit_ids = [hit.id for hit in hits]

    # Linear-scan first-match order over relation_by_pair insertion:
    # node "beta"  -> earliest pair mentioning it is (alpha, beta)  -> r1;
    # node "gamma" -> earliest pair mentioning it is (beta, gamma)  -> r2;
    # r3 (alpha, gamma) is never first for any ranked node. A last-wins or
    # rebuilt-order index would surface r3 for "gamma" and fail here.
    assert set(hit_ids) == {r1, r2}
    assert r3 not in hit_ids
    assert all(hit.channel == "graph_ppr" for hit in hits)


# --------------------------------------------------------------------------- #
# Task 3 — rrf_fuse local branch: reconstruction equals the old deepcopy
# --------------------------------------------------------------------------- #

def _fuse_hit(hit_id: str, kind: str, channel: str, score: float) -> Hit:
    return Hit(
        id=hit_id,
        kind=kind,  # type: ignore[arg-type]
        tenant_id=TENANT,
        branch="main",
        text=f"text for {hit_id}",
        score=score,
        channel=channel,
        provenance=[f"cid-{hit_id}"],
        trust_tier=1,
        sensitivity=0,
        metadata={
            "confidence": 0.5,
            "privacy": {"redactions": ["r1"], "nested": {"depth": 2}},
            "lifecycle": {"access_count": 3},
        },
    )


def _rrf_fuse_deepcopy_reference(ranked_lists: list[list[Hit]], k: int, *, rrf_k: float) -> list[Hit]:
    """The pre-optimization local branch of rrf_fuse, verbatim (deepcopy)."""
    by_id: dict[tuple[str, str], Hit] = {}
    scores: dict[tuple[str, str], float] = defaultdict(float)
    channels: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            key = (hit.kind, hit.id)
            by_id[key] = hit
            scores[key] += 1.0 / (rrf_k + rank)
            channels[key].append(hit.channel)
    fused = []
    for key, hit in by_id.items():
        item = copy.deepcopy(hit)
        item.score = scores[key]
        item.channel = "+".join(sorted(set(channels[key])))
        fused.append(item)
    return sorted(fused, key=lambda item: item.score, reverse=True)[:k]


def test_rrf_fuse_local_branch_matches_deepcopy_reference() -> None:
    dense = [
        _fuse_hit("e1", "evidence", "dense_hash", 0.9),
        _fuse_hit("a1", "assertion", "dense_hash", 0.7),
        _fuse_hit("e2", "evidence", "dense_hash", 0.5),
    ]
    lexical = [
        _fuse_hit("e2", "evidence", "lexical", 0.8),
        _fuse_hit("e1", "evidence", "lexical", 0.6),
        _fuse_hit("p1", "preference", "lexical", 0.3),
    ]
    graph = [_fuse_hit("r1", "relation", "graph_ppr", 0.4)]
    ranked_lists = [dense, lexical, graph]

    expected = _rrf_fuse_deepcopy_reference(
        [[copy.deepcopy(hit) for hit in ranked] for ranked in ranked_lists], 4, rrf_k=60.0
    )
    actual = rrf_fuse(ranked_lists, 4, rrf_k=60.0)

    assert actual == expected  # dataclass field-by-field equality
    assert [hit.to_dict() for hit in actual] == [hit.to_dict() for hit in expected]


# --------------------------------------------------------------------------- #
# Task 4 — MNEMOSYNE_PARALLEL_CHANNELS (default OFF, byte-identical when ON)
# --------------------------------------------------------------------------- #

def test_parallel_channels_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_PARALLEL_CHANNELS", raising=False)
    assert pipeline_mod.parallel_channels_enabled() is False
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "1")
    assert pipeline_mod.parallel_channels_enabled() is True
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "0")
    assert pipeline_mod.parallel_channels_enabled() is False


def test_parallel_channels_byte_identical_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_time(monkeypatch)
    store = tmp_path / "store.json"
    _seed(LocalMemoryEngine(store_path=store))
    sequential = LocalMemoryEngine(store_path=store)
    parallel = LocalMemoryEngine(store_path=store)

    monkeypatch.delenv("MNEMOSYNE_PARALLEL_CHANNELS", raising=False)
    sequential_results = _retrieve_sequence(sequential)
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "1")
    parallel_results = _retrieve_sequence(parallel)

    assert parallel_results == sequential_results


def test_parallel_channels_byte_identical_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_time(monkeypatch)
    root_seq = tmp_path / "seq"
    _seed_sqlite_root(root_seq)
    root_par = tmp_path / "par"
    shutil.copytree(root_seq, root_par)

    sequential = SqliteEngine(root_seq)
    parallel = SqliteEngine(root_par)
    try:
        monkeypatch.delenv("MNEMOSYNE_PARALLEL_CHANNELS", raising=False)
        sequential_results = _retrieve_sequence(sequential)
        monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "1")
        parallel_results = _retrieve_sequence(parallel)
        assert parallel_results == sequential_results
    finally:
        sequential.close()
        parallel.close()
