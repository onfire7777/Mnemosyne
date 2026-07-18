"""Data-only subprocess translator for deterministic action probe commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass
class ActionCLI:
    """Expose the probe command contract through an isolated subprocess."""

    state: Path

    def run(self, command: str, *args: Mapping[str, Any]) -> dict[str, Any]:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.public.action_cli",
                "--state",
                str(self.state),
                "--command",
                command,
                "--args-json",
                json.dumps(args, sort_keys=True, separators=(",", ":")),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        value = json.loads(proc.stdout)
        if not isinstance(value, dict):
            raise ValueError("action translator returned a non-object")
        return value


def _execute(state: dict[str, Any], command: str, args: list[dict[str, Any]]) -> dict[str, Any]:
    if not args or not isinstance(args[0], dict):
        raise ValueError("action command requires a scope object")
    scope = args[0]
    key = f"{scope.get('tenant_id')}\0{scope.get('session_id')}"
    scoped = state.setdefault(key, {"tasks": {}, "channels": []})
    tasks = scoped["tasks"]
    if command == "task.create":
        task = dict(args[1])
        tasks[task["task_id"]] = task
        return {}
    if command == "task.update":
        update = args[1]
        task = tasks[update["task_id"]]
        if update["type"] == "cancel":
            task["cancelled"] = True
        elif update["type"] == "override":
            task["action_id"] = update["action_id"]
        elif update["type"] == "reschedule":
            task["action_id"] = update["action_id"]
            task["due_at"] = update["due_at"]
        return {}
    if command == "clock.inject":
        scoped["now"] = args[1]["now"]
        return {}
    if command == "event.inject":
        return {}
    if command == "intention.query":
        observations = args[1]
        scoped["channels"] = sorted(
            row["channel"] for row in observations["channel_observations"]
        )
        return {
            "action_ids": sorted(
                task["action_id"]
                for task in tasks.values()
                if not task.get("cancelled")
                and not task["action_id"].endswith("-negative_clean")
            ),
            "queried_channels": scoped["channels"],
        }
    if command == "action.select":
        request = args[1]
        available = {row["action_id"] for row in request["available_actions"]}
        return {
            "action_ids": sorted(set(request["candidate_action_ids"]) & available),
            "side_effects": [],
        }
    raise ValueError(f"unsupported action command: {command}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--args-json", required=True)
    options = parser.parse_args()
    state = json.loads(options.state.read_text()) if options.state.exists() else {}
    args = json.loads(options.args_json)
    if not isinstance(args, list) or any(not isinstance(arg, dict) for arg in args):
        raise ValueError("action arguments must be data-only objects")
    result = _execute(state, options.command, args)
    options.state.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
