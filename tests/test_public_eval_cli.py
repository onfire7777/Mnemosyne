from __future__ import annotations

import hashlib
import json
import sys
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import pytest

from eval.harness.cli_driver import CLIError, MnemoCLI
from eval.public.bundle import BundleError, verify_report, write_report
from eval.public.runner import run_public_suite
from mnemosyne.providers.extractive_decomposer import CONTENT_SHA256, SELECTOR


_QUERY_CUSTODY_ENV = {
    "MNEMOSYNE_QUERY_DECOMPOSER_CONTENT_SHA256": CONTENT_SHA256,
    "MNEMOSYNE_QUERY_DECOMPOSER_SELECTOR": SELECTOR,
}


def test_evaluation_read_only_disables_http_cache_and_command_retrievers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mnemosyne import cli as cli_module
    from mnemosyne import retrieval

    observed: dict[str, object] = {}

    class Embedding:
        def __init__(self, **kwargs: object) -> None:
            observed.update(kwargs)

    class Reranker:
        def __init__(self, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(retrieval, "HttpEmbeddingProvider", Embedding)
    monkeypatch.setattr(retrieval, "LocalSimilarityReranker", Reranker)
    cache = tmp_path / "durable-cache.json"
    args = Namespace(
        embedding_dims=8,
        retrieval_timeout=1.0,
        evaluation_read_only=True,
        embedding_provider="http",
        embedding_url="https://embedding.example.test",
        embedding_model="model",
        embedding_model_revision="revision",
        embedding_api_key=None,
        embedding_cache_size=100,
        embedding_cache_path=str(cache),
        embedding_cache_ttl_seconds=60.0,
        embedding_cache_scope="scope",
        reranker_provider="local",
        reranker_url=None,
        reranker_model=None,
        reranker_api_key=None,
        lexical_provider="postgres",
        lexical_command=None,
        lexical_backend="postgres-fts",
        graph_provider="postgres",
        graph_command=None,
        graph_backend="postgres-recursive-ppr",
    )
    cli_module.load_retrieval_adapters(args)
    assert observed["cache_size"] == 0 and observed["cache_path"] is None
    assert not cache.exists()
    args.lexical_provider = "command"
    args.lexical_command = "external"
    with pytest.raises(SystemExit, match="forbids command"):
        cli_module.load_retrieval_adapters(args)


def test_report_requires_matching_verified_reproduction_and_binds_note(
    tmp_path: Path,
) -> None:
    source, reproduced = tmp_path / "source", tmp_path / "reproduced"
    run_public_suite("smoke", source)
    from eval.public.bundle import reproduce_bundle

    reproduce_bundle(source, reproduced)
    report, note = tmp_path / "report.json", tmp_path / "report.md"
    result = write_report(source, reproduced, report, note)
    assert result["sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert verify_report(report, note)["valid"] is True
    assert result["sha256"] in note.read_text()
    payload = json.loads(report.read_text())
    assert payload["evidence"]["assets"][0]["dataset_sha256"]
    assert payload["evidence"]["counts"] == {"eligible": 2, "excluded": 0, "traces": 2}
    assert payload["evidence"]["metrics"]["trace_count"] == 2
    assert payload["evidence"]["reproduction"]["verified"] is True
    assert payload["generated_at"].endswith("Z")
    assert payload["command"][0:2] == ["mneme", "eval-public"]

    note.write_text(note.read_text().replace(result["sha256"], "0" * 64))
    with pytest.raises(BundleError, match="note binding"):
        verify_report(report, note)

    # Canonical byte equality rejects plausible-looking prefix/suffix text too.
    note.write_bytes(b"trusted\n" + note.read_bytes())
    with pytest.raises(BundleError, match="canonical"):
        verify_report(report, note)


def test_report_refuses_mismatched_reproduction(tmp_path: Path) -> None:
    source, reproduced = tmp_path / "source", tmp_path / "reproduced"
    run_public_suite("smoke", source)
    run_public_suite("smoke", reproduced)
    traces = reproduced / "traces.jsonl"
    traces.write_bytes(
        b"".join(reversed(traces.read_bytes().splitlines(keepends=True)))
    )
    manifest = json.loads((reproduced / "bundle-manifest.json").read_text())
    manifest["files"]["traces.jsonl"] = hashlib.sha256(traces.read_bytes()).hexdigest()
    (reproduced / "bundle-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    with pytest.raises(BundleError):
        write_report(source, reproduced, tmp_path / "report.json", tmp_path / "note.md")


def test_capture_batch_matches_capture_and_rejects_schema_before_writes(
    tmp_path: Path,
) -> None:
    cli = MnemoCLI(store=str(tmp_path / "store.json"))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {"tenant": "t", "user": "u", "source_type": "benchmark", "content": "alpha"}
        )
        + "\n"
        + json.dumps(
            {
                "tenant": "t",
                "user": "u",
                "source_type": "benchmark",
                "content": "beta",
                "trust_tier": 1,
            }
        )
        + "\n"
    )
    result = cli.capture_batch(rows)
    assert result["ok"] is True and result["count"] == 2
    assert len(result["results"]) == 2

    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        json.dumps(
            {"tenant": "t", "user": "u", "source_type": "benchmark", "content": "gamma"}
        )
        + "\n{}\n"
    )
    before = cli.search("t", "gamma")
    with pytest.raises(CLIError, match="invalid schema"):
        cli.capture_batch(bad)
    after = cli.search("t", "gamma")
    assert before == after


def test_capture_batch_consolidates_every_cid_only_when_opted_in(tmp_path: Path) -> None:
    """Eval rows pass both gates: trust 0 is writable and missing error defaults high."""
    rows = tmp_path / "facts.jsonl"
    rows.write_text(
        "\n".join(
            json.dumps(
                {
                    "tenant": "eval",
                    "user": "benchmark-corpus",
                    "actor": "user",
                    "source_type": "qa-v2-dev",
                    "source_identity": source_identity,
                    "content": content,
                    "trust_tier": 0,
                }
            )
            for source_identity, content in (
                ("d1", "Mara is the owner of Helios."),
                ("d2", "Helios is a project shipping in Q3 2026."),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    default_store = tmp_path / "default.json"
    MnemoCLI(store=str(default_store)).capture_batch(rows)
    assert json.loads(default_store.read_text(encoding="utf-8"))["relations"] == []

    consolidated_store = tmp_path / "consolidated.json"
    consolidated = MnemoCLI(store=str(consolidated_store)).capture_batch(
        rows, consolidate=True
    )
    payload = json.loads(consolidated_store.read_text(encoding="utf-8"))
    captured_cids = {item["cid"] for item in consolidated["results"]}
    relation_cids = {
        cid
        for relation in payload["relations"]
        for cid in relation["source_evidence_cids"]
    }
    job = consolidated["consolidation"]["jobs"][0]
    pass_statuses = {
        item["name"]: item["status"] for item in job["result"]["pass_results"]
    }
    assert payload["relations"]
    assert captured_cids <= relation_cids
    assert set(job["result"]["source_evidence_cids"]) == captured_cids
    assert pass_statuses["extractor"] == "complete"
    assert "source_marked_data_only" not in job["result"]["skipped"]
    assert {
        (item["tenant_id"], item["source_identity"], item["access_policy"]["tenant"])
        for item in payload["evidence"]
        if item["cid"] in captured_cids
    } == {("eval", "d1", "eval"), ("eval", "d2", "eval")}


def test_capture_batch_consolidation_failure_preserves_original_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mnemosyne import cli as cli_module

    store = tmp_path / "store.json"
    MnemoCLI(store=str(store)).capture("t", "u", "original", source_type="fixture")
    original = store.read_bytes()
    rows = tmp_path / "facts.jsonl"
    rows.write_text(
        json.dumps(
            {
                "tenant": "t",
                "user": "u",
                "source_type": "qa-v2-dev",
                "content": "Mara is the owner of Helios.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FailingExtractor:
        def extract(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            raise RuntimeError("injected consolidation failure")

    monkeypatch.setattr(cli_module, "load_candidate_extractor", lambda _args: FailingExtractor())
    args = cli_module.build_parser().parse_args(
        ["--store", str(store), "capture-batch", "--input-jsonl", str(rows), "--consolidate"]
    )
    with pytest.raises(RuntimeError, match="injected consolidation failure"):
        cli_module.cmd_capture_batch(args)
    assert store.read_bytes() == original
    assert not list(tmp_path.glob(".store.json-batch-*"))


def test_capture_batch_driver_forwards_consolidation_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[object] = []

    def fake_run(self: MnemoCLI, command: str, *args: str, **_kwargs: object) -> Namespace:
        observed.extend((command, *args))
        return Namespace(json={"ok": True})

    monkeypatch.setattr(MnemoCLI, "run", fake_run)
    MnemoCLI(store=str(tmp_path / "store.json")).capture_batch(
        tmp_path / "rows.jsonl", consolidate=True
    )
    assert observed == [
        "capture-batch",
        "--input-jsonl",
        str(tmp_path / "rows.jsonl"),
        "--consolidate",
    ]


def test_capture_batch_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text(
        json.dumps({"tenant": "t", "user": "u", "source_type": "x", "content": "x"})
        + "\n"
    )
    linked = tmp_path / "linked.jsonl"
    linked.symlink_to(target)
    with pytest.raises(CLIError, match="real file"):
        MnemoCLI(store=str(tmp_path / "store.json")).capture_batch(linked)


def test_capture_batch_preserves_only_safe_episode_adjacency_metadata(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store.json"
    cli = MnemoCLI(store=str(store))
    rows = tmp_path / "episode.jsonl"
    rows.write_text(
        json.dumps(
            {
                "tenant": "t",
                "user": "u",
                "source_type": "benchmark",
                "source_identity": "source-a",
                "session_id": "session-a",
                "turn_index": 2,
                "content": "safe episode turn",
            }
        )
        + "\n"
    )
    cli.capture_batch(rows)
    evidence = json.loads(store.read_text())["evidence"][0]
    assert evidence["session_id"] == "session-a"
    assert evidence["metadata"]["episode"] == {
        "session_id": "session-a",
        "source_identity": "source-a",
        "turn_index": 2,
    }
    assert not {"oracle_answer", "answer_session_ids"} & set(evidence["metadata"])

    for unsafe in (
        {"oracle_answer": "secret"},
        {"answer_session_ids": ["session-a"]},
        {"session_id": "session-a", "turn_index": -1},
    ):
        bad = tmp_path / "unsafe.jsonl"
        bad.write_text(
            json.dumps(
                {
                    "tenant": "t",
                    "user": "u",
                    "source_type": "benchmark",
                    "source_identity": "source-a",
                    "content": "unsafe",
                    **unsafe,
                }
            )
            + "\n"
        )
        before = store.read_bytes()
        with pytest.raises(CLIError):
            cli.capture_batch(bad)
        assert store.read_bytes() == before


def test_single_capture_preserves_exact_safe_episode_metadata(tmp_path: Path) -> None:
    store = tmp_path / "single.json"
    cli = MnemoCLI(store=str(store))
    result = cli.capture(
        "t", "u", "safe turn", source_type="benchmark",
        source_identity="source-a", session_id="session-a", turn_index=0,
    )
    evidence = json.loads(store.read_text())["evidence"][0]
    assert evidence["cid"] == result["cid"]
    assert evidence["source_identity"] == "source-a"
    assert evidence["session_id"] == "session-a"
    assert evidence["metadata"]["episode"] == {
        "session_id": "session-a",
        "source_identity": "source-a",
        "turn_index": 0,
    }

    before = store.read_bytes()
    with pytest.raises(CLIError, match="requires"):
        cli.capture(
            "t", "u", "unsafe", source_type="benchmark",
            source_identity="source-a", session_id="session-a",
        )
    assert store.read_bytes() == before


def test_evaluation_read_only_allows_concurrent_queries_without_store_writes(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store.json"
    cli = MnemoCLI(store=str(store))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {
                "tenant": "t",
                "user": "u",
                "source_type": "benchmark",
                "content": "alpha graph evidence",
            }
        )
        + "\n"
    )
    cli.capture_batch(rows)
    state_files = [store, *tmp_path.glob("store.json.runtime.json")]
    before_names = {path.name for path in tmp_path.iterdir()}
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in state_files
    }
    read_only = replace(cli, global_flags=["--evaluation-read-only"])

    def query(_: int) -> tuple[dict, dict]:
        return read_only.search("t", "alpha"), read_only.explain("t", "alpha")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(query, range(8)))

    assert all(search["hits"] for search, _ in results)
    ordinary_store = tmp_path / "ordinary.json"
    ordinary_store.write_bytes(store.read_bytes())
    ordinary = MnemoCLI(store=str(ordinary_store))
    ordinary_search = ordinary.search("t", "alpha")
    assert [hit["id"] for hit in results[0][0]["hits"]] == [
        hit["id"] for hit in ordinary_search["hits"]
    ]
    assert results[0][1]["explain"].get("channels") == ordinary_search["explain"].get(
        "channels"
    )
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in state_files
    } == before
    assert {path.name for path in tmp_path.iterdir()} == before_names | {
        "ordinary.json",
        "ordinary.json.runtime.json",
    }
    with pytest.raises(CLIError, match="restricted to local evaluation query"):
        read_only.capture_batch(rows)


def test_evaluation_query_batch_matches_public_search_explain_and_is_read_only(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store.json"
    cli = MnemoCLI(store=str(store))
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {
                "tenant": "t",
                "user": "u",
                "source_type": "benchmark",
                "content": "alpha graph evidence",
            }
        )
        + "\n"
    )
    cli.capture_batch(rows)
    queries = tmp_path / "queries.jsonl"
    query_rows = [
        {"question_id": "q1", "tenant": "t", "query": "alpha"},
        {"question_id": "q2", "tenant": "t", "query": "graph"},
    ]
    queries.write_text("".join(json.dumps(row) + "\n" for row in query_rows))
    reversed_queries = tmp_path / "reversed.jsonl"
    reversed_queries.write_text(
        "".join(json.dumps(row) + "\n" for row in reversed(query_rows))
    )
    singles = []
    for index, row in enumerate(query_rows):
        path = tmp_path / f"single-{index}.jsonl"
        path.write_text(json.dumps(row) + "\n")
        singles.append(path)
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"question_id":"q","question_id":"other","tenant":"t","query":"x"}\n'
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    read_only = replace(cli, global_flags=["--evaluation-read-only"])
    result = read_only.eval_query_batch(queries)
    assert result["count"] == 2
    assert [row["question_id"] for row in result["results"]] == ["q1", "q2"]
    assert all(row["search"]["hits"] for row in result["results"])
    reversed_result = read_only.eval_query_batch(reversed_queries)
    single_results = [read_only.eval_query_batch(path) for path in singles]

    def projections(payloads: list[dict]) -> dict[str, tuple[list[str], object]]:
        return {
            row["question_id"]: (
                [hit["id"] for hit in row["search"]["hits"]],
                row["explanation"].get("channels"),
            )
            for payload in payloads
            for row in payload["results"]
        }

    assert projections([result]) == projections([reversed_result])
    assert projections([result]) == projections(single_results)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    with pytest.raises(CLIError, match="invalid JSON"):
        read_only.eval_query_batch(duplicate)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_public_answer_and_batch_are_ordered_grounded_and_store_immutable(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store.json"
    ordinary = MnemoCLI(store=str(store))
    ordinary.capture("answer-tenant", "user-a", "Ada owns project Zephyr.")
    provider = tmp_path / "grounded-provider.py"
    provider.write_text(
        """#!/usr/bin/env python3
import json, sys
from mnemosyne.providers.grounded_protocol import GENERATION_SPEC, role_digests
from mnemosyne.providers.extractive_decomposer import disclosure
request = json.load(sys.stdin)
role = request["prompt_boundary"]["role"]
metadata = (disclosure() if role == "query_decomposer" else
            {"role": role, "model": "qwen3:8b", "model_content_digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
             **role_digests(role), "decoding_options": GENERATION_SPEC})
if role == "query_decomposer":
    evidence = request.get("evidence") or []
    response = {"queries": ([] if evidence else [request["question"]]), "metadata": metadata}
else:
    evidence = request.get("evidence") or []
    response = ({"claims": [{"spans": [{"cid": evidence[0]["cid"],
                "quote": evidence[0]["content"]}]}],
                "unresolved": False, "metadata": metadata} if evidence else
                {"claims": [], "unresolved": True, "metadata": metadata})
json.dump(response, sys.stdout)
"""
    )
    provider.chmod(0o700)
    env = {
        **_QUERY_CUSTODY_ENV,
        "MNEMOSYNE_QUERY_DECOMPOSER_PROVIDER": "command",
        "MNEMOSYNE_QUERY_DECOMPOSER_COMMAND": f"{sys.executable} {provider}",
        "MNEMOSYNE_GROUNDED_READER_PROVIDER": "command",
        "MNEMOSYNE_GROUNDED_READER_COMMAND": f"{sys.executable} {provider}",
        "MNEMOSYNE_GROUNDED_MODEL_CONTENT_SHA256": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
        "MNEMOSYNE_GROUNDED_MODEL_SELECTOR": "qwen3:8b",
    }
    read_only = replace(
        ordinary, global_flags=["--evaluation-read-only"], env=env
    )
    context = {"tenant_id": "answer-tenant", "user_id": "user-a", "role": "reader"}
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    answer = read_only.answer("Ada", context)
    assert answer["abstained"] is False
    assert answer["claims"] and answer["claims"][0]["evidence_cids"]
    assert set(answer["claims"][0]) == {"text", "evidence_cids", "spans"}
    assert set(answer["claims"][0]["spans"][0]) == {"cid", "start", "end", "slice_sha256"}
    assert answer["claims"][0]["spans"][0]["slice_sha256"] == hashlib.sha256(
        answer["answer"].encode("utf-8")
    ).hexdigest()
    assert "Ada owns project Zephyr." not in json.dumps(answer["claims"][0]["spans"])
    assert set(answer) == {"answer", "claims", "abstained", "hops", "reader"}
    assert set(answer["reader"]) == {"query_decomposer", "grounded_reader"}
    assert all(set(hop) == {"index", "queries", "channels", "retrieved_cids"} for hop in answer["hops"])
    assert "content" not in json.dumps(answer["hops"])

    rows = tmp_path / "answer-rows.jsonl"
    rows.write_text(
        "".join(
            json.dumps({"question_id": question_id, "question": "Ada", "context": context}) + "\n"
            for question_id in ("q2", "q1")
        )
    )
    before[rows.name] = rows.read_bytes()
    batch = read_only.eval_answer_batch(rows)
    assert [row["question_id"] for row in batch["results"]] == ["q2", "q1"]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_capture_batch_paraphrase_uses_initial_decomposition_and_reaches_reader(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store.json"
    cli = MnemoCLI(store=str(store))
    captures = tmp_path / "captures.jsonl"
    captures.write_text(
        "\n".join(
            json.dumps(
                {
                    "tenant": "dev", "user": "dev-user",
                    "source_type": "qa-v2-dev", "source_identity": doc,
                    "content": content, "trust_tier": 0,
                }
            )
            for doc, content in (
                ("d1", "Mara owns Helios."),
                ("d2", "Helios ships in Q3 2026."),
            )
        ) + "\n"
    )
    cli.capture_batch(captures)
    provider = tmp_path / "decomposing-provider.py"
    provider.write_text(
        """import json, sys
from mnemosyne.providers.grounded_protocol import GENERATION_SPEC, role_digests
from mnemosyne.providers.extractive_decomposer import disclosure
request = json.load(sys.stdin)
role = request["prompt_boundary"]["role"]
metadata = (disclosure() if role == "query_decomposer" else
            {"role": role, "model": "qwen3:8b", "model_content_digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
             **role_digests(role), "decoding_options": GENERATION_SPEC})
evidence = request.get("evidence") or []
if role == "query_decomposer":
    queries = (["Mara"] if not evidence else
               (["Mara", "project", "ship"] if not any("Q3 2026" in row["content"] for row in evidence) else []))
    response = {"queries": queries, "metadata": metadata}
else:
    row = next(item for item in evidence if "Q3 2026" in item["content"])
    response = {"claims": [{"spans": [{"cid": row["cid"], "quote": "Q3 2026"}]}],
                "unresolved": False, "metadata": metadata}
json.dump(response, sys.stdout)
"""
    )
    env = {
        **_QUERY_CUSTODY_ENV,
        "MNEMOSYNE_QUERY_DECOMPOSER_PROVIDER": "command",
        "MNEMOSYNE_QUERY_DECOMPOSER_COMMAND": f"{sys.executable} {provider}",
        "MNEMOSYNE_GROUNDED_READER_PROVIDER": "command",
        "MNEMOSYNE_GROUNDED_READER_COMMAND": f"{sys.executable} {provider}",
        "MNEMOSYNE_GROUNDED_MODEL_CONTENT_SHA256": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
        "MNEMOSYNE_GROUNDED_MODEL_SELECTOR": "qwen3:8b",
    }
    rows = tmp_path / "answers.jsonl"
    rows.write_text(json.dumps({
        "question_id": "q1", "question": "When does Mara's project ship?",
        "context": {"tenant_id": "dev", "user_id": "dev-user", "role": "reader"},
    }) + "\n")
    result = replace(
        cli, global_flags=["--evaluation-read-only"], env=env
    ).eval_answer_batch(rows)["results"][0]
    assert result["abstained"] is False and result["claims"]
    assert len(result["hops"]) == 3
    assert result["hops"][2]["queries"] == ["2026", "ships"]
    assert [hop["queries"] for hop in result["hops"]] == [
        ["Mara"],
        ["Helios"],
        ["2026", "ships"],
    ]


def test_answer_batch_prevalidates_and_provider_failures_leave_no_state(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store.json"
    ordinary = MnemoCLI(store=str(store))
    ordinary.capture("answer-tenant", "user-a", "Ada owns project Zephyr.")
    marker = tmp_path / "provider-called"
    provider = tmp_path / "slow-provider.py"
    provider.write_text(
        f"import pathlib,time\npathlib.Path({str(marker)!r}).write_text('called')\ntime.sleep(1)\n"
    )
    env = {
        **_QUERY_CUSTODY_ENV,
        "MNEMOSYNE_QUERY_DECOMPOSER_PROVIDER": "command",
        "MNEMOSYNE_QUERY_DECOMPOSER_COMMAND": f"{sys.executable} {provider}",
        "MNEMOSYNE_GROUNDED_READER_PROVIDER": "command",
        "MNEMOSYNE_GROUNDED_READER_COMMAND": f"{sys.executable} {provider}",
        "MNEMOSYNE_GROUNDED_MODEL_CONTENT_SHA256": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
        "MNEMOSYNE_GROUNDED_MODEL_SELECTOR": "qwen3:8b",
        "MNEMOSYNE_GROUNDED_PROVIDER_TIMEOUT": "0.01",
    }
    read_only = replace(ordinary, global_flags=["--evaluation-read-only"], env=env)
    context = {"tenant_id": "answer-tenant", "user_id": "user-a", "role": "reader"}
    bad = tmp_path / "bad-answers.jsonl"
    bad.write_text(
        json.dumps({"question_id": "q1", "question": "Ada", "context": context})
        + "\n{}\n"
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(CLIError, match="invalid schema"):
        read_only.eval_answer_batch(bad)
    assert not marker.exists()
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before

    timed_out = read_only.answer("Ada", context)
    assert timed_out["abstained"] is True and timed_out["reader"] == {}
    after_allowed_marker = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path != marker
    }
    assert after_allowed_marker == before

def test_capture_batch_rolls_back_a_later_capture_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    from mnemosyne import cli as cli_module

    store = tmp_path / "store.json"
    store.write_text('{"original":true}\n')
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        "".join(
            json.dumps(
                {"tenant": "t", "user": "u", "source_type": "x", "content": value}
            )
            + "\n"
            for value in ("one", "two")
        )
    )

    class FailingTools:
        def __init__(self, staged: Path) -> None:
            self.staged = staged
            self.calls = 0
            self.engine = self

        def defer_persistence(self):
            return nullcontext()

        def capture(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            self.staged.write_text(json.dumps({"captured": self.calls}))
            if self.calls == 2:
                raise RuntimeError("injected later failure")
            return {"ok": True}

    monkeypatch.setattr(
        cli_module, "load_tools", lambda args: FailingTools(Path(args.store))
    )
    args = argparse.Namespace(
        backend="local",
        store=str(store),
        input_jsonl=rows,
        max_records=10,
        max_ingest_bytes=1024 * 1024,
    )
    with pytest.raises(RuntimeError, match="injected"):
        cli_module.cmd_capture_batch(args)
    assert store.read_text() == '{"original":true}\n'
    assert not list(tmp_path.glob(".store.json-batch-*"))


def test_local_engine_deferred_persistence_flushes_once_or_discards(
    tmp_path: Path,
) -> None:
    from mnemosyne.engine import LocalMemoryEngine

    committed = tmp_path / "committed.json"
    engine = LocalMemoryEngine(store_path=committed)
    with engine.defer_persistence():
        with engine.defer_persistence():
            engine._persist()
            engine._persist()
            assert not committed.exists()
        assert not committed.exists()
    assert committed.is_file()

    discarded = tmp_path / "discarded.json"
    engine = LocalMemoryEngine(store_path=discarded)
    with pytest.raises(RuntimeError, match="abort"):
        with engine.defer_persistence():
            engine._persist()
            raise RuntimeError("abort")
    assert not discarded.exists()
    with pytest.raises(RuntimeError, match="transaction was aborted"):
        engine._persist()


def test_cli_qa_run_verify_reproduce_and_report_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    from eval.public.runner import load_qa_protocol, qa_protocol_digests
    import eval.public.runner as public_runner
    from mnemosyne.cli import main

    protocol, digests = load_qa_protocol(), qa_protocol_digests()
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    candidate = {
        "candidate_version": protocol["version"], "created_at_utc": "2026-07-11T00:00:00Z",
        "git_sha": head, "model_content_sha256": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41", **digests,
        "evidence_budget": protocol["evidence_budget"],
        "abstention": protocol["abstention"], "transport_retries": 0,
    }
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n")
    source, reproduced = tmp_path / "qa-source", tmp_path / "qa-reproduced"
    report, note = tmp_path / "qa-report.json", tmp_path / "qa-report.md"
    monkeypatch.setattr(public_runner, "require_clean_candidate_checkout", lambda _sha: None)
    assert main(["eval-public", "--suite", "qa-smoke", "--candidate-manifest", str(candidate_path), "--out-dir", str(source)]) == 0
    assert main(["eval-public", "--verify-bundle", str(source)]) == 0
    assert main(["eval-public", "--reproduce-bundle", str(source), "--out-dir", str(reproduced)]) == 0
    assert (source / "candidate-manifest.json").read_bytes() == (reproduced / "candidate-manifest.json").read_bytes()
    assert main(["eval-public", "--write-report", str(source), "--reproduced-bundle", str(reproduced), "--report-output", str(report), "--report-note", str(note)]) == 0
    assert main(["eval-public", "--verify-report", str(report), "--report-note", str(note)]) == 0
