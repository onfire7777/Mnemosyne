import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval import store_recall
from eval.store_recall import ranked_evidence


def test_working_citations_do_not_inflate_retrieved_ranks():
    hits = [
        {"id": "working", "kind": "working", "provenance": ["a", "b", "c"]},
        {"id": "real", "kind": "evidence"},
        {"id": "real", "kind": "evidence"},
    ]
    assert ranked_evidence(hits) == ["working", "real"]


def test_only_unambiguous_idless_projections_identify_evidence():
    assert ranked_evidence([
        {"kind": "working", "provenance": ["a", "b"]},
        {"provenance": ["c"], "metadata": {"source_evidence_cids": ["c"]}},
    ]) == ["c"]


def test_malformed_citations_are_not_character_ids():
    assert ranked_evidence([
        {"provenance": "abc", "metadata": {"source_evidence_cids": "def"}},
        {"id": 123, "provenance": [None, 456]},
    ]) == []


@pytest.mark.parametrize("prepare_vectors", [False, True])
def test_report_uses_shared_interpolated_latency_percentiles(tmp_path, monkeypatch, prepare_vectors):
    from mnemosyne import cli

    store = tmp_path / "source"
    store.mkdir()
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([
        {"id": "q1", "question": "one", "gold": ["a"]},
        {"id": "q2", "question": "two", "gold": ["a"]},
    ]), encoding="utf-8")
    output = tmp_path / "report.json"
    closed = []
    preparations = []
    graph = SimpleNamespace(prepare=lambda queries, embedder: preparations.append(queries))
    engine = SimpleNamespace(
        adapters=SimpleNamespace(passage_graph=graph if prepare_vectors else None, embedding=None),
        close=lambda: closed.append(True),
    )
    tools = SimpleNamespace(
        engine=engine,
        search=lambda **kwargs: {
            "hits": [{"id": "a12345678901-first"}, {"id": "a12345678901-second"}],
            "abstained": False,
        },
    )
    monkeypatch.setattr(cli, "load_tools", lambda args: tools)
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(store), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(output),
    ])
    clock = iter(([-2.0, 0.0] if prepare_vectors else []) + [0.0, 0.0, 0.010, 0.010, 0.040, 0.040])
    monkeypatch.setattr(store_recall.time, "perf_counter", lambda: next(clock))

    store_recall.main()

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["latency_ms"] == {"p50": 20.0, "p95": 29.0}
    assert report["recall_at_5"] == 1.0
    for row in report["rows"]:
        assert row["top5"] == ["a12345678901", "a12345678901"]
        assert row["top5_evidence_cids"] == ["a12345678901-first", "a12345678901-second"]
    assert report["latency_scope"] == "search_calls_excluding_setup_and_query_preparation"
    assert report["query_vectors_prepared"] is prepare_vectors
    assert report["query_preparation_seconds"] == (2.0 if prepare_vectors else 0.0)
    assert preparations == ([["one", "two"]] if prepare_vectors else [])
    assert closed == [True]


@pytest.mark.parametrize("stage", ["index", "prepare", "search"])
def test_failed_run_closes_engine_before_removing_store(tmp_path, monkeypatch, stage):
    from mnemosyne import cli

    source = tmp_path / "source"
    source.mkdir()
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q", "question": "one", "gold": ["a"]}]))
    output = tmp_path / "report.json"
    closed = []
    copies = []

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic evaluation failure")

    def load_tools(args):
        from pathlib import Path

        copy = Path(args.store)
        copies.append(copy)
        engine = SimpleNamespace(
            adapters=SimpleNamespace(
                passage_graph=SimpleNamespace(prepare=fail) if stage == "prepare" else None,
                embedding=None,
            ),
            close=lambda: closed.append(copy.exists()),
        )
        return SimpleNamespace(engine=engine, index_passages=fail, search=fail)

    monkeypatch.setattr(cli, "load_tools", load_tools)
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(output),
        *(["--index-first"] if stage == "index" else []),
    ])
    with pytest.raises(RuntimeError, match="synthetic evaluation failure"):
        store_recall.main()
    assert closed == [True]
    assert not copies[0].exists()
    assert source.exists()
    assert not output.exists()


@pytest.mark.parametrize("questions", [
    [], {}, [None], [{"gold": []}], [{"gold": [""]}],
    [{"gold": [" "]}], [{"gold": [123]}], [{"gold": "cid"}],
    [{"id": "q", "gold": ["a"]}],
    [{"id": "q", "gold": ["a"], "question": ""}],
    [{"id": "q", "gold": ["a"], "question": " "}],
    [{"id": "q", "gold": ["a"], "question": 123}],
    [{"gold": ["a"], "question": "valid query"}],
])
def test_invalid_questions_are_rejected_before_loading_store(tmp_path, monkeypatch, questions):
    from mnemosyne import cli

    path = tmp_path / "questions.json"
    path.write_text(json.dumps(questions))

    def unexpected_load(*args):
        pytest.fail("invalid questions must not load a store or provider")

    monkeypatch.setattr(cli, "load_tools", unexpected_load)
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(tmp_path / "absent-store"),
        "--tenant", "synthetic", "--questions", str(path),
        "--out", str(tmp_path / "out.json"),
    ])
    with pytest.raises(SystemExit) as exc:
        store_recall.main()
    assert exc.value.code == 2
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("output_path", [".", "report.json", "nested/report.json", "nested/../report.json"])
def test_output_inside_source_is_rejected_before_evaluation(tmp_path, monkeypatch, output_path):
    source = tmp_path / "source"
    source.mkdir()
    sentinel = source / "report.json"
    sentinel.write_bytes(b"source data must survive")
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(tmp_path / "absent.json"),
        "--out", str(source / output_path),
    ])
    with pytest.raises(SystemExit) as exc:
        store_recall.main()
    assert exc.value.code == 2
    assert sentinel.read_bytes() == b"source data must survive"
    assert not (source / "nested").exists()


def test_real_sqlite_evaluation_preserves_source_store(tmp_path, monkeypatch):
    from eval.harness.cli_driver import MnemoCLI

    for name in list(os.environ):
        if name.startswith("MNEMOSYNE_"):
            monkeypatch.delenv(name)
    source = tmp_path / "source"
    cli = MnemoCLI(store=str(source), backend="sqlite", global_flags=["--store", str(source)])
    cli.capture("synthetic", "tester", "Mars is a red planet.", trust_tier=0)
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert before
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([
        {"id": "q", "question": "Mars red planet", "gold": ["not-a-matching-cid"]},
    ]), encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(output),
    ])
    store_recall.main()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["questions"] == 1
    assert report["recall_at_5"] == 0.0
    assert report["rows"][0]["top5_evidence_cids"]
    after = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert after == before


@pytest.mark.parametrize("wal", [False, True])
@pytest.mark.parametrize("index_first", [False, True])
def test_external_passage_index_is_copied_before_load_and_index(tmp_path, monkeypatch, wal, index_first):
    from mnemosyne import cli

    source = tmp_path / "source"
    source.mkdir()
    index = tmp_path / "external.sqlite"
    original = sqlite3.connect(index)
    if wal:
        original.execute("PRAGMA journal_mode=WAL")
    original.execute("CREATE TABLE markers (value TEXT)")
    original.execute("INSERT INTO markers VALUES ('original')")
    original.commit()
    before = index.read_bytes()
    wal_path = Path(str(index) + "-wal")
    before_wal = wal_path.read_bytes() if wal else None
    monkeypatch.setenv("MNEMOSYNE_PASSAGE_INDEX", str(index))
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q", "question": "one", "gold": ["a"]}]))
    output = tmp_path / "report.json"
    seen = []

    def load_tools(args):
        seen.append(Path(args.passage_index))
        conn = sqlite3.connect(args.passage_index)
        assert conn.execute("SELECT value FROM markers").fetchall() == [("original",)]
        # Loading a writable sidecar may migrate it before indexing starts.
        conn.execute("INSERT INTO markers VALUES ('load')")
        conn.commit()

        def index_passages(tenant):
            conn.execute("INSERT INTO markers VALUES ('indexed')")
            conn.commit()
            return {"indexed": True}

        return SimpleNamespace(
            engine=SimpleNamespace(adapters=SimpleNamespace(passage_graph=None), close=conn.close),
            index_passages=index_passages,
            search=lambda **kwargs: {"hits": [{"id": "a"}], "abstained": False},
        )

    monkeypatch.setattr(cli, "load_tools", load_tools)
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(output),
        *(["--index-first"] if index_first else []),
    ])
    try:
        store_recall.main()
        assert original.execute("SELECT value FROM markers").fetchall() == [("original",)]
        assert index.read_bytes() == before
        if wal:
            assert wal_path.read_bytes() == before_wal
        assert seen[0] != index and not seen[0].exists()
        assert os.environ["MNEMOSYNE_PASSAGE_INDEX"] == str(index)
    finally:
        original.close()


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_output_cannot_replace_external_passage_index(tmp_path, monkeypatch, suffix):
    source = tmp_path / "source"
    source.mkdir()
    index = tmp_path / "external.sqlite"
    monkeypatch.setenv("MNEMOSYNE_PASSAGE_INDEX", str(index))
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(tmp_path / "absent.json"), "--out", str(index) + suffix,
    ])
    with pytest.raises(SystemExit) as exc:
        store_recall.main()
    assert exc.value.code == 2


def test_new_external_passage_index_is_created_only_in_copy(tmp_path, monkeypatch):
    from mnemosyne import cli

    source = tmp_path / "source"
    source.mkdir()
    index = tmp_path / "not-created" / "external.sqlite"
    monkeypatch.setenv("MNEMOSYNE_PASSAGE_INDEX", str(index))
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q", "question": "one", "gold": ["a"]}]))
    output = tmp_path / "report.json"
    opened = []

    def load_tools(args):
        opened.append(Path(args.passage_index))
        conn = sqlite3.connect(args.passage_index)
        conn.execute("CREATE TABLE markers (value TEXT)")
        return SimpleNamespace(
            engine=SimpleNamespace(adapters=SimpleNamespace(passage_graph=None), close=conn.close),
            search=lambda **kwargs: {"hits": [], "abstained": True},
        )

    monkeypatch.setattr(cli, "load_tools", load_tools)
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(output),
    ])
    store_recall.main()
    assert not index.parent.exists()
    assert opened[0] != index and not opened[0].exists()


def test_output_hardlink_to_passage_index_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    index = tmp_path / "external.sqlite"
    index.write_bytes(b"do not overwrite")
    output = tmp_path / "report.json"
    output.hardlink_to(index)
    monkeypatch.setenv("MNEMOSYNE_PASSAGE_INDEX", str(index))
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(tmp_path / "absent.json"), "--out", str(output),
    ])
    with pytest.raises(SystemExit) as exc:
        store_recall.main()
    assert exc.value.code == 2
    assert index.read_bytes() == b"do not overwrite"


def test_main_store_snapshots_each_live_database_without_sidecars(tmp_path, monkeypatch):
    from mnemosyne import cli

    monkeypatch.delenv("MNEMOSYNE_PASSAGE_INDEX", raising=False)
    source = tmp_path / "source"
    source.mkdir()
    assets = source / "tenant.proj"
    assets.mkdir()
    (assets / "notes.txt").write_bytes(b"preserve projection assets")
    # This is an ordinary asset despite its suffix, not a SQLite sidecar.
    (assets / "notes.txt-wal").write_bytes(b"also preserve this asset")
    originals = []
    snapshots = []
    for relative in ("tenant.db", "another.db", "tenant.proj/cache.sqlite"):
        database = source / relative
        conn = sqlite3.connect(database)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE records (value TEXT)")
        conn.execute("INSERT INTO records VALUES ('committed')")
        conn.commit()
        # This is still absent from the main file, so byte-copying only it loses data.
        conn.execute("INSERT INTO records VALUES ('uncommitted')")
        originals.append(conn)
        snapshots.append((database, database.read_bytes(), Path(str(database) + "-wal").read_bytes()))
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q", "question": "one", "gold": ["a"]}]))
    output = tmp_path / "report.json"

    def load_tools(args):
        copy = Path(args.store)
        assert (copy / "tenant.proj/notes.txt").read_bytes() == b"preserve projection assets"
        assert (copy / "tenant.proj/notes.txt-wal").read_bytes() == b"also preserve this asset"
        for database, _, _ in snapshots:
            copied = copy / database.relative_to(source)
            for suffix in ("-wal", "-shm", "-journal"):
                assert not Path(str(copied) + suffix).exists(), "backup must be a standalone database"
            # immutable ignores all sidecars and reads the standalone snapshot itself.
            conn = sqlite3.connect(f"{copied.as_uri()}?immutable=1", uri=True)
            try:
                assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert conn.execute("SELECT value FROM records").fetchall() == [("committed",)]
            finally:
                conn.close()
        return SimpleNamespace(
            engine=SimpleNamespace(adapters=SimpleNamespace(passage_graph=None)),
            search=lambda **kwargs: {"hits": [], "abstained": True},
        )

    monkeypatch.setattr(cli, "load_tools", load_tools)
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(output),
    ])
    try:
        store_recall.main()
        for database, original_bytes, original_wal in snapshots:
            assert database.read_bytes() == original_bytes
            assert Path(str(database) + "-wal").read_bytes() == original_wal
        for conn in originals:
            assert conn.execute("SELECT value FROM records").fetchall() == [("committed",), ("uncommitted",)]
    finally:
        for conn in originals:
            conn.close()


@pytest.mark.parametrize("relative", ["tenant.db", "tenant.db-wal", "tenant.db-shm", "nested/asset.txt"])
def test_output_hardlink_to_source_store_file_is_rejected(tmp_path, monkeypatch, relative):
    monkeypatch.delenv("MNEMOSYNE_PASSAGE_INDEX", raising=False)
    source = tmp_path / "source"
    original = source / relative
    original.parent.mkdir(parents=True)
    original.write_bytes(b"source content")
    output = tmp_path / "report.json"
    output.hardlink_to(original)
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(tmp_path / "absent.json"), "--out", str(output),
    ])
    with pytest.raises(SystemExit) as exc:
        store_recall.main()
    assert exc.value.code == 2
    assert original.read_bytes() == b"source content"


@pytest.mark.parametrize("keeps_changing", [False, True])
def test_database_snapshot_retries_changed_wal_or_fails_closed(tmp_path, monkeypatch, keeps_changing):
    database = tmp_path / "source.db"
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE records (value TEXT)")
    writer.execute("INSERT INTO records VALUES ('original')")
    writer.commit()
    output = tmp_path / "snapshot.db"
    real_copy = store_recall.shutil.copy2
    copies = []

    def copy_with_concurrent_write(src, dst, *args, **kwargs):
        result = real_copy(src, dst, *args, **kwargs)
        if Path(src) == database:
            copies.append(src)
            if keeps_changing or len(copies) == 1:
                writer.execute("INSERT INTO records VALUES (?)", (f"concurrent-{len(copies)}",))
                writer.commit()
        return result

    monkeypatch.setattr(store_recall.shutil, "copy2", copy_with_concurrent_write)
    try:
        if keeps_changing:
            with pytest.raises(RuntimeError, match="three snapshot attempts"):
                store_recall.snapshot_sqlite_database(database, output)
            assert len(copies) == 3
            assert not output.exists()
        else:
            store_recall.snapshot_sqlite_database(database, output)
            assert len(copies) == 2
            with sqlite3.connect(output) as snapshot:
                assert snapshot.execute("SELECT value FROM records").fetchall() == [
                    ("original",), ("concurrent-1",),
                ]
        assert not list(tmp_path.glob("sqlite-snapshot-*"))
    finally:
        writer.close()


@pytest.mark.parametrize("accepts_timezone", [False, True])
@pytest.mark.parametrize("timezone", ["America/Los_Angeles", None])
def test_optional_question_timezone_is_forwarded_when_supported(tmp_path, monkeypatch, accepts_timezone, timezone):
    from mnemosyne import cli

    monkeypatch.delenv("MNEMOSYNE_PASSAGE_INDEX", raising=False)
    source = tmp_path / "source"
    source.mkdir()
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{
        "id": "q", "question": "yesterday", "gold": ["a"],
        "now": "2026-10-22T02:00:00Z", "query_timezone": timezone,
    }]))
    seen = []

    def modern_search(*, tenant_id, query, lean, evaluated_at=None, query_timezone=None):
        seen.append((evaluated_at, query_timezone))
        return {"hits": [], "abstained": True}

    def legacy_search(*, tenant_id, query, lean, evaluated_at=None):
        seen.append((evaluated_at, None))
        return {"hits": [], "abstained": True}

    monkeypatch.setattr(cli, "load_tools", lambda args: SimpleNamespace(
        engine=SimpleNamespace(adapters=SimpleNamespace(passage_graph=None)),
        search=modern_search if accepts_timezone else legacy_search,
    ))
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(source), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(tmp_path / "report.json"),
    ])
    store_recall.main()
    assert seen == [("2026-10-22T02:00:00Z", timezone if accepts_timezone else None)]


@pytest.mark.parametrize("timezone", ["", " ", 123, "not/a/timezone"])
def test_invalid_question_timezone_rejected_before_loading(tmp_path, monkeypatch, timezone):
    from mnemosyne import cli

    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{
        "id": "q", "question": "yesterday", "gold": ["a"], "query_timezone": timezone,
    }]))
    monkeypatch.setattr(cli, "load_tools", lambda args: pytest.fail("must validate first"))
    monkeypatch.setattr("sys.argv", [
        "store_recall", "--store", str(tmp_path / "absent-store"), "--tenant", "synthetic",
        "--questions", str(questions), "--out", str(tmp_path / "report.json"),
    ])
    with pytest.raises(SystemExit) as exc:
        store_recall.main()
    assert exc.value.code == 2
