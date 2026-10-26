"""Compare repeated current runs separately from the historical quality floor."""

from __future__ import annotations

import json
from pathlib import Path

from eval.tests.test_quality_gate import (
    BASELINE_PATH,
    _assert_fresh_coverage,
    _assert_nonregression,
    _run_report,
    _strip_nondeterministic_fields,
)


def test_quality_gate_current_run_reproduces_bit_for_bit(tmp_path: Path) -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    _assert_fresh_coverage(baseline, "all")
    # Keep both development and held-out coverage in the existing default test.
    # Quality may improve relative to the historical baseline, but two runs of
    # the same current implementation must still agree on every stable field.
    first = _run_report(tmp_path, "all", "first")
    second = _run_report(tmp_path, "all", "second")
    for report in (first, second):
        _assert_fresh_coverage(report, "all")
        _assert_nonregression(report, baseline, "all")
    assert _strip_nondeterministic_fields(first) == _strip_nondeterministic_fields(second), (
        "Repeated current quality-gate runs differ in stable output"
    )
