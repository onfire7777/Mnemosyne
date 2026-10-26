"""Book answers retain admitted context and fail closed on ungrounded response metadata."""

import copy
import json

import pytest

from mnemosyne import frameworks


@pytest.mark.parametrize("large_field", ["source", "document"])
def test_direct_answer_receives_tail_of_entire_admitted_input(monkeypatch, large_field):
    long_text = "context " * 6000 + "FINAL CHAPTER: Preserve the final condition."
    document = long_text if large_field == "document" else "A short framework."
    units = [long_text if large_field == "source" else "A short source."]
    prompts = []

    def capture(system, user, *args):
        prompts.append(user)
        return {"answer": "Preserve the final condition.", "units": [1], "answered": True}

    monkeypatch.setattr(frameworks, "chat_json", capture)
    result = frameworks.ask({"document": document}, units, "What is the final condition?")
    assert result["answered"]
    assert len(prompts) == 1
    assert document in prompts[0]
    assert units[0] in prompts[0]
    assert "FINAL CHAPTER: Preserve the final condition." in prompts[0]


def test_direct_oversized_answer_fails_before_provider_dispatch():
    with pytest.raises(ValueError, match="source was not truncated"):
        frameworks.ask({"document": "x" * frameworks.MAX_PROMPT_CHARS}, ["source"], "question")


@pytest.mark.parametrize("response", [
    None, [], "not an object", {},
    {"answer": 1, "units": [1], "answered": True},
    {"answer": {"claim": "fabricated"}, "units": [1], "answered": True},
    {"answer": "   ", "units": [1], "answered": True},
    {"answer": "Claim", "units": [1], "answered": "false"},
    {"answer": "Claim", "units": [1], "answered": 1},
    {"answer": "Claim", "units": [1], "answered": None},
    {"answer": "Claim", "units": "1", "answered": True},
    {"answer": "Claim", "units": {"unit": 1}, "answered": True},
    {"answer": "Claim", "units": None, "answered": True},
    {"answer": "Claim", "units": [], "answered": True},
    {"answer": "Claim", "units": [True], "answered": True},
    {"answer": "Claim", "units": [False], "answered": True},
    {"answer": "Claim", "units": ["1"], "answered": True},
    {"answer": "Claim", "units": [1.0], "answered": True},
    {"answer": "Claim", "units": [0], "answered": True},
    {"answer": "Claim", "units": [-1], "answered": True},
    {"answer": "Claim", "units": [999], "answered": True},
    {"answer": "Claim", "units": [1, 1], "answered": True},
    {"answer": "Claim", "units": [{"unit": 1}], "answered": True},
    {"answer": "Claim", "answered": True},
    {"units": [1], "answered": True},
])
def test_invalid_model_output_is_explicit_abstention(monkeypatch, response):
    monkeypatch.setattr(frameworks, "chat_json", lambda *a, **k: response)
    result = frameworks.ask({"document": "Framework"}, ["Source"], "Question")
    assert result["answered"] is False
    assert result["units"] == []
    assert result["diagnostic"]["code"] == "invalid_answer_response"
    assert result["diagnostic"]["issues"]
    assert "fabricated" not in result["answer"]
    json.dumps(result)  # Even malformed provider data yields a safe, stable result shape.


@pytest.mark.parametrize("response", [
    {"answer": "The source says this.", "units": [2, 1], "answered": True},
    {"answer": "These passages do not establish the answer.", "units": [], "answered": False},
    {"answer": "Unit two does not specify that detail.", "units": [2], "answered": False},
    {"answer": "", "units": [], "answered": False},
])
def test_valid_full_source_answer_or_truthful_abstention_is_preserved(monkeypatch, response):
    monkeypatch.setattr(frameworks, "chat_json", lambda *a, **k: response)
    result = frameworks.ask({"document": "Framework"}, ["One", "Two"], "Question")
    assert result == response
    assert "diagnostic" not in result


@pytest.mark.parametrize("citations", [[2], [1, 2]])
def test_valid_but_unsupplied_citation_invalidates_whole_selected_answer(monkeypatch, citations):
    prompts = []
    def fake(system, user, *args):
        prompts.append(user)
        return {"answer": "Claim from the absent second chapter.", "units": citations, "answered": True}
    monkeypatch.setattr(frameworks, "chat_json", fake)
    result = frameworks.ask({"nodes": []}, ["Alpha source", "Beta source"], "Question", [1], [])
    assert "Beta source" not in prompts[0]
    assert not result["answered"] and result["units"] == []
    assert "supplied" in " ".join(result["diagnostic"]["issues"])
    assert result["answer"] != "Claim from the absent second chapter."


@pytest.mark.parametrize("numbers", [[0], [-1], [True], [False], [1.0], ["1"], [3], "1", (1,)])
def test_invalid_requested_source_indexes_fail_before_provider(monkeypatch, numbers):
    monkeypatch.setattr(frameworks, "chat_json", lambda *a, **k: pytest.fail("must reject invalid caller selection"))
    with pytest.raises(ValueError, match="requested source units"):
        frameworks.ask({"nodes": []}, ["One", "Two"], "Question", numbers, [])


def test_complete_original_views_are_deterministic_and_preserved(monkeypatch):
    view = {"id": 7, "canonical_id": 2, "chapter": "第三章", "units": [2], "content": "Full source detail",
            "fields": {"Source Quote": {"Quote": "Second source", "Core Sentence": "Second source"},
                       "Action": "Preserve this full action."}}
    before = copy.deepcopy(view)
    reordered = dict(reversed(list(view.items())))
    assert frameworks._answer_nodes_block([view]) == frameworks._answer_nodes_block([reordered])
    prompts = []
    def fake(system, user, *args):
        assert "selected context" in system and "entire book" in system
        assert frameworks._answer_prompt_size([view], ["First source", "Second source"], [2], "Question") == (
            len(frameworks.RULEBOOK) + len(system) + len(user))
        prompts.append(user)
        return {"answer": "Second source", "units": [2], "answered": True}
    monkeypatch.setattr(frameworks, "chat_json", fake)
    result = frameworks.ask({"nodes": []}, ["First source", "Second source"], "Question", [2], node_views=[view])
    assert result["answered"]
    assert prompts == [frameworks._answer_context_prompt([view], ["First source", "Second source"], [2], "Question")]
    assert "Preserve this full action." in prompts[0] and "第三章" in prompts[0]
    assert view == before


@pytest.mark.parametrize("view", [
    {"id": 1}, {"id": 1, "units": "1"}, {"id": 1, "units": [True]}, {"id": 1, "units": [0]},
    {"id": 1, "units": [2]}, {"id": 1, "units": [1, 1]},
    {"id": 1, "units": [1], "contributions": [{"units": [2], "content": "Absent chapter"}]},
    {"id": 1, "view_id": "0:0", "units": [1], "record": {"units": [2], "content": "Absent chapter"}},
])
@pytest.mark.parametrize("use_views", [True, False])
def test_selected_records_cannot_smuggle_unsupplied_provenance(monkeypatch, view, use_views):
    monkeypatch.setattr(frameworks, "chat_json", lambda *a, **k: pytest.fail("invalid view must not reach provider"))
    kwargs = {"node_views": [view]} if use_views else {"node_ids": [1]}
    with pytest.raises(ValueError, match="node view"):
        frameworks.ask({"nodes": [view]}, ["First", "Second"], "Question", [1], **kwargs)


def test_empty_selection_does_not_authorize_an_existing_source_unit(monkeypatch):
    monkeypatch.setattr(frameworks, "chat_json", lambda *a, **k: {"answer": "Claim", "answered": True, "units": [1]})
    result = frameworks.ask({"nodes": []}, ["Source"], "Question", [], [])
    assert not result["answered"]
    assert "diagnostic" in result


def test_provider_runtime_failure_is_not_disguised_as_model_abstention(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic provider unavailable")
    monkeypatch.setattr(frameworks, "chat_json", fail)
    with pytest.raises(RuntimeError, match="synthetic provider unavailable"):
        frameworks.ask({"document": "Framework"}, ["Source"], "Question")


def test_wrapped_original_record_retains_canonical_identity_and_source(monkeypatch):
    original = {"id": 5, "units": [1], "chapter": "Original chapter", "content": "Source detail", "fields": {"Action": "Act"}}
    wrapper = {"view_id": "8:0", "canonical_id": 8, "units": [1], "record": original}
    def fake(system, user, *args):
        assert frameworks._answer_nodes_block([wrapper]) in user
        return {"answer": "Source detail", "units": [1], "answered": True}
    monkeypatch.setattr(frameworks, "chat_json", fake)
    assert frameworks.ask({}, ["Source detail"], "Question", [1], node_views=[wrapper])["answered"]
