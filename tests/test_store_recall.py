import json
import os
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
