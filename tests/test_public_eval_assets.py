from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from eval.public.assets import AssetError, AssetSpec, load_pinned_json_asset


def _spec(raw: bytes) -> AssetSpec:
    return AssetSpec(
        filename="dataset.json",
        sha256=hashlib.sha256(raw).hexdigest(),
        revision="a" * 40,
        license="MIT",
        citation="Example et al. (2026)",
        split_role="test",
        contamination="none known",
    )


def test_asset_is_loaded_only_from_digest_gated_offline_directory(tmp_path: Path) -> None:
    raw = b'{"rows":[{"id":"q1"}]}\n'
    (tmp_path / "dataset.json").write_bytes(raw)
    assert load_pinned_json_asset(tmp_path, _spec(raw)) == {"rows": [{"id": "q1"}]}
    (tmp_path / "dataset.json").write_text("{}\n")
    with pytest.raises(AssetError, match="digest"):
        load_pinned_json_asset(tmp_path, _spec(raw))


def test_asset_rejects_mutable_or_incomplete_custody(tmp_path: Path) -> None:
    raw = b"[]\n"
    (tmp_path / "dataset.json").write_bytes(raw)
    for field, value in (
        ("revision", "main"),
        ("license", ""),
        ("citation", ""),
        ("split_role", ""),
        ("contamination", ""),
    ):
        values = _spec(raw).__dict__ | {field: value}
        with pytest.raises(AssetError):
            load_pinned_json_asset(tmp_path, AssetSpec(**values))


def test_asset_rejects_links_paths_and_ambiguous_json(tmp_path: Path) -> None:
    raw = b"[]\n"
    outside = tmp_path.parent / "outside-public-asset.json"
    outside.write_bytes(raw)
    try:
        (tmp_path / "dataset.json").symlink_to(outside)
    except OSError:
        (tmp_path / "dataset.json").write_bytes(raw)
    else:
        with pytest.raises(AssetError, match="link"):
            load_pinned_json_asset(tmp_path, _spec(raw))
    with pytest.raises(AssetError, match="filename"):
        load_pinned_json_asset(tmp_path, AssetSpec(**(_spec(raw).__dict__ | {"filename": "../outside-public-asset.json"})))
    (tmp_path / "dataset.json").unlink()
    (tmp_path / "dataset.json").write_text('{"x":NaN}\n')
    bad = _spec((tmp_path / "dataset.json").read_bytes())
    with pytest.raises(AssetError, match="JSON"):
        load_pinned_json_asset(tmp_path, bad)


def test_asset_rejects_noncanonical_license_and_linked_parent(tmp_path: Path) -> None:
    raw = b"[]\n"
    real = tmp_path / "real"
    real.mkdir()
    (real / "dataset.json").write_bytes(raw)
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pass
    else:
        nested = AssetSpec(**(_spec(raw).__dict__ | {"filename": "linked/dataset.json"}))
        with pytest.raises(AssetError, match="components"):
            load_pinned_json_asset(tmp_path, nested)
    bad_license = AssetSpec(**(_spec(raw).__dict__ | {"license": "MIT License"}))
    with pytest.raises(AssetError, match="SPDX"):
        load_pinned_json_asset(real, bad_license)
