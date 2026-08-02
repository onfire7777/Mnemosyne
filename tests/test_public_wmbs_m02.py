from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from eval.public import wmbs_m02 as m02
from eval.public.scoring import normalize_answer as canonical_normalize_answer


REPO_ROOT = Path(__file__).resolve().parents[1]


def _resign(fixture: dict) -> None:
    fixture["fixture_sha256"] = m02.canonical_sha256(
        {key: value for key, value in fixture.items() if key != "fixture_sha256"}
    )


def _perfect_traces(fixture: dict, *, evidence: bool = False) -> list[dict]:
    traces = []
    for question in fixture["questions"]:
        answer = question["answers"][0] if question["answers"] else None
        trace = {
            "case_id": question["question_id"],
            "question_id": question["question_id"],
            "ranked_hits": [
                {"rank": rank, "stable_item_id": stable_item_id}
                for rank, stable_item_id in enumerate(question["gold_doc_ids"], start=1)
            ],
            "answer": answer,
            "abstained": answer is None,
        }
        if evidence and question["family"] != "unanswerable":
            trace["evidence_ids"] = list(question["gold_doc_ids"])
        traces.append(trace)
    return traces


def _case(fixture: dict, family: str) -> tuple[int, dict]:
    return next(
        (index, question)
        for index, question in enumerate(fixture["questions"])
        if question["family"] == family
    )


def test_committed_fixture_bytes_equal_generated_bytes() -> None:
    expected = m02.canonical_json(m02.generate_fixture(m02.DEFAULT_SEED))
    assert m02.FIXTURE_PATH.read_bytes() == expected
    fixture = m02.load_fixture()
    assert fixture["fixture_sha256"] == m02.canonical_sha256(
        {key: value for key, value in fixture.items() if key != "fixture_sha256"}
    )
    assert fixture["license"] == "CC0-1.0"
    assert len(fixture["corpus"]) == 240
    assert len(fixture["questions"]) == 60
    assert {
        family: sum(q["family"] == family for q in fixture["questions"])
        for family in m02.QUERY_FAMILIES
    } == {
        "exact": 10,
        "paraphrase": 10,
        "entity": 10,
        "relation": 10,
        "multi-hop": 10,
        "unanswerable": 10,
    }


def test_generator_is_seed_deterministic_and_seed_sensitive() -> None:
    first = m02.canonical_json(m02.generate_fixture(7))
    assert first == m02.canonical_json(m02.generate_fixture(7))
    assert first != m02.canonical_json(m02.generate_fixture(8))


def test_multi_document_gold_is_observable_from_query_and_corpus() -> None:
    for fixture in (m02.generate_fixture(), m02.load_fixture()):
        corpus = {
            document["stable_item_id"]: document for document in fixture["corpus"]
        }
        for question in fixture["questions"]:
            if len(question["gold_doc_ids"]) < 2:
                continue
            marker = question["answers"][0]
            assert marker in question["text"]
            assert all(
                marker in corpus[doc_id]["content"]
                for doc_id in question["gold_doc_ids"]
            )


def test_scorer_scores_the_committed_fixture() -> None:
    fixture = m02.load_fixture()
    result = m02.score_retrieval(fixture, _perfect_traces(fixture))
    assert result["total"] == 60
    assert result["trace_count"] == 60
    assert result["metrics"]["recall_at_10"] == 1.0


def test_scorer_rejects_gold_ids_outside_corpus() -> None:
    fixture = m02.generate_fixture()
    fixture["questions"][0]["gold_doc_ids"] = ["not-in-corpus"]
    _resign(fixture)
    with pytest.raises(m02.WmbsM02Error, match="reference the corpus"):
        m02.score_retrieval(fixture, _perfect_traces(fixture))


def test_scorer_rejects_duplicate_ranked_ids() -> None:
    fixture = m02.generate_fixture()
    traces = _perfect_traces(fixture)
    index, question = _case(fixture, "exact")
    stable_item_id = question["gold_doc_ids"][0]
    traces[index]["ranked_hits"] = [
        {"rank": 1, "stable_item_id": stable_item_id},
        {"rank": 2, "stable_item_id": stable_item_id},
    ]
    with pytest.raises(m02.WmbsM02Error, match="duplicate ranked stable_item_id"):
        m02.score_retrieval(fixture, traces)


def test_scorer_scores_unanswerable_with_empty_gold_and_empty_hits() -> None:
    fixture = m02.generate_fixture()
    result = m02.score_retrieval(fixture, _perfect_traces(fixture))
    assert result["metrics"]["unanswerable_correct_rate"] == 1.0

    invalid = deepcopy(fixture)
    _, question = _case(invalid, "exact")
    question["gold_doc_ids"] = []
    _resign(invalid)
    with pytest.raises(m02.WmbsM02Error, match="gold_doc_ids"):
        m02.score_retrieval(invalid, _perfect_traces(invalid))

    traces = _perfect_traces(fixture)
    index, _ = _case(fixture, "exact")
    traces[index]["ranked_hits"] = []
    with pytest.raises(m02.WmbsM02Error, match="non-empty ranked_hits"):
        m02.score_retrieval(fixture, traces)


def test_unanswerable_hallucination_is_incorrect_and_unsupported() -> None:
    fixture = m02.load_fixture()
    traces = _perfect_traces(fixture)
    index, _ = _case(fixture, "unanswerable")
    traces[index]["answer"] = "hallucinated answer"
    traces[index]["abstained"] = False
    metrics = m02.score_retrieval(fixture, traces)["metrics"]
    assert metrics["unanswerable_correct_rate"] == 0.9
    assert metrics["unsupported_claim_rate"] == pytest.approx(1 / 51)


def test_abstained_trace_rejects_fabricated_answer() -> None:
    fixture = m02.load_fixture()
    traces = _perfect_traces(fixture)
    index, _ = _case(fixture, "unanswerable")
    traces[index]["ranked_hits"] = [
        {"rank": 1, "stable_item_id": fixture["corpus"][0]["stable_item_id"]}
    ]
    traces[index]["answer"] = "fabricated answer"
    with pytest.raises(m02.WmbsM02Error, match="abstained trace answer must be null"):
        m02.score_retrieval(fixture, traces)


@pytest.mark.parametrize("abstained", [1, "false", None])
def test_scorer_rejects_non_boolean_abstained(abstained: object) -> None:
    fixture = m02.generate_fixture()
    traces = _perfect_traces(fixture)
    index, _ = _case(fixture, "unanswerable")
    traces[index]["abstained"] = abstained
    with pytest.raises(m02.WmbsM02Error, match="abstained must be a bool"):
        m02.score_retrieval(fixture, traces)


@pytest.mark.parametrize("answer", [1, False, ["Portland"]])
def test_scorer_rejects_non_string_answer(answer: object) -> None:
    fixture = m02.generate_fixture()
    traces = _perfect_traces(fixture)
    index, _ = _case(fixture, "exact")
    traces[index]["answer"] = answer
    with pytest.raises(m02.WmbsM02Error, match="answer must be a string or null"):
        m02.score_retrieval(fixture, traces)


def test_scorer_rejects_unknown_trace_keys() -> None:
    fixture = m02.generate_fixture()
    traces = _perfect_traces(fixture)
    traces[0]["abstainned"] = False
    with pytest.raises(m02.WmbsM02Error, match="closed fields"):
        m02.score_retrieval(fixture, traces)


@pytest.mark.parametrize(
    "hits",
    [
        [{"rank": 2, "stable_item_id": "m02-doc-020"}],
        [
            {"rank": 1, "stable_item_id": "m02-doc-020"},
            {"rank": 1, "stable_item_id": "m02-doc-021"},
        ],
    ],
)
def test_scorer_rejects_noncontiguous_or_duplicate_ranks(hits: list[dict]) -> None:
    fixture = m02.generate_fixture()
    traces = _perfect_traces(fixture)
    index, _ = _case(fixture, "exact")
    traces[index]["ranked_hits"] = hits
    with pytest.raises(m02.WmbsM02Error, match="contiguous"):
        m02.score_retrieval(fixture, traces)


def test_trace_identity_agrees_across_bundle_and_scoring_bindings() -> None:
    fixture = m02.generate_fixture()
    for field in ("case_id", "question_id"):
        traces = _perfect_traces(fixture)
        traces[0][field] = "wrong"
        with pytest.raises(m02.WmbsM02Error, match="case_id == question_id"):
            m02.score_retrieval(fixture, traces)


def test_metrics_shape_is_descriptive_and_finite_corpus_only() -> None:
    fixture = m02.generate_fixture()
    result = m02.score_retrieval(fixture, _perfect_traces(fixture))
    assert result["finite_corpus_only"] is True
    assert result["interval"] == {"method": "descriptive"}
    assert set(result["intervals"]) == set(result["metrics"])
    assert all(
        value == {"method": "descriptive"} for value in result["intervals"].values()
    )
    forbidden = {"low", "high", "confidence", "iterations", "seed"}
    assert not forbidden.intersection(result["interval"])
    assert all(
        not forbidden.intersection(value) for value in result["intervals"].values()
    )
    assert result["metrics"]["recall_at_1"] == 0.8
    assert result["metrics"]["ndcg_at_5"] == 1.0
    assert result["metrics"]["exact_match"] == 1.0
    assert result["metrics"]["token_f1"] == 1.0


def test_unsupported_claim_rate_uses_retrieved_gold_not_answer_correctness() -> None:
    fixture = m02.generate_fixture()
    traces = _perfect_traces(fixture)
    index, _ = _case(fixture, "exact")
    traces[index]["answer"] = "the wrong city"
    metrics = m02.score_retrieval(fixture, traces)["metrics"]
    assert metrics["unsupported_claim_rate"] == 0.0
    assert metrics["exact_match"] == 0.98


def test_article_only_non_abstained_answer_counts_as_unsupported_claim() -> None:
    fixture = m02.generate_fixture()
    traces = _perfect_traces(fixture)
    index, question = _case(fixture, "exact")
    wrong_doc_id = next(
        document["stable_item_id"]
        for document in fixture["corpus"]
        if document["stable_item_id"] not in question["gold_doc_ids"]
    )
    traces[index]["answer"] = "the"
    traces[index]["ranked_hits"] = [{"rank": 1, "stable_item_id": wrong_doc_id}]
    assert (
        m02.score_retrieval(fixture, traces)["metrics"]["unsupported_claim_rate"]
        == 0.02
    )


@pytest.mark.parametrize(
    ("gold", "prediction"),
    [("The Portland", "portland!!!"), ("Ａ Café", "café")],
)
def test_em_and_f1_match_frozen_answer_normalization(
    gold: str, prediction: str
) -> None:
    assert m02._normalized_answer(gold) == canonical_normalize_answer(gold)
    assert m02._normalized_answer(prediction) == canonical_normalize_answer(prediction)
    assert canonical_normalize_answer(gold) == canonical_normalize_answer(prediction)
    fixture = m02.generate_fixture()
    index, question = _case(fixture, "exact")
    question["answers"] = [gold]
    _resign(fixture)
    traces = _perfect_traces(fixture)
    traces[index]["answer"] = prediction
    metrics = m02.score_retrieval(fixture, traces)["metrics"]
    assert metrics["exact_match"] == 1.0
    assert metrics["token_f1"] == 1.0


def test_evidence_recall_requires_complete_answerable_disclosure() -> None:
    fixture = m02.generate_fixture()
    partial = _perfect_traces(fixture)
    index, question = _case(fixture, "exact")
    partial[index]["evidence_ids"] = list(question["gold_doc_ids"])
    assert (
        m02.score_retrieval(fixture, partial)["metrics"]["evidence_recall"]
        == "unsupported"
    )

    no_ids = _perfect_traces(fixture)
    for trace in no_ids:
        if trace["ranked_hits"]:
            trace["evidence_ids"] = []
    assert (
        m02.score_retrieval(fixture, no_ids)["metrics"]["evidence_recall"]
        == "unsupported"
    )

    complete = _perfect_traces(fixture, evidence=True)
    assert m02.score_retrieval(fixture, complete)["metrics"]["evidence_recall"] == 1.0


def test_unmeasured_metrics_are_unsupported_not_estimated() -> None:
    fixture = m02.generate_fixture()
    metrics = m02.score_retrieval(fixture, _perfect_traces(fixture))["metrics"]
    assert {
        name: metrics[name] for name in ("latency", "tokens", "calls", "storage")
    } == {
        "latency": "unsupported",
        "tokens": "unsupported",
        "calls": "unsupported",
        "storage": "unsupported",
    }
    assert metrics["evidence_recall"] == "unsupported"


def test_no_baseline_or_improvement_claim_is_produced() -> None:
    fixture = m02.generate_fixture()
    result = m02.score_retrieval(fixture, _perfect_traces(fixture))
    forbidden = {
        "baseline",
        "comparison",
        "paired_interval",
        "improvement",
        "non_inferiority",
    }
    assert not forbidden.intersection(result)
    assert not forbidden.intersection(result["metrics"])


def test_fixture_validation_rejects_mutation_and_normalizes_questions() -> None:
    fixture = m02.generate_fixture()
    mutated = deepcopy(fixture)
    mutated["corpus"][0]["content"] += " mutated"
    with pytest.raises(m02.WmbsM02Error, match="digest mismatch"):
        m02.validate_fixture(mutated)

    normalized = m02.normalize_fixture(fixture)
    assert set(normalized) == {q["question_id"] for q in fixture["questions"]}
    assert normalized["m02-exact-00"]["family"] == "exact"


def test_whole_memory_abi_artifacts_are_present() -> None:
    assert (REPO_ROOT / "eval/public/schema/wmbs-0.1-draft.schema.json").is_file()
    assert (REPO_ROOT / "eval/public/adapters/whole_memory_reference.py").is_file()


def test_module_imports_only_stdlib() -> None:
    tree = ast.parse(Path(m02.__file__).read_text(encoding="utf-8"))
    roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert roots <= {
        "__future__",
        "collections",
        "hashlib",
        "json",
        "math",
        "random",
        "string",
        "pathlib",
        "typing",
        "unicodedata",
    }
