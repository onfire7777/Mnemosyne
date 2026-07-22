import json

import pytest

from mnemosyne.providers.deterministic_synthesis import (
    DeterministicSynthesisError,
    DeterministicSynthesizer,
)


def _payload(operation: str, *quotes: str) -> dict[str, object]:
    return {
        "operation": operation,
        "spans": [
            {"cid": f"source-{index}", "quote": quote}
            for index, quote in enumerate(quotes, 1)
        ],
    }


@pytest.mark.parametrize(
    ("operation", "quotes", "answer"),
    [
        ("add", ("0.10", "2.900"), "3"),
        ("subtract", ("1", "2.50"), "-1.5"),
        ("multiply", ("-2.5", "4"), "-10"),
        ("divide", ("1", "8"), "0.125"),
    ],
)
def test_arithmetic_is_exact_and_canonical(
    operation: str, quotes: tuple[str, ...], answer: str
) -> None:
    assert DeterministicSynthesizer().synthesize(_payload(operation, *quotes))["answer"] == answer


def test_output_preserves_provenance_order_and_exact_quotes() -> None:
    payload = {
        "operation": "add",
        "spans": [
            {"cid": "z", "quote": "1.20"},
            {"cid": "a", "quote": "2.80"},
        ],
    }

    assert DeterministicSynthesizer().synthesize(payload) == {
        "answer": "4",
        "operation": "add",
        "provenance": payload["spans"],
        "unresolved": False,
    }


def test_output_has_deterministic_canonical_serialization() -> None:
    synthesizer = DeterministicSynthesizer()
    first = synthesizer.synthesize(_payload("add", "1.0", "2.00"))
    second = synthesizer.synthesize(_payload("add", "1.0", "2.00"))

    def canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    assert canonical(first) == canonical(second)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"operation": "add", "spans": [], "extra": True},
        {"operation": 1, "spans": []},
        {"operation": "sum", "spans": []},
        {"operation": "add", "spans": "1,2"},
        {"operation": "add", "spans": []},
        {"operation": "add", "spans": [{"cid": "a", "quote": "1"}]},
        {"operation": "add", "spans": [{"cid": "", "quote": "1"}, {"cid": "b", "quote": "2"}]},
        {"operation": "add", "spans": [{"cid": "a", "quote": ""}, {"cid": "b", "quote": "2"}]},
        {"operation": "add", "spans": [{"cid": "a", "quote": "1", "extra": 0}, {"cid": "b", "quote": "2"}]},
    ],
)
def test_payload_and_spans_are_strict(payload: object) -> None:
    with pytest.raises(DeterministicSynthesisError):
        DeterministicSynthesizer().synthesize(payload)  # type: ignore[arg-type]


def test_duplicate_identical_spans_are_rejected() -> None:
    span = {"cid": "same", "quote": "1"}
    with pytest.raises(DeterministicSynthesisError):
        DeterministicSynthesizer().synthesize({"operation": "add", "spans": [span, dict(span)]})


@pytest.mark.parametrize(
    "quote",
    [
        "1 + 2",
        "12 kg",
        "1e3",
        "NaN",
        "Infinity",
        "1,000",
        "True",
        ".5",
        "01",
        "--1",
    ],
)
def test_unsafe_or_ambiguous_decimal_text_is_rejected(quote: str) -> None:
    with pytest.raises(DeterministicSynthesisError):
        DeterministicSynthesizer().synthesize(_payload("add", quote, "1"))


@pytest.mark.parametrize("value", [True, False, 1, 1.0, float("nan"), float("inf")])
def test_non_string_numeric_values_are_rejected(value: object) -> None:
    payload = {"operation": "add", "spans": [{"cid": "a", "quote": value}, {"cid": "b", "quote": "1"}]}
    with pytest.raises(DeterministicSynthesisError):
        DeterministicSynthesizer().synthesize(payload)


@pytest.mark.parametrize(
    "payload",
    [
        _payload("add", "1" * 65, "1"),
        _payload("add", "0." + "1" * 19, "1"),
        _payload("multiply", "99999999999999999999999999999999999999", "99999999999999999999999999999999999999"),
    ],
)
def test_decimal_and_result_bounds_are_enforced(payload: dict[str, object]) -> None:
    with pytest.raises(DeterministicSynthesisError):
        DeterministicSynthesizer().synthesize(payload)


@pytest.mark.parametrize(
    "payload",
    [
        _payload("divide", "1", "0"),
        _payload("divide", "1", "3"),
        _payload("divide", "1", "1048576"),
    ],
)
def test_division_fails_closed_for_zero_nonterminating_or_over_scale_results(
    payload: dict[str, object],
) -> None:
    with pytest.raises(DeterministicSynthesisError):
        DeterministicSynthesizer().synthesize(payload)


def test_negative_zero_is_normalized() -> None:
    assert DeterministicSynthesizer().synthesize(_payload("multiply", "-0.0", "2"))["answer"] == "0"
