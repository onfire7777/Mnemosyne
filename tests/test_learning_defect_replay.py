import pytest
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.guards import LearningGuardError
from mnemosyne.experience.defects import replay


def test_exported_guard_failure_is_replayable_and_required_to_resume():
    runtime = LearningRuntime(LocalMemoryEngine())
    with pytest.raises(LearningGuardError):
        runtime.writer.apply(
            "t", "injected", lambda state: state["policy"].update(authority=1)
        )
    defect = runtime.defects("t")[0]
    bundle = runtime.defect_export("t", defect["id"])
    assert replay(bundle) == {"passed": True, "detected_class": "X2"}
    with pytest.raises(ValueError):
        runtime.resume("t")
    runtime.verify_defect("t", defect["id"], "test-fix", True)
    assert not runtime.resume("t")["frozen"]
