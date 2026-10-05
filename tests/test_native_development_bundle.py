"""Disk evidence verification is separate from registered execution."""
import json

import pytest

from eval.public.bundle import BundleError, verify_bundle
from eval.public.native_bundle import verify_native_development_bundle, write_native_development_bundle
from tests import test_locomo_results as locomo_results
from tests.test_locomo_results import encode, inventory

native_inputs = locomo_results.inputs


def test_native_disk_round_trip_preserves_bytes_and_refuses_registration(native_inputs, tmp_path):
    metadata, payloads, python = native_inputs
    destination = tmp_path / "native"
    result = write_native_development_bundle(destination, metadata, payloads, scorer_python=python)
    receipt = verify_native_development_bundle(destination, scorer_python=python)
    assert receipt == {"valid": True, "registered": False, "model_execution_verified": False,
                       "publication_authorized": False, "result": result}
    assert all((destination / name).read_bytes() == raw for name, raw in payloads.items())
    with pytest.raises(FileExistsError):
        write_native_development_bundle(destination, metadata, payloads, scorer_python=python)
    assert verify_native_development_bundle(destination, scorer_python=python) == receipt
    with pytest.raises(BundleError, match="inventory"):
        verify_bundle(destination)


@pytest.mark.parametrize("fault", ["result", "trace", "extra", "symlink", "secret", "large"])
def test_native_disk_package_rejects_tampering(native_inputs, tmp_path, fault):
    metadata, payloads, python = native_inputs
    destination = tmp_path / "native"
    write_native_development_bundle(destination, metadata, payloads, scorer_python=python)
    if fault == "result":
        result = json.loads((destination / "result.json").read_bytes())
        result["metrics"][3]["value"] = 1
        (destination / "result.json").write_bytes(encode(result))
    elif fault == "trace":
        (destination / "traces.jsonl").write_bytes(b'{}\n')
    elif fault == "extra":
        (destination / "unexpected.json").write_bytes(b'{}')
    elif fault == "symlink":
        (destination / "traces.jsonl").unlink()
        outside = tmp_path / "outside"
        outside.write_bytes(b'')
        (destination / "traces.jsonl").symlink_to(outside)
    elif fault == "secret":
        payloads["extra.txt"] = b"-----BEGIN PRIVATE KEY-----"
        inventory(payloads)
        for name, raw in payloads.items():
            (destination / name).write_bytes(raw)
    else:
        with (destination / "traces.jsonl").open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(BundleError):
        verify_native_development_bundle(destination, scorer_python=python)


def test_native_write_rejects_secrets_before_creating_destination(native_inputs, tmp_path):
    metadata, payloads, python = native_inputs
    payloads["extra.txt"] = b"-----BEGIN PRIVATE KEY-----"
    inventory(payloads)
    destination = tmp_path / "native"
    with pytest.raises(BundleError, match="secret-like"):
        write_native_development_bundle(destination, metadata, payloads, scorer_python=python)
    assert not destination.exists()


def test_native_writer_cleans_up_failed_creation(native_inputs, tmp_path, monkeypatch):
    from pathlib import Path
    metadata, payloads, python = native_inputs
    original = Path.open
    destination = tmp_path / "native"

    def fail_write(path, mode="r", *args, **kwargs):
        if path.parent == destination and path.name == "result.json":
            raise OSError("synthetic disk failure")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_write)
    with pytest.raises(OSError, match="synthetic disk failure"):
        write_native_development_bundle(destination, metadata, payloads, scorer_python=python)
    assert not destination.exists()


@pytest.mark.parametrize("mutation", ["content", "replace", "extra"])
def test_native_package_rejects_changes_during_scorer_replay(native_inputs, tmp_path, monkeypatch, mutation):
    from eval.public import native_bundle
    metadata, payloads, python = native_inputs
    destination = tmp_path / "native"
    write_native_development_bundle(destination, metadata, payloads, scorer_python=python)
    original = native_bundle.assemble_development_result

    def mutate_after_replay(*args, **kwargs):
        result = original(*args, **kwargs)
        path = destination / "traces.jsonl"
        if mutation == "content":
            path.write_bytes(b'changed after snapshot')
        elif mutation == "replace":
            path.unlink()
            path.write_bytes(b'')
        else:
            (destination / "unexpected.txt").write_bytes(b'extra')
        return result

    monkeypatch.setattr(native_bundle, "assemble_development_result", mutate_after_replay)
    with pytest.raises(BundleError, match="changed during verification"):
        verify_native_development_bundle(destination, scorer_python=python)


def test_saved_native_package_can_be_verified_in_separate_process(native_inputs, tmp_path):
    import subprocess
    import sys

    metadata, payloads, python = native_inputs
    destination = tmp_path / "native"
    result = write_native_development_bundle(destination, metadata, payloads, scorer_python=python)
    command = [sys.executable, "-m", "eval.public.native_bundle", str(destination), "--scorer-python", python]
    verified = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert verified.returncode == 0, verified.stderr
    receipt = json.loads(verified.stdout)
    assert receipt["valid"] and receipt["result"] == result
    assert not receipt["registered"] and not receipt["model_execution_verified"]
    assert not receipt["publication_authorized"]
    (destination / "traces.jsonl").write_bytes(b'{}\n')
    rejected = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert rejected.returncode == 1 and rejected.stdout == ""
    assert json.loads(rejected.stderr)["valid"] is False
    assert "digest mismatch" in json.loads(rejected.stderr)["error"]
