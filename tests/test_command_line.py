from __future__ import annotations

import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import mnemosyne.command_line as command_line
from eval.harness import answer_quality


@pytest.mark.parametrize(
    "argv",
    [
        [],
        [""],
        ["tool", "two words"],
        ["tool", 'embedded"quote'],
        ["tool", r"trailing\\"],
        ["tool", r'backslashes\\\"before quote'],
        ["tool", "", "\t", "a b", r"C:\\Program Files\\tool.exe"],
    ],
)
def test_windows_parser_round_trips_list2cmdline(argv: list[str]) -> None:
    assert command_line._split_windows_command_line(subprocess.list2cmdline(argv)) == argv


def test_split_command_selects_windows_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command_line, "os", SimpleNamespace(name="nt"))
    assert command_line.split_command('tool "two words"') == ["tool", "two words"]


def test_role_ladder_uses_shared_command_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    role_ladder = runpy.run_path(
        Path(__file__).parents[1] / "infra" / "providers" / "role-ladder.py"
    )
    calls: list[str] = []
    monkeypatch.setitem(
        role_ladder["_command_for"].__globals__,
        "split_command",
        lambda command: calls.append(command) or ["tool"],
    )
    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_FRONTIER_COMMAND", 'tool "two words"')

    assert role_ladder["_command_for"]("judge", "frontier") == ["tool"]
    assert calls == ['tool "two words"']


def test_llm_judge_uses_shared_command_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(answer_quality, "split_command", lambda command: calls.append(command) or ["tool"])
    monkeypatch.setattr(
        answer_quality.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout='{"score": 1}', stderr=""),
    )

    assert answer_quality.make_llm_judge('tool "two words"')("q", "c", "g") == 1.0
    assert calls == ['tool "two words"']
