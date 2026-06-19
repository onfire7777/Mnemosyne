from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


TENANT = "tenant-cli"
USER = "user-cli"


def run_cli(store: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "mnemosyne.cli", "--store", str(store), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def run_raw_cli(store: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mnemosyne.cli", "--store", str(store), *args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_cli_backend_selection_requires_postgres_dsn(tmp_path: Path) -> None:
    result = run_raw_cli(tmp_path / "mnemosyne.json", "--backend", "postgres", "--postgres-dsn", "", "search", "--tenant", TENANT, "--query", "anything")

    assert result.returncode != 0
    assert "Postgres backend requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN." in result.stderr


def test_cli_tools_command_does_not_require_engine_backend(tmp_path: Path) -> None:
    result = run_raw_cli(tmp_path / "mnemosyne.json", "--backend", "postgres", "--postgres-dsn", "", "tools")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert any(tool["name"] == "search" for tool in payload["tools"])


def test_cli_preference_write_requires_explicit_or_high_trust_source(tmp_path: Path) -> None:
    denied = run_raw_cli(
        tmp_path / "mnemosyne.json",
        "preference",
        "--tenant",
        TENANT,
        "--user",
        USER,
        "--category",
        "workflow",
        "--statement",
        "Infer this low-trust preference.",
    )
    allowed = run_cli(
        tmp_path / "mnemosyne.json",
        "preference",
        "--tenant",
        TENANT,
        "--user",
        USER,
        "--category",
        "workflow",
        "--statement",
        "Prefer explicit CLI preferences.",
        "--explicit",
    )

    assert denied.returncode != 0
    assert "preference denied" in denied.stderr
    assert allowed["security"]["allowed"] is True


def test_cli_profile_graph_learning_and_parametric_flows_persist(tmp_path: Path) -> None:
    store = tmp_path / "mnemosyne.json"

    profile = run_cli(
        store,
        "profile-add",
        "--tenant",
        TENANT,
        "--user",
        USER,
        "--kind",
        "explicit_preference",
        "--statement",
        "Prefer precise operational summaries.",
    )
    profile_context = run_cli(store, "profile-context", "--tenant", TENANT, "--user", USER)
    assert profile["id"]
    assert profile_context["authoritative"][0]["statement"] == "Prefer precise operational summaries."

    run_cli(
        store,
        "relation",
        "--tenant",
        TENANT,
        "--source",
        "Mnemosyne",
        "--predicate",
        "uses",
        "--target",
        "Postgres",
    )
    graph = run_cli(store, "graph-neighbors", "--tenant", TENANT, "--seed", "Mnemosyne")
    assert graph["hits"][0]["text"] == "Mnemosyne uses Postgres"

    trajectory = run_cli(
        store,
        "trajectory-log",
        "--tenant",
        TENANT,
        "--user",
        USER,
        "--session",
        "session-cli",
        "--task",
        "date math deploy",
        "--steps",
        json.dumps([{"name": "calculate", "status": "failed", "error": "off by one day"}]),
        "--outcome",
        "failure",
        "--reward",
        "-1",
        "--memory-version",
        "v1",
    )
    lesson = run_cli(store, "lesson-induce", "--trajectory-id", trajectory["id"])
    procedure = run_cli(store, "procedure-induce", "--lesson-id", lesson["id"])
    validated = run_cli(store, "procedure-validate", "--procedure-id", procedure["id"])
    promoted = run_cli(
        store,
        "lesson-promote",
        "--lesson-id",
        lesson["id"],
        "--cases",
        json.dumps(
            [
                {
                    "id": "case-lesson",
                    "signature": "date math deploy",
                    "query": "lesson off by one day",
                    "expected_substring": "verify with tools",
                    "protected": True,
                }
            ]
        ),
    )
    artifact = run_cli(store, "parametric-propose", "--tenant", TENANT)

    assert validated["status"] == "validated"
    assert promoted["promoted"] is True
    assert set(artifact["source_ids"]) == {lesson["id"], procedure["id"]}
