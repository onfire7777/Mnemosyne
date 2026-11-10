"""Automatic user feedback must reflect an explicit response to the prior turn."""

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime


def _followup(text, previous="Explain this code"):
    runtime = LearningRuntime(LocalMemoryEngine())
    first = runtime.observe_turn("t", "u", "s", previous, "Here is my answer")
    runtime.observe_turn("t", "u", "s", text, "")
    return runtime.episode("t", first["episode_id"])


@pytest.mark.parametrize(
    "text",
    [
        "Actually this worked perfectly",
        "Actually it works",
        "I meant to say thank you",
        "I meant the current month.",
        "No worries, thank you",
        "No problem, continue",
        "No, that is correct",
        "That is not wrong",
        "Your answer is not incorrect",
        "Explain why this code is wrong",
        "What is wrong with this code?",
        "Instead of SQL, explain Redis",
        "Use the word 'instead' in a sentence",
        "Please correct it if necessary",
        'The report says "you are wrong". Explain the disagreement.',
        '"No, that is wrong."',
        "> No, that is wrong.\nExplain the quoted feedback.",
        "```text\nNo, that is wrong.\n```\nSummarize this example.",
        "Explain this code",
        "Explain this code for tomorrow",
    ],
)
def test_neutral_quoted_or_negated_followup_does_not_finalize_prior_as_failure(text):
    prior = _followup(text)
    assert prior["status"] == "open"
    assert prior["reward"] is None
    assert prior["signals"] == []


@pytest.mark.parametrize(
    "text",
    [
        "No, that is wrong.",
        "That is incorrect.",
        "Your answer is wrong.",
        "No, use bullet points instead.",
        "No, respond only with a JSON object. Do not use Markdown fences.",
        "No, do not include the debug log.",
        "Actually, use bullet points instead.",
        "Use inventory totals instead.",
        "Please correct it.",
        "Please fix your answer.",
        "No, I meant the current month.",
        "This still doesn't work.",
        "This still does not work.",
    ],
)
def test_explicit_correction_still_records_negative_feedback(text):
    prior = _followup(text)
    assert prior["status"] == "resolved"
    assert prior["reward"] == -1
    assert [signal["kind"] for signal in prior["signals"]] == ["correction"]


@pytest.mark.parametrize(
    "text",
    [
        "Please try again.",
        "Try again, that failed.",
        "You didn't answer my question.",
    ],
)
def test_explicit_retry_still_records_reask_feedback(text):
    prior = _followup(text)
    assert prior["status"] == "resolved"
    assert prior["reward"] == -0.6
    assert [signal["kind"] for signal in prior["signals"]] == ["reask"]


@pytest.mark.parametrize("text", ["Thanks!", "That works.", "Correct."])
def test_existing_explicit_acceptance_remains_low_weight_feedback(text):
    prior = _followup(text)
    assert prior["status"] == "resolved"
    assert prior["reward"] == 0.6
    assert [signal["kind"] for signal in prior["signals"]] == ["acceptance"]
