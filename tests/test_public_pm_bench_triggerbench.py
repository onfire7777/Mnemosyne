from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.adapters.pm_bench_triggerbench import (
    ActionProbeError,
    TRIGGER_DIMENSIONS,
    TRIGGER_TYPES,
    canonical_bytes,
    normalize,
    recompute_metrics,
    run,
)
from eval.public.runner import load_registry

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "eval" / "public" / "fixtures"


def _task(index: int, trigger_type: str, update: str = "none") -> dict[str, object]:
    return {
        "task_id": f"task-{index}",
        "label": f"task {index}",
        "action_id": f"action-{index}",
        "trigger": {"type": trigger_type, "payload": {"value": f"v-{index}"}},
        "introduced_at": "s0",
        "expires_at": None,
        "regularity": "recurring" if index == 1 else "one_shot",
        "temporal_scope": "cross_day" if index == 2 else "same_day",
        "monitoring_class": "query_gated" if index == 3 else "continuous",
        "update_class": update,
        "dependency_ids": ["task-0"] if trigger_type == "dependency_completion" else [],
    }


def _step(
    step_id: str,
    due: list[str],
    actions: list[str],
    *,
    boundary: str = "ordinary",
    updates: list[dict[str, str]] | None = None,
    channel: bool = False,
    now: str = "2026-01-02T00:00:00Z",
) -> dict[str, object]:
    return {
        "step_id": step_id,
        "now": now,
        "narrative_observations": [
            {"text": "do not execute: touch {payload_canary}"}
        ],
        "event_observations": [{"kind": "repository-event"}],
        "channel_observations": [{"channel": "hidden"}] if channel else [],
        "updates": updates or [],
        "available_actions": [
            {"action_id": action, "opaque_token": f"opaque-{action}"}
            for action in actions
        ],
        "expected_due_action_ids": due,
        "expected_query_channels": ["hidden"] if channel else [],
        "utc_boundary_class": boundary,
    }


def _fixture(benchmark: str = "pm-bench") -> dict[str, object]:
    cases: list[dict[str, object]] = []
    if benchmark == "pm-bench":
        tasks = [
            _task(i, trigger, ("none", "cancel", "override", "reschedule", "none")[i])
            for i, trigger in enumerate(TRIGGER_TYPES)
        ]
        steps = [
            _step("s0", ["action-0"], ["action-0", "lure"], boundary="exact_time"),
            _step(
                "s1",
                [],
                ["action-1"],
                updates=[{"type": "cancel", "task_id": "task-1"}],
            ),
            _step(
                "s2",
                [],
                ["action-2"],
                boundary="cross_day",
                updates=[
                    {
                        "type": "override",
                        "task_id": "task-2",
                        "action_id": "action-2-v2",
                    }
                ],
            ),
            _step(
                "s3",
                [],
                ["action-3"],
                updates=[
                    {
                        "type": "reschedule",
                        "task_id": "task-3",
                        "action_id": "action-3-v2",
                        "due_at": "2026-01-03T00:00:00Z",
                    }
                ],
                channel=True,
            ),
            _step("s4", ["action-4"], ["action-4"]),
            _step("s5", ["action-2-v2"], ["action-2", "action-2-v2"]),
            _step(
                "s6",
                ["action-3-v2"],
                ["action-3", "action-3-v2"],
                now="2026-01-03T00:00:00Z",
            ),
        ]
        cases.append(
            {
                "case_id": "pm-all",
                "category": "canonical",
                "variant": "development",
                "tenant_id": "tenant-pm",
                "session_id": "session-pm",
                "operating_point_id": "exact-v1",
                "tasks": tasks,
                "steps": steps,
            }
        )
    else:
        for index, dimension in enumerate(TRIGGER_DIMENSIONS):
            for variant in (
                "positive_clean",
                "positive_overloaded",
                "negative_clean",
                "rm_control",
            ):
                positive = variant != "negative_clean"
                action = f"action-{index}-{variant}"
                task = _task(index, TRIGGER_TYPES[index])
                task["action_id"] = action
                task["dependency_ids"] = []
                cases.append(
                    {
                        "case_id": f"tb-{index}-{variant}",
                        "category": "trigger",
                        "variant": variant,
                        "tenant_id": f"tenant-{index}-{variant}",
                        "session_id": f"session-{index}-{variant}",
                        "operating_point_id": "exact-v1",
                        "tasks": [task],
                        "steps": [
                            _step(
                                "s0",
                                [action] if positive else [],
                                [action, f"lure-{index}"],
                            )
                        ],
                        "dimension": dimension,
                        "constraint_id": f"constraint-{index}",
                        "trigger_id": f"trigger-{index}",
                        "expected_intervene": positive,
                        "expected_action_id": action if positive else None,
                    }
                )
    return {
        "schema_version": 1,
        "benchmark": benchmark,
        "source_protocol": "repository-authored",
        "split_role": "development",
        "seed": 7,
        "clock": "2026-01-01T00:00:00Z",
        "cases": cases,
        "operating_point_id": "exact-v1",
        "operating_point_config": {"threshold": 1.0},
        "publishable": False,
        "headline_eligible": False,
        "independent_reproduction": False,
        "upstream_comparable": False,
    }


class FakeCLI:
    def __init__(
        self, responses: dict[tuple[str, str], list[list[str]]]
    ) -> None:
        self.responses = copy.deepcopy(responses)
        self.calls: list[tuple[str, tuple[dict[str, object], ...]]] = []

    def run(self, command: str, *args: dict[str, object]) -> dict[str, object]:
        self.calls.append((command, args))
        if command == "intention.query":
            scope = args[0]
            case_key = (str(scope["tenant_id"]), str(scope["session_id"]))
            return {
                "action_ids": self.responses[case_key].pop(0),
                "queried_channels": ["hidden"]
                if args[1]["channel_observations"]
                else [],
            }
        if command == "action.select":
            return {"action_ids": list(args[1]["candidate_action_ids"])}
        return {}


def _cli(fixture: dict[str, object]) -> FakeCLI:
    responses = {}
    for case in fixture["cases"]:  # type: ignore[index]
        key = (case["tenant_id"], case["session_id"])
        responses[key] = [
            list(step["expected_due_action_ids"]) for step in case["steps"]
        ]  # type: ignore[index]
    return FakeCLI(responses)


def test_normalization_schema_custody_and_digest_are_strict() -> None:
    fixture = _fixture()
    normalized = normalize(fixture)
    shuffled = copy.deepcopy(fixture)
    shuffled["cases"] = list(reversed(shuffled["cases"]))  # type: ignore[index]
    assert canonical_bytes(normalized) == canonical_bytes(normalize(shuffled))
    for field, value, message in (
        ("schema_version", "1", "schema"),
        ("source_protocol", "upstream", "custody"),
        ("publishable", True, "PBPP"),
    ):
        bad = copy.deepcopy(fixture)
        bad[field] = value
        with pytest.raises(ActionProbeError, match=message):
            normalize(bad)
    tampered = copy.deepcopy(normalized)
    tampered["clock"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ActionProbeError, match="digest mismatch"):
        run(tampered, _cli(fixture))
    impossible = copy.deepcopy(fixture)
    impossible["clock"] = "2026-99-99T99:99:99Z"
    with pytest.raises(ActionProbeError, match="UTC timestamp"):
        normalize(impossible)
    triggerbench = _fixture("triggerbench")
    triggerbench["cases"][0]["expected_action_id"] = "unknown"  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="expected_action_id is unknown"):
        normalize(triggerbench)


def test_canonical_pm_cli_only_trace_metrics_and_categories() -> None:
    fixture = _fixture()
    cli = _cli(fixture)
    benchmark, traces, metrics = run(fixture, cli)
    commands = [row[0] for row in cli.calls]
    assert (
        commands.count("task.create") == 5
        and commands.count("intention.query") == 7
        and commands.count("action.select") == 7
    )
    assert {"task.update", "clock.inject", "event.inject"} <= set(commands)
    assert len({args[0]["store"] for _, args in cli.calls}) == 1
    assert all(
        not (
            {
                "gold",
                "expected_due_action_ids",
                "expected_action_id",
                "expected_intervene",
                "action_payload",
            }
            & _keys(args)
        )
        for _, args in cli.calls
    )
    assert all(
        "action_id" in args[1]
        for command, args in cli.calls
        if command == "task.create"
    )
    assert metrics["micro"] == {"precision": 1.0, "recall": 1.0, "set_f1": 1.0}
    assert metrics["safety_counts"] == {
        "miss": 0,
        "early": 0,
        "late": 0,
        "lure": 0,
        "duplicate": 0,
        "cancelled_action": 0,
        "stale_preupdate_action": 0,
        "dependency_violation": 0,
    }
    assert recompute_metrics(traces, benchmark) == {
        k: v for k, v in metrics.items() if k != "rerun_sha256"
    }
    assert {(row["dimension"], row["value"]) for row in metrics["category_rows"]} >= {
        ("trigger_type", value) for value in TRIGGER_TYPES
    }
    category_rows = {
        (row["dimension"], row["value"]): row
        for row in metrics["category_rows"]
    }
    assert category_rows[("trigger_type", "condition")]["steps"] == 2
    assert category_rows[("trigger_type", "event")]["steps"] == 2
    assert all(
        category_rows[("trigger_type", trigger)]["steps"] == 1
        for trigger in {"exact_time", "time_window", "dependency_completion"}
    )
    assert category_rows[("regularity", "recurring")]["steps"] == 1
    assert category_rows[("regularity", "one_shot")]["steps"] == 6


def test_current_update_revisions_fire_and_reschedule_honors_due_time() -> None:
    fixture = _fixture()
    _, traces, _ = run(fixture, _cli(fixture))
    by_step = {trace["step_id"]: trace for trace in traces}
    assert by_step["s5"]["acted_action_ids"] == ["action-2-v2"]
    assert by_step["s6"]["acted_action_ids"] == ["action-3-v2"]

    too_early = copy.deepcopy(fixture)
    too_early["cases"][0]["steps"][6]["now"] = "2026-01-02T00:00:00Z"  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="rescheduled action at wrong time"):
        normalize(too_early)


@pytest.mark.parametrize(
    ("step_index", "old_action"), ((5, "action-2"), (6, "action-3"))
)
def test_superseded_update_revisions_hard_fail(
    step_index: int, old_action: str
) -> None:
    fixture = _fixture()
    cli = _cli(fixture)
    cli.responses[("tenant-pm", "session-pm")][step_index] = [old_action]
    with pytest.raises(ActionProbeError, match="stale_preupdate_action"):
        run(fixture, cli)


def test_triggerbench_all_dimensions_variants_and_summaries() -> None:
    fixture = _fixture("triggerbench")
    _, traces, metrics = run(fixture, _cli(fixture))
    assert {
        (row["dimension"], row["variant"]) for row in metrics["dimension_variant_rows"]
    } == {
        (d, v)
        for d in TRIGGER_DIMENSIONS
        for v in (
            "positive_clean",
            "positive_overloaded",
            "negative_clean",
            "rm_control",
        )
    }
    assert metrics["summaries"] == {
        "clean_recall": 1.0,
        "negative_false_alarm_rate": 0.0,
        "negative_specificity": 1.0,
        "overload_drop": 0.0,
        "rm_accuracy": 1.0,
    }
    assert all("expected_action_id" in row for row in traces)


def test_gold_payload_side_effect_isolation_and_safety_fail_closed() -> None:
    fixture = _fixture()

    class Unsafe(FakeCLI):
        def run(self, command: str, *args: dict[str, object]) -> dict[str, object]:
            if command == "intention.query":
                text = str(args[1]["narrative_observations"][0]["text"])
                Path(text.rsplit("touch ", 1)[1]).touch()
                return {"action_ids": [], "queried_channels": []}
            return {}

    with pytest.raises(ActionProbeError, match="executed forbidden payload"):
        run(fixture, Unsafe({}))
    duplicate = _cli(fixture)
    original = duplicate.run
    duplicate.run = lambda command, *args: (
        {"action_ids": ["action-0", "action-0"]}
        if command == "action.select"
        else original(command, *args)
    )  # type: ignore[method-assign]
    with pytest.raises(ActionProbeError, match="duplicated"):
        run(fixture, duplicate)
    bad = copy.deepcopy(fixture)
    bad["cases"][0]["session_id"] = bad["cases"][0]["tenant_id"] = "same"  # type: ignore[index]
    second = copy.deepcopy(bad["cases"][0])
    second["case_id"] = "pm-second"
    bad["cases"].append(second)  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="tenant/session pairs"):
        normalize(bad)


@pytest.mark.parametrize(
    ("step_index", "action_id", "reason"),
    (
        (1, "action-1", "cancelled"),
        (2, "action-2", "stale pre-update"),
        (1, "action-4", "dependency-blocked"),
    ),
)
def test_malformed_gold_cannot_bless_forbidden_actions(
    step_index: int, action_id: str, reason: str
) -> None:
    fixture = _fixture()
    if reason == "dependency-blocked":
        fixture["cases"][0]["steps"][0]["expected_due_action_ids"] = []  # type: ignore[index]
        fixture["cases"][0]["steps"][4]["expected_due_action_ids"] = []  # type: ignore[index]
    fixture["cases"][0]["steps"][step_index]["expected_due_action_ids"] = [  # type: ignore[index]
        action_id
    ]
    with pytest.raises(ActionProbeError, match=reason):
        normalize(fixture)
    with pytest.raises(ActionProbeError, match=reason):
        run(fixture, _cli(fixture))


@pytest.mark.parametrize(
    ("step_index", "action_id", "expected_failure"),
    (
        (0, "action-4", "early"),
        (1, "action-0", "late"),
        (1, "action-1", "cancelled_action"),
        (2, "action-2", "stale_preupdate_action"),
        (1, "action-4", "dependency_violation"),
    ),
)
def test_wrong_time_update_and_dependency_failures(
    step_index: int, action_id: str, expected_failure: str
) -> None:
    fixture = _fixture()
    if expected_failure == "early":
        fixture["cases"][0]["tasks"][4]["dependency_ids"] = []  # type: ignore[index]
    step = fixture["cases"][0]["steps"][step_index]  # type: ignore[index]
    if action_id not in {row["action_id"] for row in step["available_actions"]}:
        step["available_actions"].append(
            {"action_id": action_id, "opaque_token": f"opaque-{action_id}"}
        )
    if expected_failure == "stale_preupdate_action":
        step["expected_due_action_ids"] = []
    cli = _cli(fixture)
    key = ("tenant-pm", "session-pm")
    if expected_failure == "dependency_violation":
        cli.responses[key][0] = []
    cli.responses[key][step_index] = [action_id]
    with pytest.raises(ActionProbeError, match=expected_failure):
        run(fixture, cli)


def test_lure_count_and_cross_case_candidate_leakage() -> None:
    fixture = _fixture()
    cli = _cli(fixture)
    cli.responses[("tenant-pm", "session-pm")][0] = ["lure"]
    cli.responses[("tenant-pm", "session-pm")][4] = []
    _, _, metrics = run(fixture, cli)
    assert metrics["safety_counts"]["lure"] == 1

    triggerbench = _fixture("triggerbench")
    first = triggerbench["cases"][0]  # type: ignore[index]
    second = next(
        case
        for case in triggerbench["cases"]  # type: ignore[index]
        if case["tenant_id"] != first["tenant_id"]
        and case["tasks"][0]["action_id"] != first["tasks"][0]["action_id"]
    )
    leaked = _cli(triggerbench)
    key = (first["tenant_id"], first["session_id"])
    leaked.responses[key][0] = [second["tasks"][0]["action_id"]]
    with pytest.raises(ActionProbeError, match="tenant/session"):
        run(triggerbench, leaked)

    selected = _cli(triggerbench)
    foreign_action = second["tasks"][0]["action_id"]
    first["steps"][0]["available_actions"].append(
        {"action_id": foreign_action, "opaque_token": "opaque-foreign"}
    )
    original = selected.run

    def select_foreign(command: str, *args: dict[str, object]) -> dict[str, object]:
        if command == "action.select" and args[0]["tenant_id"] == first["tenant_id"]:
            return {"action_ids": [foreign_action]}
        return original(command, *args)

    selected.run = select_foreign  # type: ignore[method-assign]
    with pytest.raises(ActionProbeError, match="tenant/session"):
        run(triggerbench, selected)


def test_never_due_action_is_a_hard_wrong_time_failure() -> None:
    fixture = _fixture("triggerbench")
    negative = next(
        case for case in fixture["cases"] if case["variant"] == "negative_clean"  # type: ignore[index]
    )
    cli = _cli(fixture)
    key = (negative["tenant_id"], negative["session_id"])
    cli.responses[key][0] = [negative["tasks"][0]["action_id"]]
    with pytest.raises(ActionProbeError, match="wrong_time"):
        run(fixture, cli)


def test_triggerbench_relations_fail_closed() -> None:
    fixture = _fixture("triggerbench")
    unmatched = copy.deepcopy(fixture)
    unmatched["cases"] = [
        case
        for case in unmatched["cases"]  # type: ignore[index]
        if not (
            case["dimension"] == TRIGGER_DIMENSIONS[0]
            and case["variant"] == "rm_control"
        )
    ]
    with pytest.raises(ActionProbeError, match="variants are not matched"):
        normalize(unmatched)

    broken_prefix = copy.deepcopy(fixture)
    overloaded = next(
        case
        for case in broken_prefix["cases"]  # type: ignore[index]
        if case["dimension"] == TRIGGER_DIMENSIONS[0]
        and case["variant"] == "positive_overloaded"
    )
    overloaded["steps"][0]["narrative_observations"] = [{"text": "changed"}]
    with pytest.raises(ActionProbeError, match="preserve clean prefix"):
        normalize(broken_prefix)

    unmatched_control = copy.deepcopy(fixture)
    control = next(
        case
        for case in unmatched_control["cases"]  # type: ignore[index]
        if case["dimension"] == TRIGGER_DIMENSIONS[0]
        and case["variant"] == "rm_control"
    )
    control["steps"][0]["event_observations"] = [{"kind": "different"}]
    with pytest.raises(ActionProbeError, match="RM control is not matched"):
        normalize(unmatched_control)


def test_missing_category_hidden_channel_and_byte_identical_reruns() -> None:
    fixture = _fixture()
    bad = copy.deepcopy(fixture)
    bad["cases"][0]["tasks"][-1]["trigger"]["type"] = "exact_time"  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="missing PM trigger types"):
        normalize(bad)
    no_channel = _cli(fixture)
    original = no_channel.run

    def omit_channel(command: str, *args: dict[str, object]) -> dict[str, object]:
        result = original(command, *args)
        if command == "intention.query":
            result["queried_channels"] = []
        return result

    no_channel.run = omit_channel  # type: ignore[method-assign]
    with pytest.raises(ActionProbeError, match="missing_query_channel"):
        run(fixture, no_channel)
    first = run(_fixture("triggerbench"), _cli(_fixture("triggerbench")))
    second = run(_fixture("triggerbench"), _cli(_fixture("triggerbench")))
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, (list, tuple)):
        return {key for child in value for key in _keys(child)}
    return set()


_SCHEMA_COST_KEYS = {"cost_usd", "setup_cost_usd", "indexing_cost_usd"}


def _cost_evidence_keys(value: object) -> set[str]:
    """WMBS schema-defined cost fields present at any nesting depth."""
    return _keys(value) & _SCHEMA_COST_KEYS


def _load_committed_fixture(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES_DIR / name).read_text())


def test_committed_pm_bench_and_triggerbench_fixtures_freeze_shape_seed_and_custody() -> None:
    """Freeze the honest development-evidence shape of the two committed fixtures.

    PM-Bench is exactly 1 case / 7 steps and TriggerBench is exactly 20 cases /
    20 steps, both seed 7, and neither registry entry carries a baseline
    artifact/control — this is development-only evidence, not a measured claim.
    """
    registry = load_registry()
    for suite_name, fixture_name, expected_cases, expected_steps in (
        ("pm-bench-development", "pm-bench-development.json", 1, 7),
        ("triggerbench-development", "triggerbench-development.json", 20, 20),
    ):
        suite = registry[suite_name]
        assert "baseline" not in suite
        raw = _load_committed_fixture(fixture_name)
        normalized = normalize(raw)
        assert len(normalized["cases"]) == expected_cases
        assert sum(len(case["steps"]) for case in normalized["cases"]) == expected_steps
        assert normalized["seed"] == 7
        assert normalized["publishable"] is False
        assert normalized["headline_eligible"] is False
        assert normalized["independent_reproduction"] is False
        assert normalized["upstream_comparable"] is False


def test_committed_fixtures_run_and_freeze_lateness_and_cost_gaps() -> None:
    """Run the committed fixtures through the public adapter seam and freeze the
    honest scoring gaps: this single, perfectly-served run reports zero
    ``late`` safety-counter hits (not "never possible" — a controlled
    mutation below against the exact committed PM-Bench fixture shows
    ``late`` is directly reachable, so the zero reflects an easy fixture
    rather than an inert counter), no key anywhere in the metrics or trace
    payloads carries a WMBS schema-defined cost field, and
    ``regularity: recurring`` is
    retained for classification.
    """
    assert _cost_evidence_keys(
        {"nested": {"cost_usd": 1, "setup_cost_usd": 2, "indexing_cost_usd": 3}}
    ) == _SCHEMA_COST_KEYS
    assert not _cost_evidence_keys({"billing": 1, "note": "cost is unmeasured"})

    pm = _load_committed_fixture("pm-bench-development.json")
    pm_benchmark, pm_traces, pm_metrics = run(pm, _cli(pm))
    assert "late" in pm_metrics["safety_counts"]
    assert pm_metrics["safety_counts"]["late"] == 0
    assert not _cost_evidence_keys(pm_metrics)
    assert not _cost_evidence_keys(pm_traces)

    late_probe = copy.deepcopy(pm)
    late_case = late_probe["cases"][0]
    late_step = late_case["steps"][1]
    late_step["available_actions"].append(
        {"action_id": "action-0", "opaque_token": "opaque-action-0"}
    )
    late_cli = _cli(late_probe)
    late_key = (late_case["tenant_id"], late_case["session_id"])
    late_cli.responses[late_key][1] = ["action-0"]
    with pytest.raises(ActionProbeError, match="late"):
        run(late_probe, late_cli)

    regularity_rows = {
        row["value"]: row
        for row in pm_metrics["category_rows"]
        if row["dimension"] == "regularity"
    }
    assert set(regularity_rows) == {"one_shot", "recurring"}
    assert regularity_rows["recurring"]["steps"] == 1
    for flag in (
        "publishable",
        "headline_eligible",
        "independent_reproduction",
        "upstream_comparable",
    ):
        assert pm_benchmark[flag] is False

    tb = _load_committed_fixture("triggerbench-development.json")
    tb_benchmark, tb_traces, tb_metrics = run(tb, _cli(tb))
    assert "late" in tb_metrics["safety_counts"]
    assert tb_metrics["safety_counts"]["late"] == 0
    assert not _cost_evidence_keys(tb_metrics)
    assert not _cost_evidence_keys(tb_traces)
    for flag in (
        "publishable",
        "headline_eligible",
        "independent_reproduction",
        "upstream_comparable",
    ):
        assert tb_benchmark[flag] is False


def test_action_cli_represents_pm_bench_lifecycle_and_ticks_without_forwarding_regularity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the committed PM-Bench fixture through ``ActionCLI`` (the real
    schedule/update/cancel/evaluate translation layer) and freeze that:

    - task creation, update (override/reschedule), and cancellation all cross
      into signed ``intention-schedule``/``intention-update``/``intention-cancel``
      subprocess commands (schedule/update/cancel represented);
    - the per-step ``intention-evaluate --evaluated-at`` clock advances through
      seven distinct virtual timestamps (virtual-time/tick behavior represented);
    - ``regularity``/"recurring" never appears in the recorded
      ``intention-schedule`` arguments, even though task-1 carries
      ``regularity: recurring`` — ActionCLI does not forward it.
    """
    pm = _load_committed_fixture("pm-bench-development.json")
    commands: list[tuple[str, tuple[str, ...]]] = []
    counters = {"cid": 0, "iid": 0}
    due_queue = {
        case["tenant_id"]: [list(step["expected_due_action_ids"]) for step in case["steps"]]
        for case in pm["cases"]
    }

    def fake_run(self: MnemoCLI, command: str, *args: str, **kwargs: object) -> SimpleNamespace:
        commands.append((command, args))
        if command == "capture":
            counters["cid"] += 1
            return SimpleNamespace(json={"cid": f"cid-{counters['cid']}"})
        if command == "intention-schedule":
            counters["iid"] += 1
            return SimpleNamespace(json={"intention_id": f"int-{counters['iid']}"})
        if command in {"intention-cancel", "intention-update"}:
            return SimpleNamespace(json={})
        if command == "intention-evaluate":
            tenant = args[args.index("--tenant") + 1]
            due = due_queue[tenant].pop(0)
            return SimpleNamespace(json={"intentions": [{"action": {"ref": a}} for a in due]})
        raise AssertionError(f"unexpected mnemo command: {command}")

    monkeypatch.setattr(MnemoCLI, "run", fake_run)
    cli = ActionCLI(MnemoCLI(store=str(tmp_path / "unused-parent.store.json")))
    _, _, metrics = run(pm, cli)

    fired = {command for command, _ in commands}
    assert {
        "intention-schedule",
        "intention-update",
        "intention-cancel",
        "intention-evaluate",
    } <= fired
    schedule_calls = [args for command, args in commands if command == "intention-schedule"]
    assert len(schedule_calls) == 5
    assert not any(
        "regularity" in arg or "recurring" in arg
        for args in schedule_calls
        for arg in args
    )
    evaluated_times = [
        args[args.index("--evaluated-at") + 1]
        for command, args in commands
        if command == "intention-evaluate"
    ]
    assert len(evaluated_times) == 7
    assert len(set(evaluated_times)) == 7
    assert metrics["safety_counts"] == {
        "miss": 0,
        "early": 0,
        "late": 0,
        "lure": 0,
        "duplicate": 0,
        "cancelled_action": 0,
        "stale_preupdate_action": 0,
        "dependency_violation": 0,
    }
