"""Learned procedures retain the observed operation and its execution context."""

import json

from mnemosyne.experience.candidates import candidate_score, observed_steps


def episode(events):
    return {"tool_events": events, "reward": 1, "signals": [{"kind": "verifier", "value": 1}]}


def test_shell_commands_and_arguments_remain_distinct_steps():
    checks = episode([
        {"name": "shell", "source": "tool", "command": "ruff check src", "cwd": "/project"},
        {"name": "shell", "source": "tool", "command": "pytest tests", "cwd": "/project"},
    ])
    reads = episode([
        {"name": "shell", "source": "tool", "command": "cat pyproject.toml", "cwd": "/project"},
        {"name": "shell", "source": "tool", "command": "git status", "cwd": "/project"},
    ])
    assert observed_steps(checks) != observed_steps(reads)
    assert json.loads(observed_steps(checks)[0]) == {
        "type": "tool_action", "tool": "shell", "command": "ruff check src", "cwd": "/project",
    }


def test_structured_arguments_and_conditions_are_preserved_exactly():
    action = {"name": "fetch", "source": "tool", "arguments": {
        "url": "https://example.org/CaseSensitive", "headers": {"If-Match": '"version-2"'},
    }, "conditions": {"mode": "read-only"}}
    parsed = json.loads(observed_steps(episode([action]))[0])
    assert parsed["arguments"] == action["arguments"]
    assert parsed["conditions"] == action["conditions"]


def test_legacy_procedure_still_matches_its_original_tool_names():
    actual = episode([{"name": "shell", "source": "tool", "command": "pytest tests"}])
    assert candidate_score({"kind": "procedure", "steps": ["shell"]}, actual) == 1
    new_steps = observed_steps(actual)
    assert candidate_score({"kind": "procedure", "steps": new_steps}, actual) == 1
    changed = episode([{"name": "shell", "source": "tool", "command": "pytest other_tests"}])
    assert candidate_score({"kind": "procedure", "steps": new_steps}, changed) == 0


def test_untrusted_and_unserializable_actions_cannot_become_partial_procedures():
    assert observed_steps(episode([{"name": "shell", "source": "assistant", "command": "bad"}])) == []
    invalid = [{"name": "read", "source": "tool"},
               {"name": "shell", "source": "tool", "arguments": {"bad": float("nan")}}]
    assert observed_steps(episode(invalid)) == []


def test_activation_requires_consistently_successful_targeted_verification():
    from types import SimpleNamespace
    from mnemosyne.experience.runtime import stat_key
    from mnemosyne.experience.sleep import activation_supported
    from mnemosyne.experience.stats import Posterior

    artifact = {"id": "checked", "kind": "procedure", "revision": 1, "task_class": "task",
                "gate_passed": True, "source_cids": ["source"], "source_episode_ids": ["episode"]}
    statistics = {**Posterior(alpha=25, beta=1, n=24).to_dict(),
                  "served_n": 24, "served_successes": 24, "control_n": 24,
                  "control_successes": 0, "verified_n": 12, "verified_successes": 1}
    state = {"stats": {stat_key("procedure", "checked", 1, "task"): statistics}}
    runtime = SimpleNamespace()
    assert not activation_supported(runtime, state, artifact)
    statistics["verified_successes"] = 12
    assert activation_supported(runtime, state, artifact)


def test_real_command_procedure_is_grounded_and_reused_for_a_paraphrase(tmp_path):
    import subprocess
    import sys
    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.experience.runtime import LearningRuntime

    runtime = LearningRuntime(LocalMemoryEngine())
    query = "Run the arithmetic smoke check"
    command = [sys.executable, "-c", "print(6 * 7)"]
    for index in range(2):
        context = runtime.prepare_context("t", "u", str(index), query, ["shell"])
        completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
        verified = completed.returncode == 0 and completed.stdout.strip() == "42"
        captured = runtime.observe_turn(
            "t", "u", str(index), query, "", receipt_ids=[context["receipt_id"]],
            tool_events=[{"name": "shell", "source": "tool", "command": command,
                          "cwd": str(tmp_path), "output": completed.stdout, "verdict": verified}],
        )
        runtime.resolve("t", captured["episode_id"])
    runtime.consolidate("t")
    state = runtime.writer.read("t")
    procedure = next(item for item in state["artifacts"].values() if item["kind"] == "procedure")
    assert procedure["state"] == "probation"
    action = json.loads(procedure["steps"][0])
    assert action["command"] == command and action["cwd"] == str(tmp_path)
    assert procedure["gate_passed"]
    assert all(quote["quote"] in runtime.engine.get_evidence("t", quote["cid"]).content
               for quote in procedure["source_quotes"])
    contexts = [runtime.prepare_context("t", "u", str(index + 2),
                                       "Execute the arithmetic smoke check", ["shell"])
                for index in range(2)]
    offered = [item for context in contexts for item in context["procedures"]]
    assert any(item["id"] == procedure["id"] and json.loads(item["steps"][0]) == action
               for item in offered)
