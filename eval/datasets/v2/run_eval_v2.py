#!/usr/bin/env python3
"""Run the existing §33 SLO suites against the v2 corpus — no harness edits.

Blueprint refs: §33, §16 G2, FR-3.

This is a thin, net-new runner that REUSES the unmodified harness
(``eval/harness/*``) and feeds it the v2 datasets in this directory. It exists so
v2 can be measured today without touching ``eval/run_eval.py`` or anything under
``src/mnemosyne`` (see this directory's README for the one-line additive shim that
would let the stock ``run_eval.py`` pick v2 up via ``MNEMO_EVAL_DATASET_DIR`` —
recorded as a reconciliation item, not applied here).

It mirrors what ``run_eval.py`` does for the retrieval + answer-quality suites,
but on the bigger v2 corpus and the hard-QA set, and prints a compact scorecard.

USAGE
-----
    # local deterministic engine (runs now)
    python eval/datasets/v2/run_eval_v2.py

    # with the deterministic distractor-aware judge (breaks the G2 ceiling so the
    # +15% lift is measurable without an LLM)
    python eval/datasets/v2/run_eval_v2.py --distractor-judge

    # with a real strict LLM judge
    MNEMO_EVAL_JUDGE_CMD="<judge cmd>" python eval/datasets/v2/run_eval_v2.py

    # sharpen with real services (forwarded verbatim, exactly like run_eval.py)
    python eval/datasets/v2/run_eval_v2.py \
        --global-flag --embedding-provider --global-flag http \
        --global-flag --embedding-url --global-flag http://localhost:8080/embed

    # write a JSON report alongside the stock reports
    python eval/datasets/v2/run_eval_v2.py --out eval/reports/slo_report_v2.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# eval/datasets/v2 -> repo root is three parents up.
_REPO = _HERE.parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from eval.harness import suites  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((_HERE / name).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run §33 suites against the v2 corpus (no harness edits)")
    p.add_argument("--backend", choices=["local", "postgres"], default="local")
    p.add_argument("--postgres-dsn", default=None)
    p.add_argument(
        "--global-flag",
        action="append",
        default=[],
        dest="global_flags",
        help="extra top-level CLI flag forwarded to mneme (repeatable)",
    )
    p.add_argument(
        "--distractor-judge",
        action="store_true",
        help="wire the deterministic distractor-aware judge (v2_judge.py) so the G2 lift is measurable without an LLM",
    )
    p.add_argument("--out", default=None, help="write the JSON scorecard to this path")
    p.add_argument("--print-json", action="store_true")
    args = p.parse_args(argv)

    # If requested, point the harness's pluggable judge at our deterministic
    # distractor-aware judge using the EXISTING env-var ABI (no harness change).
    if args.distractor_judge and not os.environ.get("MNEMO_EVAL_JUDGE_CMD"):
        os.environ["MNEMO_EVAL_QA_DATASET"] = str(_HERE / "qa_hard_v2.json")
        os.environ["MNEMO_EVAL_JUDGE_CMD"] = f"{sys.executable} {_HERE / 'v2_judge.py'}"

    suites.configure_backend(args.backend, args.postgres_dsn)
    gf = list(args.global_flags)

    retrieval = _load("retrieval_v2.json")
    qa_hard = _load("qa_hard_v2.json")

    print("[v2] retrieval_suite on retrieval_v2 ...", file=sys.stderr)
    ret = suites.retrieval_suite(retrieval, global_flags=gf)
    print("[v2] retrieval_suite on qa_hard_v2 (multi-hop/temporal/contradiction) ...", file=sys.stderr)
    ret_qa = suites.retrieval_suite(qa_hard, global_flags=gf)
    print("[v2] calibration_suite on retrieval_v2 ...", file=sys.stderr)
    cal = suites.calibration_suite(retrieval, global_flags=gf)
    print("[v2] answer_quality_suite (G2) on qa_hard_v2 ...", file=sys.stderr)
    g2 = suites.answer_quality_suite(qa_hard, global_flags=gf)

    verdicts = (
        ret.get("verdicts", [])
        + ret_qa.get("verdicts", [])
        + cal.get("verdicts", [])
        + g2.get("verdicts", [])
    )
    passed = sum(1 for v in verdicts if v.get("pass"))
    total = len(verdicts)

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backend": args.backend,
            "global_flags": gf,
            "judge": g2.get("judge"),
            "datasets": {
                "retrieval_v2_docs": len(retrieval["corpus"]),
                "retrieval_v2_queries": len(retrieval["queries"]),
                "qa_hard_v2_cases": len(qa_hard["queries"]),
            },
            "note": "net-new v2 runner; reuses the unmodified eval/harness suites",
        },
        "overall": {"passed": passed, "total": total, "all_pass": passed == total},
        "suites": {
            "retrieval_v2": ret,
            "retrieval_qa_hard_v2": ret_qa,
            "calibration_v2": cal,
            "answer_quality_g2_v2": g2,
        },
    }

    # Compact scorecard to stderr.
    print(
        f"[v2] retrieval recall@k={ret['recall_at_k']['mean']} ndcg@k={ret['ndcg_at_k']['mean']} "
        f"(n={ret['n_queries']})",
        file=sys.stderr,
    )
    print(
        f"[v2] hard-QA-as-retrieval recall@k={ret_qa['recall_at_k']['mean']} ndcg@k={ret_qa['ndcg_at_k']['mean']} "
        f"(n={ret_qa['n_queries']})",
        file=sys.stderr,
    )
    print(f"[v2] calibration ECE={cal['ece']}", file=sys.stderr)
    print(
        f"[v2] G2 judge={g2.get('judge')} full={g2.get('full_context_answer_rate')} "
        f"memory={g2.get('memory_answer_rate')} lift={g2.get('absolute_lift')} "
        f"token_fraction={g2.get('mean_token_fraction')}",
        file=sys.stderr,
    )
    print(f"[v2] verdicts {passed}/{total} pass", file=sys.stderr)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"[v2] wrote {out}", file=sys.stderr)
    if args.print_json:
        print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
