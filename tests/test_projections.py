# tests/test_projections.py
from __future__ import annotations

from pathlib import Path

from mnemosyne.projections import ProjectionRegistry, ProjectionSpec


def test_ensure_rebuilds_on_fingerprint_mismatch(tmp_path: Path):
    calls: list[str] = []
    state = {"fp": "v1"}
    reg = ProjectionRegistry(tmp_path)
    reg.register(ProjectionSpec(
        name="demo", version=1,
        fingerprint=lambda: state["fp"],
        rebuild=lambda: calls.append("rebuilt"),
    ))
    assert reg.ensure("demo") is True and calls == ["rebuilt"]   # first run: no stored fp
    assert reg.ensure("demo") is False and calls == ["rebuilt"]  # stable: no rebuild
    state["fp"] = "v2"
    assert reg.ensure("demo") is True and calls == ["rebuilt", "rebuilt"]


def test_version_bump_forces_rebuild(tmp_path: Path):
    calls: list[str] = []
    reg = ProjectionRegistry(tmp_path)
    spec = ProjectionSpec(name="demo", version=1, fingerprint=lambda: "same", rebuild=lambda: calls.append("r"))
    reg.register(spec)
    reg.ensure("demo")
    reg2 = ProjectionRegistry(tmp_path)
    reg2.register(ProjectionSpec(name="demo", version=2, fingerprint=lambda: "same", rebuild=lambda: calls.append("r")))
    assert reg2.ensure("demo") is True and len(calls) == 2


def test_status_reports_all_registered(tmp_path: Path):
    reg = ProjectionRegistry(tmp_path)
    reg.register(ProjectionSpec(name="a", version=1, fingerprint=lambda: "x", rebuild=lambda: None))
    assert set(reg.status()) == {"a"}
    assert reg.status()["a"]["version"] == 1


def test_ensure_rebuilds_when_stored_state_file_deleted(tmp_path: Path):
    """Registry state loss (projections.json gone) must re-trigger rebuild-on-mismatch."""
    calls: list[str] = []
    reg = ProjectionRegistry(tmp_path)
    reg.register(ProjectionSpec(
        name="demo", version=1,
        fingerprint=lambda: "same",
        rebuild=lambda: calls.append("r"),
    ))
    assert reg.ensure("demo") is True and calls == ["r"]
    state_file = tmp_path / "projections.json"
    assert state_file.exists()
    state_file.unlink()  # simulate lost/wiped derived-state sidecar
    assert reg.ensure("demo") is True and calls == ["r", "r"]  # re-reports rebuild
    assert state_file.exists()  # re-persists the fingerprint
    assert reg.ensure("demo") is False and calls == ["r", "r"]  # stable again
