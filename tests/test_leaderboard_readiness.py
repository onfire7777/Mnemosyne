import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from leaderboard.readiness import ReadinessError, evaluate, main


GATES = (
    "pbpp",
    "part_i_results",
    "register_a",
    "identical_treatment",
    "operator_entry",
)


def _record() -> dict[str, object]:
    record: dict[str, object] = {
        gate: {"satisfied": True, "evidence": f"evidence/{gate}.json"}
        for gate in GATES
    }
    operator_entry = record["operator_entry"]
    assert isinstance(operator_entry, dict)
    operator_entry["label"] = "operator-entry"
    return record


def _write(path: Path, record: dict[str, object]) -> Path:
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_ready_only_when_every_gate_is_explicitly_satisfied() -> None:
    assert evaluate(_record()) == {"blocked_gates": [], "ready": True}


@pytest.mark.parametrize("gate", GATES)
def test_reports_each_unsatisfied_gate_as_blocked(gate: str) -> None:
    record = _record()
    value = record[gate]
    assert isinstance(value, dict)
    value["satisfied"] = False

    assert evaluate(record) == {"blocked_gates": [gate], "ready": False}


def test_blocked_gate_names_are_sorted() -> None:
    record = _record()
    for gate in ("register_a", "pbpp", "operator_entry"):
        value = record[gate]
        assert isinstance(value, dict)
        value["satisfied"] = False

    assert evaluate(record) == {
        "blocked_gates": ["operator_entry", "pbpp", "register_a"],
        "ready": False,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.pop("pbpp"),
        lambda record: record.update(unexpected={}),
        lambda record: _gate(record, "pbpp").pop("satisfied"),
        lambda record: _gate(record, "pbpp").update(unexpected=True),
        lambda record: _gate(record, "pbpp").update(satisfied="true"),
        lambda record: _gate(record, "pbpp").update(evidence=1),
        lambda record: _gate(record, "pbpp").update(evidence="   "),
        lambda record: _gate(record, "operator_entry").update(label="Mnemosyne"),
    ],
)
def test_rejects_noncanonical_records(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    record = _record()
    mutate(record)

    with pytest.raises(ReadinessError):
        evaluate(record)


@pytest.mark.parametrize("value", [None, [], "record"])
def test_rejects_non_object_records(value: object) -> None:
    with pytest.raises(ReadinessError):
        evaluate(value)


def test_cli_emits_deterministic_sorted_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _record()
    second = {key: copy.deepcopy(first[key]) for key in reversed(first)}

    assert main([str(_write(tmp_path / "first.json", first))]) == 0
    first_output = capsys.readouterr()
    assert main([str(_write(tmp_path / "second.json", second))]) == 0
    second_output = capsys.readouterr()

    expected = '{"blocked_gates":[],"ready":true}\n'
    assert first_output.out == second_output.out == expected
    assert first_output.err == second_output.err == ""


def test_cli_returns_one_for_valid_but_blocked_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _record()
    _gate(record, "part_i_results")["satisfied"] = False

    assert main([str(_write(tmp_path / "blocked.json", record))]) == 1
    output = capsys.readouterr()
    assert output.out == '{"blocked_gates":["part_i_results"],"ready":false}\n'
    assert output.err == ""


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        '{"pbpp":{"satisfied":true,"satisfied":false}}',
    ],
)
def test_cli_returns_two_for_malformed_or_duplicate_key_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    raw: str,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(raw, encoding="utf-8")

    assert main([str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "error: invalid readiness record\n"


def _gate(record: dict[str, object], name: str) -> dict[str, object]:
    value = record[name]
    assert isinstance(value, dict)
    return value
