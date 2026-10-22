"""Advisory model storage has durable, isolated compare-and-swap semantics."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Barrier, Event
from types import SimpleNamespace
from typing import Any

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mental_model_storage import MentalModelConflict
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request: Any, tmp_path: Any):
    value = LocalMemoryEngine(store_path=tmp_path / "store.json") if request.param == "local" else SqliteEngine(tmp_path / "store")
    yield value
    value.close()


def record(tenant: str = "t", model: str = "m", branch: str = "main") -> dict[str, Any]:
    return {"tenant_id": tenant, "branch": branch, "model_id": model, "owner_id": "owner",
            "name": "Launch", "question": "Where is launch?", "scope": {"tags": ["launch"]},
            "created_at": "2026-10-22T00:00:00+00:00", "updated_at": "2026-10-22T00:00:00+00:00",
            "status": "ready", "answer": {"text": "silver raven destination", "citations": []},
            "corpus_fingerprint": "abc", "revisions": [], "source_evidence_cids": []}


def test_create_update_delete_and_conflicts(engine: Any):
    saved = engine.save_mental_model_record("t", "m", record())
    assert saved["version"] == 1
    with pytest.raises(MentalModelConflict):
        engine.save_mental_model_record("t", "m", record())
    saved["name"] = "Revised"
    updated = engine.save_mental_model_record("t", "m", saved, expected_version=1)
    assert updated["version"] == 2
    with pytest.raises(MentalModelConflict):
        engine.save_mental_model_record("t", "m", saved, expected_version=1)
    with pytest.raises(MentalModelConflict):
        engine.delete_mental_model_record("t", "m", expected_version=1)
    assert engine.delete_mental_model_record("t", "m", expected_version=2)
    assert not engine.delete_mental_model_record("t", "m", expected_version=2)
    with pytest.raises(MentalModelConflict):
        engine.save_mental_model_record("t", "m", saved, expected_version=2)


def test_copies_and_scope_are_detached(engine: Any):
    source = record()
    saved = engine.save_mental_model_record("t", "m", source)
    source["scope"]["tags"].append("bad")
    saved["answer"]["text"] = "bad"
    rows = engine.list_mental_model_records("t")
    rows[0]["scope"]["tags"].clear()
    current = engine.get_mental_model_record("t", "m")
    assert current["scope"] == {"tags": ["launch"]}
    assert current["answer"]["text"] == "silver raven destination"
    assert engine.get_mental_model_record("other", "m") is None
    assert engine.get_mental_model_record("t", "m", "other") is None
    assert engine.list_mental_model_records("other") == []
    current["owner_id"] = "intruder"
    with pytest.raises(ValueError, match="immutable"):
        engine.save_mental_model_record("t", "m", current, expected_version=1)


@pytest.mark.parametrize("value", [True, 0, -1, "1", 1.5])
def test_invalid_expected_versions_are_rejected(engine: Any, value: Any):
    with pytest.raises(ValueError):
        engine.save_mental_model_record("t", "m", record(), expected_version=value)
    with pytest.raises(ValueError):
        engine.delete_mental_model_record("t", "m", expected_version=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "numeric key"}, (1, 2)])
def test_non_json_values_are_rejected(engine: Any, value: Any):
    source = record()
    source["scope"]["bad"] = value
    with pytest.raises(ValueError):
        engine.save_mental_model_record("t", "m", source)
    assert engine.get_mental_model_record("t", "m") is None


def test_only_one_concurrent_update_wins(engine: Any):
    engine.save_mental_model_record("t", "m", record())
    ready = Barrier(2)

    def update(name: str) -> bool:
        source = record()
        source["name"] = name
        ready.wait()
        try:
            engine.save_mental_model_record("t", "m", source, expected_version=1)
            return True
        except MentalModelConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, ["one", "two"])) == [False, True]
    assert engine.get_mental_model_record("t", "m")["version"] == 2


def test_records_are_raw_export_only_and_never_retrieved(engine: Any):
    engine.save_mental_model_record("t", "m", record())
    raw = engine.export_tenant("t")
    assert raw["mental_models"][0]["answer"]["text"] == "silver raven destination"
    raw["mental_models"][0]["answer"]["text"] = "bad"
    assert engine.get_mental_model_record("t", "m")["answer"]["text"] != "bad"
    scoped = engine.export_tenant_filtered("t", {"tenant_id": "t", "user_id": "owner", "role": "reader"})
    assert not scoped.get("mental_models")
    assert "silver raven destination" not in json.dumps(scoped)
    assert not engine.retrieve("silver raven destination", "t").hits
    assert engine.export_all()["mental_models"][0]["model_id"] == "m"


def test_forget_removes_answer_and_invalidates_old_writer(engine: Any):
    cid = engine.append_evidence(Evidence(tenant_id="t", user_id="owner", actor="user", source_type="episode", content="source"))
    source = record()
    source["source_evidence_cids"] = [cid]
    engine.save_mental_model_record("t", "m", source)
    engine.forget("t", cid)
    saved = engine.get_mental_model_record("t", "m")
    assert saved["answer"] is None
    assert saved["status"] == "stale"
    assert saved["corpus_fingerprint"] is None
    assert saved["version"] == 2
    assert "silver raven destination" not in json.dumps(engine.export_tenant("t"))
    with pytest.raises(MentalModelConflict):
        engine.save_mental_model_record("t", "m", source, expected_version=1)


def test_discard_purges_only_branch_records(engine: Any):
    engine.branch("scratch", tenant_id="t")
    engine.save_mental_model_record("t", "m", record())
    engine.save_mental_model_record("t", "m", record(branch="scratch"), branch="scratch")
    engine.discard("scratch", tenant_id="t")
    assert engine.get_mental_model_record("t", "m", "scratch") is None
    assert engine.get_mental_model_record("t", "m") is not None


def test_branch_discard_keeps_other_tenant_model_editable(engine: Any):
    for tenant in ("t", "other"):
        engine.branch("scratch", tenant_id=tenant)
        engine.save_mental_model_record(tenant, "m", record(tenant=tenant, branch="scratch"), branch="scratch")
    engine.discard("scratch", tenant_id="t")
    other = engine.get_mental_model_record("other", "m", "scratch")
    updated = engine.save_mental_model_record("other", "m", other, branch="scratch", expected_version=1)
    assert updated["version"] == 2


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_restart_preserves_record(tmp_path: Any, backend: str):
    path = tmp_path / ("store.json" if backend == "local" else "store")
    make = (lambda: LocalMemoryEngine(store_path=path)) if backend == "local" else (lambda: SqliteEngine(path))
    first = make()
    saved = first.save_mental_model_record("t", "m", record())
    first.close()
    second = make()
    try:
        assert second.get_mental_model_record("t", "m") == saved
    finally:
        second.close()


def test_sqlite_other_connection_detects_stale_version(tmp_path: Any):
    first, second = SqliteEngine(tmp_path), SqliteEngine(tmp_path)
    try:
        first.save_mental_model_record("t", "m", record())
        old = second.get_mental_model_record("t", "m")
        first.save_mental_model_record("t", "m", old, expected_version=1)
        with pytest.raises(MentalModelConflict):
            second.save_mental_model_record("t", "m", old, expected_version=1)
        assert second.get_mental_model_record("t", "m")["version"] == 2
    finally:
        first.close()
        second.close()


def test_local_raw_export_can_be_restored(tmp_path: Any):
    source = LocalMemoryEngine()
    try:
        value = record()
        value["scope"]["literal"] = {"$mnemosyne:literal": {"keep": "this shape"}}
        saved = source.save_mental_model_record("t", "m", value)
        path = tmp_path / "restored.json"
        path.write_text(source.to_json())
        restored = LocalMemoryEngine(store_path=path)
        try:
            assert restored.get_mental_model_record("t", "m") == saved
        finally:
            restored.close()
    finally:
        source.close()


def test_local_canary_discard_purges_advisory_models():
    engine = LocalMemoryEngine()
    try:
        engine.branch("canary", kind="canary", tenant_id="t")
        engine.save_mental_model_record("t", "m", record(branch="canary"), branch="canary")
        engine.discard("canary", tenant_id="t")
        assert engine.get_mental_model_record("t", "m", "canary") is None
    finally:
        engine.close()


def test_failed_local_persistence_rolls_back_model_write(tmp_path: Any, monkeypatch: Any):
    engine = LocalMemoryEngine(store_path=tmp_path / "store.json")
    try:
        initial = engine.save_mental_model_record("t", "m", record())

        def fail() -> None:
            raise OSError("simulated disk failure")

        monkeypatch.setattr(engine, "_persist", fail)
        with pytest.raises(OSError):
            engine.save_mental_model_record("t", "m", initial, expected_version=1)
        assert engine.get_mental_model_record("t", "m") == initial
        with pytest.raises(OSError):
            engine.delete_mental_model_record("t", "m", expected_version=1)
        assert engine.get_mental_model_record("t", "m") == initial
    finally:
        engine.close()


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_erasure_is_durable_and_preserves_other_tenant(tmp_path: Any, backend: str):
    path = tmp_path / ("store.json" if backend == "local" else "store")
    make = (lambda: LocalMemoryEngine(store_path=path)) if backend == "local" else (lambda: SqliteEngine(path))
    engine = make()
    try:
        cid = engine.append_evidence(Evidence(tenant_id="t", user_id="owner", actor="user", source_type="episode", content="source"))
        engine.save_mental_model_record("t", "m", record())
        engine.save_mental_model_record("other", "m", record(tenant="other"))
        engine.forget("t", cid)
    finally:
        engine.close()
    restored = make()
    try:
        assert restored.get_mental_model_record("t", "m")["answer"] is None
        assert restored.get_mental_model_record("other", "m")["answer"]["text"] == "silver raven destination"
    finally:
        restored.close()


def _postgres_with_results(results: list[Any]) -> tuple[Any, list[tuple[str, Any]]]:
    """Exercise adapter conflict handling without a PostgreSQL service."""
    statements: list[tuple[str, Any]] = []
    pending = iter(results)
    cursor = SimpleNamespace(
        execute=lambda query, params: statements.append((query, params)),
        fetchone=lambda: next(pending),
    )
    connection = SimpleNamespace(cursor=lambda **kwargs: nullcontext(cursor))
    engine = PostgresEngine.__new__(PostgresEngine)
    engine._psycopg = SimpleNamespace(rows=SimpleNamespace(dict_row=None))
    engine._jsonb = lambda value: value
    engine.connect = lambda: nullcontext(connection)
    engine.ensure_tenant_and_branch = lambda *args: None
    return engine, statements


def test_postgres_concurrent_create_conflict_is_not_an_overwrite():
    engine, statements = _postgres_with_results([None, None])
    with pytest.raises(MentalModelConflict):
        engine.save_mental_model_record("t", "m", record())
    writes = [query for query, _ in statements if query.startswith("INSERT")]
    assert len(writes) == 1 and "DO NOTHING" in writes[0]
    assert not any(query.startswith("UPDATE") for query, _ in statements)


def test_postgres_stale_revision_does_not_issue_a_write():
    stored = {**record(), "version": 2}
    engine, statements = _postgres_with_results([{"record": stored}])
    with pytest.raises(MentalModelConflict):
        engine.save_mental_model_record("t", "m", stored, expected_version=1)
    assert not any(query.startswith(("UPDATE", "INSERT", "DELETE")) for query, _ in statements)


def test_postgres_read_detaches_json_from_driver():
    stored = {**record(), "version": 1}
    engine, statements = _postgres_with_results([{"record": stored}])
    result = engine.get_mental_model_record("t", "m")
    result["scope"]["tags"].clear()
    assert stored["scope"] == {"tags": ["launch"]}
    assert statements[-1][1][1:] == ("main", "m")


def test_model_guard_keeps_source_snapshot_stable_through_publication(engine: Any, tmp_path: Any):
    """A final source read and publication exclude competing source writes."""
    cid = engine.append_evidence(Evidence(tenant_id="t", user_id="owner", actor="user", source_type="episode", content="source"))
    engine.save_mental_model_record("t", "m", record())
    other = SqliteEngine(engine.root_dir) if isinstance(engine, SqliteEngine) else engine
    other.get_evidence("t", cid)  # Initialize the second SQL connection before the lock.
    attempted, finished = Event(), Event()

    def tighten():
        attempted.set()
        other.backfill_evidence_privacy("t", cid, ["secret"])
        finished.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with engine.mental_model_guard("t"):
                before = engine.export_tenant("t")["evidence"]
                pending = pool.submit(tighten)
                assert attempted.wait(2)
                assert not finished.wait(0.1)
                current = engine.get_mental_model_record("t", "m")
                saved = engine.save_mental_model_record("t", "m", current, expected_version=1)
                assert saved["version"] == 2
                assert engine.export_tenant("t")["evidence"] == before
                assert engine.get_mental_model_record("t", "m") == saved
            pending.result(timeout=3)
        assert finished.is_set()
        assert engine.get_evidence("t", cid).sensitivity > 0
        with engine.mental_model_guard("t"):
            assert engine.delete_mental_model_record("t", "m", expected_version=2)
        assert engine.get_mental_model_record("t", "m") is None
    finally:
        if other is not engine:
            other.close()


def test_sqlite_model_guard_rolls_back_publication_on_error(tmp_path: Any):
    engine = SqliteEngine(tmp_path / "store")
    try:
        before = engine.save_mental_model_record("t", "m", record())
        with pytest.raises(RuntimeError, match="failed view"):
            with engine.mental_model_guard("t"):
                engine.save_mental_model_record("t", "m", before, expected_version=1)
                assert engine.get_mental_model_record("t", "m")["version"] == 2
                raise RuntimeError("failed view")
        assert engine.get_mental_model_record("t", "m") == before
        with pytest.raises(RuntimeError, match="failed delete"):
            with engine.mental_model_guard("t"):
                engine.delete_mental_model_record("t", "m", expected_version=1)
                raise RuntimeError("failed delete")
        assert engine.get_mental_model_record("t", "m") == before
    finally:
        engine.close()


def test_sqlite_model_guard_does_not_adopt_unrelated_transaction(tmp_path: Any):
    engine = SqliteEngine(tmp_path / "store")
    try:
        conn = engine._connect("t")
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError, match="transaction"):
            with engine.mental_model_guard("t"):
                pytest.fail("unrelated transaction was adopted")
        assert conn.in_transaction
        conn.rollback()
        with engine.mental_model_guard("t"):
            engine.save_mental_model_record("t", "m", record())
        assert engine.get_mental_model_record("t", "m")["version"] == 1
    finally:
        engine.close()
