"""SLO measurement suites driven through the public CLI.

Each function loads a seed dataset, drives the CLI, and returns a structured
result block with metrics + confidence intervals + an SLO verdict. The blueprint
targets (§16) are encoded as the ``target`` field on each verdict.

Suites:
  * retrieval_suite       -> recall@k, nDCG@k (FR-3)
  * latency_suite         -> fast-path P95 under concurrent load (§16 ≤300-400ms)
  * calibration_suite     -> ECE (§16 ≤0.05, FR-6) + abstention precision
  * answer_quality_suite  -> G2 (+15% vs full context at ≤10% tokens)
  * poison_suite_eval     -> G7 poison block rate (≥95%)
"""

from __future__ import annotations

import concurrent.futures
import statistics
import tempfile
import uuid
from pathlib import Path
from typing import Any

from . import metrics
from .answer_quality import AnswerCase, count_tokens, make_judge, score_answer_cases
from .cli_driver import MnemoCLI


# Blueprint §16 SLO targets.
SLO_TARGETS = {
    "fast_path_p95_ms": 400.0,          # §16 P95 ≤ ~300-400 ms (we use the looser bound)
    "ece_max": 0.05,                    # §16 ECE ≤ 0.05
    "g2_min_lift": 0.15,                # §16 +15% answer quality vs full context
    "g2_max_token_fraction": 0.10,      # ... at ≤10% tokens
    "poison_block_rate_min": 0.95,      # §16 G7 ≥95% block
    "recall_at_k_min": 0.80,            # internal seed target (not a public benchmark, §12 N3)
    "ndcg_at_k_min": 0.80,
}


# Backend selection is process-global for a run; the runner sets it once via
# ``configure_backend`` so every suite's fresh CLI inherits it without threading
# the argument through every signature.
_BACKEND = {"backend": "local", "postgres_dsn": None}


def configure_backend(backend: str = "local", postgres_dsn: str | None = None) -> None:
    _BACKEND["backend"] = backend
    _BACKEND["postgres_dsn"] = postgres_dsn


def _fresh_cli(global_flags: list[str] | None = None) -> MnemoCLI:
    store = Path(tempfile.gettempdir()) / f"mnemo_slo_{uuid.uuid4().hex}.json"
    return MnemoCLI(
        store=str(store),
        backend=_BACKEND["backend"],
        postgres_dsn=_BACKEND["postgres_dsn"],
        global_flags=global_flags or [],
    )


def _load_corpus(cli: MnemoCLI, dataset: dict) -> dict[str, str]:
    """Capture every corpus doc; return cid -> doc_id mapping for relevance scoring.

    We tag each capture's source_type with the doc_id so we can map the opaque
    evidence cid the CLI returns back to the labelled doc_id.
    """
    tenant = dataset["tenant"]
    user = dataset.get("user", "eval-user")
    cid_to_doc: dict[str, str] = {}
    for doc in dataset["corpus"]:
        res = cli.capture(
            tenant,
            user,
            doc["content"],
            source_type=f"seed:{doc['doc_id']}",
            trust_tier=int(doc.get("trust_tier", 0)),
        )
        cid_to_doc[res["cid"]] = doc["doc_id"]
    return cid_to_doc


# --------------------------------------------------------------------------- #
# Retrieval: recall@k / nDCG@k
# --------------------------------------------------------------------------- #
def retrieval_suite(dataset: dict, *, global_flags: list[str] | None = None) -> dict[str, Any]:
    cli = _fresh_cli(global_flags)
    tenant = dataset["tenant"]
    k = int(dataset.get("k", 5))
    cid_to_doc = _load_corpus(cli, dataset)

    per_query: list[dict[str, Any]] = []
    recalls: list[float] = []
    ndcgs: list[float] = []
    abstain_correct = 0
    abstain_total = 0
    for q in dataset["queries"]:
        res = cli.search(tenant, q["query"])
        hits = res.get("hits", [])
        retrieved_doc_ids = [cid_to_doc.get(h["id"], h["id"]) for h in hits]
        relevant = q.get("relevant_doc_ids", [])
        if not q.get("answerable", True):
            abstain_total += 1
            abstained = bool(res.get("abstained"))
            abstain_correct += int(abstained)
            per_query.append({"qid": q["qid"], "answerable": False, "abstained": abstained})
            continue
        r = metrics.recall_at_k(retrieved_doc_ids, relevant, k)
        nd = metrics.ndcg_at_k(retrieved_doc_ids, relevant, k)
        recalls.append(r)
        ndcgs.append(nd)
        per_query.append(
            {
                "qid": q["qid"],
                "recall_at_k": round(r, 4),
                "ndcg_at_k": round(nd, 4),
                "retrieved": retrieved_doc_ids[:k],
                "relevant": relevant,
            }
        )

    recall_ci = metrics.bootstrap_mean_interval(recalls)
    ndcg_ci = metrics.bootstrap_mean_interval(ndcgs)
    mean_recall = statistics.fmean(recalls) if recalls else 0.0
    mean_ndcg = statistics.fmean(ndcgs) if ndcgs else 0.0
    abstain_precision = (abstain_correct / abstain_total) if abstain_total else None

    return {
        "suite": "retrieval",
        "k": k,
        "n_queries": len(recalls),
        "recall_at_k": {"mean": round(mean_recall, 4), **recall_ci.as_dict()},
        "ndcg_at_k": {"mean": round(mean_ndcg, 4), **ndcg_ci.as_dict()},
        "abstention": {
            "unanswerable_cases": abstain_total,
            "correctly_abstained": abstain_correct,
            "precision": abstain_precision,
        },
        "verdicts": [
            _verdict("recall@k", mean_recall, SLO_TARGETS["recall_at_k_min"], ">=", recall_ci),
            _verdict("nDCG@k", mean_ndcg, SLO_TARGETS["ndcg_at_k_min"], ">=", ndcg_ci),
        ],
        "per_query": per_query,
    }


# --------------------------------------------------------------------------- #
# Latency: fast-path P95 under concurrent load
# --------------------------------------------------------------------------- #
def latency_suite(
    dataset: dict,
    *,
    concurrency: int = 8,
    rounds: int = 6,
    global_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Measure fast-path read latency under concurrent load.

    We issue ``concurrency * rounds`` concurrent ``mneme search`` calls and record
    per-call wall time. NOTE: each call is a fresh Python process, so the numbers
    include interpreter + import startup and are a CONSERVATIVE UPPER BOUND on the
    engine's own fast-path latency. The report labels this. With the postgres
    backend + a long-lived server the same harness measures true service latency.
    """
    import shutil

    cli = _fresh_cli(global_flags)
    tenant = dataset["tenant"]
    _load_corpus(cli, dataset)
    queries = [q["query"] for q in dataset["queries"] if q.get("answerable", True)]
    if not queries:
        queries = [q["query"] for q in dataset["queries"]]

    # Startup baseline: time the cheapest CLI command (``tools``) which lists the
    # tool surface WITHOUT touching the store or running retrieval. The median of
    # these is the per-process interpreter+import overhead we subtract to estimate
    # the engine's own fast-path latency (the SLO is about service latency, not
    # Python cold-start). With a long-lived server backend this overhead is paid
    # once, not per request — so this adjustment is the honest apples-to-apples.
    baseline_samples: list[float] = []
    for _ in range(max(4, concurrency)):
        res = cli.run("tools", check=False, parse_json=False)
        baseline_samples.append(res.wall_ms)
    baseline = metrics.percentile(baseline_samples, 0.5)

    # Concurrency model. The LOCAL single-file backend writes runtime state on
    # every read and is NOT safe for concurrent writers sharing one store file
    # (atomic-replace races) — by design it is a single-process store; production
    # concurrency is the Postgres backend's job (§16/§I). To measure parallel-load
    # latency faithfully WITHOUT manufacturing artificial single-file write
    # contention, each concurrent worker gets its own clone of the pre-warmed
    # store. On the postgres backend all workers share the real concurrent-safe
    # store (no cloning) — pass --backend postgres for true shared-load numbers.
    is_local = _BACKEND["backend"] == "local"
    worker_clis: list[MnemoCLI] = []
    if is_local:
        warm_store = Path(cli.store)
        for w in range(concurrency):
            clone = warm_store.with_name(f"{warm_store.stem}_w{w}.json")
            shutil.copyfile(warm_store, clone)
            rstate = warm_store.with_suffix(warm_store.suffix + ".runtime.json")
            if rstate.exists():
                shutil.copyfile(rstate, clone.with_suffix(clone.suffix + ".runtime.json"))
            worker_clis.append(
                MnemoCLI(store=str(clone), backend="local", global_flags=global_flags or [])
            )
    else:
        worker_clis = [cli] * concurrency

    tasks = [(i % concurrency, queries[i % len(queries)]) for i in range(concurrency * rounds)]
    latencies: list[float] = []

    def _one(item: tuple[int, str]) -> float:
        worker_idx, query = item
        _, ms = worker_clis[worker_idx].timed_search(tenant, query)
        return ms

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        for ms in pool.map(_one, tasks):
            latencies.append(ms)

    summary = metrics.latency_summary(latencies)
    p95_ci = metrics.bootstrap_percentile_interval(latencies, 0.95)
    # Startup-adjusted (engine-only) estimate: subtract the per-process baseline.
    adjusted = [max(0.0, ms - baseline) for ms in latencies]
    adj_summary = metrics.latency_summary(adjusted)
    adj_p95_ci = metrics.bootstrap_percentile_interval(adjusted, 0.95)
    target = SLO_TARGETS["fast_path_p95_ms"]
    return {
        "suite": "fast_path_latency",
        "measurement": "subprocess wall time; raw includes per-process interpreter+import startup",
        "concurrency": concurrency,
        "concurrency_model": (
            "local: per-worker cloned pre-warmed store (single-file backend is single-writer by design)"
            if is_local
            else "postgres: shared concurrent-safe store (true shared load)"
        ),
        "total_calls": len(latencies),
        "startup_baseline_ms": round(baseline, 2),
        "raw": {
            "p50_ms": round(summary.p50, 2),
            "p95_ms": round(summary.p95, 2),
            "p99_ms": round(summary.p99, 2),
            "mean_ms": round(summary.mean, 2),
            "max_ms": round(summary.maximum, 2),
            "p95_ci": p95_ci.as_dict(),
        },
        "startup_adjusted": {
            "p50_ms": round(adj_summary.p50, 2),
            "p95_ms": round(adj_summary.p95, 2),
            "p99_ms": round(adj_summary.p99, 2),
            "p95_ci": adj_p95_ci.as_dict(),
            "note": "engine-only estimate = raw - median(startup baseline); this is what a "
            "long-lived server backend would expose. The raw P95 is a CLI-cold-start upper bound.",
        },
        # Backward-compatible top-level fields (raw).
        "p50_ms": round(summary.p50, 2),
        "p95_ms": round(summary.p95, 2),
        "p99_ms": round(summary.p99, 2),
        "mean_ms": round(summary.mean, 2),
        "max_ms": round(summary.maximum, 2),
        "p95_ci": p95_ci.as_dict(),
        "verdicts": [
            _verdict("fast_path_p95_ms_raw", summary.p95, target, "<=", p95_ci),
            _verdict("fast_path_p95_ms_engine_only", adj_summary.p95, target, "<=", adj_p95_ci),
        ],
    }


# --------------------------------------------------------------------------- #
# Calibration: ECE + abstention
# --------------------------------------------------------------------------- #
def calibration_suite(dataset: dict, *, global_flags: list[str] | None = None) -> dict[str, Any]:
    """Derive (confidence, correct) pairs from real CLI searches and compute ECE.

    For each answerable query, confidence = the CLI's reported ``confidence`` and
    correct = whether the gold answer appears in the returned hits (a real, judge-
    free correctness signal). Unanswerable queries contribute (confidence, correct=
    not-answered) so over-confidence on abstain cases is penalised.
    """
    from .answer_quality import substring_judge

    cli = _fresh_cli(global_flags)
    tenant = dataset["tenant"]
    _load_corpus(cli, dataset)
    confidences: list[float] = []
    correct: list[bool] = []
    rows: list[dict[str, Any]] = []
    for q in dataset["queries"]:
        res = cli.search(tenant, q["query"])
        conf = float(res.get("confidence", 0.0))
        abstained = bool(res.get("abstained"))
        ctx = " ".join(h.get("text") or "" for h in res.get("hits", []))
        gold = q.get("gold_answer") or ""
        if q.get("answerable", True):
            is_correct = substring_judge(q["query"], ctx, gold) >= 1.0
        else:
            # correct iff it abstained / surfaced nothing
            is_correct = abstained or not ctx.strip()
        # When the system abstains, its *effective* confidence in an answer is low.
        effective_conf = 0.0 if abstained else conf
        confidences.append(effective_conf)
        correct.append(is_correct)
        rows.append(
            {"qid": q["qid"], "confidence": round(effective_conf, 4), "correct": is_correct, "abstained": abstained}
        )

    ece = metrics.expected_calibration_error(confidences, correct, n_bins=10)
    acc = sum(1 for c in correct if c)
    acc_ci = metrics.wilson_interval(acc, len(correct))
    # Cross-check against the public calibration-tune command on the same labels.
    cal_dataset = [{"confidence": c, "correct": bool(ok)} for c, ok in zip(confidences, correct)]
    tune = cli.calibration_tune(tenant, cal_dataset, dry_run=True, min_examples=1)

    target = SLO_TARGETS["ece_max"]
    ece_verdict = {
        "name": "ece",
        "value": round(ece.ece, 4),
        "target": target,
        "op": "<=",
        "pass": (ece.ece <= target) if ece.n else False,
        "ci": None,
    }
    return {
        "suite": "calibration",
        "n": ece.n,
        "ece": round(ece.ece, 4),
        "bins": ece.bins,
        "accuracy": {"value": round(acc / len(correct), 4) if correct else 0.0, **acc_ci.as_dict()},
        "calibration_tune_crosscheck": {
            "threshold": tune.get("threshold"),
            "metrics": tune.get("metrics"),
            "ok": tune.get("ok"),
        },
        "verdicts": [ece_verdict],
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# Answer quality: G2 (+15% vs full context at <=10% tokens)
# --------------------------------------------------------------------------- #
def answer_quality_suite(dataset: dict, *, global_flags: list[str] | None = None) -> dict[str, Any]:
    """G2: answer quality vs full context at ≤10% tokens.

    The memory context is a **budget-constrained** slice: we greedily add the
    highest-ranked hits until adding the next would exceed 10% of the full-corpus
    token count. This is the honest G2 setup — the memory layer must answer from a
    tiny slice, not the whole top-k.

    Two verdicts:
      * ``g2_answer_quality_lift`` — memory answer-rate minus full-context rate
        (the blueprint's literal +15% target). With a strict LLM judge this is the
        real signal; with the deterministic substring judge full-context trivially
        contains every answer, so this verdict is naturally hard to pass and is
        reported as a floor (see note).
      * ``g2_token_efficiency`` — the *achievable-now* proxy: memory must reach
        ≥ (full-context answer-rate − small epsilon) **using ≤10% of the tokens.**
        This proves the efficiency claim that G2 is really about, and it is
        meaningful under the deterministic judge.
    """
    cli = _fresh_cli(global_flags)
    tenant = dataset["tenant"]
    _load_corpus(cli, dataset)
    judge, judge_name = make_judge()

    full_context = "\n".join(doc["content"] for doc in dataset["corpus"])
    full_tokens, _ = count_tokens(full_context)
    budget_tokens = max(1, int(full_tokens * SLO_TARGETS["g2_max_token_fraction"]))

    cases: list[AnswerCase] = []
    for q in dataset["queries"]:
        if not q.get("answerable", True):
            continue
        res = cli.search(tenant, q["query"])
        # Greedily fill the token budget with the highest-ranked hits.
        slice_texts: list[str] = []
        used = 0
        for h in res.get("hits", []):
            txt = h.get("text") or ""
            t, _ = count_tokens(txt)
            if slice_texts and used + t > budget_tokens:
                break
            slice_texts.append(txt)
            used += t
        mem_ctx = " ".join(slice_texts)
        cases.append(
            AnswerCase(
                qid=q["qid"],
                question=q["query"],
                gold=q.get("gold_answer"),
                full_context=full_context,
                memory_context=mem_ctx,
                answerable=True,
            )
        )
    scores = score_answer_cases(cases, judge, token_budget_fraction=SLO_TARGETS["g2_max_token_fraction"])
    if not scores:
        return {"suite": "answer_quality_g2", "judge": judge_name, "n": 0, "verdicts": []}

    full_rate = statistics.fmean(s.full_score for s in scores)
    mem_rate = statistics.fmean(s.memory_score for s in scores)
    lift = mem_rate - full_rate
    rel_lift = (lift / full_rate) if full_rate > 0 else (mem_rate if mem_rate > 0 else 0.0)
    mean_token_fraction = statistics.fmean(s.token_fraction for s in scores)
    within_budget = all(s.within_budget for s in scores)
    lift_ci = metrics.bootstrap_mean_interval([s.memory_score - s.full_score for s in scores])
    mem_rate_ci = metrics.bootstrap_mean_interval([s.memory_score for s in scores])

    g2_lift_pass = (lift >= SLO_TARGETS["g2_min_lift"]) and within_budget
    # Token-efficiency proxy: parity (within 5pp) at <=10% tokens.
    efficiency_pass = within_budget and (mem_rate >= full_rate - 0.05)

    return {
        "suite": "answer_quality_g2",
        "judge": judge_name,
        "n": len(scores),
        "full_corpus_tokens": full_tokens,
        "token_budget": budget_tokens,
        "full_context_answer_rate": round(full_rate, 4),
        "memory_answer_rate": round(mem_rate, 4),
        "absolute_lift": round(lift, 4),
        "relative_lift": round(rel_lift, 4),
        "mean_token_fraction": round(mean_token_fraction, 4),
        "within_token_budget": within_budget,
        "lift_ci": lift_ci.as_dict(),
        "memory_rate_ci": mem_rate_ci.as_dict(),
        "verdicts": [
            {
                "name": "g2_answer_quality_lift",
                "value": round(lift, 4),
                "target": SLO_TARGETS["g2_min_lift"],
                "op": ">=",
                "pass": g2_lift_pass,
                "note": f"absolute lift vs full context at token-fraction {round(mean_token_fraction,4)}; "
                f"under the deterministic substring judge full-context is a 1.0 ceiling so this is a FLOOR — "
                f"set MNEMO_EVAL_JUDGE_CMD for the real signal",
                "ci": lift_ci.as_dict(),
            },
            {
                "name": "g2_token_efficiency",
                "value": round(mem_rate, 4),
                "target": round(full_rate - 0.05, 4),
                "op": ">=",
                "pass": efficiency_pass,
                "note": f"answer-rate parity (within 5pp of full-context {round(full_rate,4)}) using "
                f"≤{int(SLO_TARGETS['g2_max_token_fraction']*100)}% of tokens (mean {round(mean_token_fraction,4)})",
                "ci": mem_rate_ci.as_dict(),
            },
        ],
        "per_query": [
            {
                "qid": s.qid,
                "full": s.full_score,
                "memory": s.memory_score,
                "token_fraction": round(s.token_fraction, 4),
                "within_budget": s.within_budget,
            }
            for s in scores
        ],
    }


# --------------------------------------------------------------------------- #
# Poison block rate (G7)
# --------------------------------------------------------------------------- #
def poison_suite_eval(dataset: dict, *, global_flags: list[str] | None = None) -> dict[str, Any]:
    cli = _fresh_cli(global_flags)
    tenant = dataset["tenant"]
    user = dataset.get("user", "eval-user")
    max_trust = int(dataset.get("max_trust_tier_for_read", 2))
    # Load benign corpus.
    for doc in dataset.get("benign_corpus", []):
        cli.capture(tenant, user, doc["content"], source_type="seed", trust_tier=int(doc.get("trust_tier", 0)))

    blocked = 0
    rows: list[dict[str, Any]] = []
    for attack in dataset["attacks"]:
        poison_cid = cli.capture(
            tenant,
            "attacker",
            attack["injected_content"],
            source_type="shared-memory",
            actor="external",
            trust_tier=int(attack["injected_trust_tier"]),
        )["cid"]
        # Trust-filtered read (the rail). Attack is BLOCKED if the injected
        # instruction does not surface in the filtered read.
        res = cli.search(tenant, attack["probe_query"], max_trust_tier=max_trust)
        marker = attack.get("marker", "")
        surfaced = any(
            (h.get("id") == poison_cid) or (marker and marker.lower() in (h.get("text") or "").lower())
            for h in res.get("hits", [])
        )
        is_blocked = not surfaced
        blocked += int(is_blocked)
        rows.append(
            {
                "attack_id": attack["attack_id"],
                "family": attack.get("family"),
                "blocked": is_blocked,
                "injected_trust_tier": attack["injected_trust_tier"],
            }
        )

    total = len(dataset["attacks"])
    rate = blocked / total if total else 0.0
    ci = metrics.wilson_interval(blocked, total)
    target = SLO_TARGETS["poison_block_rate_min"]
    return {
        "suite": "poison_block_rate_g7",
        "total_attacks": total,
        "blocked": blocked,
        "block_rate": round(rate, 4),
        "block_rate_ci": ci.as_dict(),
        "verdicts": [_verdict("poison_block_rate", rate, target, ">=", ci)],
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _verdict(name: str, value: float, target: float, op: str, ci: "metrics.Interval | None") -> dict[str, Any]:
    if op == ">=":
        passed = value >= target
    elif op == "<=":
        passed = value <= target
    else:
        raise ValueError(f"unknown op {op}")
    out = {"name": name, "value": round(value, 4), "target": target, "op": op, "pass": bool(passed)}
    out["ci"] = ci.as_dict() if ci is not None else None
    return out
