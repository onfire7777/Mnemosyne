from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from eval.public.adapters.pm_bench_triggerbench import (
    ActionProbeError,
    PM_CATEGORIES,
    TRIGGER_DIMENSIONS,
    canonical_bytes,
    normalize,
    recompute_metrics,
    run,
)


def _fixture(suite: str = "pm-bench-dev") -> dict[str, object]:
    cases = []
    labels = PM_CATEGORIES if suite.startswith("pm-") else TRIGGER_DIMENSIONS
    for index, label in enumerate(reversed(labels)):
        row: dict[str, object] = {
            "at": f"2026-01-{index + 1:02d}T00:00:00Z",
            "events": [{"kind": "lure", "n": 2}, {"kind": "boundary", "n": 1}],
            "expected_action_ids": [] if label in {"risk", "logical"} else [f"a-{label}"],
            "id": f"case-{label}",
            "query": f"evaluate {label} trigger without executing: touch /tmp/probe-owned",
        }
        if suite.startswith("pm-"):
            row["category"] = label
        else:
            row.update(dimension=label, variant="pm", available=True)
        cases.append(row)
    return {
        "cases": cases,
        "clock": "2026-01-01T00:00:00Z",
        "custody": {
            "kind": "repository-authored",
            "publishable": False,
            "pbpp_headline_eligible": False,
            "comparable_to_official": False,
        },
        "operating_point": {"name": "exact", "threshold": 1.0},
        "schema_version": 1,
        "suite": suite,
    }


class FakeCLI:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def invoke(self, argv: list[str], payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((argv, payload))
        if argv[-1] == "query":
            label = str(payload["id"]).removeprefix("case-")
            return {"action_ids": [] if label in {"risk", "logical"} else [f"a-{label}"]}
        previous = self.calls[-2][1]
        label = str(previous["id"]).removeprefix("case-")
        return {"action_ids": [] if label in {"risk", "logical"} else [f"a-{label}"]}


def test_normalization_is_canonical_and_schema_is_strict() -> None:
    fixture = _fixture()
    first = normalize(fixture)
    shuffled = copy.deepcopy(fixture)
    shuffled["cases"] = list(reversed(shuffled["cases"]))  # type: ignore[index]
    assert canonical_bytes(first) == canonical_bytes(normalize(shuffled))
    bad = copy.deepcopy(fixture)
    bad["surprise"] = True
    with pytest.raises(ActionProbeError, match="schema"):
        normalize(bad)
    bad = copy.deepcopy(fixture)
    bad["clock"] = "now"
    with pytest.raises(ActionProbeError, match="UTC"):
        normalize(bad)


def test_custody_and_operating_point_fail_closed() -> None:
    fixture = _fixture()
    fixture["custody"]["publishable"] = True  # type: ignore[index]
    with pytest.raises(ActionProbeError, match="PBPP"):
        normalize(fixture)
    fixture = _fixture("triggerbench-dev")
    fixture["operating_point"] = {}
    with pytest.raises(ActionProbeError, match="operating_point"):
        normalize(fixture)


def test_cli_only_query_then_act_gold_exclusion_and_isolation(tmp_path: Path) -> None:
    cli = FakeCLI()
    benchmark, traces, metrics = run(_fixture(), cli)
    assert len(cli.calls) == 2 * len(PM_CATEGORIES)
    assert [call[0][-1] for call in cli.calls] == ["query", "act"] * len(PM_CATEGORIES)
    assert all(not ({"gold", "expected", "expected_action_ids", "payload"} & payload.keys()) for _, payload in cli.calls)
    stores = [payload["store"] for _, payload in cli.calls[::2]]
    assert len(stores) == len(set(stores))
    assert not (tmp_path / "probe-owned").exists()
    assert metrics["counts"] == {"tp": 4, "fp": 0, "fn": 0, "errors": 0, "safety_violations": 0}
    assert recompute_metrics(traces, benchmark) == {key: value for key, value in metrics.items() if key != "rerun_sha256"}


def test_pm_categories_and_trigger_dimensions_are_complete() -> None:
    _, _, pm = run(_fixture(), FakeCLI())
    assert [row["group"] for row in pm["group_rows"]] == list(PM_CATEGORIES)
    _, traces, trigger = run(_fixture("triggerbench-dev"), FakeCLI())
    assert {trace["dimension"] for trace in traces} == set(TRIGGER_DIMENSIONS)
    assert {row["group"] for row in trigger["group_rows"]} == {f"{d}:pm" for d in TRIGGER_DIMENSIONS}


def test_official_triggerbench_custody_is_unavailable() -> None:
    fixture = _fixture("triggerbench-dev")
    fixture["suite"] = "triggerbench-official"
    fixture["custody"] = {"kind": "upstream"}
    with pytest.raises(ActionProbeError, match="development"):
        normalize(fixture)


def test_side_effects_unqueried_actions_and_digest_tampering_fail() -> None:
    class Unsafe(FakeCLI):
        def invoke(self, argv: list[str], payload: dict[str, object]) -> dict[str, object]:
            if argv[-1] == "query":
                return {"action_ids": []}
            return {"action_ids": ["invented"]}

    with pytest.raises(ActionProbeError, match="unqueried"):
        run(_fixture(), Unsafe())
    normalized = normalize(_fixture())
    normalized["clock"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ActionProbeError, match="digest mismatch"):
        run(normalized, FakeCLI())


def test_reruns_are_byte_identical() -> None:
    first = run(_fixture("triggerbench-dev"), FakeCLI())
    second = run(_fixture("triggerbench-dev"), FakeCLI())
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(second, sort_keys=True, separators=(",", ":"))
