"""Synthetic ingestion tests; no held-out LoCoMo examples or scores."""
from copy import deepcopy
import json

import pytest

from eval.public.adapters.locomo import LoCoMoError, normalize_dialogs, split_samples


def sample(sample_id="synthetic"):
    return {"sample_id": sample_id,
            "conversation": {"speaker_a": "A", "speaker_b": "B", "session_1_date_time": "test date",
                             "session_1": [{"speaker": "A", "dia_id": "D1:1", "text": "Input conversation."}]},
            "observation": "GENERATED_NOT_INPUT", "session_summary": "SUMMARY_NOT_INPUT",
            "qa": [{"question": "Synthetic question?", "category": c, "answer": "SCORER_SECRET",
                    "evidence": ["(D1:1)"] if c != 5 else [], "extra_annotation": "KEEP_LABEL"}
                   for c in range(1, 6)]}


def test_dialog_normalization_preserves_order_dates_and_label_boundary():
    source = sample()
    conversation = source["conversation"]
    conversation["session_10"] = [{"dia_id": "D10:1", "speaker": "B", "text": "Later."}]
    conversation["session_10_date_time"] = "another source date"
    conversation["session_2"] = [{"dia_id": "D2:1", "speaker": "A", "text": "Middle."}]
    conversation["session_2_date_time"] = "middle source date"
    dialog = conversation["session_1"][0]
    dialog.update(blip_caption="Synthetic caption", img_url="https://invalid.example/image",
                  answer="DIALOG_LABEL_SECRET", evidence="EVIDENCE_SECRET")
    before = deepcopy(source)
    included = normalize_dialogs([source], caption_policy="include-source-caption")
    assert [r["session_id"] for r in included["records"]] == ["session_1", "session_2", "session_10"]
    assert [r["source_timestamp"] for r in included["records"]] == [
        "test date", "middle source date", "another source date"]
    assert included["records"][0]["caption"] == "Synthetic caption"
    serialized = json.dumps(included)
    for hidden in ("SCORER_SECRET", "DIALOG_LABEL_SECRET", "EVIDENCE_SECRET", "invalid.example",
                   "GENERATED_NOT_INPUT", "SUMMARY_NOT_INPUT"):
        assert hidden not in serialized
    excluded = normalize_dialogs([source], caption_policy="exclude-caption")
    assert all(row["caption"] is None for row in excluded["records"])
    assert [r["record_id"] for r in included["records"]] == [r["record_id"] for r in excluded["records"]]
    assert included == normalize_dialogs([source], caption_policy="include-source-caption")
    assert source == before


def test_dialog_ids_are_conversation_scoped_and_turn_order_is_preserved():
    first, second = sample("first"), sample("second")
    first["conversation"]["session_1"].append({"dia_id": "D1:2", "speaker": "B", "text": "Reply."})
    rows = normalize_dialogs([first, second], caption_policy="exclude-caption")["records"]
    assert [r["position"] for r in rows] == [0, 1, 0]
    assert len({r["record_id"] for r in rows}) == 3
    first["conversation"]["session_1"].append(deepcopy(first["conversation"]["session_1"][0]))
    with pytest.raises(LoCoMoError, match="duplicate dialog"):
        normalize_dialogs([first], caption_policy="exclude-caption")


@pytest.mark.parametrize("key,value", [
    ("session_1", []), ("session_1", [None]), ("session_1_date_time", None),
    ("session_1_date_time", ""), ("session_01", []), ("session_2_date_time", "orphan"), (1, "bad key"),
])
def test_dialog_normalization_rejects_ambiguous_sessions(key, value):
    source = sample()
    source["conversation"][key] = value
    with pytest.raises(LoCoMoError):
        normalize_dialogs([source], caption_policy="exclude-caption")


@pytest.mark.parametrize("key,value", [("dia_id", ""), ("speaker", None), ("text", " "), ("blip_caption", [])])
def test_dialog_normalization_rejects_bad_turns(key, value):
    source = sample()
    source["conversation"]["session_1"][0][key] = value
    with pytest.raises(LoCoMoError):
        normalize_dialogs([source], caption_policy="exclude-caption")


def test_dialog_normalization_requires_explicit_caption_policy():
    with pytest.raises(LoCoMoError, match="caption_policy"):
        normalize_dialogs([sample()], caption_policy="automatic")


@pytest.mark.parametrize("category", range(1, 6))
def test_single_question_prompt_preserves_upstream_whitespace_and_custody(category):
    from hashlib import sha256
    from eval.public.adapters.locomo import prepare_single_question_prompt
    annotation = sample()["qa"][category - 1]
    before = deepcopy(annotation)
    draw = 0.75 if category == 5 else None
    record = prepare_single_question_prompt("Synthetic context Ω.\n", annotation, choice_draw=draw)
    prompt = record["prompt"]
    assert prompt.startswith("Synthetic context Ω.\n\n\n\nBased on the above context,")
    assert prompt.endswith(" Short answer:\n")
    assert ("SCORER_SECRET" in prompt) == (category == 5)
    assert "KEEP_LABEL" not in prompt and "D1:1" not in prompt
    assert ("Use DATE" in prompt) == (category == 2)
    assert ("exact words" in prompt) == (category != 5)
    assert record["prompt_sha256"] == sha256(prompt.encode()).hexdigest()
    assert record["context_sha256"] == sha256("Synthetic context Ω.\n".encode()).hexdigest()
    assert record["generation"] == {"num_gen": 1, "num_tokens_request": 32, "temperature": 0}
    assert not record["context_conformance_verified"]
    assert record == prepare_single_question_prompt("Synthetic context Ω.\n", annotation, choice_draw=draw)
    assert annotation == before


def test_single_question_prompt_rejects_non_text_context():
    from eval.public.adapters.locomo import prepare_single_question_prompt
    with pytest.raises(LoCoMoError, match="context"):
        prepare_single_question_prompt(None, sample()["qa"][0])


def test_nonrag_context_retains_upstream_reverse_session_assembly_and_caption():
    from eval.public.adapters.locomo import prepare_nonrag_context
    source = sample()
    source["conversation"]["session_1"][0]["blip_caption"] = "A scene"
    source["conversation"]["session_3"] = [{"dia_id": "D3:1", "speaker": "B", "text": "Later."}]
    source["conversation"]["session_3_date_time"] = "later date"
    output = prepare_nonrag_context(source, token_count=len, max_length=10000,
                                    num_question_tokens=10, batch_size=1)
    assert output["context"] == ('DATE: later date\nCONVERSATION:\nB said, "Later."\n\n'
                                 'DATE: test date\nCONVERSATION:\nA said, "Input conversation."\n'
                                 ' and shared A scene.\n\n\n\n\n')
    assert not output["truncated"]
    records = normalize_dialogs([source], caption_policy="include-source-caption")["records"]
    assert output["included_record_ids"] == [row["record_id"] for row in reversed(records)]


def test_nonrag_context_strict_boundary_keeps_header_even_when_no_turn_fits():
    from eval.public.adapters.locomo import prepare_nonrag_context
    source = sample()
    header = "DATE: test date\nCONVERSATION:\n"
    turn = 'A said, "Input conversation."\n\n'
    threshold = len(header + turn) + 2 + 10 + 50
    exact = prepare_nonrag_context(source, token_count=len, max_length=threshold,
                                   num_question_tokens=10, batch_size=1)
    assert exact["truncated"] and exact["included_record_ids"] == []
    assert exact["context"] == header + "\n\n"
    extra = prepare_nonrag_context(source, token_count=len, max_length=threshold + 1,
                                   num_question_tokens=10, batch_size=1)
    assert not extra["truncated"] and len(extra["included_record_ids"]) == 1


@pytest.mark.parametrize("value", [-1, True, 0.5, None])
def test_nonrag_context_rejects_invalid_token_counter(value):
    from eval.public.adapters.locomo import prepare_nonrag_context
    with pytest.raises(LoCoMoError, match="token_count"):
        prepare_nonrag_context(sample(), token_count=lambda _: value, max_length=1000,
                               num_question_tokens=10, batch_size=1)


def test_nonrag_request_composes_source_question_and_preserves_speaker_order():
    from eval.public.adapters.locomo import prepare_nonrag_request
    source = sample()
    source["conversation"]["session_1"].append({"dia_id": "D1:2", "speaker": "B", "text": "Reply."})
    result = prepare_nonrag_request(source, 4, speaker_order=["B", "A"], token_count=len,
                                    max_length=10000, choice_draw=0.1)
    assert result["prompt"].startswith("Below is a conversation between two people: B and A.")
    assert result["speaker_order"] == ["B", "A"]
    assert result["question_id"] == split_samples([source])["questions"][4]["question_id"]
    assert "SCORER_SECRET" not in result["context_assembly"]["context"]
    assert "SCORER_SECRET" in result["prompt"]
    assert not result["publication_authorized"]
    assert not result["context_assembly"]["truncated"]


@pytest.mark.parametrize("speakers", [["A", "A"], ["B", "C"], ["A"], None])
def test_nonrag_request_rejects_implicit_or_invalid_speaker_order(speakers):
    from eval.public.adapters.locomo import prepare_nonrag_request
    with pytest.raises(LoCoMoError, match="speaker_order"):
        prepare_nonrag_request(sample(), 0, speaker_order=speakers, token_count=len, max_length=1000)


@pytest.mark.parametrize("index", [-1, 5, True, 0.5])
def test_nonrag_request_rejects_invalid_question_selection(index):
    from eval.public.adapters.locomo import prepare_nonrag_request
    with pytest.raises(LoCoMoError, match="question_index"):
        prepare_nonrag_request(sample(), index, speaker_order=["A", "B"], token_count=len, max_length=1000)


def test_separates_inputs_without_rewriting_or_dropping_source_annotations():
    source = [sample()]
    before = deepcopy(source)
    result = split_samples(source)
    inputs = json.dumps([result["conversations"], result["questions"]])
    assert all(token not in inputs for token in ["SCORER_SECRET", "GENERATED_NOT_INPUT", "SUMMARY_NOT_INPUT", "KEEP_LABEL"])
    assert result["conversations"][0]["conversation"] == source[0]["conversation"]
    assert [row["annotation"] for row in result["annotations"]] == source[0]["qa"]
    assert source == before
    assert result == split_samples(source)
    assert len({q["question_id"] for q in result["questions"]}) == 5
    assert [q["question_id"] for q in result["questions"]] == [a["question_id"] for a in result["annotations"]]
    result["annotations"][0]["annotation"]["answer"] = "changed"
    result["conversations"][0]["conversation"]["speaker_a"] = "changed"
    assert source == before


def test_sample_identity_is_collision_safe_and_order_independent():
    a, b = sample("a:0"), sample("a")
    result, reversed_result = split_samples([a, b]), split_samples([b, a])
    def key(q):
        return q["question_id"]
    assert sorted(result["questions"], key=key) == sorted(reversed_result["questions"], key=key)
    assert len({q["question_id"] for q in result["questions"]}) == 10


@pytest.mark.parametrize("category", [True, 0, 6, 1.0, "1", None])
def test_rejects_invalid_category(category):
    source = sample()
    source["qa"][0]["category"] = category
    with pytest.raises(LoCoMoError, match="category"):
        split_samples([source])


@pytest.mark.parametrize("source", [None, [], {}, [None], [sample(), sample()]])
def test_rejects_ambiguous_or_missing_samples(source):
    with pytest.raises(LoCoMoError):
        split_samples(source)


@pytest.mark.parametrize("field,value", [("question", ""), ("evidence", None), ("evidence", [1]), ("answer", float("nan"))])
def test_rejects_malformed_annotations(field, value):
    source = sample()
    source["qa"][0][field] = value
    with pytest.raises(LoCoMoError):
        split_samples([source])


def test_question_transformation_is_replayable_and_does_not_use_global_randomness(monkeypatch):
    from eval.public.adapters.locomo import prepare_upstream_question
    import random

    def forbidden():
        raise AssertionError("hidden randomness")
    monkeypatch.setattr(random, "random", forbidden)
    annotation = sample()["qa"][4]
    for draw in (0, 0.499999, 0.5, 0.999999):
        prepared = prepare_upstream_question(annotation, choice_draw=draw)
        assert prepared == prepare_upstream_question(annotation, choice_draw=draw)
        abstain = "a" if draw < 0.5 else "b"
        assert prepared["answer_key"][abstain] == "Not mentioned in the conversation"
        assert prepared["choice_draw"] == draw
        assert prepared["query"].endswith(f"(a) {prepared['answer_key']['a']} (b) {prepared['answer_key']['b']}. ")


@pytest.mark.parametrize("draw", [None, True, -0.1, 1, float("nan"), float("inf"), "0.2"])
def test_adversarial_choice_requires_valid_recorded_draw(draw):
    from eval.public.adapters.locomo import prepare_upstream_question
    with pytest.raises(LoCoMoError):
        prepare_upstream_question(sample()["qa"][4], choice_draw=draw)


def test_non_adversarial_transformation_does_not_expose_answer():
    from eval.public.adapters.locomo import prepare_upstream_question
    for annotation in sample()["qa"][:4]:
        result = prepare_upstream_question(annotation)
        assert "SCORER_SECRET" not in json.dumps(result)
        assert result["answer_key"] is None
        assert ("Use DATE" in result["query"]) == (annotation["category"] == 2)
        with pytest.raises(LoCoMoError):
            prepare_upstream_question(annotation, choice_draw=0.1)


@pytest.mark.parametrize("raw,expected", [(" A ", "first"), ("(A)", "first"), ("b", "second"),
                                         ("x", "second"), ("yes", "second"), ("(b)", "second"),
                                         ("", ""), (" No Information Available ", "no information available")])
def test_upstream_decoder_retains_raw_and_short_output_semantics(raw, expected):
    from eval.public.adapters.locomo import decode_upstream_category5
    result = decode_upstream_category5(raw, {"a": "first", "b": "second"})
    assert result["raw_prediction"] == raw
    assert result["decoded_prediction"] == expected
