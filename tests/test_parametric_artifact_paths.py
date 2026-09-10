"""Artifact IDs must identify ordinary files, never named file streams."""

import json

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


@pytest.mark.parametrize("tenants,ids", [(("Tenant-A", "tenant-a"), ("model", "model")), (("tenant", "tenant"), ("Model", "model"))])
def test_case_distinct_identities_do_not_overwrite_each_other(tmp_path, tenants, ids):
    store = ParametricArtifactStore(tmp_path)
    artifacts = [ParametricArtifact(tenant_id=t, id=i, source_ids=[], adapter_kind="test") for t, i in zip(tenants, ids)]
    uris = [store.write(a, {"owner": n}) for n, a in enumerate(artifacts)]
    assert uris[0] != uris[1]
    assert [store.read(uri)["payload"] for uri in uris] == [{"owner": 0}, {"owner": 1}]
    assert [store.load_artifact(uri) for uri in uris] == artifacts
    store.write(artifacts[0], {"owner": "updated"})
    assert store.read(uris[0])["payload"] == {"owner": "updated"}
    assert store.read(uris[1])["payload"] == {"owner": 1}


@pytest.mark.parametrize("stored_tenant,stored_id", [("other", "model"), ("tenant", "other")])
def test_legacy_reads_reject_mismatched_identity(tmp_path, stored_tenant, stored_id):
    directory = tmp_path / "tenant"
    directory.mkdir()
    artifact = ParametricArtifact(tenant_id=stored_tenant, id=stored_id, source_ids=[], adapter_kind="test")
    path = directory / "model.json"
    path.write_text(json.dumps({"artifact": artifact.to_dict(), "payload": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        ParametricArtifactStore(tmp_path).read("local-parametric://tenant/model.json")


def test_legacy_artifact_remains_readable_and_unchanged_after_update(tmp_path):
    directory = tmp_path / "tenant"
    directory.mkdir()
    artifact = ParametricArtifact(tenant_id="tenant", id="model", source_ids=[], adapter_kind="test")
    path = directory / "model.json"
    original = json.dumps({"artifact": artifact.to_dict(), "payload": {"version": 1}}).encode()
    path.write_bytes(original)
    store = ParametricArtifactStore(tmp_path)
    uri = "local-parametric://tenant/model.json"
    assert store.read(uri)["payload"] == {"version": 1}
    assert path.read_bytes() == original
    assert store.write(artifact, {"version": 2}) == uri
    assert store.read(uri)["payload"] == {"version": 2}
    assert path.read_bytes() == original


@pytest.mark.parametrize("replacement", [b"not-json", b'{"artifact":{"tenant_id":"other","id":"model"}}'])
def test_invalid_new_artifact_does_not_fall_back_to_legacy(tmp_path, replacement):
    directory = tmp_path / "tenant"
    directory.mkdir()
    artifact = ParametricArtifact(tenant_id="tenant", id="model", source_ids=[], adapter_kind="test")
    (directory / "model.json").write_text(
        json.dumps({"artifact": artifact.to_dict(), "payload": {"version": 1}}), encoding="utf-8"
    )
    store = ParametricArtifactStore(tmp_path)
    uri = store.write(artifact, {"version": 2})
    new_files = [path for path in tmp_path.rglob("*.json") if path.parent != directory]
    assert len(new_files) == 1
    new_files[0].write_bytes(replacement)
    with pytest.raises(ValueError):
        store.read(uri)
