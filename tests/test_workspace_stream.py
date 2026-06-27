from __future__ import annotations

import pytest

from mnemosyne.workspace import ShadowWorkspaceController, WorkspaceItem


def test_shadow_workspace_stream_runs_bounded_default_mode_ticks() -> None:
    controller = ShadowWorkspaceController(max_workspace_items=1, max_cycles=5, max_idle_ticks=2)

    report = controller.run_shadow_stream(
        tenant_id="tenant-stream",
        item_ticks=[
            [
                WorkspaceItem(id="low", priority=0.1, content="low priority"),
                WorkspaceItem(id="focus-a", priority=0.9, content="first salient focus"),
            ],
            [
                WorkspaceItem(id="focus-b", priority=0.8, content="second salient focus"),
            ],
        ],
        evidence=[
            {
                "cid": "cid-stream-a",
                "tenant_id": "tenant-stream",
                "access_policy": {"tenant": "tenant-stream"},
                "content": "First retained source supports continuous replay.",
            },
            {
                "cid": "cid-stream-b",
                "tenant_id": "tenant-stream",
                "access_policy": {"tenant": "tenant-stream"},
                "content": "Second retained source supports stream gating.",
            },
        ],
        confidence=0.82,
        resource_health=0.94,
        error_rate=0.01,
        latency_ms=80.0,
        memory_pressure=0.25,
        rail_budget=0.96,
    )
    payload = report.to_dict()

    assert payload["shadow_only"] is True
    assert payload["critical_path"] is False
    assert payload["production_mutation"] is False
    assert payload["promotion_gate_required"] is True
    assert payload["stopped_reason"] == "anti_rumination_idle_exit"
    assert payload["idle_ticks"] == 2
    assert payload["rumination_score"] == 0.5
    assert [cycle["cycle"]["cycle_index"] for cycle in payload["cycles"]] == [1, 2, 3, 4]
    assert payload["trace"][0]["focus_id"] == "focus-a"
    assert payload["trace"][1]["previous_focus_id"] == "focus-a"
    assert payload["trace"][2]["idle_generated"] is True
    assert payload["trace"][3]["idle_generated"] is True
    assert payload["trace"][0]["content"].startswith("[shadow-trace-redacted:")
    assert "first salient focus" not in payload["trace"][0]["content"]
    assert "content" not in payload["cycles"][0]["selected_items"][0]
    assert payload["cycles"][0]["selected_items"][0]["content_ref"].startswith("[shadow-trace-redacted:")
    assert payload["cycles"][0]["selected_items"][0]["content_chars"] == len("first salient focus")
    assert "first salient focus" not in str(payload["cycles"])
    assert all(entry["reality_class"] == "self_generated" for entry in payload["trace"])
    assert all(entry["trust_tier"] == 5 for entry in payload["trace"])
    assert all(entry["data_not_instructions"] is True for entry in payload["trace"])
    assert payload["cycle_consistency"]["score"] == 1.0
    assert all(payload["cycle_consistency"]["checks"].values())
    invocations = [invocation for cycle in payload["cycles"] for invocation in cycle["specialist_invocations"]]
    assert len(invocations) == 1
    assert invocations[0]["critical_path"] is False
    assert invocations[0]["output_summary"]["candidate_count"] == 1


def test_shadow_workspace_stream_exits_on_repeated_focus_rumination() -> None:
    controller = ShadowWorkspaceController(max_workspace_items=1, max_cycles=6, max_idle_ticks=2)

    report = controller.run_shadow_stream(
        tenant_id="tenant-stream",
        item_ticks=[
            [WorkspaceItem(id="same-focus", priority=0.9, content="repeat")],
            [WorkspaceItem(id="same-focus", priority=0.9, content="repeat")],
            [WorkspaceItem(id="same-focus", priority=0.9, content="repeat")],
            [WorkspaceItem(id="should-not-run", priority=1.0, content="not reached")],
        ],
    )
    payload = report.to_dict()

    assert payload["stopped_reason"] == "anti_rumination_repeated_focus_exit"
    assert payload["idle_ticks"] == 0
    assert payload["rumination_score"] == 0.666667
    assert [entry["focus_id"] for entry in payload["trace"]] == [
        "same-focus",
        "same-focus",
        "same-focus",
    ]
    assert payload["trace"][1]["useful_state"] is False
    assert payload["trace"][2]["useful_state"] is False
    assert payload["cycle_consistency"]["score"] == 1.0
    assert all(payload["cycle_consistency"]["checks"].values())


def test_shadow_workspace_stream_rejects_cross_tenant_items() -> None:
    controller = ShadowWorkspaceController(max_workspace_items=1, max_cycles=2)

    with pytest.raises(ValueError, match="access policy"):
        controller.run_shadow_stream(
            tenant_id="tenant-stream",
            item_ticks=[
                [
                    WorkspaceItem(
                        id="foreign",
                        priority=1.0,
                        content="foreign content",
                        metadata={"access_policy": {"tenant": "other-tenant"}},
                    )
                ]
            ],
        )


@pytest.mark.parametrize(
    "item",
    [
        {
            "id": "foreign-top-level-tenant",
            "priority": 1.0,
            "tenant_id": "other-tenant",
            "content": "foreign top-level tenant content",
        },
        {
            "id": "foreign-top-level-policy",
            "priority": 1.0,
            "access_policy": {"tenant": "other-tenant"},
            "content": "foreign top-level policy content",
        },
    ],
)
def test_shadow_workspace_stream_rejects_cross_tenant_mapping_items(item: dict[str, object]) -> None:
    controller = ShadowWorkspaceController(max_workspace_items=1, max_cycles=2)

    with pytest.raises(ValueError):
        controller.run_shadow_stream(tenant_id="tenant-stream", item_ticks=[[item]])


def test_shadow_workspace_stream_caps_tick_iterables_before_materialization() -> None:
    consumed: list[int] = []

    def tick_items():
        for index in range(10):
            consumed.append(index)
            yield WorkspaceItem(id=f"item-{index}", priority=1.0 - (index / 100), content=f"item {index}")

    controller = ShadowWorkspaceController(
        max_workspace_items=1,
        max_cycles=1,
        max_items_per_tick=2,
    )

    report = controller.run_shadow_stream(tenant_id="tenant-stream", item_ticks=[tick_items()])
    payload = report.to_dict()

    assert consumed == [0, 1]
    assert payload["trace"][0]["selected_item_ids"] == ["item-0"]


def test_shadow_workspace_controller_rejects_invalid_cycle_caps() -> None:
    with pytest.raises(ValueError, match="max_cycles"):
        ShadowWorkspaceController(max_cycles=0)


def test_shadow_workspace_stream_exports_bounded_consolidation_advisory() -> None:
    controller = ShadowWorkspaceController(max_workspace_items=1, max_cycles=2)

    report = controller.run_shadow_stream(
        tenant_id="tenant-stream",
        item_ticks=[
            [
                WorkspaceItem(
                    id="focus-advisory",
                    priority=0.91,
                    content="raw workspace advisory content must stay private",
                    metadata={"cid": "cid-advisory-a", "tenant_id": "tenant-stream"},
                )
            ]
        ],
    )

    advisory = report.to_consolidation_advisory()

    assert advisory["shadow_only"] is True
    assert advisory["critical_path"] is False
    assert advisory["production_mutation"] is False
    assert advisory["advisory_only"] is True
    assert advisory["promotion_gate_required"] is True
    assert advisory["applied_to_prediction_gate"] is False
    assert advisory["applied_to_replay_priority"] is False
    assert advisory["applied_to_mutation"] is False
    assert advisory["prediction_error"]["score"] == 1.0
    assert advisory["replay_scores"]["cid-advisory-a"]["importance"] == 0.91
    assert advisory["items"][0]["workspace_item_id"] == "focus-advisory"
    assert "raw workspace advisory content" not in str(advisory)
