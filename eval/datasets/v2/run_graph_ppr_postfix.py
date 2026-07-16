"""Capture the Phase 12 local-engine graph fix on development data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval.datasets.v2.run_graph_ppr_baseline import (
    _DATASET,
    _run_decomposition_matrix,
    _run_retrieval,
    _validate_output_path,
    load_dataset,
)


def run_postfix(output: Path) -> dict[str, Any]:
    output = _validate_output_path(output)
    dataset = load_dataset(_DATASET)
    first = _run_retrieval(dataset, output / "run-1", consolidate=True)
    second = _run_retrieval(dataset, output / "run-2", consolidate=True)
    summary = {
        "dataset_id": dataset["dataset_id"],
        "decomposition_matrix": _run_decomposition_matrix(),
        "runs": [first, second],
        "traces_byte_identical": (output / "run-1/traces.jsonl").read_bytes()
        == (output / "run-2/traces.jsonl").read_bytes(),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run_postfix(args.output)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
