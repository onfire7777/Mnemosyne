"""SqliteEngine embedding cache (A1) + cached-PPR projection + projection
registry (Phase-2 Task 8).

Covers the retired embedding cache (never written any more; admission matrix and
purge rails for rows left in existing stores, privacy class 13), the cached-PPR
projection served by ``graph_ppr(use_cache=True)`` (signature parity with the
live traversal, ``graph_signal_cached`` metadata, fingerprint-mismatch recompute,
and the TOCTOU capture-before-rebuild handoff), the FTS5 rebuildable projection,
and the optional sqlite-vec vec0 dense channel (skip-guarded when the extra is
absent). The default dense channel stays the packed-BLOB kernel exact scan.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from mnemosyne.models import Evidence, Relation
from mnemosyne.retrieval import HashingEmbeddingProvider
from mnemosyne.sqlite_engine import SqliteEngine, sqlite_vec_available

# --- helpers ----------------------------------------------------------------


def _seed_cache(engine: SqliteEngine, tenant: str, cid: str) -> None:
    """A row as an older build's mirror left it (nothing writes the table now)."""
    conn = engine._connect(tenant)
    with conn:
        conn.execute(
            "INSERT INTO embedding_cache (tenant_id, cache_key, model_id, embedding, dims, created_at) "
            "VALUES (?, ?, 'legacy-model', x'00', 1, '')",
            (tenant, cid),
        )


def _cache_rows(engine: SqliteEngine, tenant: str, cid: str) -> int:
    return engine._connect(tenant).execute(
        "SELECT COUNT(*) FROM embedding_cache WHERE tenant_id = ? AND cache_key = ?", (tenant, cid)
    ).fetchone()[0]


def _append(
    engine: SqliteEngine,
    tenant: str,
    user: str,
    content: str,
    *,
    sensitivity: int = 0,
    access_policy: dict | None = None,
    source_type: str = "chat",
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type=source_type,
            content=content,
            sensitivity=sensitivity,
            access_policy=access_policy if access_policy is not None else {"tenant": tenant},
        )
    )


def _seed_graph(engine: SqliteEngine, tenant: str, user: str) -> tuple[str, str]:
    """The contract-suite's proven cached-PPR shape (S0 evidence so the relation
    survives the default-reader security gate). Returns (seed, relation_id)."""
    cid = _append(
        engine,
        tenant,
        user,
        "Cached graph PPR seed evidence links a materialized seed to its target.",
    )
    seed = f"cached ppr seed {uuid4()}"
    rid = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source=seed,
            predicate="points_to",
            target="cached ppr target",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )
    return seed, rid


def _sig(hits) -> list[tuple]:
    return [(h.id, h.channel, h.text, round(h.score, 8), tuple(h.provenance)) for h in hits]


# --- schema -----------------------------------------------------------------


def test_task8_tables_present_and_absent_from_export(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    conn = engine._connect("t1")
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"embedding_cache", "graph_ppr_cache"} <= names
    # the caches are pure derived state — never surfaced by export (parity safety)
    export = engine.export_tenant("t1")
    assert "embedding_cache" not in export
    assert "graph_ppr_cache" not in export


# --- embedding cache: admission matrix --------------------------------------


def test_embedding_cache_admission_matrix(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    admits = engine._embedding_cache_admits
    # S0/S1/S2 with a usable partition are admitted (S2 cid is subject-salted).
    assert admits(sensitivity=0, access_policy={}) is True
    assert admits(sensitivity=1, access_policy={"tenant": "t"}) is True
    assert admits(sensitivity=2, access_policy={"tenant": "t"}) is True
    # S3 fails closed (no sensitive-embedding deployment flag exists); S4 never.
    assert admits(sensitivity=3, access_policy={"tenant": "t"}) is False
    assert admits(sensitivity=4, access_policy={"tenant": "t"}) is False
    # none-partition rails: embed_ok:false / restricted / hold / hold:* / unknown.
    assert admits(sensitivity=0, access_policy={"embed_ok": False}) is False
    assert admits(sensitivity=0, access_policy={"restricted": True}) is False
    assert admits(sensitivity=0, access_policy={"hold": True}) is False
    assert admits(sensitivity=0, access_policy={"hold:legal": True}) is False
    assert admits(sensitivity=0, access_policy={"totally_unknown_key": 1}) is False
    # erased/non-live rows are never admitted.
    assert admits(sensitivity=0, access_policy={}, erased=True) is False


def test_set_embedding_does_not_write_a_second_copy(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    cid = _append(engine, tenant, "u", "public admissible content", sensitivity=1)
    assert engine.set_evidence_embedding(tenant, cid, [0.1, 0.2, 0.3, 0.4]) is True
    assert engine.get_evidence(tenant, cid).embedding == [0.1, 0.2, 0.3, 0.4]
    assert _cache_rows(engine, tenant, cid) == 0


# --- embedding cache: privacy class 13 --------------------------------------


def test_class13_purge_leaves_no_cid_recoverable_trace(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    content = "erase me: ssn 987-65-4321 confidential"
    cid = _append(engine, tenant, "alice", content, sensitivity=2)
    _seed_cache(engine, tenant, cid)
    conn = engine._connect(tenant)

    assert engine.purge_embedding_cache(tenant, cid) == 1

    # sha256(guess) finds no confirmation: keys are subject-salted cids, never a
    # plain content hash, and the purged row is gone entirely.
    plain_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert cid != plain_hash
    by_guess = conn.execute(
        "SELECT COUNT(*) FROM embedding_cache WHERE cache_key = ?", (plain_hash,)
    ).fetchone()[0]
    assert by_guess == 0
    total = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
    assert total == 0


# --- embedding cache: restriction/hold purge rails --------------------------


def test_backfill_privacy_purges_cached_embedding(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    cid = _append(engine, tenant, "u", "email me at user@example.com please", sensitivity=1)
    _seed_cache(engine, tenant, cid)
    # privacy backfill raises sensitivity + restricts → cache must be purged.
    assert engine.backfill_evidence_privacy(tenant, cid, ["email"], pii_sensitivity=3) is True
    assert _cache_rows(engine, tenant, cid) == 0


def test_update_metadata_purges_cache_on_hold_but_not_on_benign_patch(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"

    benign = _append(engine, tenant, "u", "benign patch target", sensitivity=1)
    _seed_cache(engine, tenant, benign)
    engine.update_evidence_metadata(tenant, benign, {"topic": "weather"})
    assert _cache_rows(engine, tenant, benign) == 1  # kept

    held = _append(engine, tenant, "u", "hold patch target", sensitivity=1)
    _seed_cache(engine, tenant, held)
    engine.update_evidence_metadata(tenant, held, {"hold": True})
    assert _cache_rows(engine, tenant, held) == 0  # purged


# --- cached-PPR projection --------------------------------------------------


def test_cached_ppr_served_with_graph_signal_cached_metadata(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    seed, rid = _seed_graph(engine, tenant, "u")

    live = engine.graph_ppr([seed], 1, tenant_id=tenant, branch="main")
    report = engine.refresh_graph_ppr_cache([seed], 1, tenant_id=tenant, branch="main")
    cached = engine.graph_ppr([seed], 1, tenant_id=tenant, branch="main", use_cache=True)

    assert report["refreshed"] is True
    assert report["hit_count"] == len(live) == 1
    assert set(report) >= {"refreshed", "hit_count", "seed_hash", "as_of_key", "relation_fingerprint"}
    assert rid in {h.id for h in cached}
    # signature-identical to the live traversal, but carries the cached marker.
    assert _sig(cached) == _sig(live)
    assert all(h.metadata.get("graph_signal_cached") is True for h in cached)
    assert all(h.metadata.get("graph_signal_cached") is None for h in live)


def test_cached_ppr_default_and_unpopulated_match_live(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    seed, _ = _seed_graph(engine, tenant, "u")
    live = engine.graph_ppr([seed], 5, tenant_id=tenant, branch="main")
    # unpopulated cache: use_cache=True falls through to a byte-identical live path
    uncached = engine.graph_ppr([seed], 5, tenant_id=tenant, branch="main", use_cache=True)
    assert _sig(uncached) == _sig(live)
    assert all(h.metadata.get("graph_signal_cached") is None for h in uncached)


def test_cached_ppr_fingerprint_mismatch_triggers_live_recompute(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    seed, _ = _seed_graph(engine, tenant, "u")
    cid = _append(engine, tenant, "u", "second relation source evidence link.")
    engine.refresh_graph_ppr_cache([seed], 1, tenant_id=tenant, branch="main")

    rid2 = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source=seed,
            predicate="points_new",
            target="cached ppr changed target",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )
    live = engine.graph_ppr([seed], 10, tenant_id=tenant, branch="main")
    cached = engine.graph_ppr([seed], 10, tenant_id=tenant, branch="main", use_cache=True)
    # stale payload (pre-change fingerprint) is not served → live recompute.
    assert rid2 in {h.id for h in cached}
    assert _sig(cached) == _sig(live)
    assert all(h.metadata.get("graph_signal_cached") is None for h in cached)


def test_refresh_graph_ppr_cache_rejects_missing_seed_or_tenant(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    assert engine.refresh_graph_ppr_cache([], 5, tenant_id="t")["refreshed"] is False
    assert engine.refresh_graph_ppr_cache(["seed"], 5, tenant_id=None)["refreshed"] is False


def test_elevated_context_bypasses_cache(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    seed, _ = _seed_graph(engine, tenant, "u")
    engine.refresh_graph_ppr_cache([seed], 1, tenant_id=tenant, branch="main")
    assert engine._is_default_reader_context(None) is True
    assert engine._is_default_reader_context({"tenant_id": tenant}) is True
    assert engine._is_default_reader_context({"include_quarantined": True}) is False
    assert engine._is_default_reader_context({"role": "admin"}) is False
    # an elevated context never serves the materialized (default-reader) payload.
    elevated = engine.graph_ppr(
        [seed], 1, tenant_id=tenant, branch="main", use_cache=True, filt={"include_quarantined": True}
    )
    assert all(h.metadata.get("graph_signal_cached") is None for h in elevated)


# --- registry TOCTOU: fingerprint captured BEFORE rebuild -------------------


def test_cached_ppr_captures_fingerprint_before_rebuild(tmp_path: Path) -> None:
    tenant = "t"

    mutated = {"done": False}

    class _MutatingEngine(SqliteEngine):
        def _compute_graph_ppr(self, seeds, k, **kwargs):  # type: ignore[override]
            hits = super()._compute_graph_ppr(seeds, k, **kwargs)
            # mutate the graph AFTER the pre-rebuild fingerprint was captured but
            # BEFORE the payload is written — the TOCTOU window.
            if not mutated["done"]:
                mutated["done"] = True
                self.add_relation(
                    Relation(
                        tenant_id=tenant,
                        source=seed,
                        predicate="raced_in",
                        target="cached ppr raced target",
                        source_evidence_cids=[cid],
                        access_policy={"tenant": tenant},
                    )
                )
            return hits

    engine = _MutatingEngine(tmp_path / "root")
    cid = _append(engine, tenant, "u", "toctou seed evidence link.")
    seed = f"cached ppr seed {uuid4()}"
    engine.add_relation(
        Relation(
            tenant_id=tenant,
            source=seed,
            predicate="points_to",
            target="cached ppr target",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )

    fp_before = engine._relations_fingerprint(tenant, "main")
    report = engine.refresh_graph_ppr_cache([seed], 1, tenant_id=tenant, branch="main")
    fp_after = engine._relations_fingerprint(tenant, "main")

    # the mutation happened during compute, so the two fingerprints differ...
    assert fp_after != fp_before
    # ...and the STORED fingerprint is the PRE-rebuild snapshot (capture-before).
    assert report["relation_fingerprint"] == fp_before
    # therefore the next read recomputes (mismatch) rather than serving a payload
    # that never reflected a consistent graph snapshot.
    served = engine.graph_ppr([seed], 1, tenant_id=tenant, branch="main", use_cache=True)
    assert all(h.metadata.get("graph_signal_cached") is None for h in served)


# --- FTS5 rebuildable projection --------------------------------------------


def _fts_count(engine: SqliteEngine, tenant: str) -> int:
    conn = engine._connect(tenant)
    return conn.execute("SELECT COUNT(*) FROM evidence_fts").fetchone()[0]


def test_evidence_fts_projection_registered_and_rebuilds_on_source_change(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    _append(engine, tenant, "u", "first fts document about lighthouses")

    status = engine.projection_status(tenant)
    assert "evidence-fts" in status and "cached-ppr" in status

    first = engine.ensure_projections(tenant)
    assert first["evidence-fts"] is True  # first-ever run rebuilds
    assert engine.ensure_projections(tenant)["evidence-fts"] is False  # fresh now

    _append(engine, tenant, "u", "second fts document about beacons")
    # a source (evidence) change bumps the fingerprint → rebuild-on-mismatch.
    assert engine.ensure_projections(tenant)["evidence-fts"] is True


def test_rebuild_evidence_fts_repairs_drift(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    _append(engine, tenant, "u", "alpha fts row")
    _append(engine, tenant, "u", "beta fts row")
    assert _fts_count(engine, tenant) == 2

    conn = engine._connect(tenant)
    with conn:
        conn.execute("DELETE FROM evidence_fts")  # simulate index drift
    assert _fts_count(engine, tenant) == 0

    engine._rebuild_evidence_fts(tenant)  # re-derive from evidence rows
    assert _fts_count(engine, tenant) == 2


# --- optional sqlite-vec vec0 dense projection ------------------------------


def test_dense_channel_defaults_to_packed_blob_when_vec_absent(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    assert engine.dense_channel(tenant) == "packed-blob-exact-scan"
    report = engine.dense_channel_report(tenant)
    assert "packed-BLOB" in report
    if not sqlite_vec_available():
        assert "sqlite-vec absent" in report
        # vec0 projection is not even registered when the extra is unavailable.
        assert "evidence-vec0" not in engine.projection_status(tenant)


@pytest.mark.skipif(not sqlite_vec_available(), reason="sqlite-vec extra not installed")
def test_vec0_projection_registered_and_buildable_when_available(tmp_path: Path) -> None:  # pragma: no cover
    engine = SqliteEngine(tmp_path / "root")
    tenant = "t"
    cid = _append(engine, tenant, "u", "vec0 candidate document", sensitivity=0)
    engine.set_evidence_embedding(tenant, cid, [0.1] * HashingEmbeddingProvider.dims)
    assert "evidence-vec0" in engine.projection_status(tenant)
    engine.ensure_projections(tenant)
    assert engine.dense_channel(tenant) in {"sqlite-vec-vec0", "packed-blob-exact-scan"}
