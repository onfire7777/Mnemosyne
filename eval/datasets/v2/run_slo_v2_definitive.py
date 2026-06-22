#!/usr/bin/env python3
"""DEFINITIVE at-scale SLO scoreboard: v2 corpus + REAL providers + Postgres.

Blueprint refs: §16 (SLO targets), §33 (eval harness), FR-3 (retrieval), G2, G7.

This is a NET-NEW runner (no harness edits, no src edits). It reuses the
*unmodified* ``eval/harness`` suites and feeds them:

  * the Wave-4 v2 corpus (105 docs) + v2 query sets (45 retrieval, 24 hard-QA),
  * the stock poison_suite.json (G7) — there is no v2 poison set, so the canonical
    poison attacks are used and labelled as such,

against ``--backend postgres`` with the real embedding (BAAI/bge-small-en-v1.5)
and cross-encoder reranker (cross-encoder/ms-marco-MiniLM-L-6-v2) served over HTTP
by ``services/embedding/app.py``. Provider HTTP flags are forwarded VERBATIM to the
CLI via ``--global-flag`` (identical ABI to ``run_eval.py``).

It extends ``run_eval_v2.py`` (retrieval + calibration + G2) with the two SLO
families that runner omits:

  * fast-path P95 latency (warm) via ``suites.latency_suite`` on the postgres
    backend (shared concurrent-safe store; the startup-adjusted P95 is the
    engine-only / warm-server number),
  * poison block rate (G7) via ``suites.poison_suite_eval``.

So the resulting scorecard reports ALL SIX §16 families in one JSON:
recall@k, nDCG@k, ECE, G2 lift @ token-fraction, fast-path P95 (warm), poison-block.

USAGE
-----
    python eval/datasets/v2/run_slo_v2_definitive.py \
        --backend postgres --postgres-dsn "$DSN" --distractor-judge \
        --global-flag --embedding-provider --global-flag http \
        --global-flag --embedding-url --global-flag http://127.0.0.1:8088/embed \
        --global-flag --embedding-dims --global-flag 1024 \
        --global-flag --reranker-provider --global-flag http \
        --global-flag --reranker-url --global-flag http://127.0.0.1:8088/rerank \
        --out eval/reports/slo_v2_definitive.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from eval.harness import suites  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Definitive v2 + real-providers + Postgres SLO scoreboard")
    p.add_argument("--backend", choices=["local", "postgres"], default="postgres")
    p.add_argument("--postgres-dsn", default=None)
    p.add_argument("--global-flag", action="append", default=[], dest="global_flags")
    p.add_argument("--distractor-judge", action="store_true")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--latency-rounds", type=int, default=6)
    p.add_argument("--retrieval-limit", type=int, default=None,
                   help="cap retrieval queries for a representative subset (states sample size)")
    p.add_argument("--qa-limit", type=int, default=None,
                   help="cap hard-QA queries for a representative subset")
    p.add_argument("--skip-latency", action="store_true")
    p.add_argument("--skip-poison", action="store_true")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    if args.distractor_judge and not os.environ.get("MNEMO_EVAL_JUDGE_CMD"):
        os.environ["MNEMO_EVAL_QA_DATASET"] = str(_HERE / "qa_hard_v2.json")
        os.environ["MNEMO_EVAL_JUDGE_CMD"] = f"{sys.executable} {_HERE / 'v2_judge.py'}"

    suites.configure_backend(args.backend, args.postgres_dsn)
    gf = list(args.global_flags)

    retrieval = _load(_HERE / "retrieval_v2.json")
    qa_hard = _load(_HERE / "qa_hard_v2.json")
    poison = _load(_REPO / "eval" / "datasets" / "poison_suite.json")

    # Optional representative subsetting (sample size is recorded in meta).
    full_ret_q = len(retrieval["queries"])
    full_qa_q = len(qa_hard["queries"])
    if args.retrieval_limit is not None:
        retrieval = dict(retrieval, queries=retrieval["queries"][: args.retrieval_limit])
    if args.qa_limit is not None:
        qa_hard = dict(qa_hard, queries=qa_hard["queries"][: args.qa_limit])

    print("[def] retrieval_suite on retrieval_v2 ...", file=sys.stderr)
    ret = suites.retrieval_suite(retrieval, global_flags=gf)
    print("[def] retrieval_suite on qa_hard_v2 ...", file=sys.stderr)
    ret_qa = suites.retrieval_suite(qa_hard, global_flags=gf)
    print("[def] calibration_suite on retrieval_v2 ...", file=sys.stderr)
    cal = suites.calibration_suite(retrieval, global_flags=gf)
    print("[def] answer_quality_suite (G2) on qa_hard_v2 ...", file=sys.stderr)
    g2 = suites.answer_quality_suite(qa_hard, global_flags=gf)

    lat = None
    if not args.skip_latency:
        print(f"[def] latency_suite on retrieval_v2 (postgres warm, c={args.concurrency}) ...", file=sys.stderr)
        lat = suites.latency_suite(
            retrieval, concurrency=args.concurrency, rounds=args.latency_rounds, global_flags=gf
        )

    poison_res = None
    if not args.skip_poison:
        print("[def] poison_suite_eval (G7) on poison_suite.json ...", file=sys.stderr)
        poison_res = suites.poison_suite_eval(poison, global_flags=gf)

    suite_blocks = {
        "retrieval_v2": ret,
        "retrieval_qa_hard_v2": ret_qa,
        "calibration_v2": cal,
        "answer_quality_g2_v2": g2,
    }
    if lat is not None:
        suite_blocks["fast_path_latency_v2"] = lat
    if poison_res is not None:
        suite_blocks["poison_block_g7"] = poison_res

    verdicts = [v for blk in suite_blocks.values() for v in blk.get("verdicts", [])]
    passed = sum(1 for v in verdicts if v.get("pass"))
    total = len(verdicts)

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backend": args.backend,
            "postgres_dsn_present": bool(args.postgres_dsn),
            "global_flags": gf,
            "judge": g2.get("judge"),
            "cli_python": sys.executable,
            "datasets": {
                "retrieval_v2_docs": len(retrieval["corpus"]),
                "retrieval_v2_queries_run": len(retrieval["queries"]),
                "retrieval_v2_queries_total": full_ret_q,
                "qa_hard_v2_cases_run": len(qa_hard["queries"]),
                "qa_hard_v2_cases_total": full_qa_q,
                "poison_attacks": len(poison["attacks"]),
            },
            "note": "net-new definitive runner; reuses unmodified eval/harness suites; "
            "real bge-small-en-v1.5 + cross-encoder over HTTP; postgres backend",
        },
        "overall": {"passed": passed, "total": total, "all_pass": passed == total},
        "targets": suites.SLO_TARGETS,
        "suites": suite_blocks,
    }

    # Compact scorecard to stderr.
    print(f"[def] recall@k={ret['recall_at_k']['mean']} nDCG@k={ret['ndcg_at_k']['mean']} (n={ret['n_queries']})", file=sys.stderr)
    print(f"[def] hardQA recall@k={ret_qa['recall_at_k']['mean']} nDCG@k={ret_qa['ndcg_at_k']['mean']} (n={ret_qa['n_queries']})", file=sys.stderr)
    print(f"[def] ECE={cal['ece']}", file=sys.stderr)
    print(f"[def] G2 judge={g2.get('judge')} full={g2.get('full_context_answer_rate')} mem={g2.get('memory_answer_rate')} lift={g2.get('absolute_lift')} tok_frac={g2.get('mean_token_fraction')}", file=sys.stderr)
    if lat is not None:
        print(f"[def] fast-path P95 raw={lat['raw']['p95_ms']}ms warm(engine-only)={lat['startup_adjusted']['p95_ms']}ms", file=sys.stderr)
    if poison_res is not None:
        print(f"[def] poison block_rate={poison_res['block_rate']} ({poison_res['blocked']}/{poison_res['total_attacks']})", file=sys.stderr)
    print(f"[def] verdicts {passed}/{total} pass", file=sys.stderr)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"[def] wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
