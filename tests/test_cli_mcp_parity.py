"""Every MCP tool has a CLI command, and every argument of it a CLI route.

``mcp_tools.TOOL_SPEC`` is what an MCP client can call; ``mneme`` is what an
operator can type. These tests pin the two together, so a tool or a tool
argument added to the MCP surface without a CLI route fails here by name:

* each tool is a command under its own hyphenated name (``assert_fact`` is
  ``mneme assert-fact``), alongside any older command name that runs it;
* that command's handler calls that very tool, not a sibling that happens to
  share an implementation today;
* every parameter of the tool is passed by the handler, from the command line.

The structural checks read ``cli.py`` rather than run it, so they cover all 60
tools in a few milliseconds. The behavioural tests below them drive the routes
that were missing until this file was written.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

import mnemosyne.cli as cli
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools

TOOL_NAMES: list[str] = sorted(tool["name"] for tool in TOOL_SPEC)

#: Parameters that are not tool arguments: ``session_identity`` is the verified
#: token, which the CLI takes from ``--session-token`` for every command.
NOT_ARGUMENTS = {"self", "session_identity"}

#: How a handler names the ``MemoryTools`` it calls.
RECEIVERS = {"tools", "load_tools(args)"}

#: Arguments a handler builds from flags before the call, so the value passed is
#: a local name: ``ingest`` reads ``--file`` into ``data`` and checks ``--content``;
#: ``working-promote`` parses each ``--regression-case`` into ``cases``.
BUILT_FROM_FLAGS = {("ingest", "content"), ("ingest", "data"), ("working_promote", "cases")}

TENANT = "tenant-parity"
USER = "user-parity"


@lru_cache(maxsize=1)
def _cli_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


@lru_cache(maxsize=1)
def _handler_by_command() -> dict[str, str]:
    parser = cli.build_parser()
    sub = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    return {command: sub_parser.get_default("func").__name__ for command, sub_parser in sub.choices.items()}


def _command(tool: str) -> str:
    return tool.replace("_", "-")


def _parameters(tool: str) -> list[str]:
    return [name for name in inspect.signature(getattr(MemoryTools, tool)).parameters if name not in NOT_ARGUMENTS]


def _tool_calls(tool: str) -> list[ast.Call]:
    """The calls of ``tools.<tool>`` inside the handler bound to the tool's command."""

    handler = _cli_functions()[_handler_by_command()[_command(tool)]]
    return [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == tool
        and ast.unparse(node.func.value) in RECEIVERS
    ]


def _expansion_keys(expr: ast.expr) -> list[str]:
    """The keys a ``**helper(args)`` passes: the helper must return a dict literal."""

    assert isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name), ast.unparse(expr)
    helper = _cli_functions()[expr.func.id]
    for node in ast.walk(helper):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            return [key.value for key in node.value.keys if isinstance(key, ast.Constant)]
    raise AssertionError(f"{expr.func.id} does not return a dict literal")


def _passed(tool: str) -> dict[str, str | None]:
    """Each argument the handler passes, with the expression it passes (None inside a helper)."""

    parameters = _parameters(tool)
    passed: dict[str, str | None] = {}
    for call in _tool_calls(tool):
        for index, value in enumerate(call.args):
            passed[parameters[index]] = ast.unparse(value)
        for keyword in call.keywords:
            if keyword.arg is None:
                passed.update(dict.fromkeys(_expansion_keys(keyword.value)))
            else:
                passed[keyword.arg] = ast.unparse(keyword.value)
    return passed


# --- structure: all 60 tools --------------------------------------------------


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_every_mcp_tool_is_a_cli_command_under_its_own_name(tool: str) -> None:
    assert _command(tool) in _handler_by_command(), f"no `mneme {_command(tool)}` command for MCP tool {tool}"


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_the_command_runs_its_own_tool(tool: str) -> None:
    handler = _handler_by_command()[_command(tool)]
    assert _tool_calls(tool), f"`mneme {_command(tool)}` runs {handler}, which never calls tools.{tool}"


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_every_tool_argument_is_reachable_from_the_command(tool: str) -> None:
    missing = [name for name in _parameters(tool) if name not in _passed(tool)]
    assert not missing, f"`mneme {_command(tool)}` cannot set {missing} of MCP tool {tool}"


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_tool_arguments_come_from_the_command_line(tool: str) -> None:
    """A handler that passes a constant has an argument in name only."""

    fixed = [
        f"{name}={expression}"
        for name, expression in _passed(tool).items()
        if name not in NOT_ARGUMENTS
        and expression is not None
        and "args" not in expression
        and (tool, name) not in BUILT_FROM_FLAGS
    ]
    assert not fixed, f"`mneme {_command(tool)}` passes a fixed value for {fixed}"


def test_renamed_commands_keep_working_and_share_one_handler() -> None:
    handlers = _handler_by_command()
    for command, alias in cli.MCP_TOOL_COMMAND_ALIASES.items():
        assert handlers[command] == handlers[alias]
    assert {alias.replace("-", "_") for alias in cli.MCP_TOOL_COMMAND_ALIASES.values()} <= set(TOOL_NAMES)


# --- behaviour: the routes that were missing ----------------------------------


def _run(capsys: pytest.CaptureFixture[str], store: Path, *args: str) -> dict[str, Any]:
    capsys.readouterr()
    assert cli.main(["--store", str(store), *args]) == 0
    return json.loads(capsys.readouterr().out)


def _add_profile_entry(capsys: pytest.CaptureFixture[str], store: Path, statement: str) -> str:
    added = _run(
        capsys, store, "profile-add", "--tenant", TENANT, "--user", USER, "--kind", "explicit_preference",
        "--statement", statement, "--scope", json.dumps({"project": "parity"}),
    )
    return added["id"]


def _profile_statements(capsys: pytest.CaptureFixture[str], store: Path) -> list[tuple[str, dict[str, Any]]]:
    context = _run(
        capsys, store, "profile-context", "--tenant", TENANT, "--user", USER, "--scope", json.dumps({"project": "parity"})
    )
    return [(entry["statement"], entry["scope"]) for entry in context["authoritative"]]


def test_profile_retire_takes_an_entry_back(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    entry_id = _add_profile_entry(capsys, store, "Prefers tea.")

    retired = _run(capsys, store, "profile-retire", "--tenant", TENANT, "--user", USER, "--id", entry_id)

    assert retired["retired"] is True
    assert retired["status"] == "retracted"
    assert _profile_statements(capsys, store) == []


def test_profile_retire_honours_role_and_scope(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    entry_id = _add_profile_entry(capsys, store, "Prefers tea.")

    with pytest.raises(PermissionError, match="profile_retire denied"):
        cli.main(["--store", str(store), "profile-retire", "--tenant", TENANT, "--user", USER, "--id", entry_id, "--role", "agent"])
    with pytest.raises(ValueError, match="not found in this tenant/user scope"):
        cli.main(["--store", str(store), "profile-retire", "--tenant", TENANT, "--user", "someone-else", "--id", entry_id])
    assert _profile_statements(capsys, store) == [("Prefers tea.", {"project": "parity"})]


def test_profile_correct_keeps_the_scope_unless_context_is_given(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    entry_id = _add_profile_entry(capsys, store, "Prefers tea.")

    corrected = _run(
        capsys, store, "profile-correct", "--tenant", TENANT, "--user", USER, "--id", entry_id,
        "--statement", "Prefers green tea.",
    )
    assert _profile_statements(capsys, store) == [("Prefers green tea.", {"project": "parity"})]

    _run(
        capsys, store, "profile-correct", "--tenant", TENANT, "--user", USER, "--id", corrected["id"],
        "--statement", "Prefers oolong.", "--context", json.dumps({"project": "other"}),
    )
    assert _profile_statements(capsys, store) == []


def test_profile_correct_role_reaches_the_policy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    entry_id = _add_profile_entry(capsys, store, "Prefers tea.")

    with pytest.raises(PermissionError):
        cli.main([
            "--store", str(store), "profile-correct", "--tenant", TENANT, "--user", USER, "--id", entry_id,
            "--statement", "Prefers coffee.", "--role", "reader",
        ])
    assert _profile_statements(capsys, store) == [("Prefers tea.", {"project": "parity"})]


def test_capture_metadata_is_stored_and_must_be_an_object(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    capture = ("capture", "--tenant", TENANT, "--user", USER, "--source-type", "cli")

    captured = _run(capsys, store, *capture, "--content", "Parity likes tea.", "--metadata", json.dumps({"origin": "parity"}))
    record = _run(capsys, store, "get", "--tenant", TENANT, "--id", captured["cid"])["record"]

    assert record["metadata"]["origin"] == "parity"
    with pytest.raises(ValueError, match="--metadata must be a JSON object"):
        cli.main(["--store", str(store), *capture, "--content", "Never stored.", "--metadata", "[1]"])


def test_search_and_deep_search_take_the_lean_and_budget_arguments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    _run(capsys, store, "capture", "--tenant", TENANT, "--user", USER, "--source-type", "cli", "--content", "Parity likes tea.")
    query = ("--tenant", TENANT, "--query", "tea")

    full = _run(capsys, store, "search", *query)
    lean = _run(capsys, store, "search", *query, "--lean", "--token-budget", "400")
    deep = _run(capsys, store, "deep-search", *query, "--lean", "--token-budget", "400")

    assert "explain" in full
    assert "explain" not in lean and "explain" not in deep
    assert lean["token_budget"] == 400 and deep["token_budget"] == 400
    assert lean["hits"]


def test_search_session_read_still_needs_a_session_token(tmp_path: Path) -> None:
    """``--session-id`` is the working-memory read: no flag may stand in for the token."""

    with pytest.raises(PermissionError):
        cli.main(["--store", str(tmp_path / "store.json"), "search", "--tenant", TENANT, "--query", "tea", "--session-id", "s1"])


def test_search_rejects_an_unparseable_evaluated_at(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        cli.main([
            "--store", str(tmp_path / "store.json"), "search", "--tenant", TENANT, "--query", "tea",
            "--evaluated-at", "not-a-date",
        ])


def test_new_flags_parse_to_the_tool_defaults() -> None:
    parser = cli.build_parser()

    forget = ["forget", "--tenant", TENANT, "--cid", "c"]
    assert parser.parse_args(forget).all_branches is True
    assert parser.parse_args([*forget, "--no-all-branches"]).all_branches is False

    working = [
        "working-query", "--tenant", TENANT, "--session-id", "s", "--user", USER, "--agent-id", "a",
        "--task-id", "t", "--branch", "main", "--as-of", "2030-01-01T00:00:00+00:00",
    ]
    assert (parser.parse_args(working).limit, parser.parse_args(working).kind) == (None, [])
    narrowed = parser.parse_args([*working, "--limit", "3", "--kind", "goal", "--kind", "note"])
    assert (narrowed.limit, narrowed.kind) == (3, ["goal", "note"])

    prefetch = parser.parse_args(["prefetch", "--tenant", TENANT, "--candidates", "[]"])
    assert (prefetch.role, prefetch.user, prefetch.capability_tag, prefetch.purpose) == ("agent", None, [], None)


def test_prefetch_and_preference_accept_the_added_arguments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    _run(capsys, store, "capture", "--tenant", TENANT, "--user", USER, "--source-type", "cli", "--content", "Parity likes tea.")

    preference = _run(
        capsys, store, "preference", "--tenant", TENANT, "--user", USER, "--category", "tone", "--statement", "Be brief.",
        "--explicit", "--access-policy", json.dumps({"tenant": TENANT}),
    )
    prefetched = _run(
        capsys, store, "prefetch", "--tenant", TENANT,
        "--candidates", json.dumps([{"query": "tea", "probability": 0.9, "reason": "parity"}]),
        "--role", "reader", "--user", USER, "--capability-tag", "parity", "--purpose", "testing",
    )

    assert preference["id"]
    assert prefetched["results"][0]["executed"] is True
    with pytest.raises(ValueError, match="--access-policy must be a JSON object"):
        cli.main([
            "--store", str(store), "preference", "--tenant", TENANT, "--user", USER, "--category", "tone",
            "--statement", "Be brief.", "--access-policy", "[]",
        ])


def test_assert_fact_alias_writes_a_fact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"
    captured = _run(capsys, store, "capture", "--tenant", TENANT, "--user", USER, "--source-type", "cli", "--content", "Parity likes tea.")

    asserted = _run(
        capsys, store, "assert-fact", "--tenant", TENANT, "--user", USER, "--subject", "parity", "--predicate", "likes",
        "--object", "tea", "--evidence-cid", captured["cid"], "--trust-tier", "0", "--source-trust-tier", "0",
    )

    assert asserted["security"]["operation"] == "assert_fact"


@pytest.mark.parametrize(
    ("alias", "command", "arguments"),
    [
        (
            "schedule-intention",
            "intention-schedule",
            ["--user", USER, "--agent", "a", "--trigger-expression", "{}", "--action", "{}",
             "--due-at", "2030-01-01T00:00:00+00:00", "--evidence-cid", "c", "--reschedule-history", "[]"],
        ),
        ("cancel-intention", "intention-cancel", ["--intention-id", "i"]),
        ("update-intention", "intention-update", ["--intention-id", "i", "--user", USER, "--agent", "a"]),
        (
            "evaluate-intentions",
            "intention-evaluate",
            ["--evaluated-at", "2030-01-01T00:00:00+00:00", "--trigger-context", "{}", "--operating-point", "{}"],
        ),
        ("list-intentions", "intention-list", []),
    ],
)
def test_an_mcp_name_alias_is_held_to_the_session_gate_of_its_command(
    tmp_path: Path, alias: str, command: str, arguments: list[str]
) -> None:
    """The gate is keyed on the command name, so an alias must not walk round it."""

    with pytest.raises(SystemExit, match=f"{command} requires --session-token"):
        cli.main(["--store", str(tmp_path / "store.json"), alias, "--tenant", TENANT, *arguments])


def test_propose_and_record_commands_run_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.json"

    trajectory = _run(
        capsys, store, "trajectory-record", "--tenant", TENANT, "--user", USER, "--session", "s", "--task", "parity task",
        "--steps", json.dumps([{"action": "x", "error": "boom"}]), "--outcome", "failure", "--reward", "0",
        "--memory-version", "v1",
    )
    lesson = _run(capsys, store, "lesson-propose", "--trajectory-id", trajectory["id"])
    procedure = _run(capsys, store, "procedure-propose", "--lesson-id", lesson["id"])

    assert trajectory["id"] and lesson["id"] and procedure["id"]
