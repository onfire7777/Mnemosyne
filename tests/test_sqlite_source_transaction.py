"""Atomic SQLite source mutation, document identities, and journal ordering."""

from __future__ import annotations

import copy
import sqlite3
from contextlib import nullcontext

import pytest

from mnemosyne.journal import CIDJournal, journal_filename
from mnemosyne.models import Assertion, Evidence
from mnemosyne.privacy import ErasureMode
from mnemosyne.sqlite_engine import SqliteEngine, _evidence_from_row


def evidence(text, *, tenant="tenant", owner="owner", segment=None):
    return Evidence(tenant_id=tenant, user_id=owner, actor="user", source_type="document",
                    content=text, document_segment_id=segment, metadata={"revision": 1})


def test_failed_source_batch_restores_sources_projections_metadata_and_journal(tmp_path):
    root, journal_root = tmp_path / "store", tmp_path / "journal"
    engine = SqliteEngine(root, journal_dir=journal_root)
    old = engine.append_evidence(evidence("Original source", segment="doc/old"))
    engine.upsert_assertion(Assertion(tenant_id="tenant", user_id="owner", subject="release",
                                     predicate="is", object="Tuesday", source_evidence_cids=[old]))
    before = copy.deepcopy(engine.export_tenant("tenant"))
    journal = journal_root / journal_filename("tenant")
    journal_before = journal.read_bytes()
    nonce = engine._retrieval_result_cache_nonce
    with pytest.raises(ValueError, match="abort after all writes"):
        with engine.source_transaction("tenant"):
            new = engine.append_evidence(evidence("Replacement source", segment="doc/new"))
            assert engine.update_evidence_metadata("tenant", new, {"revision": 2})
            assert engine.get_evidence("tenant", new).metadata["revision"] == 2
            assert engine.forget("tenant", old)["erased"]
            assert journal.read_bytes() == journal_before
            raise ValueError("abort after all writes")
    assert engine.export_tenant("tenant") == before
    assert engine.get_evidence("tenant", new) is None
    assert journal.read_bytes() == journal_before
    assert engine._retrieval_result_cache_nonce != nonce
    engine.close()
    reopened = SqliteEngine(root)
    assert reopened.export_tenant("tenant") == before
    reopened.close()


def test_nested_batch_commits_once_and_other_reader_sees_only_committed_state(tmp_path):
    root, journal_root = tmp_path / "store", tmp_path / "journal"
    writer = SqliteEngine(root, journal_dir=journal_root)
    old = writer.append_evidence(evidence("Original source"))
    observer = SqliteEngine(root)
    assert observer.get_evidence("tenant", old) is not None
    journal = journal_root / journal_filename("tenant")
    before = journal.read_bytes()
    with writer.source_transaction("tenant"):
        with writer.source_transaction("tenant"):
            new = writer.append_evidence(evidence("Replacement source", segment="new"))
            writer.forget("tenant", old)
        assert writer.get_evidence("tenant", new) is not None
        assert observer.get_evidence("tenant", new) is None
        assert observer.get_evidence("tenant", old) is not None
        assert journal.read_bytes() == before
    assert observer.get_evidence("tenant", old) is None
    assert observer.get_evidence("tenant", new).document_segment_id == "new"
    assert journal.read_bytes() != before
    writer.close()
    observer.close()


@pytest.mark.parametrize("failure", ["nested", "validation", "unsupported", "scope", "mental", "mental-invalid"])
def test_caught_failure_poisoning_rolls_back_and_allows_later_retry(tmp_path, failure):
    engine = SqliteEngine(tmp_path)
    row = evidence("This row must be rolled back", segment="new")
    with pytest.raises(RuntimeError, match="aborted"):
        with engine.source_transaction("tenant"):
            cid = engine.append_evidence(row)
            try:
                if failure == "nested":
                    with engine.source_transaction("tenant"):
                        raise ValueError("inner failure")
                elif failure == "validation":
                    engine.update_evidence_metadata("tenant", cid, {"access_policy": {}})
                elif failure == "unsupported":
                    engine.branch("uncommitted", tenant_id="tenant")
                elif failure == "scope":
                    engine.get_evidence("tenant", cid, "other-branch")
                else:
                    with engine.mental_model_guard("" if failure == "mental-invalid" else "tenant"):
                        pass
            except (ValueError, RuntimeError):
                pass
    assert engine.get_evidence("tenant", cid) is None
    with engine.source_transaction("tenant"):
        assert engine.append_evidence(row) == cid
    assert engine.get_evidence("tenant", cid) is not None
    engine.close()


@pytest.mark.parametrize("operation", ["commit", "rollback", "context", "script", "authorizer"])
def test_raw_connection_cannot_end_source_transaction(tmp_path, operation):
    engine = SqliteEngine(tmp_path)
    conn = engine._connect("tenant")
    with pytest.raises(RuntimeError, match="aborted"):
        with engine.source_transaction("tenant"):
            cid = engine.append_evidence(evidence("Uncommitted row"))
            with pytest.raises(RuntimeError, match="owns commit"):
                if operation == "commit":
                    conn.commit()
                elif operation == "rollback":
                    conn.rollback()
                elif operation == "context":
                    with conn:
                        pass
                elif operation == "script":
                    conn.executescript("SELECT 1;")
                else:
                    conn.set_authorizer(None)
    assert engine.get_evidence("tenant", cid) is None
    engine.close()


@pytest.mark.parametrize("sql", ["COMMIT", "/* comment */ COMMIT", "ROLLBACK", "SAVEPOINT unsafe"])
def test_existing_cursor_cannot_end_source_transaction(tmp_path, sql):
    engine = SqliteEngine(tmp_path)
    cursor = engine._connect("tenant").cursor()
    with pytest.raises(RuntimeError, match="aborted"):
        with engine.source_transaction("tenant"):
            cid = engine.append_evidence(evidence("Uncommitted row"))
            with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
                cursor.execute(sql)
    assert engine.get_evidence("tenant", cid) is None
    engine.close()


def test_source_transaction_rejects_entry_from_mental_model_guard(tmp_path):
    engine = SqliteEngine(tmp_path)
    with engine.mental_model_guard("tenant"):
        with pytest.raises(RuntimeError, match="mental model guard"):
            with engine.source_transaction("tenant"):
                pytest.fail("incompatible source transaction opened")
    engine.close()


def test_source_transaction_rejects_nested_different_tenant_without_creating_database(tmp_path):
    engine = SqliteEngine(tmp_path)
    with pytest.raises(RuntimeError, match="aborted"):
        with engine.source_transaction("tenant"):
            cid = engine.append_evidence(evidence("Uncommitted row"))
            with pytest.raises(ValueError, match="scope mismatch"):
                with engine.source_transaction("other"):
                    pass
    assert not engine._tenant_db_path("other").exists()
    assert engine.get_evidence("tenant", cid) is None
    engine.close()


def test_legacy_schema_and_old_row_decoder_keep_existing_cid(tmp_path):
    engine = SqliteEngine(tmp_path)
    cid = engine.append_evidence(evidence("Legacy source"))
    path = engine._tenant_db_path("tenant")
    engine.close()
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("ALTER TABLE evidence DROP COLUMN document_segment_id")
        old = _evidence_from_row(conn.execute("SELECT * FROM evidence").fetchone())
        assert old.cid == cid and old.document_segment_id is None
    reopened = SqliteEngine(tmp_path)
    assert reopened.get_evidence("tenant", cid).document_segment_id is None
    assert reopened.append_evidence(evidence("Legacy source")) == cid
    assert "document_segment_id" in {
        row[1] for row in reopened._connect("tenant").execute("PRAGMA table_info(evidence)")
    }
    reopened.close()


def test_document_tombstone_matches_identity_and_owner_but_legacy_blocks_replay(tmp_path):
    engine = SqliteEngine(tmp_path)
    cid = engine.append_evidence(evidence("Same segment words", segment="doc/a"))
    engine.forget("tenant", cid)
    assert engine.append_evidence(evidence("Same segment words", segment="doc/a")) == cid
    assert engine.get_evidence("tenant", cid) is None
    other_owner = engine.append_evidence(evidence("Same segment words", owner="other", segment="doc/a"))
    other_segment = engine.append_evidence(evidence("Same segment words", segment="doc/b"))
    assert engine.get_evidence("tenant", other_owner) is not None
    assert engine.get_evidence("tenant", other_segment) is not None
    legacy = engine.append_evidence(evidence("Legacy forgotten words"))
    engine.forget("tenant", legacy)
    assert engine.append_evidence(evidence("Legacy forgotten words", segment="new-identity")) == legacy
    assert engine.get_evidence("tenant", legacy) is None
    engine.close()


def test_post_commit_journal_failure_keeps_committed_rows(tmp_path, monkeypatch):
    engine = SqliteEngine(tmp_path / "store", journal_dir=tmp_path / "journal")

    def fail(*args, **kwargs):
        raise OSError("journal failure after commit")

    monkeypatch.setattr(CIDJournal, "append", fail)
    with pytest.raises(OSError, match="after commit"):
        with engine.source_transaction("tenant"):
            cid = engine.append_evidence(evidence("Committed despite journal error"))
    assert engine.get_evidence("tenant", cid) is not None
    engine.close()


def test_post_commit_append_failure_does_not_skip_later_journal_erasure(tmp_path, monkeypatch):
    journal_root = tmp_path / "journal"
    engine = SqliteEngine(tmp_path / "store", journal_dir=journal_root)
    old = engine.append_evidence(evidence("Old words to erase"))

    def fail(*args, **kwargs):
        raise OSError("new journal append failed")

    monkeypatch.setattr(CIDJournal, "append", fail)
    with pytest.raises(OSError, match="new journal append failed"):
        with engine.source_transaction("tenant"):
            new = engine.append_evidence(evidence("Replacement source"))
            engine.forget("tenant", old)
    assert engine.get_evidence("tenant", new) is not None
    assert engine.get_evidence("tenant", old) is None
    record = next(CIDJournal(journal_root / journal_filename("tenant")).records())
    assert record["cid"] == old and record["erased"] is True
    assert "content" not in record
    engine.close()


@pytest.mark.parametrize("mode", [ErasureMode.TOMBSTONE_RECOMPUTE, ErasureMode.HARD_DELETE_LEGAL])
@pytest.mark.parametrize("batched", [False, True])
def test_branch_erasure_preserves_shared_journal_until_last_live_copy(tmp_path, mode, batched):
    journal_root = tmp_path / "journal"
    engine = SqliteEngine(tmp_path / "store", journal_dir=journal_root)
    cid = engine.append_evidence(evidence("Content retained in main", segment="document/one"))
    engine.branch("draft", tenant_id="tenant")
    journal = CIDJournal(journal_root / journal_filename("tenant"))

    with engine.source_transaction("tenant", "draft") if batched else nullcontext():
        engine.forget("tenant", cid, "draft", requested_by="legal", erasure_mode=mode)
    assert engine.get_evidence("tenant", cid, "draft") is None
    assert engine.get_evidence("tenant", cid, "main") is not None
    records = list(journal.records())
    assert len(records) == 1 and records[0]["content"] == "Content retained in main"
    assert records[0].get("erased", False) is False

    with engine.source_transaction("tenant", "main") if batched else nullcontext():
        engine.forget("tenant", cid, "main", requested_by="legal", erasure_mode=mode)
    assert engine.get_evidence("tenant", cid, "main") is None
    records = list(journal.records())
    if mode is ErasureMode.HARD_DELETE_LEGAL:
        assert records == []
    else:
        assert len(records) == 1 and records[0]["erased"] is True
        assert "content" not in records[0]
    engine.close()


@pytest.mark.parametrize("mode", [ErasureMode.TOMBSTONE_RECOMPUTE, ErasureMode.HARD_DELETE_LEGAL])
def test_append_then_forget_never_publishes_erased_plaintext(tmp_path, monkeypatch, mode):
    engine = SqliteEngine(tmp_path / "store", journal_dir=tmp_path / "journal")
    published = []
    original_append = CIDJournal.append

    def capture(journal, record):
        published.append(record)
        return original_append(journal, record)

    monkeypatch.setattr(CIDJournal, "append", capture)
    with engine.source_transaction("tenant"):
        cid = engine.append_evidence(evidence("Secret erased in the same batch"))
        engine.forget("tenant", cid, requested_by="legal", erasure_mode=mode)
    assert engine.get_evidence("tenant", cid) is None
    assert published == []
    engine.close()


@pytest.mark.parametrize("mode", [ErasureMode.TOMBSTONE_RECOMPUTE, ErasureMode.HARD_DELETE_LEGAL])
@pytest.mark.parametrize("batched", [False, True])
def test_failed_source_journal_erasure_does_not_skip_derived_erasure(tmp_path, monkeypatch, mode, batched):
    journal_root = tmp_path / "journal"
    engine = SqliteEngine(tmp_path / "store", journal_dir=journal_root)
    cid = engine.append_evidence(evidence("Original source"))
    derived = []
    for text in ("Derived note one", "Derived note two"):
        row = evidence(text)
        row.source_type = "derived-note"
        row.metadata["source_evidence_cids"] = [cid]
        derived.append(engine.append_evidence(row))
    method = "purge" if mode is ErasureMode.HARD_DELETE_LEGAL else "tombstone"
    original = getattr(CIDJournal, method)
    attempted = []

    def fail_first(journal, affected_cid, *args, **kwargs):
        attempted.append(affected_cid)
        if affected_cid == cid:
            raise OSError("source journal erasure failed")
        return original(journal, affected_cid, *args, **kwargs)

    monkeypatch.setattr(CIDJournal, method, fail_first)
    with pytest.raises(OSError, match="source journal erasure failed"):
        with engine.source_transaction("tenant") if batched else nullcontext():
            engine.forget("tenant", cid, requested_by="legal", erasure_mode=mode)
    assert set(attempted) == {cid, *derived}
    assert all(engine.get_evidence("tenant", key) is None for key in (cid, *derived))
    records = {row["cid"]: row for row in CIDJournal(journal_root / journal_filename("tenant")).records()}
    for key in derived:
        if mode is ErasureMode.HARD_DELETE_LEGAL:
            assert key not in records
        else:
            assert records[key]["erased"] is True and "content" not in records[key]
    engine.close()
