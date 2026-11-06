"""Old and new entry points share configured learning capabilities."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.candidates import parametric_export
from mnemosyne.experience.integration import build_learning_runtime
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.frameworks import AutoMemorySession
from mnemosyne.gate import RegressionCase
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.learning import Procedure
from mnemosyne.parametric import ParametricTier
from mnemosyne.skills import SkillStore


def protected(name):
    return RegressionCase(name, "signature", "question", "answer", protected=True)


def test_worker_created_before_host_uses_current_explicit_dependencies():
    engine = LocalMemoryEngine()
    worker = ConsolidationWorker(engine, [protected("old")])
    lesson, procedure = object(), object()
    case = protected("current")
    tools = MemoryTools(engine, lesson_distiller=lesson, procedure_inducer=procedure,
                        protected_cases=[case])
    runtime = worker._learning_runtime()
    assert runtime.lesson_distiller is lesson
    assert runtime.procedure_inducer is procedure
    assert runtime.protected_cases == [case]
    assert worker.lesson_distiller is lesson
    assert worker.procedure_inducer is procedure
    assert tools._learning_runtime().lesson_distiller is lesson


def test_old_tools_do_not_restore_superseded_configuration():
    engine = LocalMemoryEngine()
    old = MemoryTools(engine, lesson_distiller=object(), protected_cases=[protected("old")])
    current = object()
    new = MemoryTools(engine, lesson_distiller=current, protected_cases=[])
    assert old._learning_runtime().lesson_distiller is current
    assert old._learning_runtime().protected_cases == []
    assert new._learning_runtime().lesson_distiller is current


def test_existing_sdk_runtime_observes_explicit_configuration_changes(tmp_path):
    engine = LocalMemoryEngine()
    session = AutoMemorySession(engine, "t", "u")
    runtime = session.learning_runtime
    lesson, procedure = object(), object()
    library = SkillStore(str(tmp_path / "skills.sqlite"))
    case = protected("current")
    tools = MemoryTools(engine, lesson_distiller=lesson, procedure_inducer=procedure,
                        skill_store=library, protected_cases=[case])
    assert runtime is session.learning_runtime
    assert runtime.lesson_distiller is lesson
    assert runtime.procedure_inducer is procedure
    assert runtime.skill_store is library
    assert runtime.protected_cases == [case]
    assert build_learning_runtime(engine).skill_store is library
    assert tools._learning_runtime().protected_cases == [case]


def export_runtime(*, admitted=True, count=200):
    artifact = dict(
        id="proven", tenant_id="t", user_id="u", kind="procedure",
        state="active", content="validate\nupload", revision=3,
        task_class="deploy", goal="deploy", scope="deploy", origin="learned",
        source_episode_ids=["original"], source_cids=["source"],
        gate_passed=admitted, gate_evidence={"passed": admitted, "protected_ids": ["guard"]},
        source_quotes=[{"episode_id": "original", "cid": "source", "quote": "validate"}],
        conditions=["release approved"],
    )
    state = {"artifacts": {"proven": artifact}, "episodes": {}, "receipts": {}, "credit": {}}
    for index in range(count):
        key = str(index)
        state["episodes"][key] = {"id": key, "status": "resolved", "reward": 1,
                                   "signals": [{"kind": "verifier", "value": 1}], "receipt_ids": [key]}
        state["receipts"][key] = {"items": [{"item_id": "proven", "revision": 3}]}
        state["credit"][key] = {"episode_id": key, "target_id": "proven", "revision": 3}
    return SimpleNamespace(writer=SimpleNamespace(read=lambda tenant: deepcopy(state)),
                           _sources_live=lambda *args: True, protected_cases=[protected("guard")])


def test_training_export_preserves_canonical_admission_and_provenance():
    runtime = export_runtime()
    before = runtime.writer.read("t")
    result = parametric_export(runtime, "t")
    assert result["artifact"]["source_ids"] == ["proven"]
    assert len(result["procedures"]) == 1
    assert result["procedures"][0]["n_trials"] == 200
    assert result["procedures"][0]["source_cids"] == ["source"]
    record = result["procedure_records"][0]
    assert record["id"] == result["procedures"][0]["id"]
    assert record["revision"] == 3
    assert record["user_id"] == "u"
    assert record["gate_passed"] is True
    assert record["gate_evidence"] == before["artifacts"]["proven"]["gate_evidence"]
    assert record["source_quotes"] == before["artifacts"]["proven"]["source_quotes"]
    assert len(record["parametric_verified_episode_ids"]) == 200
    restored = Procedure.from_record(record)
    assert restored.to_record() == record
    assert restored.to_dict() == result["procedures"][0]
    assert ParametricTier._eligible_source(restored, "t", {"active"})
    assert result["artifact"]["status"] == "shadow"
    assert result["training_started"] is False
    assert runtime.writer.read("t") == before


@pytest.mark.parametrize("admitted,count", [(False, 200), (True, 199)])
def test_training_export_does_not_replace_admission_with_raw_success_count(admitted, count):
    result = parametric_export(export_runtime(admitted=admitted, count=count), "t")
    assert result["artifact"]["source_ids"] == []
    assert result["procedures"] == []
    assert result["procedure_records"] == []


def test_existing_parametric_entry_point_discovers_new_native_learning():
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    runtime = LearningRuntime(engine)
    context = runtime.prepare_context("t", "u", "s", "Deploy inventory", task_type="deploy")
    observed = runtime.observe_turn(
        "t", "u", "s", "Deploy inventory", "ran upload",
        receipt_ids=[context["receipt_id"]], tool_events=[{
            "name": "benchmark_verifier", "success": False,
            "expected_steps": ["validate", "upload"], "output": "validate then upload"}],
    )
    runtime.record_signal("t", episode_id=observed["episode_id"], kind="verifier", value=-1, final=True)
    runtime.consolidate("t")
    key = next(iter(runtime.writer.read("t")["artifacts"]))
    # Admission is real; activation itself has separate outcome/control tests.
    engine._learning_data["t"]["artifacts"][key]["state"] = "active"
    before = runtime.writer.read("t")
    assert not tools.learning.procedures
    result = tools.parametric_propose("t", role="operator", source_trust_tier=0)
    assert result["source_ids"] == [key]
    assert result["status"] == "shadow"
    assert runtime.writer.read("t") == before
