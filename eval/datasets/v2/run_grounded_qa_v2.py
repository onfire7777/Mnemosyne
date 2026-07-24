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
_SCALE_DATASET = Path(__file__).with_name("qa_scale_dev_v1.json").resolve()
_SCALE_SHA256 = "54b3cf83e95bb023f4eff65d2ac2d25eff621685d5ef9f58fd75432ac294c8d2"
_FROZEN_BATCH_TIMEOUT_SECONDS = 3600
_PREFLIGHT_SCHEMA = "grounded-qa-scale-preflight-v1"
# Immutable 12-04-01 freeze bind for 12-04-02 evidence (read-only external custody).
PHASE12_V19_FREEZE = {
    "path": str(
        Path.home()
        / ".local/share/mnemosyne/candidates/phase12-v19/candidate-manifest.json"
    ),
    "git_sha": "df438ca34061467ecc227bcf4d45bb1f7e886aee",
    "manifest_sha256": (
        "e81fc655f81ab43f1cfd5ad1b8644a9271a190027c49233efe89a2dd682c95f3"
    ),
    "candidate_version": "phase12-candidate-v19",
}


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


def _grounding_summary(traces: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate grounding/citation/abstention/second-hop/graph participation."""
    unsupported = 0
    fabricated = 0
    graph = 0
    second_hop = 0
    abstained = 0
    for trace in traces:
        retrieved = {
            cid
            for hop in trace.get("hops", []) or []
            if isinstance(hop, dict)
            for cid in hop.get("retrieved_cids", []) or []
        }
        hops = trace.get("hops", []) or []
        second_hop += int(len(hops) > 1)
        graph += int(
            bool((trace.get("graph_evidence") or {}).get("participated"))
            or any(
                channel in {"graph", "ppr"}
                for hop in hops
                if isinstance(hop, dict)
                for channel in hop.get("channels", []) or []
            )
        )
        abstained += int(trace.get("abstained") is True)
        for claim in trace.get("claims", []) or []:
            if not isinstance(claim, dict):
                continue
            citations = claim.get("evidence_cids", []) or []
            unsupported += int(not citations)
            fabricated += sum(1 for cid in citations if cid not in retrieved)
    return {
        "abstained": abstained,
        "fabricated_citations": fabricated,
        "graph_participation": graph,
        "second_hop": second_hop,
        "unsupported_claims": unsupported,
    }


def attach_custody(
    result: Mapping[str, Any],
    *,
    git_sha: str,
    candidate_manifest_sha256: str,
    candidate_version: str | None = None,
) -> dict[str, Any]:
    """Bind external candidate custody onto an evaluate() result (report surface)."""
    if not isinstance(git_sha, str) or len(git_sha) != 40 or any(
        ch not in "0123456789abcdef" for ch in git_sha
    ):
        raise ValueError("grounded QA custody git_sha is invalid")
    if (
        not isinstance(candidate_manifest_sha256, str)
        or len(candidate_manifest_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in candidate_manifest_sha256)
    ):
        raise ValueError("grounded QA custody candidate_manifest_sha256 is invalid")
    projected = dict(result)
    projected["candidate_git_sha"] = git_sha
    projected["candidate_manifest_sha256"] = candidate_manifest_sha256
    if candidate_version is not None:
        projected["candidate_version"] = _string(candidate_version, "candidate_version")
    return projected


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
        if isinstance(cli, MnemoCLI):
            cli.install_consolidation_gate_case(runtime_rows[0]["content"])
        captured = cli.capture_batch(capture_path, consolidate=True)
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
        hops = result.get("hops")
        graph_evidence = result.get("graph_evidence")
        if not isinstance(graph_evidence, dict):
            # Dual-path parity with qa_report: project participated when hop
            # channels include graph/ppr even if the CLI omitted graph_evidence.
            hop_rows = hops if isinstance(hops, list) else []
            participated = any(
                channel in {"graph", "ppr"}
                for hop in hop_rows
                if isinstance(hop, dict)
                for channel in hop.get("channels", []) or []
            )
            graph_evidence = {"participated": participated}
        traces.append(
            {
                "abstained": result.get("abstained"),
                "answer": result.get("answer"),
                "claims": result.get("claims"),
                "graph_evidence": graph_evidence,
                "hops": hops,
                "question_id": question["qid"],
                "reader": result.get("reader"),
                "retrieved_doc_ids": retrieved,
                "scoring_family": "qa",
            }
        )
    # Gold labels exist only here, for the public scorer — never in CLI payloads above.
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
        "grounding": _grounding_summary(traces),
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


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validated_preflight(
    path: Path,
    *,
    candidate_digest: str,
    runtime_digest: str,
) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("scale preflight receipt must be a real file")
    raw = path.read_bytes()
    value = json.loads(raw)
    expected = {
        "candidate_manifest_sha256",
        "dataset_sha256",
        "metrics",
        "result_sha256",
        "retrieval",
        "runtime_manifest_sha256",
        "schema",
        "trace_count",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("scale preflight receipt schema mismatch")
    if (
        value["schema"] != _PREFLIGHT_SCHEMA
        or value["candidate_manifest_sha256"] != candidate_digest
        or value["runtime_manifest_sha256"] != runtime_digest
        or value["dataset_sha256"] != _SCALE_SHA256
        or value["trace_count"] != 24
        or value["metrics"] != {"exact_match": 1.0, "token_f1": 1.0}
        or value["retrieval"] != {"ndcg_at_5": 1.0, "recall_at_5": 1.0}
        or not isinstance(value["result_sha256"], str)
        or len(value["result_sha256"]) != 64
    ):
        raise ValueError("scale preflight receipt did not pass the exact gate")
    return value, hashlib.sha256(raw).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt-ledger", type=Path)
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--preflight-receipt", type=Path)
    parser.add_argument("--write-preflight-receipt", type=Path)
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
    scale = args.dataset.resolve() == _SCALE_DATASET
    candidate_digest = hashlib.sha256(args.candidate_manifest.read_bytes()).hexdigest()
    if args.write_preflight_receipt is not None and args.write_preflight_receipt.expanduser().resolve() in {
        output,
        store,
    }:
        raise ValueError("scale preflight receipt must have a distinct external path")
    if frozen:
        if (
            not args.execute_frozen
            or args.attempt_ledger is None
            or args.runtime_manifest is None
            or args.preflight_receipt is None
            or args.write_preflight_receipt is not None
        ):
            raise ValueError(
                "frozen execution requires attempt ledger, runtime manifest, and scale preflight receipt"
            )
        if hashlib.sha256(args.dataset.read_bytes()).hexdigest() != _FROZEN_SHA256:
            raise ValueError("frozen dataset digest mismatch")
        runtime_digest = hashlib.sha256(args.runtime_manifest.read_bytes()).hexdigest()
        _, preflight_digest = _validated_preflight(
            args.preflight_receipt,
            candidate_digest=candidate_digest,
            runtime_digest=runtime_digest,
        )
        runtime_env = grounded_runtime_environment(
            args.runtime_manifest, candidate, args.ollama_url, repo_root=_ROOT
        )
        attempt_root = (Path.home() / ".local/state/mnemosyne/qa-attempts").resolve()
        if args.attempt_ledger.expanduser().resolve() != attempt_root:
            raise ValueError(f"attempt root must be the canonical path: {attempt_root}")
        attempt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        ledger = attempt_root / f"{candidate_digest}-qa_hard_v2.json"
        _write_exclusive(
            ledger,
            {
                "candidate_manifest_sha256": candidate_digest,
                "dataset_sha256": _FROZEN_SHA256,
                "preflight_receipt_sha256": preflight_digest,
                "runtime_manifest_sha256": runtime_digest,
                "split": "qa_hard_v2",
            },
        )
    else:
        if args.execute_frozen:
            raise ValueError("--execute-frozen is restricted to canonical qa_hard_v2")
        if args.preflight_receipt is not None:
            raise ValueError("--preflight-receipt is restricted to frozen execution")
        if args.write_preflight_receipt is not None and (
            not scale or args.runtime_manifest is None
        ):
            raise ValueError(
                "scale preflight receipts require the canonical scale dataset and runtime manifest"
            )
        if scale and hashlib.sha256(args.dataset.read_bytes()).hexdigest() != _SCALE_SHA256:
            raise ValueError("scale preflight dataset digest mismatch")
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
        timeout_s=_FROZEN_BATCH_TIMEOUT_SECONDS if frozen or scale else 120.0,
    )
    result = attach_custody(
        evaluate(dataset, cli),
        git_sha=str(expected_sha),
        candidate_manifest_sha256=candidate_digest,
        candidate_version=(
            str(candidate["candidate_version"])
            if isinstance(candidate.get("candidate_version"), str)
            else None
        ),
    )
    if args.write_preflight_receipt is not None:
        metrics = result.get("qa", {}).get("metrics")
        retrieval = result.get("retrieval")
        if (
            result.get("trace_count") != 24
            or metrics != {"exact_match": 1.0, "token_f1": 1.0}
            or retrieval != {"ndcg_at_5": 1.0, "recall_at_5": 1.0}
            or any(row.get("abstained") is not False for row in result.get("traces", []))
        ):
            raise ValueError("scale preflight result did not pass the exact gate")
        receipt = _external_new_path(
            args.write_preflight_receipt, "scale preflight receipt"
        )
        _write_exclusive(
            receipt,
            {
                "candidate_manifest_sha256": candidate_digest,
                "dataset_sha256": _SCALE_SHA256,
                "metrics": metrics,
                "result_sha256": _digest(result),
                "retrieval": retrieval,
                "runtime_manifest_sha256": hashlib.sha256(
                    args.runtime_manifest.read_bytes()
                ).hexdigest(),
                "schema": _PREFLIGHT_SCHEMA,
                "trace_count": 24,
            },
        )
    _write_exclusive(output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
