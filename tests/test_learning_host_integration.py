from __future__ import annotations

import asyncio
import inspect

import pytest

from mnemosyne.cli import LEARNING_TOOL_COMMANDS, build_parser
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.frameworks import AutoMemorySession
from mnemosyne.mcp_server import _to_mcp_tool_spec
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.policy import LEARNING_COMPONENTS, LEARNING_RAILS, OperatingPolicy


def test_learning_defaults_active_and_old_policy_compatible():
    policy = OperatingPolicy.from_dict(
        {"top_k": 3, "immutable_rails": {"tenant_isolation_required": True}}
    )
    assert policy.learning_enabled
    assert policy.learning_modes == dict.fromkeys(LEARNING_COMPONENTS, "active")
    assert all(policy.immutable_rails[k] for k in LEARNING_RAILS)


@pytest.mark.parametrize(
    "value",
    [
        {"learning_enabled": "true"},
        {"learning_typo": False},
        {"learning_modes": {"guards": "off"}},
        {"learning_exploration_rate": 0},
        {"learning_resolution_window_minutes": 0},
        {"immutable_rails": {"single_learning_write_path": False}},
    ],
)
def test_learning_policy_loading_fails_closed(value):
    with pytest.raises(ValueError):
        OperatingPolicy.from_dict(value)


def test_all_host_commands_have_typed_mcp_and_cli_surface():
    parser = build_parser()
    for name in LEARNING_TOOL_COMMANDS:
        spec = next(item for item in TOOL_SPEC if item["name"] == name)
        schema = _to_mcp_tool_spec(spec)["inputSchema"]
        assert "tenant_id" in schema["required"]
        sub = parser._subparsers._group_actions[0].choices[name.replace("_", "-")]
        flags = {action.dest for action in sub._actions}
        assert set(schema["properties"]) <= flags


def test_capture_feedback_and_session_ownership():
    tools = MemoryTools(LocalMemoryEngine())
    context = tools.prepare_context("t", "u", "s", "verify operation")
    observed = tools.observe_turn(
        "t", "u", "s", "verify operation", "done", receipt_ids=[context["receipt_id"]]
    )
    with pytest.raises(PermissionError):
        tools.record_signal(
            "t", "other", "s", "verifier", 1, episode_id=observed["episode_id"]
        )
    result = tools.record_signal(
        "t",
        "u",
        "s",
        "verifier",
        1,
        episode_id=observed["episode_id"],
        final=True,
        evidence="external test",
    )
    assert result
    assert tools.end_session("t", "u", "s")["episodes"] == 1


def test_untrusted_host_cannot_forge_verifier_events():
    tools = MemoryTools(LocalMemoryEngine())
    with pytest.raises(PermissionError):
        tools.observe_turn(
            "t",
            "u",
            "s",
            "q",
            "a",
            tool_events=[{"verdict": True}],
            source_trust_tier=2,
        )


@pytest.mark.parametrize(
    "name",
    [
        "learning_pause",
        "learning_resume",
        "learning_status",
        "learning_reflect",
        "learning_defects",
    ],
)
def test_admin_methods_use_existing_operator_boundary(name):
    tools = MemoryTools(LocalMemoryEngine())
    with pytest.raises(PermissionError):
        getattr(tools, name)("t", role="agent", source_trust_tier=0)
    assert getattr(tools, name)("t", role="operator", source_trust_tier=0) is not None


def test_sdk_records_receipt_and_only_completed_response():
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u", auto_consolidate=False)
    wrapped = session.wrap(
        lambda message: {"content": "done", "tool_events": [{"verdict": True}]}
    )
    response = wrapped("verify")
    assert response["content"] == "done"
    state = session.learning_runtime.writer.read("t")
    assert len(state["receipts"]) == len(state["episodes"]) == 1
    assert next(iter(state["episodes"].values()))["signals"][0]["kind"] == "verifier"
    session.close()


def test_sdk_awaits_async_completion_and_no_capture_on_error():
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u", auto_consolidate=False)

    async def response(message):
        return "finished"

    result = session.wrap(response)("verify")
    assert inspect.isawaitable(result)
    assert not session.learning_runtime.writer.read("t")["episodes"]
    assert asyncio.run(result) == "finished"
    assert len(session.learning_runtime.writer.read("t")["episodes"]) == 1


def test_sdk_other_branches_do_not_cross_read_learning_main():
    session = AutoMemorySession(
        LocalMemoryEngine(), "t", "u", branch="canary", auto_consolidate=False
    )
    assert session.learning_runtime is None


def test_legacy_migration_is_scoped_idempotent_and_unrewarded():
    from mnemosyne.experience.runtime import LearningRuntime
    from mnemosyne.learning import LearningSystem, Trajectory
    from mnemosyne.runtime_state import migrate_legacy_learning

    engine = LocalMemoryEngine()
    old = LearningSystem(engine)
    for tenant in ("t", "foreign"):
        old.log_trajectory(
            Trajectory(tenant, "u", "s", "legacy task", [], "success", 1, "v1")
        )
    runtime = LearningRuntime(engine)
    assert migrate_legacy_learning(runtime, old, "t")["archived"] == 1
    assert migrate_legacy_learning(runtime, old, "t")["archived"] == 0
    state = runtime.writer.read("t")
    assert len(state["episodes"]) == 1
    episode = next(iter(state["episodes"].values()))
    assert episode["status"] == "legacy"
    assert episode["reward"] is None
    assert not state["credit"]


def test_learning_job_uses_runtime_and_checks_branch():
    from mnemosyne.jobs import RuntimeJobHandlers, LEARNING_CONSOLIDATE_JOB
    from mnemosyne.queue import InProcessQueue

    handlers = RuntimeJobHandlers(LocalMemoryEngine(), InProcessQueue())
    result = handlers.handlers()[LEARNING_CONSOLIDATE_JOB]({"tenant_id": "t"})
    assert result.status == "complete"
    with pytest.raises(ValueError):
        handlers.run_learning_consolidation({"tenant_id": "t", "branch": "canary"})


def test_mcp_transport_exposes_real_learning_tools(tmp_path):
    from mnemosyne.mcp_server import MnemosyneMcpServer

    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    try:
        result = server.call_tool(
            "prepare_context",
            {"tenant_id": "t", "user_id": "u", "session_id": "s", "query": "check"},
        )
        assert result["receipt_id"]
        result = server.call_tool(
            "observe_turn",
            {
                "tenant_id": "t",
                "user_id": "u",
                "session_id": "s",
                "user_text": "check",
                "assistant_text": "done",
                "receipt_ids": [result["receipt_id"]],
            },
        )
        assert result["episode_id"]
    finally:
        server.close()


@pytest.mark.parametrize("rail", LEARNING_RAILS)
def test_every_learning_rail_is_immutable_at_load(rail):
    with pytest.raises(ValueError):
        OperatingPolicy.from_dict({"immutable_rails": {rail: False}})


@pytest.mark.parametrize(
    "value",
    [
        {"learning_trace_lambda": 1.1},
        {"learning_trace_tau_minutes": 0},
        {"learning_exploration_floor": 0},
        {"learning_exploration_floor": 0.2, "learning_exploration_rate": 0.1},
        {"learning_probation_outcomes": {"schema": 1, "standalone": 12}},
        {"learning_homeostasis_budget": 0.3},
        {"learning_contingency_min_samples": 7},
        {"learning_goal_check_comparison_rate": 0},
        {"learning_distill_mode": "automatic"},
    ],
)
def test_additional_learning_policy_floors(value):
    with pytest.raises(ValueError):
        OperatingPolicy.from_dict(value)


def test_learning_defaults_match_drift_manifest():
    import tomllib
    from pathlib import Path

    with (Path(__file__).parents[1] / "config" / "drift-baseline.toml").open(
        "rb"
    ) as stream:
        baseline = tomllib.load(stream)
    policy = OperatingPolicy()
    assert len(LEARNING_RAILS) == 24
    for key, value in baseline["learning"]["defaults"].items():
        assert getattr(policy, key) == value
