from __future__ import annotations

import json
from pathlib import Path

from eval.datasets.v2 import run_graph_ppr_postfix as postfix
from eval.harness.cli_driver import MnemoCLI
from mnemosyne.consolidation import _deterministic_candidates, _extract_simple_fact
from mnemosyne.models import Evidence


def test_simple_fact_extractor_scans_prose_deterministically() -> None:
    text = (
        "Bridge fixture\n"
        "Mara owns Helios. Helios ships in Q3 2026. "
        "Mara, Helios."
    )

    assert _extract_simple_fact(text, strip_title=True) == [
        ("Helios", "ships in", "Q3 2026"),
        ("Mara", "owns", "Helios"),
        ("Mara", "related_to", "Helios"),
    ]
    assert _extract_simple_fact(text, strip_title=True) == _extract_simple_fact(
        text, strip_title=True
    )


def test_simple_fact_extractor_strips_only_explicit_title_prefixes() -> None:
    titled = "What is Helios?\nMara owns Helios."
    untitled = "Mara owns Helios\nHelios ships in Q3 2026."

    assert _extract_simple_fact(titled, strip_title=True) == [
        ("Mara", "owns", "Helios")
    ]
    assert _extract_simple_fact(untitled) == [
        ("Helios", "ships in", "Q3 2026"),
        ("Mara", "owns", "Helios"),
    ]


def test_deterministic_candidates_preserve_policy_and_stable_order() -> None:
    evidence = Evidence(
        tenant_id="eval",
        user_id="benchmark-corpus",
        actor="user",
        source_type="hipporag:dev",
        source_identity="bridge",
        content="Bridge fixture\nMara owns Helios. Helios ships in Q3 2026.",
        trust_tier=2,
        sensitivity=3,
        access_policy={"tenant": "eval", "users": ["benchmark-corpus"]},
        cid="cid-bridge",
    )

    candidates = _deterministic_candidates({}, [evidence])

    assert [
        (
            row["candidate_subject"],
            row["candidate_predicate"],
            row["candidate_object"],
        )
        for row in candidates
    ] == [
        ("Helios", "ships in", "Q3 2026"),
        ("Mara", "owns", "Helios"),
    ]
    assert all(row["trust_tier"] == 2 for row in candidates)
    assert all(row["sensitivity"] == 3 for row in candidates)
    assert all(row["access_policy"] == evidence.access_policy for row in candidates)


def test_capture_batch_persists_every_extracted_fact_with_provenance(
    tmp_path: Path,
) -> None:
    rows = tmp_path / "facts.jsonl"
    rows.write_text(
        json.dumps(
            {
                "tenant": "eval",
                "user": "benchmark-corpus",
                "actor": "user",
                "source_type": "hipporag:dev",
                "source_identity": "bridge",
                "content": (
                    "Bridge fixture\n"
                    "Mara owns Helios. Helios ships in Q3 2026."
                ),
                "trust_tier": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store = tmp_path / "store.json"
    cli = MnemoCLI(store=str(store))
    cli.install_consolidation_gate_case("Mara owns Helios.")

    captured = cli.capture_batch(rows, consolidate=True)
    state = json.loads(store.read_text(encoding="utf-8"))
    source_cid = captured["results"][0]["cid"]
    assertions = {
        (row["subject"], row["predicate"], row["object"]): row
        for row in state["assertions"]
        if row["branch"] == "main"
    }

    assert set(assertions) == {
        ("Helios", "ships in", "Q3 2026"),
        ("Mara", "owns", "Helios"),
    }
    assert all(row["source_evidence_cids"] == [source_cid] for row in assertions.values())
    assert all(row["access_policy"]["tenant"] == "eval" for row in assertions.values())
    assert len(state["relations"]) >= len(assertions)


def test_reconsolidating_identical_evidence_keeps_relations_idempotent(
    tmp_path: Path,
) -> None:
    rows = tmp_path / "facts.jsonl"
    rows.write_text(
        json.dumps(
            {
                "tenant": "eval",
                "user": "benchmark-corpus",
                "source_type": "qa-v2-dev",
                "source_identity": "d1",
                "content": "Mara owns Helios.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store = tmp_path / "store.json"
    cli = MnemoCLI(store=str(store))
    cli.install_consolidation_gate_case("Mara owns Helios.")

    cli.capture_batch(rows, consolidate=True)
    first = [
        row
        for row in json.loads(store.read_text(encoding="utf-8"))["relations"]
        if row["branch"] == "main"
    ]
    cli.capture_batch(rows, consolidate=True)
    second = [
        row
        for row in json.loads(store.read_text(encoding="utf-8"))["relations"]
        if row["branch"] == "main"
    ]

    assert len(second) == len(first)
    assert {
        (row["source"], row["predicate"], row["target"])
        for row in second
    } == {
        (row["source"], row["predicate"], row["target"])
        for row in first
    }


def test_local_graph_fix_has_deterministic_bridge_recall(tmp_path: Path) -> None:
    summary = postfix.run_postfix(tmp_path / "postfix")

    assert summary["dataset_id"] == "qa_scale_dev_v1"
    assert summary["decomposition_matrix"] == {"case_count": 16, "passed": 16}
    assert summary["traces_byte_identical"] is True
    for run in summary["runs"]:
        assert run["actual_engine"] == "local"
        assert run["relations"] > 0
        assert run["graph_ppr_channel_sum"] > 0
        assert run["direct_retrieval_recall_at_5"] == 1.0
        assert run["per_query"]["q01"]["direct_retrieval_recall_at_5"] == 1.0
        assert run["per_query"]["q01"]["graph_ppr"] > 0

    report = Path(
        "eval/reports/phase-12-graph-fix-b-local-dev-2026-07-16.md"
    ).read_text(encoding="utf-8")
    assert "local-engine development iteration — non-headline, non-production evidence" in report
    assert all(run["trace_sha256"] in report for run in summary["runs"])
    assert "| Persisted relations | 7 | 7 |" in report


def test_graph_fix_preserves_dense_lexical_single_hop_retrieval(
    tmp_path: Path,
) -> None:
    rows = tmp_path / "corpus.jsonl"
    rows.write_text(
        "\n".join(
            json.dumps(
                {
                    "tenant": "eval",
                    "user": "benchmark-corpus",
                    "source_type": "qa-v2-dev",
                    "source_identity": doc_id,
                    "content": content,
                }
            )
            for doc_id, content in (
                ("d1", "Mara owns Helios."),
                ("d2", "Helios ships in Q3 2026."),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    query = tmp_path / "query.jsonl"
    query.write_text(
        json.dumps(
            {
                "question_id": "single-hop",
                "tenant": "eval",
                "query": "Who owns Helios?",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    observed: list[tuple[str, bool]] = []
    for name, consolidate in (("baseline", False), ("postfix", True)):
        cli = MnemoCLI(store=str(tmp_path / f"{name}.json"))
        if consolidate:
            cli.install_consolidation_gate_case("Mara owns Helios.")
        captured = cli.capture_batch(rows, consolidate=consolidate)
        d1_cid = captured["results"][0]["cid"]
        read_cli = MnemoCLI(
            store=cli.store,
            global_flags=["--evaluation-read-only"],
        )
        hits = read_cli.eval_query_batch(query)["results"][0]["search"]["hits"]
        dense_lexical = [
            hit
            for hit in hits
            if "dense" in hit["channel"] or "lexical" in hit["channel"]
        ]
        observed.append(
            (name, any(d1_cid in hit.get("provenance", []) for hit in dense_lexical))
        )

    assert observed == [("baseline", True), ("postfix", True)]
