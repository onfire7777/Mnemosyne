"""Check the network boundary without fetching any corpus."""

import hashlib
import io
import json
from unittest.mock import patch

import pytest

from eval.compact_answering import train_intake as subject


def test_verified_transfer_never_exposes_wrong_or_overwritten_asset(tmp_path):
    expected = b"approved train bytes"
    digest = hashlib.sha256(expected).hexdigest()
    for n, data in enumerate((expected[:-1], b"x" * len(expected), expected + b"!")):
        target = tmp_path / str(n)
        with pytest.raises(ValueError):
            subject._copy_verified(io.BytesIO(data), target, len(expected), digest)
        assert not target.exists()
        assert target.with_name(target.name + ".partial").exists()
    target = tmp_path / "valid"
    subject._copy_verified(io.BytesIO(expected), target, len(expected), digest)
    assert target.read_bytes() == expected
    with pytest.raises(FileExistsError):
        subject._copy_verified(io.BytesIO(expected), target, len(expected), digest)
    assert target.read_bytes() == expected


def test_fixed_allowlist_and_complete_quarantine_receipt(tmp_path):
    assert len(subject.ASSETS) == 5
    assert sum(a[3] for a in subject.ASSETS) == 348175076
    assert all(a[2] == "README.md" or "/train-" in a[2] for a in subject.ASSETS)
    assert all("fullwiki" not in a[2] for a in subject.ASSETS)
    data = b"train"
    asset = (*subject.ASSETS[1][:3], len(data), hashlib.sha256(data).hexdigest())
    destination = tmp_path / "quarantine"
    with (
        patch.object(subject, "ASSETS", (asset,)),
        patch.object(
            subject.urllib.request, "urlopen", return_value=io.BytesIO(data)
        ) as fetch,
    ):
        receipt = subject.intake(destination)
    assert not receipt["training_admitted"]
    assert json.loads((destination / "intake.json").read_text()) == receipt
    assert (destination / receipt["assets"][0]["local_path"]).read_bytes() == data
    assert asset[1] in fetch.call_args.args[0]
    with pytest.raises(FileExistsError):
        subject.intake(destination)


def test_failed_intake_has_no_completed_receipt(tmp_path):
    destination = tmp_path / "failed"
    with patch.object(
        subject.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")
    ):
        with pytest.raises(ValueError):
            subject.intake(destination)
    assert not (destination / "intake.json").exists()
    assert not list(destination.rglob("*.parquet"))
