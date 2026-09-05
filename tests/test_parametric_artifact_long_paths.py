"""Artifact identity stays logical while Windows file IO supports long paths."""

import os
from pathlib import Path

import pytest

from mnemosyne.parametric import ParametricArtifact, ParametricArtifactStore


def test_long_artifact_filename_roundtrips_without_changing_identity(tmp_path):
    root = tmp_path / ("r" * max(1, 220 - len(str(tmp_path)) - 1))
    store = ParametricArtifactStore(root)
    artifact = ParametricArtifact("tenant", ["source"], "test", id="a" * 80)
    logical_path = root / "tenant" / f"{artifact.id}.json"
    assert len(str(logical_path.with_suffix(".json.tmp"))) > 260
    try:
        uri = store.write(artifact, {"revision": 1})
        assert uri == f"local-parametric://tenant/{artifact.id}.json"
        assert store.root == root.resolve()
        assert store.read(uri)["payload"] == {"revision": 1}
        artifact.status = "promoted"
        assert store.write(artifact, {"revision": 2}) == uri
        assert store.load_artifact(uri).status == "promoted"
        assert store.read(uri)["payload"] == {"revision": 2}
    finally:
        # Remove only these known long filenames so pytest can clean its
        # otherwise short temporary directories even on MAX_PATH systems.
        for path in (logical_path, logical_path.with_suffix(".json.tmp")):
            cleanup = "\\\\?\\" + str(path) if os.name == "nt" else str(path)
            try:
                os.unlink(cleanup)
            except FileNotFoundError:
                pass


def test_invalid_artifact_segments_still_fail_before_io(tmp_path):
    store = ParametricArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="invalid parametric tenant"):
        store.write(ParametricArtifact("../outside", [], "test"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path syntax")
def test_windows_io_path_preserves_unc_share_and_existing_prefix():
    unc = Path(r"\\server\share\folder\artifact.json")
    expected = Path(r"\\?\UNC\server\share\folder\artifact.json")
    assert ParametricArtifactStore._io_path(unc) == expected
    assert ParametricArtifactStore._io_path(expected) == expected
