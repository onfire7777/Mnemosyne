"""Book answers must not silently lose the end of an admitted source/document."""

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
