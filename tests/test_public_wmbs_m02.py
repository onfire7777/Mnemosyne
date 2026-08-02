from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from eval.public import wmbs_m02 as m02


REPO_ROOT = Path(__file__).resolve().parents[1]


def _question(*, family: str = "exact", gold: list[str] | None = None) -> dict:
    return {
        "question_id": "q-001",
        "family": family,
        "text": "Where is the package?",
        "gold_doc_ids": ["doc-a"] if gold is None else gold,
        "answers": ["Portland"] if family != "unanswerable" else [],
    }


def _trace(*, hits: list[dict] | None = None, answer: str | None = "Portland") -> dict:
    return {
        "case_id": "q-001",
        "question_id": "q-001",
        "ranked_hits": (
            [{"rank": 1, "stable_item_id": "doc-a"}] if hits is None else hits
        ),
        "answer": answer,
        "abstained": answer is None,
    }


def _single_fixture(question: dict | None = None) -> dict:
    return {"questions": [_question() if question is None else question]}


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


def test_scorer_rejects_duplicate_ranked_ids() -> None:
    trace = _trace(
        hits=[
            {"rank": 1, "stable_item_id": "doc-a"},
            {"rank": 2, "stable_item_id": "doc-a"},
        ]
    )
    with pytest.raises(m02.WmbsM02Error, match="duplicate ranked stable_item_id"):
        m02.score_retrieval(_single_fixture(), [trace])


def test_scorer_scores_unanswerable_with_empty_gold_and_empty_hits() -> None:
    result = m02.score_retrieval(
        _single_fixture(_question(family="unanswerable", gold=[])),
        [_trace(hits=[], answer=None)],
    )
    assert result["metrics"]["unanswerable_correct_rate"] == 1.0

    for family in m02.QUERY_FAMILIES - {"unanswerable"}:
        with pytest.raises(m02.WmbsM02Error, match="gold_doc_ids"):
            m02.score_retrieval(
                _single_fixture(_question(family=family, gold=[])), [_trace()]
            )
        with pytest.raises(m02.WmbsM02Error, match="non-empty ranked_hits"):
            m02.score_retrieval(
                _single_fixture(_question(family=family)), [_trace(hits=[])]
            )


@pytest.mark.parametrize("abstained", [1, "false", None])
def test_scorer_rejects_non_boolean_abstained(abstained: object) -> None:
    trace = _trace(hits=[], answer=None)
    trace["abstained"] = abstained
    with pytest.raises(m02.WmbsM02Error, match="abstained must be a bool"):
        m02.score_retrieval(
            _single_fixture(_question(family="unanswerable", gold=[])), [trace]
        )


@pytest.mark.parametrize(
    "hits",
    [
        [{"rank": 2, "stable_item_id": "doc-a"}],
        [
            {"rank": 1, "stable_item_id": "doc-a"},
            {"rank": 1, "stable_item_id": "doc-b"},
        ],
    ],
)
def test_scorer_rejects_noncontiguous_or_duplicate_ranks(hits: list[dict]) -> None:
    with pytest.raises(m02.WmbsM02Error, match="contiguous"):
        m02.score_retrieval(_single_fixture(), [_trace(hits=hits)])


def test_trace_identity_agrees_across_bundle_and_scoring_bindings() -> None:
    for field in ("case_id", "question_id"):
        trace = _trace()
        trace[field] = "wrong"
        with pytest.raises(m02.WmbsM02Error, match="case_id == question_id"):
            m02.score_retrieval(_single_fixture(), [trace])


def test_metrics_shape_is_descriptive_and_finite_corpus_only() -> None:
    result = m02.score_retrieval(_single_fixture(), [_trace()])
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
    assert result["metrics"]["recall_at_1"] == 1.0
    assert result["metrics"]["ndcg_at_5"] == 1.0
    assert result["metrics"]["exact_match"] == 1.0
    assert result["metrics"]["token_f1"] == 1.0


def test_unsupported_claim_rate_uses_retrieved_gold_not_answer_correctness() -> None:
    metrics = m02.score_retrieval(_single_fixture(), [_trace(answer="the wrong city")])[
        "metrics"
    ]
    assert metrics["unsupported_claim_rate"] == 0.0
    assert metrics["exact_match"] == 0.0


@pytest.mark.parametrize(
    ("gold", "prediction"),
    [("The Portland", "portland!!!"), ("Ａ Café", "café")],
)
def test_em_and_f1_match_frozen_answer_normalization(
    gold: str, prediction: str
) -> None:
    question = _question()
    question["answers"] = [gold]
    metrics = m02.score_retrieval(
        _single_fixture(question), [_trace(answer=prediction)]
    )["metrics"]
    assert metrics["exact_match"] == 1.0
    assert metrics["token_f1"] == 1.0


def test_unmeasured_metrics_are_unsupported_not_estimated() -> None:
    metrics = m02.score_retrieval(_single_fixture(), [_trace()])["metrics"]
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
    result = m02.score_retrieval(_single_fixture(), [_trace()])
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
    mutated["questions"][0]["gold_doc_ids"] = []
    with pytest.raises(m02.WmbsM02Error):
        m02.validate_fixture(mutated)

    normalized = m02.normalize_fixture(fixture)
    assert set(normalized) == {q["question_id"] for q in fixture["questions"]}
    assert normalized["m02-exact-00"]["family"] == "exact"


def test_whole_memory_abi_artifacts_are_present() -> None:
    assert (REPO_ROOT / "eval/public/schema/wmbs-0.1-draft.schema.json").is_file()
    assert (REPO_ROOT / "eval/public/adapters/whole_memory_reference.py").is_file()


def test_module_imports_only_stdlib_and_eval_public() -> None:
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
        "re",
        "pathlib",
        "typing",
        "eval",
    }
