"""Calibration monitors require forecasts recorded before the observed outcome."""

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.guards import LearningGuardError
from mnemosyne.experience.monitors import diagnostics
from mnemosyne.experience.runtime import LearningRuntime


def _successful_turn(runtime, session, receipt=None):
    observed = runtime.observe_turn(
        "calibration", "alice", session, "Calculate 2 plus 2", "",
        tool_events=[{
            "name": "calculator", "source": "tool", "status": "ok",
            "verdict": True, "output": "4",
        }],
        receipt_ids=[receipt["receipt_id"]] if receipt else [],
    )
    runtime.resolve("calibration", observed["episode_id"])


@pytest.fixture
def forecast_batch():
    runtime = LearningRuntime(LocalMemoryEngine())
    # Every prediction is captured before any of this batch's outcomes arrives.
    contexts = [runtime.prepare_context(
        "calibration", "alice", f"forecast-{index}", "Calculate 2 plus 2",
        available_tools=["calculator"], task_type="batch-calibration",
    ) for index in range(100)]
    assert {context["prediction"] for context in contexts} == {0.5}
    for index, context in enumerate(contexts):
        _successful_turn(runtime, f"forecast-{index}", context)
    return runtime


def test_unforecasted_successes_do_not_freeze_learning_as_miscalibration():
    runtime = LearningRuntime(LocalMemoryEngine())
    for index in range(100):
        _successful_turn(runtime, f"unforecasted-{index}")
    state = runtime.writer.read("calibration")
    assert not state["receipts"]
    assert {row["prediction"] for row in state["episodes"].values()} == {0.5}
    failures = diagnostics(
        state, source_lookup=lambda cid: runtime.engine.get_evidence("calibration", cid)
    )
    assert not any(failure["class"] == "X5" for failure in failures)
    runtime.consolidate("calibration")
    state = runtime.writer.read("calibration")
    assert not state["defects"]
    assert not state["policy"].get("frozen", False)


def test_genuine_batch_forecasts_still_trigger_calibration_guard(forecast_batch):
    state = forecast_batch.writer.read("calibration")
    failures = diagnostics(
        state,
        source_lookup=lambda cid: forecast_batch.engine.get_evidence("calibration", cid),
    )
    assert any(failure["class"] == "X5" for failure in failures)
    with pytest.raises(LearningGuardError, match="X5"):
        forecast_batch.consolidate("calibration")
    assert forecast_batch.writer.read("calibration")["policy"]["frozen"]


def test_legacy_forecasts_remain_calibration_evidence(forecast_batch):
    state = forecast_batch.writer.read("calibration")
    for receipt in state["receipts"].values():
        receipt.pop("raw_prediction", None)
    failures = diagnostics(state)
    assert any(failure["class"] == "X5" for failure in failures)


@pytest.mark.parametrize("ownership", ["missing", "tenant_id", "user_id", "session_id"])
def test_invalid_receipts_do_not_supply_calibration_evidence(forecast_batch, ownership):
    state = forecast_batch.writer.read("calibration")
    if ownership == "missing":
        state["receipts"].clear()
    else:
        for receipt in state["receipts"].values():
            receipt[ownership] = "different-owner"
    failures = diagnostics(state)
    assert {failure["class"] for failure in failures} == {"X3"}
