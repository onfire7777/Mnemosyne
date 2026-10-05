"""Persist unregistered native development evidence; never grant run admission."""
from pathlib import Path
import os
import shutil
import stat

from eval.public.adapters.locomo import LoCoMoError
from eval.public.adapters.locomo_results import assemble_development_result
from eval.public.bundle import BundleError, SECRET, _canonical, _parse_json
from leaderboard.validate import DIGEST_PAYLOAD_NAMES

_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _check_payloads(payloads):
    if any(not isinstance(raw, bytes) for raw in payloads.values()):
        raise BundleError("native evidence payloads must be bytes")
    if (len(payloads) > 64 or any(len(raw) > _MAX_FILE_BYTES for raw in payloads.values())
            or sum(map(len, payloads.values())) > _MAX_TOTAL_BYTES):
        raise BundleError("native evidence exceeds bounded package size")
    if any(SECRET.search(raw.decode("utf-8", errors="replace")) for raw in payloads.values()):
        raise BundleError("secret-like material detected")


def _signature(info):
    return tuple(getattr(info, field) for field in
                 ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _no_links(path):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise BundleError("native evidence paths must not contain links")


def verify_native_development_bundle(root, *, scorer_python):
    """Read bounded artifact snapshots and reconstruct the saved atomic result.

    This separate development entry point does not substitute for verify_bundle's
    registry admission or for executing the model again in reproduce_bundle.
    """
    root = Path(root).absolute()
    _no_links(root)
    if not root.is_dir():
        raise BundleError("native evidence must be a directory")
    root_signature = _signature(root.stat())
    entries = sorted(root.iterdir())
    if len(entries) > 64:
        raise BundleError("native evidence exceeds bounded package size")
    payloads = {}
    signatures = {}
    for entry in entries:
        _no_links(entry)
        if not entry.is_file():
            raise BundleError("native evidence must contain only regular files")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(entry, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise BundleError("native evidence must contain only regular files")
            raw = stream.read(_MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        current = entry.stat()
        # Reading may update atime; only identity/content metadata must stay fixed.
        if any(_signature(before) != _signature(item) for item in (after, current)):
            raise BundleError("native evidence changed during verification")
        _no_links(entry)
        signatures[entry] = _signature(before)
        payloads[entry.name] = raw
        _check_payloads(payloads)
    _no_links(root)
    if sorted(root.iterdir()) != entries:
        raise BundleError("native evidence inventory changed during verification")
    if "result.json" not in payloads:
        raise BundleError("native evidence is missing its atomic result")
    try:
        result = _parse_json(payloads.pop("result.json").decode("utf-8"), "result.json")
    except UnicodeDecodeError as exc:
        raise BundleError("native evidence result must be UTF-8") from exc
    if not isinstance(result, dict):
        raise BundleError("native evidence result must be an object")
    metadata = {key: value for key, value in result.items()
                if key not in {"schema_version", "metrics", *DIGEST_PAYLOAD_NAMES}}
    try:
        expected = assemble_development_result(metadata, payloads, scorer_python=scorer_python)
    except LoCoMoError as exc:
        raise BundleError(str(exc)) from exc
    if _canonical(result) != _canonical(expected):
        raise BundleError("saved native result does not match artifact replay")
    _no_links(root)
    if _signature(root.stat()) != root_signature or sorted(root.iterdir()) != entries:
        raise BundleError("native evidence inventory changed during verification")
    for entry, signature in signatures.items():
        _no_links(entry)
        if _signature(entry.stat()) != signature:
            raise BundleError("native evidence changed during verification")
    return {"valid": True, "registered": False, "model_execution_verified": False,
            "publication_authorized": False, "result": expected}


def write_native_development_bundle(destination, metadata, payloads, *, scorer_python):
    """Create a new package only after replay; refuse to overwrite any destination.

    Files use exact supplied bytes. Interrupted writes are incomplete packages,
    not successful verification receipts; callers must retain that distinction.
    """
    payloads = dict(payloads)
    if "result.json" in payloads:
        raise BundleError("result.json is reserved for the projected atomic result")
    _check_payloads(payloads)
    result = assemble_development_result(metadata, payloads, scorer_python=scorer_python)
    payloads["result.json"] = _canonical(result)
    _check_payloads(payloads)
    destination = Path(destination).absolute()
    _no_links(destination)
    destination.mkdir()  # Exclusive creation: never remove an existing directory.
    try:
        for name, raw in payloads.items():
            with (destination / name).open("xb") as stream:
                stream.write(raw)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return result


def main(argv=None):
    """Verify a saved development package without executing a memory model."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("package", type=Path, help="saved native development evidence directory")
    parser.add_argument("--scorer-python", type=Path, required=True,
                        help="explicit trusted Python executable with pinned scorer dependencies")
    args = parser.parse_args(argv)
    try:
        receipt = verify_native_development_bundle(args.package, scorer_python=args.scorer_python)
    except (BundleError, LoCoMoError, OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
