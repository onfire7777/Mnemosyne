"""Offline, immutable custody for public benchmark JSON assets."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_HEX = frozenset("0123456789abcdef")
SPDX_LICENSES = frozenset({"Apache-2.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "MIT"})


class AssetError(ValueError):
    """An external benchmark asset failed closed."""


@dataclass(frozen=True)
class AssetSpec:
    filename: str
    sha256: str
    revision: str
    license: str
    citation: str
    split_role: str
    contamination: str


def validate_asset_spec(spec: AssetSpec) -> None:
    path = PurePosixPath(spec.filename)
    if path.is_absolute() or ".." in path.parts or str(path) != spec.filename:
        raise AssetError("asset filename must be a normalized relative path")
    if len(spec.revision) != 40 or set(spec.revision) - _HEX:
        raise AssetError("asset revision must be an exact 40-hex pin")
    if len(spec.sha256) != 64 or set(spec.sha256) - _HEX:
        raise AssetError("asset digest must be an exact lowercase SHA-256")
    if spec.license not in SPDX_LICENSES:
        raise AssetError("asset license must be an allowlisted canonical SPDX identifier")
    for field in ("citation", "split_role", "contamination"):
        if not isinstance(getattr(spec, field), str) or not getattr(spec, field).strip():
            raise AssetError(f"asset {field} is required")


def load_pinned_json_asset(dataset_dir: Path | str, spec: AssetSpec) -> Any:
    """Load a local JSON asset only after path and digest verification.

    This function deliberately has no downloader. Callers must acquire the exact
    pinned bytes separately and provide an offline dataset directory.
    """
    validate_asset_spec(spec)
    root = Path(dataset_dir)
    if not root.is_dir() or root.is_symlink():
        raise AssetError("dataset directory must be a real directory, not a link")
    root = root.resolve()
    asset = root.joinpath(*PurePosixPath(spec.filename).parts)
    current = root
    for component in PurePosixPath(spec.filename).parts:
        current /= component
        if current.is_symlink():
            raise AssetError("asset path components must not be links")
    if asset.is_symlink() or not asset.is_file():
        raise AssetError("asset must be a real file, not a link")
    try:
        asset.resolve().relative_to(root)
    except ValueError as exc:
        raise AssetError("asset path escapes dataset directory") from exc
    raw = asset.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec.sha256:
        raise AssetError(f"asset digest mismatch: {spec.filename}")
    try:
        value = json.loads(
            raw,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AssetError(f"invalid JSON asset: {spec.filename}") from exc
    _reject_non_finite(value)
    return value


def load_asset_set(dataset_dir: Path | str, specs: list[AssetSpec]) -> dict[str, Any]:
    """Load an explicit asset set; duplicate filenames are forbidden."""
    if len({spec.filename for spec in specs}) != len(specs):
        raise AssetError("duplicate asset filename")
    return {spec.filename: load_pinned_json_asset(dataset_dir, spec) for spec in specs}


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise AssetError("non-finite number in JSON asset")
    if isinstance(value, dict):
        for nested in value.values():
            _reject_non_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_non_finite(nested)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = nested
    return value
