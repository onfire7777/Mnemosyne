"""Whole-book Q&A packs complete source-grounded records with the real lexical index."""

import copy
import json
import re

import pytest

from mnemosyne import frameworks
from mnemosyne.skills import SkillStore, _answer_views


def node(index, content, *, units=None, fields=None, contributions=None):
    value = {"id": index, "type": "principle", "title": "A principle", "content": content,
             "units": [1] if units is None else units, "fields": fields or {},
             "parent": None, "depends_on": None}
    if contributions is not None:
        value["contributions"] = contributions
    return value


def store_for(nodes, units, document=None):
    store = SkillStore.__new__(SkillStore)
    framework = {"nodes": nodes, "document": "x" * 80_001 if document is None else document}
    row = {"skill_id": "book", "revision": 3, "conversion": "completed", "name": "Book",
           "model": "codex:test-stub", "framework": json.dumps(framework), "units": json.dumps(units)}
    store._skill = lambda *args: row
    return store


@pytest.fixture
def provider(monkeypatch):
    """Exercise chat_json and its input guard, but never launch Codex or an external provider."""
    state = {"prompts": [], "response": None}
    tokens = [(variable, variable.set(value)) for variable, value in (
        (frameworks.CACHE, ""), (frameworks.MODEL, ""), (frameworks.STATS, None))]

    def answer(system, user, model):
        state["prompts"].append((system, user))
        citations = [int(value) for value in re.findall(r"(?m)^\[Unit (\d+)\]$", user)]
        response = state["response"] or {"answer": "Supported by the supplied source.",
                                         "units": citations[:1], "answered": bool(citations)}
        return {"choices": [{"message": {"content": json.dumps(response)}}]}

    monkeypatch.setattr(frameworks, "_codex", answer)
    monkeypatch.setattr(frameworks, "_post", lambda *args: pytest.fail("external provider must not run"))
    yield state
    for variable, token in reversed(tokens):
        variable.reset(token)


def supplied_views(provider):
    user = provider["prompts"][-1][1]
    block = user.split("FRAMEWORK ITEMS:\n", 1)[1].split("\n\nBOOK PASSAGES:", 1)[0]
    return [] if block == "none" else [json.loads(line) for line in block.splitlines()]


def assert_bounded(result, provider, question):
    system, user = provider["prompts"][-1]
    assert len(frameworks.RULEBOOK) + len(system) + len(user) <= frameworks.MAX_PROMPT_CHARS
    assert user.endswith("QUESTION: " + question)
    assert result["context"]["context_chars"] == len(user) - len(question)
    assert result["context"]["context_chars"] <= result["context"]["context_budget_chars"] <= 80_000


def test_oversized_top_ranked_record_does_not_starve_compact_match(provider):
    nodes = [node(0, "quasar " * 16_000), node(1, "quasar useful compact answer")]
    result = store_for(nodes, ["quasar supporting source"]).ask("book", "quasar")
    assert result["context"]["selected_view_ids"] == ["1:0"]
    assert result["context"]["omission_reasons"]["views"]["context_budget"] == 1
    assert supplied_views(provider)[0]["record"] == nodes[1]
    assert_bounded(result, provider, "quasar")


def test_oversized_top_ranked_source_does_not_starve_compact_match(provider):
    result = store_for([], ["quasar " * 16_000, "quasar useful compact source"]).ask("book", "quasar")
    assert result["context"]["selected_units"] == [2]
    assert result["units"] == [2]
    assert result["context"]["omission_reasons"]["units"]["context_budget"] == 1
    assert_bounded(result, provider, "quasar")


def test_contribution_only_field_is_searchable_and_preserved_with_provenance(provider):
    original = node(7, "A general rule", units=[2], fields={
        "Action": "Use the zircon criterion. Keep every condition, including the final caveat.",
        "Source Quote": {"Quote": "Wait until the last condition holds.",
                         "Core Sentence": "Wait until the last condition holds."}})
    original.update({"chapter": "第三章", "part": 4, "view_id": "original-key-is-preserved"})
    nodes = [node(0, "A general rule", units=[1, 2], contributions=[original])]
    before = copy.deepcopy(nodes)
    units = ["Unrelated introduction.", "Wait until the last condition holds."]
    result = store_for(nodes, units).ask("book", "zircon")
    selected = supplied_views(provider)
    assert selected == [{"view_id": "0:0", "canonical_id": 0, "units": [2], "record": original}]
    assert result["context"]["selected_units"] == [2]
    assert units[1] in provider["prompts"][0][1]
    assert result["context"]["partial"] is True
    assert nodes == before


def test_record_reserves_its_full_source_even_when_source_has_no_query_word(provider):
    source = "An active galactic nucleus uses this detailed procedure through its final condition."
    nodes = [node(0, "quasar is the canonical name", units=[2])]
    result = store_for(nodes, ["quasar unrelated introduction", source]).ask("book", "quasar")
    assert result["context"]["selected_units"] == [1, 2]
    assert supplied_views(provider)[0]["units"] == [2]
    assert "[Unit 2]\n" + source in provider["prompts"][0][1]
    assert_bounded(result, provider, "quasar")


def test_many_large_contributions_are_bounded_individually_without_clipping(provider):
    originals = [node(7, "quasar rule", fields={"Action": f"CHAPTER-{i}: " + "x" * 4000 + f" END-{i}"})
                 for i in range(70)]
    nodes = [node(0, "quasar general rule", contributions=originals)]
    result = store_for(nodes, ["quasar complete source"]).ask("book", "quasar")
    selected = supplied_views(provider)
    assert 0 < len(selected) < len(originals)
    for view in selected:
        position = int(view["view_id"].split(":")[1])
        assert view["record"] == originals[position]
    assert result["context"]["selected_view_count"] == len(selected)
    assert result["context"]["omitted_view_count"] == 70 - len(selected)
    assert len(json.dumps(result["context"])) < 2500
    assert_bounded(result, provider, "quasar")


def test_record_excluded_when_its_complete_source_cannot_fit(provider):
    nodes = [node(0, "quasar unique framework assertion", units=[2])]
    result = store_for(nodes, ["quasar unrelated introduction", "evidence " * 12_000]).ask("book", "quasar")
    assert result["context"]["selected_view_ids"] == []
    assert result["context"]["selected_units"] == [1]
    assert "unique framework assertion" not in provider["prompts"][0][1]
    assert "[Unit 2]" not in provider["prompts"][0][1]
    assert result["context"]["omission_reasons"]["views"]["context_budget"] == 1


def test_absent_source_citation_cannot_be_made_valid_by_a_matching_record(provider):
    provider["response"] = {"answer": "An unsupported conclusion.", "units": [2], "answered": True}
    nodes = [node(0, "quasar unique assertion", units=[2])]
    result = store_for(nodes, ["quasar introduction", "evidence " * 12_000]).ask("book", "quasar")
    assert result["answered"] is False and result["units"] == []
    assert result["diagnostic"]["code"] == "invalid_answer_response"
    assert "unsupported conclusion" not in result["answer"]


@pytest.mark.parametrize("query", ["zircon", "how the"])
def test_no_match_abstains_locally_and_reports_partial_scope(provider, query):
    result = store_for([node(0, "ordinary procedure")], ["A routine source."]).ask("book", query)
    assert provider["prompts"] == []
    assert result["answered"] is False and result["units"] == []
    assert result["context"]["selected_units"] == []
    assert result["context"]["selected_view_ids"] == []
    assert result["context"]["omission_reasons"]["views"]["no_match"] == 1
    assert result["context"]["omission_reasons"]["units"]["no_match"] == 1
    assert "does not establish" in result["answer"] and "whole book" in result["answer"]


def test_nothing_fits_abstains_without_provider_or_silent_truncation(provider):
    result = store_for([node(0, "quasar " * 16_000)], ["quasar " * 16_000]).ask("book", "quasar")
    assert provider["prompts"] == []
    assert result["context"]["omission_reasons"]["views"]["context_budget"] == 1
    assert result["context"]["omission_reasons"]["units"]["context_budget"] == 1
    assert not result["answered"] and result["context"]["partial"]


def test_partial_abstention_does_not_repeat_model_claim_about_entire_book(provider):
    provider["response"] = {"answer": "This topic is absent from the entire book.", "units": [], "answered": False}
    result = store_for([], ["quasar one topic", "Entirely different topic"]).ask("book", "quasar")
    assert result["context"]["partial"]
    assert "This topic is absent" not in result["answer"]
    assert "selected context" in result["answer"] and "does not establish" in result["answer"]


def test_exact_rendered_cost_includes_escape_expansion_labels_and_question(provider, monkeypatch):
    nodes = [node(i, "quasar", fields={"Action": "\"\n\\第三章" * 100}) for i in range(2)]
    units = ["A full supporting source, including the final caveat."]
    question = "quasar " + "padding" * 200
    first = _answer_views({"nodes": nodes})[:1]
    cap = frameworks._answer_prompt_size(first, units, [1], question)
    monkeypatch.setattr(frameworks, "MAX_PROMPT_CHARS", cap)
    result = store_for(nodes, units).ask("book", question)
    assert supplied_views(provider) == first
    system, user = provider["prompts"][0]
    assert len(frameworks.RULEBOOK) + len(system) + len(user) == cap
    assert_bounded(result, provider, question)


def test_question_alone_exceeding_prompt_limit_fails_before_provider(provider, monkeypatch):
    question = "quasar " * 100
    monkeypatch.setattr(frameworks, "MAX_PROMPT_CHARS", frameworks._answer_prompt_size([], [], [], question) - 1)
    with pytest.raises(ValueError, match="question was not truncated"):
        store_for([], ["quasar source"]).ask("book", question)
    assert provider["prompts"] == []


def test_small_book_retains_full_document_source_and_public_answer_fields(provider):
    document = "Complete definitive framework with its final paragraph."
    units = ["First complete source.", "Second complete source."]
    response = {"answer": "An answer supported by the full source.", "units": [2], "answered": True}
    provider["response"] = response
    result = store_for([node(0, "A principle")], units, document=document).ask("book", "question")
    assert {key: result[key] for key in response} == response
    assert result["skill_id"] == "book" and result["revision"] == 3
    assert result["context"]["mode"] == "full" and result["context"]["partial"] is False
    assert result["context"]["selected_units"] == [1, 2]
    for text in [document, *units]:
        assert text in provider["prompts"][0][1]
    assert_bounded(result, provider, "question")


def test_full_mode_does_not_claim_unrendered_original_record_fields_were_supplied(provider):
    nodes = [node(0, "A principle", fields={"Tag justifications": "HIDDEN_REASON_SENTINEL"})]
    units = ["A complete source."]
    framework = {"name": "Book", "nodes": nodes, "edges": [], "meta": frameworks._overview({}),
                 "coverage": frameworks.coverage(units, nodes),
                 "logic": {"logic_issues": [], "logic_warnings": []}}
    document = frameworks.render(framework)
    assert "HIDDEN_REASON_SENTINEL" not in document
    result = store_for(nodes, units, document=document).ask("book", "question")
    assert result["context"]["framework_representation"] == "document"
    assert result["context"]["selected_view_ids"] == []
    assert result["context"]["selected_view_count"] == 0
    assert "total_view_count" not in result["context"]
    assert "omitted_view_count" not in result["context"]
    assert result["context"]["selected_units"] == [1] and not result["context"]["partial"]
    assert "HIDDEN_REASON_SENTINEL" not in provider["prompts"][0][1]
