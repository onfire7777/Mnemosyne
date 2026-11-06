import pytest

from mnemosyne.journal import safe_tenant_filename
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


def test_shared_journal_alias_rejected_before_either_root_ledger_commit(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager
    from threading import Event, Thread, current_thread
    from mnemosyne import journal as journal_module

    owner = "../evil"
    alias = safe_tenant_filename(owner, ".db")[:-3]
    journals = tmp_path / "journals"
    first = SqliteEngine(tmp_path / "first", journal_dir=journals)
    second = SqliteEngine(tmp_path / "second", journal_dir=journals)
    inserting = Event()
    alias_lock_attempt = Event()
    original_lock = journal_module.exclusive_file_lock
    original_insert = SqliteEngine._insert_evidence_row
    outcomes = {}

    @contextmanager
    def observed_lock(path):
        if current_thread().name == "alias":
            alias_lock_attempt.set()
        with original_lock(path):
            yield

    def paused_insert(conn, evidence):
        if evidence.tenant_id == owner:
            inserting.set()
            assert alias_lock_attempt.wait(10), "alias never attempted journal lock"
        return original_insert(conn, evidence)

    def append(engine, tenant):
        try:
            _append(engine, tenant)
            outcomes[tenant] = "accepted"
        except ValueError as exc:
            outcomes[tenant] = str(exc)

    monkeypatch.setattr(journal_module, "exclusive_file_lock", observed_lock)
    monkeypatch.setattr(
        SqliteEngine, "_insert_evidence_row", staticmethod(paused_insert)
    )
    a = Thread(target=append, args=(first, owner), name="owner")
    b = Thread(target=append, args=(second, alias), name="alias")
    try:
        a.start()
        assert inserting.wait(10)
        b.start()
        a.join(10)
        b.join(10)
        assert not a.is_alive() and not b.is_alive()
        assert outcomes[owner] == "accepted"
        assert "ownership" in outcomes[alias]
        assert len(first.export_tenant(owner)["evidence"]) == 1
        assert second.export_tenant(alias)["evidence"] == []
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("operation", ["append", "forget"])
def test_foreign_journal_rejected_before_ledger_mutation(tmp_path, operation):
    import json
    from mnemosyne.journal import journal_filename

    journals = tmp_path / "journals"
    engine = SqliteEngine(tmp_path / "db", journal_dir=journals)
    try:
        cid = _append(engine, "tenant")
        path = journals / journal_filename("tenant")
        foreign = (
            json.dumps({"cid": "foreign", "tenant_id": "other", "content": "private"})
            + "\n"
        )
        path.write_text(foreign)
        before = engine.export_tenant("tenant")
        with pytest.raises(ValueError, match="ownership"):
            if operation == "append":
                engine.append_evidence(
                    Evidence(
                        tenant_id="tenant",
                        user_id="u",
                        actor="user",
                        source_type="chat",
                        content="second",
                    )
                )
            else:
                engine.forget("tenant", cid)
        assert engine.export_tenant("tenant") == before
        assert path.read_text() == foreign
    finally:
        engine.close()


def _append(engine, tenant):
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="u",
            actor="user",
            source_type="chat",
            content="private memory",
        )
    )


@pytest.mark.parametrize("reopen", [False, True])
def test_hash_alias_is_rejected_before_second_tenant_write(tmp_path, reopen):
    owner = "../evil"
    alias = safe_tenant_filename(owner, ".db")[:-3]
    engine = SqliteEngine(tmp_path)
    try:
        _append(engine, owner)
        if reopen:
            engine.close()
            engine = SqliteEngine(tmp_path)
        with pytest.raises(ValueError, match="tenant.*ownership"):
            _append(engine, alias)
        assert len(engine.export_tenant(owner)["evidence"]) == 1
        assert [
            r[0]
            for r in engine._connect(owner).execute("SELECT tenant_id FROM branches")
        ] == [owner]
    finally:
        engine.close()


def test_case_alias_cannot_delete_other_tenant_projection(tmp_path):
    probe = tmp_path / "CaseProbe"
    probe.write_text("probe")
    if not (tmp_path / "caseprobe").exists():
        pytest.skip("requires case-insensitive filesystem")
    engine = SqliteEngine(tmp_path)
    try:
        _append(engine, "Alice")
        with pytest.raises(ValueError, match="tenant.*ownership"):
            engine._rebuild_evidence_fts("alice")
        assert (
            engine._connect("Alice")
            .execute("SELECT count(*) FROM evidence_fts")
            .fetchone()[0]
            == 1
        )
    finally:
        engine.close()


def test_same_tenant_reopens_existing_database(tmp_path):
    engine = SqliteEngine(tmp_path)
    _append(engine, "tenant")
    engine.close()
    engine = SqliteEngine(tmp_path)
    try:
        assert len(engine.export_tenant("tenant")["evidence"]) == 1
    finally:
        engine.close()


def test_projection_registry_rejects_hash_alias_before_open(tmp_path):
    engine = SqliteEngine(tmp_path)
    owner = "../evil"
    try:
        _append(engine, owner)
        with pytest.raises(ValueError, match="tenant.*ownership"):
            engine._projection_registry(safe_tenant_filename(owner, ".db")[:-3])
    finally:
        engine.close()


def test_mixed_legacy_database_fails_closed_without_changing_rows(tmp_path):
    engine = SqliteEngine(tmp_path)
    _append(engine, "tenant")
    conn = engine._connect("tenant")
    with conn:
        conn.execute(
            "INSERT INTO branches(tenant_id, name, from_branch, kind, created_at) "
            "SELECT 'other', name, from_branch, kind, created_at FROM branches WHERE tenant_id = 'tenant'"
        )
    engine.close()
    engine = SqliteEngine(tmp_path)
    try:
        with pytest.raises(ValueError, match="tenant.*ownership"):
            engine.export_tenant("tenant")
    finally:
        engine.close()


def test_concurrent_engines_admit_only_one_owner_for_hash_alias(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    owner = "../evil"
    aliases = (owner, safe_tenant_filename(owner, ".db")[:-3])
    barrier = Barrier(2)

    def attempt(tenant):
        engine = SqliteEngine(tmp_path)
        try:
            barrier.wait(timeout=10)
            _append(engine, tenant)
            return "accepted"
        except ValueError as exc:
            assert "ownership" in str(exc)
            return "rejected"
        except RuntimeError as exc:
            # SQLite can reject simultaneous first-open WAL configuration
            # before schema admission. It must still never admit both owners.
            import sqlite3

            assert isinstance(exc.__cause__, sqlite3.OperationalError)
            assert "locked" in str(exc.__cause__)
            return "rejected"
        finally:
            engine.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, aliases)) == ["accepted", "rejected"]
