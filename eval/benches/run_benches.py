"""Run all four §17 measurement benches and collect their JSON metric blocks.

Each bench is also independently runnable; this runner just imports and invokes
their ``main()`` and aggregates the ``metric`` + ``target`` + ``verdict`` blocks.

Run: ``python eval/benches/run_benches.py``
Exit code is always 0 — these are measurement benches (forcing functions), not
gates. The verdicts tell you what is and isn't wired today.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_oq1_ppr_latency  # noqa: E402
import bench_oq3_recompute_amplification  # noqa: E402
import bench_oq4_demotion_objective  # noqa: E402
import bench_oq7_capability_overhead  # noqa: E402

BENCHES = [
    ("OQ1", bench_oq1_ppr_latency),
    ("OQ3", bench_oq3_recompute_amplification),
    ("OQ4", bench_oq4_demotion_objective),
    ("OQ7", bench_oq7_capability_overhead),
]


def main() -> int:
    summary: dict[str, object] = {}
    for label, mod in BENCHES:
        print(f"\n{'=' * 72}\n== {label}: {mod.__name__}\n{'=' * 72}")
        result = mod.main()
        summary[label] = {
            "bench": result.get("bench"),
            "blueprint_ref": result.get("blueprint_ref"),
            "verdict": result.get("verdict"),
            "honest_status": result.get("honest_status"),
        }
    print(f"\n{'=' * 72}\n== SUMMARY (verdicts are honest current-src status)\n{'=' * 72}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
