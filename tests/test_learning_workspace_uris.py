import json

from mnemosyne.experience.candidates import (
    observed_steps, portable_observed_steps, sequence_occurrence, template_workspace,
)
from mnemosyne.experience.environment_capture import capture_failed_python_environment
from mnemosyne.experience.strategies import strategy_applies
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.task_class import semantic_contract


def event(cwd, command="pytest -q"):
    return {"name": "shell", "source": "tool", "command": command,
            "cwd": cwd, "arguments": {"cwd": cwd}}


def test_legacy_uri_actions_match_current_paths_without_rewriting_evidence():
    old = {"tool_events": [event("file:/work/my%20project")]}
    current = {"tool_events": [event("/work/my project")]}
    old_steps = observed_steps(old)
    assert "file:/work/my%20project" in old_steps[0]
    assert sequence_occurrence(old_steps, observed_steps(current)) == [0]
    portable, root = portable_observed_steps(old)
    assert root == "/work/my project"
    assert json.loads(portable[0])["cwd"] == {"variable": "workspace"}
    assert sequence_occurrence(portable, observed_steps({"tool_events": [event("file://localhost/other")]})) == [0]
    assert sequence_occurrence(old_steps, observed_steps({"tool_events": [event("/work/my project", "pytest -q --dangerous")]})) is None


def test_remote_uri_and_commands_bound_to_old_directory_are_not_portable():
    remote = observed_steps({"tool_events": [event("file://remote/work")]})[0]
    assert template_workspace(remote, "/work") == remote
    fixed = observed_steps({"tool_events": [event("file:/work/my%20project", "cat file:/work/my%20project/settings.py")]})[0]
    assert template_workspace(fixed, "/work/my project") == fixed


def test_fixed_strategy_workspace_matches_only_same_local_directory():
    steps = observed_steps({"tool_events": [event("file:/work/my%20project")]})
    contract = semantic_contract("fix the cache bug")
    shape = {key: contract[key] for key in ("version", "intent", "constraints", "risk")}
    artifact = {"steps": steps, "strategy_contract": {"version": 1, "shape": shape,
                "workspace": "file:/work/my%20project", "required_tools": ["shell"], "steps_hash": digest(steps)}}
    assert strategy_applies(artifact, "fix the billing bug", tools=["shell"], workspace="/work/my project", require_workspace=True)
    assert not strategy_applies(artifact, "fix the billing bug", tools=["shell"], workspace="file://remote/work/my%20project", require_workspace=True)
    assert not strategy_applies(artifact, "fix the billing bug", tools=["shell"], workspace="/other", require_workspace=True)


def test_current_failed_pytest_capture_accepts_local_file_uri(tmp_path):
    (tmp_path / "test_one.py").write_text("def test_one(): assert False\n")
    observed = {"source": "tool", "runner": "pytest", "failed": 1, "exit_code": 1,
                "command": "pytest test_one.py", "cwd": tmp_path.as_uri(),
                "output": "FAILED test_one.py::test_one - assert False", "call_id": "current"}
    captured = capture_failed_python_environment(observed)
    assert captured["source_workspace"] == str(tmp_path)
    assert captured["tests"] == ["test_one.py"]
    observed["cwd"] = "file://remote" + str(tmp_path)
    assert capture_failed_python_environment(observed) is None
