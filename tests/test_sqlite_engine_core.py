"""SqliteEngine store core + schema (Phase-2 Task 2).

Covers construction (kwargs mirror LocalMemoryEngine), per-tenant WAL file
mapping with hostile-id containment, pragma discipline, first-open integrity
check, 13-collection schema idempotency, uniqueness keys, and Evidence row
round-trip byte-compatibility against the LocalMemoryEngine oracle.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine, MemoryEngine
from mnemosyne.journal import journal_filename, safe_tenant_filename
from mnemosyne.models import Evidence, parse_dt
from mnemosyne.policy import OperatingPolicy
from mnemosyne.retrieval import HashingEmbeddingProvider, LocalSimilarityReranker, RetrievalAdapters
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.sqlite_schema import ENSURE_STATEMENTS, SCHEMA_VERSION

EXPECTED_TABLES = {
    # the 13 LocalMemoryEngine._persist collections (policy lives in meta)
    "evidence",
    "assertions",
    "relations",
    "preferences",
    "justifications",
    "contradictions",
    "calibrations",
    "entities",
    "branches",
    "audit_log",
    "deletion_log",
    "merge_log",
    # runtime queue + schema/watermark bookkeeping
    "runtime_jobs",
    "meta",
}


def _pragma(conn: sqlite3.Connection, name: str):
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def _rich_evidence(**overrides) -> Evidence:
    base = dict(
        tenant_id="tenant-rt",
        user_id="user-1",
        actor="user",
        source_type="chat",
        content="Round-trip evidence about the cobalt lighthouse.",
        source_identity="mailto:user@example.com",
        session_id="sess-9",
        metadata={"topic": "lighthouse", "nested": {"a": [1, 2.5, None], "b": True}},
        modality="text",
        embedding=[0.125, -3.75, 1e-9, 42.0],
        trust_tier=2,
        capability_tags=["capA", "capB"],
        sensitivity=1,
        access_policy={"allow_principals": ["user-1"], "purpose": "assistant-memory"},
    )
    base.update(overrides)
    return Evidence(**base)


# --- construction -----------------------------------------------------------


def test_engine_satisfies_runtime_checkable_memory_engine_protocol(tmp_path: Path):
    engine = SqliteEngine(tmp_path / "root")
    assert isinstance(engine, MemoryEngine)


def test_constructor_defaults_mirror_local_with_sqlite_backend_names(tmp_path: Path):
    engine = SqliteEngine(tmp_path / "root")
    assert engine.policy.to_dict() == OperatingPolicy().to_dict()
    assert isinstance(engine.adapters.embedding, HashingEmbeddingProvider)
    assert isinstance(engine.adapters.reranker, LocalSimilarityReranker)
    # locked backend names — must not match the `local-` forbid_local denylist
    assert engine.adapters.lexical_backend == "sqlite-fts5"
    assert engine.adapters.graph_backend == "sqlite-cached-ppr"
    assert engine._journal_dir is None


def test_constructor_accepts_explicit_policy_adapters_journal_dir(tmp_path: Path):
    policy = OperatingPolicy()
    adapters = RetrievalAdapters()
    engine = SqliteEngine(
        tmp_path / "root",
        policy=policy,
        adapters=adapters,
        journal_dir=tmp_path / "journals",
    )
    assert engine.policy is policy
    assert engine.adapters is adapters
    assert engine._journal_dir == tmp_path / "journals"


# --- per-tenant files + containment ----------------------------------------


def test_safe_tenant_filename_generalizes_journal_filename():
    assert safe_tenant_filename("t-a", ".db") == "t-a.db"
    assert safe_tenant_filename("tenant.1_x-2", ".journal") == "tenant.1_x-2.journal"
    hostile = safe_tenant_filename("../evil", ".db")
    assert hostile.startswith("t-") and hostile.endswith(".db")
    assert "/" not in hostile and ".." not in hostile
    # journal_filename is now a thin wrapper — identical outputs, sane and hostile
    assert journal_filename("t-a") == safe_tenant_filename("t-a", ".journal")
    assert journal_filename("../evil") == safe_tenant_filename("../evil", ".journal")


def test_sane_tenant_id_maps_to_verbatim_db_file(tmp_path: Path):
    root = tmp_path / "root"
    engine = SqliteEngine(root)
    engine._connect("tenant.1_x-2")
    assert (root / "tenant.1_x-2.db").exists()


def test_hostile_tenant_id_is_contained_inside_root_dir(tmp_path: Path):
    root = tmp_path / "root"
    engine = SqliteEngine(root)
    engine._connect("../evil")
    db_files = sorted(p.name for p in root.glob("*.db"))
    assert db_files == [safe_tenant_filename("../evil", ".db")]
    assert db_files[0].startswith("t-")
    hashed = root / db_files[0]
    assert hashed.resolve().parent == root.resolve()
    # nothing escaped the root directory
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "evil.db").exists()


# --- pragmas + integrity ----------------------------------------------------


def test_pragmas_applied_on_connect(tmp_path: Path):
    engine = SqliteEngine(tmp_path / "root")
    conn = engine._connect("t1")
    assert _pragma(conn, "journal_mode") == "wal"
    assert _pragma(conn, "synchronous") == 2  # FULL
    assert _pragma(conn, "foreign_keys") == 1
    assert _pragma(conn, "busy_timeout") == 5000


def test_corrupt_tenant_file_raises_runtime_error_on_first_open(tmp_path: Path):
    root = tmp_path / "root"
    engine = SqliteEngine(root)
    engine._connect("t1")
    engine.close()
    (root / "t1.db").write_bytes(b"this is not a sqlite database, integrity is gone")
    fresh = SqliteEngine(root)
    with pytest.raises(RuntimeError):
        fresh._connect("t1")


# --- schema -----------------------------------------------------------------


def test_ensure_statements_are_idempotent_strings():
    assert isinstance(ENSURE_STATEMENTS, list)
    assert all(isinstance(stmt, str) for stmt in ENSURE_STATEMENTS)
    for stmt in ENSURE_STATEMENTS:
        assert "IF NOT EXISTS" in stmt, stmt


def test_schema_creates_all_collections_and_is_idempotent(tmp_path: Path):
    root = tmp_path / "root"
    engine = SqliteEngine(root)
    conn = engine._connect("t1")
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert EXPECTED_TABLES <= names
    version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    assert version == str(SCHEMA_VERSION)
    engine.close()

    # re-open: ensure runs again without error, nothing duplicated
    reopened = SqliteEngine(root)
    conn2 = reopened._connect("t1")
    assert conn2.execute("SELECT COUNT(*) FROM meta WHERE key = 'schema_version'").fetchone()[0] == 1
    assert conn2.execute("SELECT COUNT(*) FROM branches WHERE name = 'main'").fetchone()[0] == 1


def test_main_branch_registered_protected_on_open(tmp_path: Path):
    engine = SqliteEngine(tmp_path / "root")
    conn = engine._connect("t1")
    row = conn.execute(
        "SELECT tenant_id, name, from_branch, kind FROM branches WHERE name = 'main'"
    ).fetchone()
    assert tuple(row) == ("t1", "main", None, "protected")


def test_evidence_uniqueness_key_tenant_branch_cid(tmp_path: Path):
    engine = SqliteEngine(tmp_path / "root")
    ev = _rich_evidence(cid="a" * 64)
    engine._insert_evidence(ev)
    with pytest.raises(sqlite3.IntegrityError):
        engine._insert_evidence(ev)


# --- round-trip -------------------------------------------------------------


def test_evidence_round_trip_byte_identical_vs_local_oracle(tmp_path: Path):
    local = LocalMemoryEngine()
    cid = local.append_evidence(_rich_evidence())
    stored = local.evidence[local._evidence_key("tenant-rt", "main", cid)]

    engine = SqliteEngine(tmp_path / "root")
    engine._insert_evidence(stored)
    got = engine._fetch_evidence("tenant-rt", stored.cid or "")
    assert got is not None
    assert json.dumps(got.to_dict(), sort_keys=True) == json.dumps(stored.to_dict(), sort_keys=True)


def test_evidence_row_marshalling_preserves_every_field(tmp_path: Path):
    ev = _rich_evidence(
        cid="b" * 64,
        signed_provenance={"sig": "abc", "alg": "ed25519"},
        content_pointer="local-object://sha256/" + "c" * 64,
        erased=True,
        created_at=parse_dt("2026-07-02T03:04:05.123456Z"),
    )
    engine = SqliteEngine(tmp_path / "root")
    engine._insert_evidence(ev)
    got = engine._fetch_evidence(ev.tenant_id, "b" * 64)
    assert got is not None
    assert got.to_dict() == ev.to_dict()
    assert got.embedding == ev.embedding  # exact f64 round-trip through the packed BLOB
    assert got.erased is True
    missing = engine._fetch_evidence(ev.tenant_id, "d" * 64)
    assert missing is None


def test_insert_evidence_requires_cid(tmp_path: Path):
    engine = SqliteEngine(tmp_path / "root")
    with pytest.raises(ValueError):
        engine._insert_evidence(_rich_evidence(cid=None))


# --- protocol stubs ---------------------------------------------------------


def test_unimplemented_surfaces_name_their_task(tmp_path: Path):
    engine = SqliteEngine(tmp_path / "root")
    # Task 3 ledger + Task 4 scan surfaces + Task 5 assertion/bitemporal/write
    # surfaces + Task 6 branch/merge/discard + Task 7 retrieve pipeline are
    # implemented; only the erasure (Task 9) surface remains stubbed.
    from mnemosyne.models import RetrievalResult

    assert isinstance(engine.retrieve("q", "t1"), RetrievalResult)
    with pytest.raises(NotImplementedError, match="Task 9"):
        engine.forget("t1", "a" * 64)
