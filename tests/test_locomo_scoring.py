"""Run explicitly in the isolated pinned LoCoMo scorer environment."""
from importlib.metadata import PackageNotFoundError, version

import pytest

from eval.public.adapters.locomo import LoCoMoError
from eval.public.adapters.locomo_scoring import DEPENDENCIES, score_case

try:
    available = all(version(name) == expected for name, expected in DEPENDENCIES.items())
except PackageNotFoundError:
    available = False
pytestmark = pytest.mark.skipif(not available, reason="requires isolated pinned LoCoMo scorer environment")


def annotation(category=4, answer="cats running", evidence=None):
    return {"category": category, "answer": answer, "evidence": ["D1:1"] if evidence is None else evidence}


@pytest.mark.parametrize("category,answer,prediction,expected", [
    (4, "cats running", "the cat runs", 1), (4, "red blue", "red green", .5),
    (1, "red,blue", "red", .5), (3, "red; blue", "red", 1),
    (5, "distractor", "Not mentioned in the conversation", 1),
    (5, "distractor", "unknown", 0), (4, "", "", 0),
    (2, 2024, "2024", 1),
])
def test_category_scoring(category, answer, prediction, expected):
    result = score_case(annotation(category, answer), prediction)
    assert result["score"] == expected
    assert result["reported_score"] == round(expected, 3)
    assert result["upstream_recall"] == 1
    assert result["measured_recall"] is None
    assert not result["recall_applicable"]


@pytest.mark.parametrize("context,expected", [(["D1:1"], 1), (["D2:1"], 0), (["S1"], 1), (["S2"], 0)])
def test_recall_requires_observed_context(context, expected):
    result = score_case(annotation(), "cat", retrieved_context=context)
    assert result["measured_recall"] == expected
    assert result["recall_applicable"]


def test_empty_evidence_stays_unmeasured_even_when_upstream_returns_one():
    result = score_case(annotation(evidence=[]), "cat", retrieved_context=[])
    assert result["upstream_recall"] == 1
    assert result["measured_recall"] is None


def test_empty_context_with_evidence_is_rejected():
    with pytest.raises(LoCoMoError, match="undefined"):
        score_case(annotation(), "cat", retrieved_context=[])


@pytest.mark.parametrize("category", [True, "1", 0, 6])
def test_invalid_category_is_rejected(category):
    with pytest.raises(LoCoMoError):
        score_case(annotation(category), "cat")


def replay_source():
    return [{"sample_id": "synthetic", "conversation": {"session_1": []},
             "qa": [dict(annotation(category, "red blue"), question="Synthetic?")
                    for category in range(1, 6)]}]


def replay_predictions(source):
    from eval.public.adapters.locomo import split_samples
    return [{"question_id": row["question_id"], "decoded_prediction": "red",
             "retrieved_context": ["D1:1"]} for row in split_samples(source)["questions"]]


def test_replay_preserves_all_categories_and_missing_predictions():
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    predictions = replay_predictions(source)
    result = score_prediction_set(source, predictions[:-1])
    assert not result["complete"]
    assert len(result["cases"]) == 5
    assert result["cases"][-1]["status"] == "missing-prediction"
    assert result["cases"][-1]["score"] is None
    assert result["categories"]["5"]["source_count"] == 1
    assert result["categories"]["5"]["missing_count"] == 1
    assert result["categories"]["5"]["upstream_denominator_mean"] == 0
    assert result["categories"]["4"]["upstream_denominator_mean"] == .667
    assert "overall" not in result
    assert not result["publication_authorized"]


def test_replay_order_does_not_change_results_and_rounds_before_sum():
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    outputs = replay_predictions(source)
    result = score_prediction_set(source, outputs)
    assert result == score_prediction_set(source, outputs[::-1])
    assert result["complete"]
    assert result["categories"]["4"]["rounded_score_sum"] == .667


def test_fallback_recall_is_counted_separately_from_observed_retrieval():
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    outputs = replay_predictions(source)
    del outputs[0]["retrieved_context"]
    result = score_prediction_set(source, outputs)
    assert result["categories"]["1"]["fallback_recall_count"] == 1
    assert result["categories"]["1"]["observed_recall_count"] == 0
    assert result["cases"][0]["measured_recall"] is None
    assert result["categories"]["2"]["observed_recall_count"] == 1


@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "extra-field", "null-context"])
def test_replay_rejects_ambiguous_prediction_population(mutation):
    from eval.public.adapters.locomo_scoring import score_prediction_set
    source = replay_source()
    outputs = replay_predictions(source)
    if mutation == "duplicate":
        outputs.append(outputs[0].copy())
    elif mutation == "unknown":
        outputs[0]["question_id"] = "unknown"
    elif mutation == "null-context":
        outputs[0]["retrieved_context"] = None
    else:
        outputs[0]["fabricated_score"] = 1
    with pytest.raises(LoCoMoError):
        score_prediction_set(source, outputs)


def test_native_population_replays_missingness_empty_retrieval_and_tampering(tmp_path, monkeypatch):
    from copy import deepcopy
    from hashlib import sha256
    import json
    from pathlib import Path
    from eval.harness.cli_driver import MnemoCLI
    from eval.public.adapters.locomo import normalize_dialogs, split_samples
    from eval.public.adapters.locomo_native import _capture_plan, answer_captured_question
    from eval.public.adapters.locomo_scoring import replay_native_population

    sample = {"sample_id": "synthetic", "conversation": {
        "session_1_date_time": "Synthetic date", "session_1": [
            {"speaker": "A", "text": "violet kite", "dia_id": "D1:1"},
            {"speaker": "B", "text": "violet balloon", "dia_id": "D1:2"}]},
        "qa": [{"question": "Synthetic question?", "answer": "violet", "category": category,
                "evidence": ["D1:2"] if category != 5 else []} for category in range(1, 6)]}
    source = [sample]
    questions = split_samples(source)["questions"]
    tenant = "locomo:" + sha256(b"synthetic").hexdigest()
    _, evidence = _capture_plan(normalize_dialogs(source, caption_policy="exclude-caption")["records"], tenant)
    store = tmp_path / "synthetic-store"
    store.write_text("synthetic transport; no engine or model execution")
    conversation = {"sample_id": "synthetic", "tenant_id": tenant,
                    "cli": MnemoCLI(store=str(store)), "evidence": evidence}

    def answer(cli, path, *, include_derivation=False):
        request = json.loads(Path(path).read_text())
        cid = next(iter(evidence))
        start = evidence[cid]["capture"]["content"].index("violet")
        claim = {"text": "violet", "evidence_cids": [cid],
                 "derivation": {"schema_version": "mnemosyne.claim-derivation/v1", "kind": "quotation", "operation": None}, "spans": [{"cid": cid,
                 "start": start, "end": start + 6, "slice_sha256": sha256(b"violet").hexdigest()}]}
        return {"results": [{"question_id": request["question_id"], "answer": "violet",
                             "abstained": False, "claims": [claim], "hops": [{"retrieved_cids": [cid]}],
                             "reader": {"grounded_reader": {"provider": "synthetic"}}}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
    record = answer_captured_question(conversation, questions[0], sample["qa"][0])
    draws = {questions[4]["question_id"]: 0.2}
    report = replay_native_population(source, [record], caption_policy="exclude-caption", choice_draws=draws)
    assert report["categories"]["1"]["qa_source_denominator_mean"] == 1
    assert report["categories"]["1"]["native_observed_recall_mean"] == 0
    assert report["categories"]["2"]["missing_count"] == 1
    assert not report["complete"] and not report["publication_authorized"]
    assert len(report["cases"]) == 5
    corrupted = deepcopy(record)
    corrupted["decoded_prediction"] = "changed"
    for records in [[corrupted], [record, record]]:
        with pytest.raises(LoCoMoError):
            replay_native_population(source, records, caption_policy="exclude-caption", choice_draws=draws)
    with pytest.raises(LoCoMoError, match="choice draws"):
        replay_native_population(source, [record], caption_policy="exclude-caption", choice_draws={})
    complete_records = [answer_captured_question(conversation, question, annotation,
                        choice_draw=draws.get(question["question_id"]))
                        for question, annotation in zip(questions, sample["qa"], strict=True)]
    complete = replay_native_population(source, complete_records, caption_policy="exclude-caption", choice_draws=draws)
    assert complete["complete"]
    import sys
    from eval.public.adapters.locomo_replay import replay_in_environment
    assert complete == replay_in_environment(source, complete_records, caption_policy="exclude-caption",
                                             choice_draws=draws, python=sys.executable)
    assert complete == replay_native_population(source, list(reversed(complete_records)),
                                                caption_policy="exclude-caption", choice_draws=draws)
    assert complete["categories"]["5"]["native_observed_recall_mean"] is None

    def incomplete(cli, path, *, include_derivation=False):
        request = json.loads(Path(path).read_text())
        return {"results": [{"question_id": request["question_id"], "answer": None,
                             "abstained": True, "claims": [], "hops": [], "reader": {}}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", incomplete)
    failed = answer_captured_question(conversation, questions[4], sample["qa"][4], choice_draw=0.2)
    failed_report = replay_native_population(source, [*complete_records[:4], failed],
                                             caption_policy="exclude-caption", choice_draws=draws)
    assert not failed_report["complete"]
    assert failed_report["categories"]["5"]["missing_count"] == 1
    assert failed_report["categories"]["5"]["scored_count"] == 0
    assert failed_report["cases"][4]["status"] == "incomplete-reader-execution"
    narrowed = deepcopy(sample)
    narrowed["qa"] = narrowed["qa"][:1]
    narrowed_report = replay_native_population([narrowed], [record],
                                               caption_policy="exclude-caption", choice_draws={})
    assert narrowed_report["source_population_complete"]
    assert not narrowed_report["complete"]
    assert narrowed_report["absent_categories"] == ["2", "3", "4", "5"]
    assert narrowed_report["categories"]["1"]["complete"]
    assert not narrowed_report["categories"]["2"]["complete"]
