"""SqliteEngine.forget — full erasure wiring (Phase-2 Task 9).

Mode matrix (tombstone_recompute vs hard_delete_legal) across journal
tombstone/purge, embedding-cache purge, targeted projection invalidation,
deletion_log HMAC (spec §7 invariant 13), and erased-replay blocklist survival;
plus ledger-rebuild ≡ journal-rebuild, the min_corroboration guard vs the
legal-blind bypass, cascade-asymmetry parity, and forget return-shape parity —
all against the ``LocalMemoryEngine`` oracle.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.journal import CIDJournal, journal_filename
from mnemosyne.models import Assertion, Evidence, Preference, Relation
from mnemosyne.privacy import ErasureMode
from mnemosyne.sqlite_engine import SqliteEngine

TOMBSTONE = ErasureMode.TOMBSTONE_RECOMPUTE
HARD = ErasureMode.HARD_DELETE_LEGAL


def _ev(tenant: str, content: str, **over) -> Evidence:
    base = dict(
        tenant_id=tenant,
        user_id="user-1",
        actor="user",
        source_type="chat",
        content=content,
        access_policy={"tenant": tenant},
    )
    base.update(over)
    return Evidence(**base)


def _make(root: Path, journal: Path | None = None) -> SqliteEngine:
    return SqliteEngine(root, journal_dir=journal)


def _build_cascade(engine, tenant: str) -> tuple[str, str]:
    """Single-source target ``c`` + independent corroborator ``c2``; assertions,
    a relation, a preference and an entity all reference ``c`` (some solely)."""
    c = engine.append_evidence(_ev(tenant, "Alpha grounding fact about the orchid."))
    c2 = engine.append_evidence(_ev(tenant, "Beta independent corroborator fact."))
    engine.upsert_assertion(
        Assertion(tenant_id=tenant, user_id="user-1", subject="orchid", predicate="is",
                  object="rare", confidence=0.9, status="active", source_evidence_cids=[c])
    )
    engine.upsert_assertion(
        Assertion(tenant_id=tenant, user_id="user-1", subject="garden", predicate="has",
                  object="orchid", confidence=0.9, status="active", source_evidence_cids=[c, c2])
    )
    engine.add_relation(
        Relation(tenant_id=tenant, source="orchid", predicate="in", target="garden",
                 source_evidence_cids=[c])
    )
    engine.add_preference(
        Preference(tenant_id=tenant, user_id="user-1", category="tone", statement="be terse",
                   source_evidence_cids=[c])
    )
    engine.register_entity(tenant, "Orchid", source_evidence_cids=[c], access_policy={"tenant": tenant})
    return c, c2


def _journal_records(journal_dir: Path, tenant: str) -> list[dict]:
    return list(CIDJournal(journal_dir / journal_filename(tenant)).records())


def _ledger_state(engine: SqliteEngine, tenant: str, branch: str = "main") -> dict[str, dict]:
    """Read the evidence TABLE directly (export hides erased rows, Local-parity),
    so tombstone rows are visible for ledger-vs-journal rebuild equivalence."""
    conn = engine._connect(tenant)
    return {
        row["cid"]: {"content": row["content"], "erased": bool(row["erased"])}
        for row in conn.execute(
            "SELECT cid, content, erased FROM evidence WHERE tenant_id = ? AND branch = ? ORDER BY rowid",
            (tenant, branch),
        )
    }


def _embedding_cache_count(engine: SqliteEngine, tenant: str, cid: str) -> int:
    conn = engine._connect(tenant)
    row = conn.execute(
        "SELECT COUNT(*) FROM embedding_cache WHERE tenant_id = ? AND cache_key = ?", (tenant, cid)
    ).fetchone()
    return int(row[0])


def _ppr_cache_count(engine: SqliteEngine, tenant: str, branch: str = "main") -> int:
    conn = engine._connect(tenant)
    row = conn.execute(
        "SELECT COUNT(*) FROM graph_ppr_cache WHERE tenant_id = ? AND branch = ?", (tenant, branch)
    ).fetchone()
    return int(row[0])


# --- return-shape parity -----------------------------------------------------


def test_forget_evidence_not_found_shape_matches_local(tmp_path: Path):
    sqlite = _make(tmp_path / "root")
    local = LocalMemoryEngine()
    missing = "a" * 64
    s = sqlite.forget("t", missing)
    ell = local.forget("t", missing)
    assert s == ell == {"erased": False, "reason": "evidence_not_found", "cid": missing,
                        "erasure_mode": "tombstone_recompute"}


@pytest.mark.parametrize("mode", [TOMBSTONE, HARD])
def test_forget_success_return_shape_matches_local(tmp_path: Path, mode: ErasureMode):
    sqlite = _make(tmp_path / "root")
    local = LocalMemoryEngine()
    cs = sqlite.append_evidence(_ev("t", "Return-shape parity evidence."))
    cl = local.append_evidence(_ev("t", "Return-shape parity evidence."))
    rs = sqlite.forget("t", cs, requested_by="legal", erasure_mode=mode)
    rl = local.forget("t", cl, requested_by="legal", erasure_mode=mode)
    assert set(rs) == set(rl) == {"erased", "cid", "erasure_mode", "propagated"}
    assert rs["erased"] is rl["erased"] is True
    assert rs["erasure_mode"] == rl["erasure_mode"] == mode.value
    assert set(rs["propagated"]) == set(rl["propagated"])


# --- tombstone_recompute -----------------------------------------------------


def test_tombstone_hides_evidence_keeps_row_and_journal_marker(tmp_path: Path):
    jdir = tmp_path / "j"
    engine = _make(tmp_path / "root", jdir)
    cid = engine.append_evidence(_ev("t", "Tombstone me but keep the row."))
    result = engine.forget("t", cid, erasure_mode=TOMBSTONE)

    assert result["erased"] is True
    assert engine.get_evidence("t", cid) is None  # hidden from reads
    export = engine.export_tenant("t")
    assert all(item["cid"] != cid for item in export["evidence"])  # export hides erased rows
    # ...but the tombstone row is retained in the ledger table (content shredded);
    # that surviving erased row IS the replay blocklist.
    ledger = _ledger_state(engine, "t")
    assert ledger[cid]["erased"] is True and ledger[cid]["content"] == ""
    # deletion_log keeps the cid (the tombstone row still exists).
    entry = export["deletion_log"][-1]
    assert entry["evidence_cid"] == cid and entry["erasure_mode"] == "tombstone_recompute"
    # journal line is a salted-hash marker, no plaintext.
    recs = {r["cid"]: r for r in _journal_records(jdir, "t")}
    assert recs[cid].get("erased") is True
    assert "salted_hash" in recs[cid] and "content" not in recs[cid]


def test_tombstone_blocklist_survives_replay(tmp_path: Path):
    engine = _make(tmp_path / "root")
    content = "Erased-replay blocklist content."
    cid = engine.append_evidence(_ev("t", content))
    engine.forget("t", cid, erasure_mode=TOMBSTONE)
    # Re-ingesting the identical content is blocked and reuses the erased cid.
    replay = engine.append_evidence(_ev("t", content))
    assert replay == cid
    assert engine.get_evidence("t", cid) is None  # still erased, never resurrected
    assert _ledger_state(engine, "t")[cid]["erased"] is True


# --- hard_delete_legal -------------------------------------------------------


def test_hard_delete_removes_row_and_purges_journal(tmp_path: Path):
    jdir = tmp_path / "j"
    engine = _make(tmp_path / "root", jdir)
    cid = engine.append_evidence(_ev("t", "Legal shred target."))
    result = engine.forget("t", cid, requested_by="legal", erasure_mode=HARD)

    assert result["erased"] is True
    assert engine.get_evidence("t", cid) is None
    export = engine.export_tenant("t")
    assert all(item["cid"] != cid for item in export["evidence"])  # row gone
    assert _journal_records(jdir, "t") == []  # journal line purged


def test_hard_delete_deletion_log_uses_hmac_not_cid(tmp_path: Path):
    engine = _make(tmp_path / "root")
    cid = engine.append_evidence(_ev("t", "HMAC deletion-id target."))
    engine.forget("t", cid, requested_by="legal", erasure_mode=HARD)
    entry = engine.export_tenant("t")["deletion_log"][-1]
    assert entry["erasure_mode"] == "hard_delete_legal"
    assert entry["evidence_cid"] != cid  # cid replaced by the HMAC id
    assert len(entry["evidence_cid"]) == 64


def test_class13_sha256_guess_finds_no_cid_in_deletion_log(tmp_path: Path):
    """Spec §7 invariant 13: after a hard delete, no retained deletion record
    exposes the cid, nor any sha256 of guessable inputs that could confirm it."""
    engine = _make(tmp_path / "root")
    content = "Confidential SSN 123-45-6789 to be legally shredded."
    cid = engine.append_evidence(_ev("t", content))
    engine.forget("t", cid, requested_by="legal", erasure_mode=HARD)
    deletion_log = engine.export_tenant("t")["deletion_log"]
    guesses = {
        cid,
        hashlib.sha256(content.encode()).hexdigest(),
        hashlib.sha256(cid.encode()).hexdigest(),
    }
    assert all(entry["evidence_cid"] not in guesses for entry in deletion_log)


# --- erasure propagation: embedding cache + projections ----------------------


@pytest.mark.parametrize("mode", [TOMBSTONE, HARD])
def test_embedding_cache_purged_both_modes(tmp_path: Path, mode: ErasureMode):
    engine = _make(tmp_path / "root")
    cid = engine.append_evidence(_ev("t", "Cached-vector target evidence."))
    engine.cached_embedding("t", cid, "Cached-vector target evidence.",
                            sensitivity=0, access_policy={"tenant": "t"}, store=True)
    assert _embedding_cache_count(engine, "t", cid) == 1
    engine.forget("t", cid, requested_by="legal", erasure_mode=mode)
    assert _embedding_cache_count(engine, "t", cid) == 0  # privacy class 13


@pytest.mark.parametrize("mode", [TOMBSTONE, HARD])
def test_graph_ppr_cache_invalidated_on_forget(tmp_path: Path, mode: ErasureMode):
    engine = _make(tmp_path / "root")
    c, _c2 = _build_cascade(engine, "t")
    engine.refresh_graph_ppr_cache(["orchid"], 8, tenant_id="t", branch="main")
    assert _ppr_cache_count(engine, "t") >= 1
    engine.forget("t", c, requested_by="legal", erasure_mode=mode)
    assert _ppr_cache_count(engine, "t") == 0  # targeted invalidation of the branch's rows


# --- ledger-rebuild ≡ journal-rebuild ---------------------------------------


@pytest.mark.parametrize("mode", [TOMBSTONE, HARD])
def test_ledger_rebuild_equals_journal_rebuild(tmp_path: Path, mode: ErasureMode):
    """The journal and the ledger agree on which cids are live vs erased/absent
    after erasure, in both modes (a rebuild from either yields the same state)."""
    jdir = tmp_path / "j"
    engine = _make(tmp_path / "root", jdir)
    c, c2 = _build_cascade(engine, "t")
    engine.forget("t", c, requested_by="legal", erasure_mode=mode)

    # Ledger view: the evidence table (tombstone rows retained, erased flagged).
    ledger = {cid: state["erased"] for cid, state in _ledger_state(engine, "t").items()}
    # Journal view: a purged cid is absent; a tombstoned cid carries erased=True.
    journal = {r["cid"]: bool(r.get("erased")) for r in _journal_records(jdir, "t")}

    assert set(journal) == set(ledger)  # same cids present in both
    live_ledger = {cid for cid, erased in ledger.items() if not erased}
    live_journal = {cid for cid, erased in journal.items() if not erased}
    assert live_ledger == live_journal == {c2}
    if mode is HARD:
        assert c not in ledger and c not in journal  # both dropped the row entirely


# --- guard vs legal-blind ----------------------------------------------------


def test_min_corroboration_guard_blocks_operator_hard_delete_parity(tmp_path: Path):
    sqlite = _make(tmp_path / "root")
    local = LocalMemoryEngine()
    cs, _ = _build_cascade(sqlite, "t")
    cl, _ = _build_cascade(local, "t")
    rs = sqlite.forget("t", cs, requested_by="operator", erasure_mode=HARD)
    rl = local.forget("t", cl, requested_by="operator", erasure_mode=HARD)
    assert rs["erased"] is rl["erased"] is False
    assert rs["reason"] == rl["reason"] == "min_corroboration_for_delete"
    assert rs["min_corroboration_for_delete"] == rl["min_corroboration_for_delete"]
    assert len(rs["blocking_assertions"]) == len(rl["blocking_assertions"]) == 1
    # Refusal has no side effects: the row is untouched.
    assert sqlite.get_evidence("t", cs) is not None


def test_legal_blind_bypasses_guard(tmp_path: Path):
    engine = _make(tmp_path / "root")
    c, _c2 = _build_cascade(engine, "t")
    # Operator is blocked; legal shreds regardless (corroboration-blind).
    assert engine.forget("t", c, requested_by="operator", erasure_mode=HARD)["erased"] is False
    result = engine.forget("t", c, requested_by="legal", erasure_mode=HARD)
    assert result["erased"] is True
    assert engine.get_evidence("t", c) is None


# --- cascade-asymmetry parity vs Local --------------------------------------


def test_cascade_asymmetry_shape_parity_vs_local(tmp_path: Path):
    """The tombstone cascade shape matches Local's exactly: branch-scoped
    assertions/relations and tenant-scoped preferences/entities all cascade with
    the same category counts (exact ids/timestamps are per-instance volatile, so
    parity is on cascade shape — the meaningful invariant)."""
    sqlite = _make(tmp_path / "root")
    local = LocalMemoryEngine()
    cs, _ = _build_cascade(sqlite, "t")
    cl, _ = _build_cascade(local, "t")
    assert cs == cl  # deterministic subject-scoped cid
    ps = sqlite.forget("t", cs, erasure_mode=TOMBSTONE)["propagated"]
    pl = local.forget("t", cl, erasure_mode=TOMBSTONE)["propagated"]

    list_keys = [
        "retracted_assertions", "trimmed_assertions", "retracted_preferences",
        "trimmed_preferences", "expired_relations", "trimmed_relations",
        "removed_entities", "trimmed_entities", "erased_derived_evidence",
        "retained_derived_evidence", "trimmed_derived_evidence",
    ]
    for key in list_keys:
        assert len(ps[key]) == len(pl[key]), key
    # Concrete cascade: the sole-source assertion/relation/preference retract,
    # the co-sourced assertion trims to the surviving corroborator, the entity
    # (tenant-scoped, sole source) is removed.
    assert len(ps["retracted_assertions"]) == 1
    assert len(ps["trimmed_assertions"]) == 1
    assert len(ps["retracted_preferences"]) == 1
    assert len(ps["expired_relations"]) == 1
    assert ps["removed_entities"] == pl["removed_entities"]
    assert ps["standing_cascade"]["erasure_mode"] == pl["standing_cascade"]["erasure_mode"]


def test_forget_is_branch_scoped_leaves_other_branch(tmp_path: Path):
    """Local-match: the evidence/assertion/relation cascade is scoped to the
    ``branch`` argument, so a copy on another branch survives untouched."""
    engine = _make(tmp_path / "root")
    cid = engine.append_evidence(_ev("t", "Branch-scoped erasure evidence."))
    engine.branch("feature", frm="main", tenant_id="t")
    assert engine.get_evidence("t", cid, branch="feature") is not None
    engine.forget("t", cid, branch="main", requested_by="legal", erasure_mode=HARD)
    assert engine.get_evidence("t", cid, branch="main") is None  # erased on main
    survived = engine.get_evidence("t", cid, branch="feature")
    assert survived is not None and survived.erased is False  # feature branch intact
