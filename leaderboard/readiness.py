"""Validate the supplied Phase 16 launch-readiness evidence record."""

from __future__ import annotations

import json
import os
import stat
import sys
from typing import Any

from leaderboard.validate import SCHEMA_VERSION_V2, validate_record


GATES = (
    "pbpp",
    "part_i_results",
    "register_a",
    "identical_treatment",
    "operator_entry",
)
MAX_INPUT_BYTES = 1_048_576


class ReadinessError(ValueError):
    """Raised when a readiness record is not canonical."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ReadinessError("duplicate JSON key")
        value[key] = item
    return value


def evaluate(record: object) -> dict[str, object]:
    """Return the deterministic readiness result for one canonical record."""
    if not isinstance(record, dict) or set(record) != set(GATES):
        raise ReadinessError("invalid readiness record")

    blocked: list[str] = []
    for gate in GATES:
        value = record[gate]
        expected = {"satisfied", "evidence"}
        if gate == "operator_entry":
            expected.add("label")
        if not isinstance(value, dict) or set(value) != expected:
            raise ReadinessError("invalid readiness gate")
        if type(value["satisfied"]) is not bool:
            raise ReadinessError("invalid readiness status")
        if not isinstance(value["evidence"], str) or not value["evidence"].strip():
            raise ReadinessError("invalid readiness evidence")
        if gate == "operator_entry" and value["label"] != "operator-entry":
            raise ReadinessError("invalid operator entry label")
        if not value["satisfied"]:
            blocked.append(gate)

    blocked.sort()
    return {"blocked_gates": blocked, "ready": not blocked}


def evaluate_result_v2(record: object) -> dict[str, object]:
    """Return fail-closed publication readiness for one result-v2 record."""
    if not isinstance(record, dict) or validate_record(record):
        raise ReadinessError("invalid result-v2 record")

    blocked: list[str] = ["human_approval"]
    publication = record["publication"]
    assert isinstance(publication, dict)
    admission = record.get("admission_state")
    if not (
        isinstance(admission, str) and admission.startswith("RUN-READY-")
    ):
        blocked.append("admission")
    if record.get("track_kind") == "DEVELOPMENT" or publication.get(
        "publishable"
    ) is not True:
        blocked.append("publication")
    if (
        record.get("track_kind") == "DEVELOPMENT"
        or publication.get("register_b_satisfied") is not True
    ):
        blocked.append("pbpp")
    gates = record.get("safety_gates")
    if isinstance(gates, list) and any(
        isinstance(gate, dict) and gate.get("status") == "failed" for gate in gates
    ):
        blocked.append("safety_gates")
    blocked = sorted(set(blocked))
    return {"blocked_gates": blocked, "ready": not blocked}


def main(argv: list[str] | None = None) -> int:
    """Read one UTF-8 JSON record and emit its deterministic readiness result."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("error: invalid readiness record", file=sys.stderr)
        return 2

    try:
        with os.fdopen(
            os.open(args[0], os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)), "rb"
        ) as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ReadinessError("readiness record is not a regular file")
            encoded = source.read(MAX_INPUT_BYTES + 1)
        if len(encoded) > MAX_INPUT_BYTES:
            raise ReadinessError("readiness record is too large")
        raw = encoded.decode("utf-8")
    except (
        OSError,
        UnicodeError,
        ReadinessError,
    ):
        print("error: invalid readiness record", file=sys.stderr)
        return 2

    try:
        record = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (RecursionError, ValueError):
        print("error: invalid readiness record", file=sys.stderr)
        return 2

    try:
        if isinstance(record, dict) and record.get("schema_version") == SCHEMA_VERSION_V2:
            result = evaluate_result_v2(record)
        else:
            result = evaluate(record)
    except ReadinessError:
        print("error: invalid readiness record", file=sys.stderr)
        return 2

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
