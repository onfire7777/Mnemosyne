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
