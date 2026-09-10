"""Artifact IDs must identify ordinary files, never named file streams."""

import pytest

from mnemosyne.parametric import ParametricArtifact, ParametricArtifactStore


@pytest.mark.parametrize("tenant,artifact_id", [("tenant", "base:hidden"), ("tenant:hidden", "model")])
def test_stream_syntax_is_rejected_before_artifact_write(tmp_path, tenant, artifact_id):
    root = tmp_path / "store"
    store = ParametricArtifactStore(root)
    artifact = ParametricArtifact(tenant_id=tenant, id=artifact_id, source_ids=[], adapter_kind="test")
    with pytest.raises(ValueError, match="invalid parametric"):
        store.write(artifact, {"marker": "synthetic"})
    assert not root.exists()
    assert artifact.artifact_uri is None


def test_artifact_read_rejects_named_stream_even_when_it_contains_valid_json(tmp_path):
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    base = tenant / "base"
    base.write_bytes(b"unchanged")
    # On NTFS this is an alternate stream; on POSIX it is a colon-bearing file.
    stream = tenant / "base:hidden.json"
    stream.write_bytes(b'{"payload":{"marker":"synthetic"}}')
    store = ParametricArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="invalid parametric"):
        store.read("local-parametric://tenant/base:hidden.json")
    assert base.read_bytes() == b"unchanged"
    assert stream.read_bytes() == b'{"payload":{"marker":"synthetic"}}'


def test_ordinary_artifact_ids_still_round_trip(tmp_path):
    store = ParametricArtifactStore(tmp_path)
    artifact = ParametricArtifact(tenant_id="tenant-a", id="model_v1.2", source_ids=[], adapter_kind="test")
    uri = store.write(artifact, {"marker": "synthetic"})
    assert uri == "local-parametric://tenant-a/model_v1.2.json"
    assert store.read(uri)["payload"] == {"marker": "synthetic"}
    assert store.load_artifact(uri) == artifact
