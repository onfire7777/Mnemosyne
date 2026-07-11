"""Public-CLI-only grounded QA evaluator with scorer-isolated gold labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from eval.harness.cli_driver import MnemoCLI
from eval.public.runner import require_clean_candidate_checkout, validate_candidate_manifest
from eval.public.runtime_custody import grounded_runtime_environment
from eval.public.scoring import score_profile


_GOLD_FIELDS = {"gold_answer", "gold_aliases", "relevant_doc_ids", "distractor_answer"}
_ROOT = Path(__file__).resolve().parents[3]
_FROZEN_DATASET = Path(__file__).with_name("qa_hard_v2.json").resolve()
_FROZEN_SHA256 = "1864974807f2171904a5e5f04b727b3cbfb258f94c1280106ecc08a4dade52e2"
_FROZEN_BATCH_TIMEOUT_SECONDS = 3600


def load_dataset(path: Path, *, allow_frozen: bool = False) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("grounded QA dataset must be a real file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("corpus"), list) or not isinstance(value.get("queries"), list):
        raise ValueError("grounded QA dataset schema is invalid")
    if value.get("dataset_id") == "qa_hard_v2" and (
        not allow_frozen or path.resolve() != _FROZEN_DATASET
    ):
        raise ValueError("qa_hard_v2 is frozen and bound to its canonical path")
    if not value["corpus"] or not value["queries"]:
        raise ValueError("grounded QA dataset is empty")
    return value


def compare_retrieval_baseline(
    measured: Mapping[str, float], baseline: Mapping[str, float]
) -> dict[str, Any]:
    missing = set(baseline) - set(measured)
    regressions = {
        key: {"baseline": baseline[key], "measured": measured[key]}
        for key in baseline
        if key in measured and measured[key] < baseline[key]
    }
    return {"passed": not missing and not regressions, "missing": sorted(missing), "regressions": regressions}


def evaluate(dataset: dict[str, Any], cli: MnemoCLI) -> dict[str, Any]:
    """Capture/query through public CLI; introduce answers only inside scoring."""
    tenant = _string(dataset.get("tenant"), "tenant")
    user = _string(dataset.get("user"), "user")
    corpus = dataset["corpus"]
    questions = dataset["queries"]
    runtime_rows = [
        {
            "tenant": tenant,
            "user": user,
            "source_type": "qa-v2-dev",
            "source_identity": _string(row.get("doc_id"), "doc_id"),
            "content": _string(row.get("content"), "content"),
            "trust_tier": int(row.get("trust_tier", 0)),
        }
        for row in corpus
    ]
    with tempfile.TemporaryDirectory(prefix="mneme-qa-v2-") as temp:
        capture_path = Path(temp) / "corpus.jsonl"
        capture_path.write_text(_jsonl(runtime_rows), encoding="utf-8")
        captured = cli.capture_batch(capture_path)
        capture_results = captured.get("results")
        if not isinstance(capture_results, list) or len(capture_results) != len(runtime_rows):
            raise ValueError("grounded QA capture count mismatch")
        cid_to_doc: dict[str, str] = {}
        for runtime, result in zip(runtime_rows, capture_results, strict=True):
            cid = result.get("cid") if isinstance(result, dict) else None
            if not isinstance(cid, str) or not cid or cid in cid_to_doc:
                raise ValueError("grounded QA capture CID custody is invalid")
            cid_to_doc[cid] = runtime["source_identity"]
        answer_rows = [
            {
                "question_id": _string(row.get("qid"), "qid"),
                "question": _string(row.get("query"), "query"),
                "context": {"tenant_id": tenant, "user_id": user, "role": "reader"},
            }
            for row in questions
        ]
        if any(_GOLD_FIELDS & set(row) for row in answer_rows):
            raise AssertionError("gold fields crossed the scorer boundary")
        answer_path = Path(temp) / "answers.jsonl"
        answer_path.write_text(_jsonl(answer_rows), encoding="utf-8")
        answer_cli = (
            replace(
                cli,
                global_flags=[
                    *[flag for flag in cli.global_flags if flag != "--evaluation-read-only"],
                    "--evaluation-read-only",
                ],
            )
            if isinstance(cli, MnemoCLI)
            else cli
        )
        answered = answer_cli.eval_answer_batch(answer_path)
    results = answered.get("results")
    if not isinstance(results, list) or len(results) != len(questions):
        raise ValueError("grounded QA answer count mismatch")
    if [row.get("question_id") for row in results if isinstance(row, dict)] != [row["qid"] for row in questions]:
        raise ValueError("grounded QA answer order drift")
    traces, retrieval_scores = [], []
    for question, result in zip(questions, results, strict=True):
        if not isinstance(result, dict):
            raise ValueError("grounded QA answer row is invalid")
        retrieved = list(
            dict.fromkeys(
                cid_to_doc[cid]
                for hop in result.get("hops", [])
                for cid in hop.get("retrieved_cids", [])
                if cid in cid_to_doc
            )
        )
        gold_docs = _strings(question.get("relevant_doc_ids"), "relevant_doc_ids")
        retrieval_scores.append(_retrieval_score(retrieved[:5], gold_docs))
        traces.append(
            {
                "abstained": result.get("abstained"),
                "answer": result.get("answer"),
                "claims": result.get("claims"),
                "hops": result.get("hops"),
                "question_id": question["qid"],
                "reader": result.get("reader"),
                "retrieved_doc_ids": retrieved,
                "scoring_family": "qa",
            }
        )
    labels = [
        {
            "answers": list(dict.fromkeys([
                _string(question.get("gold_answer"), "gold_answer"),
                *_strings(question.get("gold_aliases"), "gold_aliases"),
            ])),
            "question_id": question["qid"],
        }
        for question in questions
    ]
    qa = score_profile("qa-em-f1-v1", labels, traces)
    retrieval = {
        "recall_at_5": sum(row[0] for row in retrieval_scores) / len(retrieval_scores),
        "ndcg_at_5": sum(row[1] for row in retrieval_scores) / len(retrieval_scores),
    }
    return {
        "dataset_id": dataset.get("dataset_id"),
        "qa": qa,
        "retrieval": retrieval,
        "trace_count": len(traces),
        "traces": traces,
    }


def _retrieval_score(ranked: list[str], gold: list[str]) -> tuple[float, float]:
    recall = len(set(ranked) & set(gold)) / len(gold)
    dcg = sum(1 / math.log2(index + 2) for index, item in enumerate(ranked) if item in set(gold))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(5, len(gold))))
    return recall, dcg / ideal


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must be a non-empty string list")
    return value


def _external_new_path(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == _ROOT or _ROOT in resolved.parents:
        raise ValueError(f"{label} must be external to the repository")
    if path.is_symlink() or resolved.exists():
        raise FileExistsError(f"{label} must be a new non-symlink path")
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return resolved


def _write_exclusive(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt-ledger", type=Path)
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--execute-frozen", action="store_true")
    args = parser.parse_args(argv)
    if args.candidate_manifest.is_symlink() or not args.candidate_manifest.is_file():
        raise ValueError("candidate manifest must be a real file")
    candidate = json.loads(args.candidate_manifest.read_text(encoding="utf-8"))
    expected_sha = os.environ.get("MNEMOSYNE_CANDIDATE_GIT_SHA") or candidate.get("git_sha")
    validate_candidate_manifest(candidate, expected_git_sha=expected_sha)
    require_clean_candidate_checkout(expected_sha)
    output = _external_new_path(args.output, "grounded QA output")
    store = _external_new_path(args.store, "grounded QA store")
    frozen = args.dataset.resolve() == _FROZEN_DATASET
    if frozen:
        if not args.execute_frozen or args.attempt_ledger is None or args.runtime_manifest is None:
            raise ValueError("frozen execution requires attempt ledger and runtime manifest")
        if hashlib.sha256(args.dataset.read_bytes()).hexdigest() != _FROZEN_SHA256:
            raise ValueError("frozen dataset digest mismatch")
        runtime_env = grounded_runtime_environment(
            args.runtime_manifest, candidate, args.ollama_url, repo_root=_ROOT
        )
        attempt_root = (Path.home() / ".local/state/mnemosyne/qa-attempts").resolve()
        if args.attempt_ledger.expanduser().resolve() != attempt_root:
            raise ValueError(f"attempt root must be the canonical path: {attempt_root}")
        attempt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        candidate_digest = hashlib.sha256(args.candidate_manifest.read_bytes()).hexdigest()
        ledger = attempt_root / f"{candidate_digest}-qa_hard_v2.json"
        _write_exclusive(
            ledger,
            {
                "candidate_manifest_sha256": candidate_digest,
                "dataset_sha256": _FROZEN_SHA256,
                "runtime_manifest_sha256": hashlib.sha256(args.runtime_manifest.read_bytes()).hexdigest(),
                "split": "qa_hard_v2",
            },
        )
    else:
        if args.execute_frozen:
            raise ValueError("--execute-frozen is restricted to canonical qa_hard_v2")
        runtime_env = (
            grounded_runtime_environment(
                args.runtime_manifest, candidate, args.ollama_url, repo_root=_ROOT
            )
            if args.runtime_manifest is not None
            else {}
        )
    dataset = load_dataset(args.dataset, allow_frozen=frozen)
    cli = MnemoCLI(
        store=str(store),
        env=runtime_env,
        timeout_s=_FROZEN_BATCH_TIMEOUT_SECONDS if frozen else 120.0,
    )
    result = evaluate(dataset, cli)
    result["candidate_manifest_sha256"] = hashlib.sha256(args.candidate_manifest.read_bytes()).hexdigest()
    _write_exclusive(output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
