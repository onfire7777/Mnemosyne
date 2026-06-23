#!/usr/bin/env python3
"""Mnemosyne §33 evaluation / SLO harness runner.

Runs the full measurement set + the five mandatory test classes against the
Mnemosyne public CLI, applies the suite-ignition (shadow-until-N) gate, and emits
JSON + Markdown SLO reports with confidence intervals.

Usage (runs end-to-end against the local deterministic engine NOW):

    python eval/run_eval.py
    python eval/run_eval.py --concurrency 16 --ignition-n 40
    # sharpen with real services (no harness change):
    python eval/run_eval.py --backend postgres --postgres-dsn "$DSN" \
        --global-flag --embedding-provider --global-flag http \
        --global-flag --embedding-url --global-flag http://localhost:8080/embed

Exit code: 0 if (ACTIVE mode AND all checks pass) OR (SHADOW mode, advisory).
Non-zero only when ACTIVE and a binding check fails — that is the promotion gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make ``eval.harness`` importable whether invoked as a script or a module.
_THIS = Path(__file__).resolve()
_EVAL_DIR = _THIS.parent
if str(_EVAL_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR.parent))

from eval.harness import ignition, report, suites  # noqa: E402
from eval.harness import test_classes as _test_classes  # noqa: E402
from eval.harness.synthetic import DEFAULT_EPISODES, generate_retrieval_cases  # noqa: E402
from eval.harness.test_classes import run_all_mandatory_classes  # noqa: E402

DATASETS = _EVAL_DIR / "datasets"
REPORTS = _EVAL_DIR / "reports"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mnemosyne §33 eval / SLO harness")
    p.add_argument("--backend", choices=["local", "postgres"], default="local")
    p.add_argument("--postgres-dsn", default=None)
    p.add_argument("--concurrency", type=int, default=8, help="concurrent searches for the latency suite")
    p.add_argument("--latency-rounds", type=int, default=6)
    p.add_argument("--ignition-n", type=int, default=ignition.DEFAULT_IGNITION_N)
    p.add_argument(
        "--global-flag",
        action="append",
        default=[],
        dest="global_flags",
        help="extra top-level CLI flag forwarded to mneme (repeatable); e.g. --embedding-provider http",
    )
    p.add_argument("--out-dir", default=str(REPORTS))
    p.add_argument("--quick", action="store_true", help="skip the synthetic+latency-heavy suites for a fast smoke run")
    p.add_argument("--print-json", action="store_true", help="print the full JSON report to stdout")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    gf = list(args.global_flags)
    # Set the process-global backend so every suite + mandatory class inherits it.
    suites.configure_backend(args.backend, args.postgres_dsn)
    _test_classes.configure_backend(args.backend, args.postgres_dsn)

    curated = _load(DATASETS / "retrieval_curated.json")
    poison = _load(DATASETS / "poison_suite.json")
    belief_path = DATASETS / "belief_cases.json"
    belief_cases = _load(belief_path)
    synthetic = generate_retrieval_cases(DEFAULT_EPISODES)

    common_flags = gf

    print("[eval] running SLO suites against the public CLI ...", file=sys.stderr)
    slo_suites = []
    slo_suites.append(suites.retrieval_suite(curated, global_flags=common_flags))
    if not args.quick:
        slo_suites.append(suites.retrieval_suite(synthetic, global_flags=common_flags))
    slo_suites.append(suites.calibration_suite(curated, global_flags=common_flags))
    slo_suites.append(suites.answer_quality_suite(curated, global_flags=common_flags))
    slo_suites.append(suites.poison_suite_eval(poison, global_flags=common_flags))
    if not args.quick:
        slo_suites.append(
            suites.latency_suite(
                curated,
                concurrency=args.concurrency,
                rounds=args.latency_rounds,
                global_flags=common_flags,
            )
        )

    print("[eval] running §33 mandatory test classes ...", file=sys.stderr)
    mandatory = run_all_mandatory_classes(str(belief_path), curated, global_flags=common_flags)
    mandatory_dicts = [m.as_dict() for m in mandatory]

    # Suite ignition (shadow-until-N).
    synth_queries = len([q for q in synthetic["queries"]]) if not args.quick else 0
    suite_size = ignition.compute_suite_size(
        curated_cases=len(curated["queries"]),
        synthetic_cases=synth_queries,
        belief_cases=len(belief_cases),
        poison_cases=len(poison["attacks"]),
        mandatory_classes=len(mandatory_dicts),
    )
    ign = ignition.evaluate_ignition(
        suite_size,
        args.ignition_n,
        state_path=Path(args.out_dir) / "suite_state.json",
        note=f"backend={args.backend} quick={args.quick}",
    )

    # Tally verdicts.
    slo_verdicts = [v for s in slo_suites for v in s.get("verdicts", [])]
    class_verdicts = [{"name": m["name"], "pass": m["passed"]} for m in mandatory_dicts]
    all_verdicts = slo_verdicts + class_verdicts
    passed = sum(1 for v in all_verdicts if v.get("pass"))
    total = len(all_verdicts)
    all_pass = passed == total

    embedding_path = "local deterministic (hashing stand-in)"
    if any("embedding-provider" in f for f in gf) or any("http" in f for f in gf):
        embedding_path = "external service (flags forwarded)"

    result = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backend": args.backend,
            "embedding_path": embedding_path,
            "global_flags": gf,
            "quick": args.quick,
            "harness_version": "1.0",
        },
        "ignition": ign.as_dict(),
        "overall": {"passed": passed, "total": total, "all_pass": all_pass},
        "slo_suites": slo_suites,
        "mandatory_classes": mandatory_dicts,
    }

    paths = report.write_reports(result, Path(args.out_dir))
    print(f"[eval] wrote {paths['json']}", file=sys.stderr)
    print(f"[eval] wrote {paths['md']}", file=sys.stderr)
    print(
        f"[eval] mode={ign.mode} suite_size={suite_size} N={args.ignition_n} "
        f"checks={passed}/{total} pass",
        file=sys.stderr,
    )

    if args.print_json:
        print(json.dumps(result, indent=2, default=str))

    # Promotion gate: only ACTIVE mode is binding.
    if ign.mode == "ACTIVE" and not all_pass:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
