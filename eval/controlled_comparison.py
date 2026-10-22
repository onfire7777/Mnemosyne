"""Reproducible paired evaluation; native Hindsight runs in a separate environment."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from threading import Event
import time
from typing import Any

from eval.runner_lock import exclusive_runner

from eval.codex_reader import read_with_codex
from eval.comparison_protocol import (
    ARMS, MODEL, REASONING_EFFORT, canonical_sha256, inference_payload,
    pack_context, score_comparison, select_question_ids, selection_manifest, validate_manifest,
)
from eval.longmemeval_recall import benchmark_timestamp
from eval.longmemeval_s.run_bench_LongMemEval import judge_prompt, rounds_of
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy

ROOT = Path(__file__).resolve().parents[1]
HINDSIGHT_COMMIT = "0691b504a88480844b2db53384b8c81971b7cf1e"
DATASET_SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
READER_TEMPLATE = (
    "Answer the question using only the retrieved memory excerpts below. Preserve dates, "
    "updates, speaker attribution and uncertainty. Give a concise but complete answer. "
    "If the excerpts do not contain enough evidence, answer 'I do not know'.\n\n"
    "Retrieved memories:\n{context}\n\nCurrent date: {date}\nQuestion: {question}\nAnswer:"
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, path)  # Atomic publication that fails if an earlier result exists.
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def dataset(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DATASET_SHA256:
        raise ValueError("dataset differs from pinned cleaned LongMemEval-S asset")
    return json.loads(raw)


def source_hashes() -> dict[str, str]:
    # PostgreSQL is validated independently; this arm uses only LocalMemoryEngine.
    files = sorted((ROOT / "src/mnemosyne").rglob("*.py"))
    files = [path for path in files if not path.name.startswith("postgres")]
    files += [ROOT / "eval" / name for name in (
        "codex_reader.py", "codex_bridge.py", "comparison_protocol.py", "controlled_comparison.py", "runner_lock.py",
        "longmemeval_recall.py", "longmemeval_s/run_bench_LongMemEval.py", "harness/metrics.py",
    )]
    files += sorted((ROOT / "eval/hindsight_adapter").glob("*.py"))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def local_runtime() -> dict:
    packages = {}
    for name in ("cryptography", "numpy", "jsonschema"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    codex = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=True, timeout=10)
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages,
            "codex_version": codex.stdout.strip(), "mnemosyne_environment_sha256": canonical_sha256({
                key: value for key, value in os.environ.items() if key.startswith(("MNEMOSYNE_", "MNEME_"))
            })}


def prepare(data: Path, run: Path, inputs: Path) -> None:
    rows = dataset(data)
    by_id = {row["question_id"]: row for row in rows}
    clean = [{"question_id": qid, **inference_payload(by_id[qid])} for qid in select_question_ids(rows)]
    native_environment = read_json(run.parent / "hindsight-environment.json")
    config = {
        "hindsight_commit": HINDSIGHT_COMMIT,
        "mnemosyne": {"backend": "LocalMemoryEngine", "ingestion": "user-assistant rounds",
                      "mode": "default", "candidate_limit": 200, "policy_token_budget": 262144,
                      "embedding": "built-in hashing", "reranker": "local/default, not neural"},
        "hindsight": {"backend": "native PostgreSQL", "ingestion": "full session documents",
                      "embedding": "BAAI/bge-small-en-v1.5",
                      "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                      "consolidation": "native synchronous", "recall": "native default",
                      "retain_chunk_characters": 32000},
        "hindsight_runtime_sha256": canonical_sha256(native_environment),
        "reader_template": READER_TEMPLATE, "input_sha256": canonical_sha256(clean),
        "local_runtime": local_runtime(),
        "source_sha256": source_hashes(),
    }
    manifest = selection_manifest(rows, DATASET_SHA256, source_config_sha256=canonical_sha256(config))
    write_new(run / "configuration.json", config)
    write_new(run / "manifest.json", manifest)
    write_new(inputs, clean)
    print(json.dumps({"manifest_sha256": manifest["manifest_sha256"], "questions": len(clean),
                      "sessions": sum(len(row["sessions"]) for row in clean)}), flush=True)


def check_frozen(run: Path, inputs: Path) -> tuple[dict, list[dict]]:
    manifest, config, clean = read_json(run / "manifest.json"), read_json(run / "configuration.json"), read_json(inputs)
    validate_manifest(manifest)
    if canonical_sha256(config) != manifest["source_config_sha256"]:
        raise ValueError("configuration differs from frozen manifest")
    if canonical_sha256(clean) != config["input_sha256"]:
        raise ValueError("input differs from frozen corpus")
    current = source_hashes()
    if current != config["source_sha256"]:
        raise ValueError("evaluation source changed after freezing; use a newly labeled run")
    if [row["question_id"] for row in clean] != manifest["question_ids"]:
        raise ValueError("input question order differs from manifest")
    return manifest, clean


def check_local_runtime(run: Path) -> None:
    if local_runtime() != read_json(run / "configuration.json")["local_runtime"]:
        raise ValueError("local runtime differs from the frozen configuration")


def mnemosyne_context(row: dict) -> dict:
    started = time.monotonic()
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=200, token_budget=262144))
    tenant = "controlled-comparison"
    metadata = {}
    try:
        for index, session in enumerate(row["sessions"]):
            for number, turns in enumerate(rounds_of(session["turns"])):
                content = "\n\n".join(f"{session['turns'][i]['role']}: {session['turns'][i]['content']}" for i in turns)
                cid = engine.append_evidence(Evidence(
                    tenant_id=tenant, user_id="benchmark", actor="user", source_type="conversation",
                    source_identity=f"session-{index}/round-{number}", content=content,
                    created_at=benchmark_timestamp(session["date"], "session date"),
                    access_policy={"tenant": tenant},
                ))
                metadata[cid] = {"session_id": session["session_id"], "date": session["date"], "turns": turns}
        retained = time.monotonic()
        result = engine.retrieve(row["question"], tenant_id=tenant, filt={
            "role": "reader", "query_timezone": "UTC",
            "evaluated_at": benchmark_timestamp(row["question_date"], "question date").isoformat(),
        }, record_access=False)
        recalled = time.monotonic()
        candidates, refs = [], []
        for hit in result.hits:
            if hit.id in metadata:
                record = engine.get_evidence(tenant, hit.id)
                candidates.append(f"Session date: {metadata[hit.id]['date']}\n{record.content}")
                refs.append(metadata[hit.id])
        return {"question_id": row["question_id"], "arm": "mnemosyne", "status": "completed",
                "candidate_texts": candidates, "candidate_metadata": refs,
                "retained_rounds": len(metadata), "stage_seconds": {
                    "retain": retained - started, "recall": recalled - retained,
                }, "usage": {}}
    finally:
        engine.close()


def run_mnemosyne(run: Path, inputs: Path, context_dir: Path) -> None:
    with exclusive_runner(context_dir / "mnemosyne"):
        _run_mnemosyne(run, inputs, context_dir)


def _run_mnemosyne(run: Path, inputs: Path, context_dir: Path) -> None:
    manifest, clean = check_frozen(run, inputs)
    check_local_runtime(run)
    for row in clean:
        output = context_dir / "mnemosyne" / (row["question_id"] + ".json")
        if output.exists():
            prior = read_json(output)
            if prior.get("manifest_sha256") != manifest["manifest_sha256"] or prior.get("question_id") != row["question_id"]:
                raise ValueError("existing native result identity mismatch")
            continue
        claim = output.with_suffix(".started.json")
        context = {"question_id": row["question_id"], "arm": "mnemosyne", "status": "failed",
                   "stage_seconds": {}, "candidate_texts": [], "error_kind": "interrupted"}
        if claim.exists():
            prior = read_json(claim)
            if prior.get("manifest_sha256") != manifest["manifest_sha256"] or prior.get("question_id") != row["question_id"]:
                raise ValueError("interrupted native attempt identity mismatch")
        else:
            write_new(claim, {"manifest_sha256": manifest["manifest_sha256"], "question_id": row["question_id"]})
            try:
                context = mnemosyne_context(row)
            except Exception as exc:
                context["error_kind"] = type(exc).__name__
        context["manifest_sha256"] = manifest["manifest_sha256"]
        write_new(output, context)
        print(json.dumps({"arm": "mnemosyne", "question_id": row["question_id"],
                          "candidates": len(context["candidate_texts"])}), flush=True)


class _AnswerRunCancelled(RuntimeError):
    kind = "cancelled"


def answer_one(reader_input: dict, judge_row: dict, context: dict, manifest: dict, *,
               cancel_event: Event | None = None) -> dict:
    started = time.monotonic()
    record = {"question_id": context["question_id"], "arm": context["arm"],
              "manifest_sha256": manifest["manifest_sha256"], "status": "failed",
              "started_at": datetime.now(timezone.utc).isoformat(),
              "stage_seconds": dict(context.get("stage_seconds", {})), "receipts": {},
              "cost_usd": None, "usage": {}, "context_sha256": canonical_sha256(context)}
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise _AnswerRunCancelled("answer run cancelled before reading")
        if context.get("status") != "completed":
            raise ValueError("native ingestion/recall did not complete")
        packed = pack_context(context["candidate_texts"])
        record["packed_context"] = {k: v for k, v in packed.items() if k != "text"}
        prompt = READER_TEMPLATE.format(
            context=packed["text"], date=reader_input["question_date"], question=reader_input["question"],
        )
        if cancel_event is not None and cancel_event.is_set():
            raise _AnswerRunCancelled("answer run cancelled before reading")
        reader = read_with_codex(prompt, model=MODEL, reasoning_effort=REASONING_EFFORT)
        record["receipts"]["reader"] = reader | {"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        record["stage_seconds"]["reader"] = reader["elapsed_seconds"]
        record["hypothesis"] = reader["answer"]
        if cancel_event is not None and cancel_event.is_set():
            raise _AnswerRunCancelled("answer run cancelled before judging")
        prompt = judge_prompt(judge_row, reader["answer"])
        if cancel_event is not None and cancel_event.is_set():
            raise _AnswerRunCancelled("answer run cancelled before judging")
        judge = read_with_codex(prompt, model=MODEL, reasoning_effort=REASONING_EFFORT)
        record["receipts"]["judge"] = judge | {"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        record["stage_seconds"]["judge"] = judge["elapsed_seconds"]
        verdict = judge["answer"].strip().lower()
        if verdict not in ("yes", "no"):
            raise ValueError("judge must return exactly yes or no")
        record.update(status="completed", judge_label=verdict == "yes")
    except Exception as exc:
        record["error_kind"] = getattr(exc, "kind", type(exc).__name__)
    finally:
        record["stage_seconds"]["total"] = time.monotonic() - started + sum(
            record["stage_seconds"].get(key, 0) for key in ("retain", "recall"))
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        for receipt in record["receipts"].values():
            for key, count in (receipt.get("usage") or {}).items():
                if type(count) is int:
                    record["usage"][key] = record["usage"].get(key, 0) + count
        record["reader_judge_usage_only"] = True
    return record


def _run_answer_job(reader: dict, judge: dict, context: dict, manifest: dict,
                    output: Path, cancel_event: Event) -> dict | None:
    # Queued work has no attempt identity until a worker admits it. Cancellation
    # before admission leaves it pending; it must not consume provider quota.
    if cancel_event.is_set():
        return None
    claim = output.parent / "attempts" / output.name
    write_new(claim, {"manifest_sha256": manifest["manifest_sha256"],
                      "question_id": context["question_id"], "arm": context["arm"]})
    result = answer_one(reader, judge, context, manifest, cancel_event=cancel_event)
    # Publication belongs to the worker, so an interrupted observer cannot lose
    # successful results or partial reader receipts while active calls drain.
    write_new(output, result)
    return result


def _cancel_and_drain_answers(futures: dict, cancel_event: Event) -> None:
    cancel_event.set()
    for future in futures:
        future.cancel()
    # An admitted provider call is allowed to finish within its existing timeout.
    # Its worker persists the receipt and will not admit a later judge stage.
    while pending := [future for future in futures if not future.done()]:
        try:
            wait(pending, timeout=0.1)
        except KeyboardInterrupt:
            # Repeated Ctrl-C must not turn a graceful drain into lost receipts.
            continue


def run_answers(data: Path, run: Path, inputs: Path, context_dir: Path) -> None:
    with exclusive_runner(run / "answers"):
        _run_answers(data, run, inputs, context_dir)


def _run_answers(data: Path, run: Path, inputs: Path, context_dir: Path) -> None:
    manifest, clean = check_frozen(run, inputs)
    check_local_runtime(run)
    rows = {row["question_id"]: row for row in dataset(data)}
    jobs = []
    for index, row in enumerate(clean):
        # Alternate arm order; no score-dependent retries or substitutions.
        for arm in (ARMS if index % 2 == 0 else ARMS[::-1]):
            qid = row["question_id"]
            output = run / "answers" / f"{qid}-{arm}.json"
            if output.exists():
                prior = read_json(output)
                if (prior.get("manifest_sha256") != manifest["manifest_sha256"]
                        or prior.get("question_id") != qid or prior.get("arm") != arm):
                    raise ValueError("existing answer identity mismatch")
                continue
            context_path = context_dir / arm / f"{qid}.json"
            if not context_path.exists():
                print(json.dumps({"question_id": qid, "arm": arm, "status": "waiting-for-context"}), flush=True)
                continue
            context = read_json(context_path)
            if context.get("arm") != arm or context.get("question_id") != qid:
                raise ValueError("native result identity mismatch")
            if context.get("manifest_sha256") != manifest["manifest_sha256"]:
                raise ValueError("native result manifest mismatch")
            claim = run / "answers" / "attempts" / f"{qid}-{arm}.json"
            if claim.exists():
                prior = read_json(claim)
                if prior.get("manifest_sha256") != manifest["manifest_sha256"]:
                    raise ValueError("interrupted attempt belongs to a different manifest")
                write_new(output, {"question_id": qid, "arm": arm, "status": "failed",
                                   "manifest_sha256": manifest["manifest_sha256"],
                                   "stage_seconds": context.get("stage_seconds", {}), "receipts": {},
                                   "error_kind": "interrupted", "cost_usd": None, "usage": None})
                continue
            reader_input = {"question": row["question"], "question_date": row["question_date"]}
            jobs.append((reader_input, rows[qid], context, output))
    cancel_event = Event()
    pool = ThreadPoolExecutor(max_workers=2)
    futures = {}
    try:
        for reader, judge, context, output in jobs:
            future = pool.submit(_run_answer_job, reader, judge, context, manifest, output, cancel_event)
            futures[future] = output
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                print(json.dumps({key: result.get(key) for key in ("question_id", "arm", "status", "judge_label")}), flush=True)
    except BaseException:
        _cancel_and_drain_answers(futures, cancel_event)
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "mnemosyne", "answers", "summarize"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.data, args.run, args.inputs)
    elif args.action == "mnemosyne":
        run_mnemosyne(args.run, args.inputs, args.contexts)
    elif args.action == "answers":
        run_answers(args.data, args.run, args.inputs, args.contexts)
    else:
        manifest, _ = check_frozen(args.run, args.inputs)
        results = [read_json(path) for path in sorted((args.run / "answers").glob("*.json"))]
        summary = score_comparison(manifest, results)
        write_new(args.run / "summary.json", summary)
        print(json.dumps(summary["arms"]), flush=True)


if __name__ == "__main__":
    main()
