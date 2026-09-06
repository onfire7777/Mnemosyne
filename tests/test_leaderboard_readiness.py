import copy
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import leaderboard.readiness as readiness
from leaderboard.readiness import ReadinessError, evaluate, evaluate_result_v2, main
from tests.test_leaderboard_result_contract import _v2_development_record, _v2_official_record


GATES = (
    "pbpp",
    "part_i_results",
    "register_a",
    "identical_treatment",
    "operator_entry",
)


def _record() -> dict[str, object]:
    record: dict[str, object] = {
        gate: {"satisfied": True, "evidence": f"evidence/{gate}.json"} for gate in GATES
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
        lambda record: record.update(pbpp=None),
        lambda record: _gate(record, "pbpp").pop("satisfied"),
        lambda record: _gate(record, "pbpp").pop("evidence"),
        lambda record: _gate(record, "pbpp").update(unexpected=True),
        lambda record: _gate(record, "pbpp").update(satisfied="true"),
        lambda record: _gate(record, "pbpp").update(evidence=1),
        lambda record: _gate(record, "pbpp").update(evidence="   "),
        lambda record: _gate(record, "operator_entry").pop("label"),
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


def test_cli_opens_regular_file_without_o_nonblock_when_unavailable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write(tmp_path / "ready.json", _record())
    monkeypatch.delattr(readiness.os, "O_NONBLOCK", raising=False)

    assert main([str(path)]) == 0
    output = capsys.readouterr()
    assert output.out == '{"blocked_gates":[],"ready":true}\n'
    assert output.err == ""


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


@pytest.mark.parametrize("argv", [[], ["first.json", "second.json"]])
def test_cli_returns_two_unless_given_exactly_one_path(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(argv) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "error: invalid readiness record\n"


@pytest.mark.parametrize("invalid_input", ["missing", "invalid-utf8", "oversized-int"])
def test_cli_returns_two_for_unreadable_or_unparseable_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    invalid_input: str,
) -> None:
    path = tmp_path / "invalid.json"
    if invalid_input == "invalid-utf8":
        path.write_bytes(b"\xff")
    elif invalid_input == "oversized-int":
        path.write_text("9" * 5000, encoding="utf-8")

    assert main([str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "error: invalid readiness record\n"


def test_cli_rejects_input_larger_than_one_megabyte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _record()
    _gate(record, "pbpp")["evidence"] = "x" * 1_048_576

    assert main([str(_write(tmp_path / "large.json", record))]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "error: invalid readiness record\n"


def test_cli_does_not_hide_unexpected_evaluation_value_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path / "ready.json", _record())

    def fail(_record: object) -> dict[str, object]:
        raise ValueError("programming error")

    monkeypatch.setattr(readiness, "evaluate", fail)

    with pytest.raises(ValueError, match="programming error"):
        main([str(path)])


def test_module_cli_propagates_process_exit_and_output(tmp_path: Path) -> None:
    record = _record()
    _gate(record, "part_i_results")["satisfied"] = False
    path = _write(tmp_path / "blocked.json", record)

    completed = subprocess.run(
        [sys.executable, "-m", "leaderboard.readiness", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stdout == '{"blocked_gates":["part_i_results"],"ready":false}\n'
    assert completed.stderr == ""


def test_module_cli_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / "readiness.fifo"
    os.mkfifo(path)

    completed = subprocess.run(
        [sys.executable, "-m", "leaderboard.readiness", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == "error: invalid readiness record\n"


def _gate(record: dict[str, object], name: str) -> dict[str, object]:
    value = record[name]
    assert isinstance(value, dict)
    return value


def test_v1_readiness_evaluate_remains_unchanged() -> None:
    assert evaluate(_record()) == {"blocked_gates": [], "ready": True}


def test_development_v2_result_is_never_publication_ready() -> None:
    result = evaluate_result_v2(_v2_development_record())

    assert result["ready"] is False
    assert "publication" in result["blocked_gates"]
    assert "pbpp" in result["blocked_gates"]
    assert "human_approval" in result["blocked_gates"]


def test_official_v2_result_stays_human_gated() -> None:
    result = evaluate_result_v2(_v2_official_record())

    assert result["ready"] is False
    assert "human_approval" in result["blocked_gates"]


def test_operator_run_without_register_b_blocks_pbpp() -> None:
    record = _v2_official_record()
    publication = record["publication"]
    assert isinstance(publication, dict)
    assert publication["label"] == "operator-run"
    assert "register_b_satisfied" not in publication

    result = evaluate_result_v2(record)
    assert result["ready"] is False
    assert "pbpp" in result["blocked_gates"]
    assert "human_approval" in result["blocked_gates"]

    publication["register_b_satisfied"] = True
    cleared = evaluate_result_v2(record)
    assert "pbpp" not in cleared["blocked_gates"]
    assert "human_approval" in cleared["blocked_gates"]
    assert cleared["ready"] is False


def test_failed_safety_gate_blocks_v2_readiness() -> None:
    record = _v2_official_record()
    record["safety_gates"] = [{"name": "no-leakage", "status": "failed"}]

    result = evaluate_result_v2(record)
    assert result["ready"] is False
    assert "safety_gates" in result["blocked_gates"]


def test_rejects_invalid_v2_readiness_record() -> None:
    record = _v2_development_record()
    del record["track_kind"]

    with pytest.raises(ReadinessError):
        evaluate_result_v2(record)


def test_cli_dispatches_v2_result_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "v2.json", _v2_development_record())

    assert main([str(path)]) == 1
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["ready"] is False
    assert "publication" in payload["blocked_gates"]
    assert output.err == ""


def test_proposed_admission_is_an_explicit_blocked_prerequisite() -> None:
    result = evaluate_result_v2(_v2_official_record())

    assert result["ready"] is False
    assert "admission" in result["blocked_gates"]
    assert "human_approval" in result["blocked_gates"]


def test_missing_prerequisites_are_not_a_soft_pass() -> None:
    development = evaluate_result_v2(_v2_development_record())

    assert development["ready"] is False
    assert {
        "admission",
        "human_approval",
        "pbpp",
        "publication",
    } <= set(development["blocked_gates"])
