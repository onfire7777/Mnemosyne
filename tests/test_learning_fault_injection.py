"""Every declared guard is exercised through a concrete prohibited mutation."""

import ast
from pathlib import Path

import pytest

from mnemosyne.experience.guards import GUARD_CLASSES, LearningGuardError, validate
from fault_injection.learning import baseline, corrupt, source_lookup


@pytest.mark.parametrize("code", GUARD_CLASSES)
def test_fault_injection_hits_its_guard(code):
    before = baseline()
    after = corrupt(code, before)
    with pytest.raises(LearningGuardError) as caught:
        validate(before, after, "injected_fault", source_lookup=source_lookup)
    assert caught.value.code == code


def test_runtime_never_imports_fault_injection():
    for path in Path("src/mnemosyne").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert all("fault_injection" not in module for module in modules), path


def test_native_learning_storage_has_one_writer_entry_point():
    root = Path(__file__).resolve().parents[1] / "src" / "mnemosyne"
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                if "LearningStore" in names:
                    assert relative == "experience/writer.py", relative
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if "._learning_data" in ast.unparse(target):
                        assert relative in {"engine.py", "experience/store.py"}, relative


@pytest.mark.parametrize("code", GUARD_CLASSES)
def test_fault_injection_is_contained_by_real_writer(code, monkeypatch):
    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.experience.writer import LearningWriter

    before = baseline()
    after = corrupt(code, before)
    engine = LocalMemoryEngine()
    engine._learning_data = {"t": before}
    monkeypatch.setattr(engine, "get_evidence", lambda tenant, cid: source_lookup(cid))
    writer = LearningWriter(engine)

    def inject(state):
        state.clear()
        state.update(after)

    with pytest.raises(LearningGuardError) as caught:
        writer.apply("t", "test_fault", inject)
    assert caught.value.code == code
    result = writer.read("t")
    assert result["policy"]["frozen"] is True
    assert [defect["class"] for defect in result["defects"].values()] == [code]
    for collection in ("receipts", "episodes", "credit", "stats", "artifacts"):
        assert result[collection] == before[collection]
