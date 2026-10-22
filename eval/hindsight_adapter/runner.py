"""Run upstream Hindsight retain/recall in its separate Python environment.

Input is a gold-free list of question_id/question/question_date/sessions objects.
Never imports an evaluator, sees reference answers, or changes retrieval ranking.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback
from typing import Any

from eval.runner_lock import exclusive_runner

SOURCE_PIN = "0691b504a88480844b2db53384b8c81971b7cf1e"
SOURCE_ARCHIVE_SHA256 = "f914adefc7976a50f2925a82caa9135f64676dffe6bea6444b99127c1656591e"


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.strptime(value, "%Y/%m/%d (%a) %H:%M")
    # Official LongMemEval dates carry no zone; both arms use explicit UTC.
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def candidate_text(fact: Any) -> str:
    """Preserve native temporal evidence inside the shared reader budget."""
    dates = [("Occurred start", fact.occurred_start), ("Occurred end", fact.occurred_end),
             ("Mentioned at", fact.mentioned_at)]
    return "\n".join([f"{label}: {value}" for label, value in dates if value] + [fact.text])


def native_usage(directory: Path, *, interrupted: bool = False) -> dict[str, Any]:
    totals: dict[str, int] = {}
    hashes = {}
    ids = []
    incomplete = interrupted or any(directory.glob("*.tmp"))
    statuses: dict[str, int] = {}
    for path in sorted(directory.glob("*.json")):
        raw = path.read_bytes()
        receipt = json.loads(raw)
        ids.append(receipt["attempt_id"])
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
        status = receipt.get("status", "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        usage = receipt.get("usage")
        if not isinstance(usage, dict):
            incomplete = True
        else:
            for key, value in usage.items():
                if type(value) is int:
                    totals[key] = totals.get(key, 0) + value
    return {"native_attempt_count": len(ids), "native_attempt_ids": ids,
            "native_receipt_sha256": hashes, "native_usage": totals,
            "native_usage_incomplete": incomplete, "native_attempt_status_counts": statuses}


def validate_case(case: Any) -> None:
    if not isinstance(case, dict) or set(case) != {"question_id", "question", "question_date", "sessions"}:
        raise ValueError("expected only question_id/question/question_date/sessions, with no gold data")
    if not isinstance(case["question_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", case["question_id"]):
        raise ValueError("invalid question identifier")
    if not isinstance(case["question"], str) or not case["question"].strip():
        raise ValueError("question must be nonempty")
    timestamp(case["question_date"])
    if not isinstance(case["sessions"], list) or not case["sessions"]:
        raise ValueError("sessions must be nonempty")
    seen = set()
    for session in case["sessions"]:
        if not isinstance(session, dict) or set(session) != {"session_id", "date", "turns"}:
            raise ValueError("invalid session fields")
        if not isinstance(session["session_id"], str) or session["session_id"] in seen:
            raise ValueError("session identifiers must be unique strings")
        seen.add(session["session_id"])
        timestamp(session["date"])
        if not isinstance(session["turns"], list) or not session["turns"]:
            raise ValueError("session turns must be nonempty")
        for turn in session["turns"]:
            if (not isinstance(turn, dict) or set(turn) != {"role", "content"}
                    or turn["role"] not in {"user", "assistant"}
                    or not isinstance(turn["content"], str) or not turn["content"].strip()):
                raise ValueError("invalid turn or unexpected gold fields")


def frozen_input(args) -> tuple[dict, list[dict]]:
    manifest = json.loads(args.manifest.read_text())
    config = json.loads((args.manifest.parent / "configuration.json").read_text())
    cases = json.loads(args.input.read_text())
    expected = digest({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected:
        raise ValueError("manifest hash mismatch")
    if digest(config) != manifest["source_config_sha256"] or digest(cases) != config["input_sha256"]:
        raise ValueError("configuration or input changed after freezing")
    if config["hindsight_commit"] != SOURCE_PIN:
        raise ValueError("Hindsight revision differs from frozen configuration")
    repo = Path(__file__).resolve().parents[2]
    for relative, expected_hash in config["source_sha256"].items():
        if hashlib.sha256((repo / relative).read_bytes()).hexdigest() != expected_hash:
            raise ValueError("evaluation source changed after freezing: " + relative)
    if not isinstance(cases, list) or not cases:
        raise ValueError("input must be a nonempty list")
    for case in cases:
        validate_case(case)
    if ([case["question_id"] for case in cases] != manifest["question_ids"]
            or len({case["question_id"] for case in cases}) != len(cases)):
        raise ValueError("question order/identifiers differ from frozen manifest")
    return manifest, cases


def model_snapshots(runtime: Path) -> dict[str, Any]:
    snapshots = {}
    for model in ("BAAI/bge-small-en-v1.5", "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        cache = runtime / "huggingface" / "hub" / ("models--" + model.replace("/", "--"))
        revision = (cache / "refs/main").read_text().strip()
        directory = cache / "snapshots" / revision
        snapshots[model] = {"revision": revision, "files": {
            str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()
        }}
    return snapshots


async def runtime_snapshot(args, configuration: dict) -> dict[str, Any]:
    import asyncpg
    import hindsight_api

    connection = await asyncpg.connect(args.dsn)
    try:
        database = {"version": await connection.fetchval("SELECT version()"),
                    "extensions": {row["extname"]: row["extversion"] for row in
                                   await connection.fetch("SELECT extname, extversion FROM pg_extension ORDER BY extname")}}
    finally:
        await connection.close()
    image = subprocess.run(
        ["docker", "--context", "colima-pentestswarm", "inspect", args.database_container,
         "--format", "{{.Image}}"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    package = Path(hindsight_api.__file__).resolve().parent
    code_hashes = {str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(package.rglob("*.py"))}
    return {"schema": "hindsight-isolated-runtime.v1", "configuration": configuration,
            "python": sys.version, "platform": platform.platform(), "database": database,
            "database_image_sha256": image, "native_code_sha256": digest(code_hashes),
            "models": model_snapshots(args.runtime_dir),
            "distributions": {dist.metadata["Name"]: dist.version for dist in
                              sorted(metadata.distributions(), key=lambda dist: dist.metadata["Name"].lower())}}


def configure(args) -> dict[str, Any]:
    # Keep local inference/download caches and every DB change in this runtime.
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "HINDSIGHT_API_LLM_PROVIDER": "openai",
        "HINDSIGHT_API_LLM_API_KEY": "unused-codex-cli-bridge",
        "HINDSIGHT_API_LLM_MODEL": "gpt-6-astra",
        "HINDSIGHT_API_LLM_REASONING_EFFORT": "low",
        "HINDSIGHT_API_LLM_MAX_CONCURRENT": "3",
        "HINDSIGHT_API_LLM_TIMEOUT": "180",
        "HINDSIGHT_API_RETAIN_CHUNK_SIZE": "32000",
        "HINDSIGHT_API_CONSOLIDATION_RECONCILE_INTERVAL_SECONDS": "0",
        "HINDSIGHT_API_SKIP_LLM_VERIFICATION": "true",
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "local",
        "HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL": "BAAI/bge-small-en-v1.5",
        "HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU": "true",
        "HINDSIGHT_API_RERANKER_PROVIDER": "local",
        "HINDSIGHT_API_RERANKER_LOCAL_MODEL": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "HINDSIGHT_API_RERANKER_LOCAL_FORCE_CPU": "true",
        "HINDSIGHT_API_VECTOR_EXTENSION": "pgvector",
        "HINDSIGHT_API_TEXT_SEARCH_EXTENSION": "native",
        "HINDSIGHT_API_MODEL_INIT_TIMEOUT": "600",
        "HINDSIGHT_API_DB_POOL_MIN_SIZE": "2",
        "HINDSIGHT_API_DB_POOL_MAX_SIZE": "10",
    }
    inherited = [key for key in os.environ if key.startswith("HINDSIGHT_API_")]
    for key in inherited:
        del os.environ[key]
    os.environ.update(settings)
    # Once bootstrapped, use immutable local snapshots rather than resolving
    # mutable upstream main again during the selected run.
    for model, key in (("BAAI/bge-small-en-v1.5", "HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL"),
                       ("cross-encoder/ms-marco-MiniLM-L-6-v2", "HINDSIGHT_API_RERANKER_LOCAL_MODEL")):
        cache = args.runtime_dir.resolve() / "huggingface" / "hub" / ("models--" + model.replace("/", "--"))
        if (cache / "refs/main").is_file():
            revision = (cache / "refs/main").read_text().strip()
            os.environ[key] = str(cache / "snapshots" / revision)
    os.environ["HF_HOME"] = str(args.runtime_dir.resolve() / "huggingface")
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["OMP_NUM_THREADS"] = "2"
    os.environ["MKL_NUM_THREADS"] = "2"
    return {"source_pin": SOURCE_PIN, "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
            "provider": "codex-cli-factory", "provider_cli_attempts_per_call": 1,
            "native_operation_retries": "upstream defaults; every call has a separate receipt",
            "generation_token_cap_enforced": False, "temperature_enforced": False,
            "cost_usd": None, "task_backend": "SyncTaskBackend",
            "recall": {"budget": "bank default", "max_tokens": 4096,
                       "prefer_observations": None, "include_chunks": False},
            "environment": {key: value for key, value in settings.items() if not key.endswith("API_KEY")}}


async def run(args) -> None:
    # Shared output/receipt directories identify colliding attempts; the runtime
    # lock also excludes initialization/configuration against the same runtime.
    with exclusive_runner(args.output_dir, args.receipt_dir, args.runtime_dir):
        await _run(args)


async def _run(args) -> None:
    configuration = configure(args)
    manifest, cases = ({}, []) if args.initialize_only else frozen_input(args)
    from eval.hindsight_adapter.codex_provider import CASE_RECEIPT_DIR, install_factory
    from hindsight_api.engine.memory_engine import MemoryEngine
    from hindsight_api.engine.task_backend import SyncTaskBackend
    from hindsight_api.models import RequestContext

    install_factory(args.receipt_dir)
    engine = MemoryEngine(db_url=args.dsn, task_backend=SyncTaskBackend(), skip_llm_verification=True)
    await engine.initialize()
    try:
        actual_runtime = await runtime_snapshot(args, configuration)
        if args.environment:
            expected_runtime = json.loads(args.environment.read_text())
            if digest(actual_runtime) != digest(expected_runtime):
                raise ValueError("native runtime differs from frozen environment")
            if not args.initialize_only:
                config = json.loads((args.manifest.parent / "configuration.json").read_text())
                if config.get("hindsight_runtime_sha256") != digest(expected_runtime):
                    raise ValueError("native runtime is not bound by frozen configuration")
        write_json(args.output_dir / "environment.json", actual_runtime)
        if args.initialize_only:
            print(json.dumps({"status": "initialized", "source_pin": SOURCE_PIN}), flush=True)
            return
        manifest_hash = manifest["manifest_sha256"]
        for case in cases:
            qid = case["question_id"]
            output_path = args.output_dir / (qid + ".json")
            input_hash = digest(case)
            if output_path.exists():
                previous = json.loads(output_path.read_text())
                if (previous.get("status") in {"completed", "failed"}
                        and previous.get("question_id") == qid and previous.get("arm") == "hindsight"
                        and previous.get("input_sha256") == input_hash
                        and previous.get("manifest_sha256") == manifest_hash
                        and previous.get("configuration_sha256") == digest(configuration)):
                    print(json.dumps({"question_id": qid, "status": "resumed-" + previous["status"]}), flush=True)
                    continue
                raise ValueError("incompatible or incomplete prior result; use a fresh output directory/database")
            bank = "comparison-" + digest([str(args.output_dir.resolve()), manifest_hash, qid])[:32]
            context = RequestContext()
            contents = [{
                "content": "\n\n".join(f'{turn["role"]}: {turn["content"]}' for turn in session["turns"]),
                "context": "Conversation between the user and their assistant.",
                "event_date": timestamp(session["date"]),
                "document_id": "session-" + digest(session["session_id"])[:32],
            } for session in case["sessions"]]
            record = {"question_id": qid, "arm": "hindsight", "status": "failed",
                      "manifest_sha256": manifest_hash, "input_sha256": input_hash,
                      "configuration_sha256": digest(configuration), "source_pin": SOURCE_PIN,
                      "bank_id": bank, "candidate_texts": [], "candidate_metadata": [],
                      "session_count": len(contents), "stage_seconds": {"retain": 0.0, "recall": 0.0}}
            marker = args.output_dir / (qid + ".started.json")
            if marker.exists():
                attempt = json.loads(marker.read_text())
                if any(attempt.get(key) != record[key] for key in
                       ("question_id", "manifest_sha256", "input_sha256", "configuration_sha256")):
                    raise ValueError("interrupted attempt belongs to a different frozen run")
                record.update(failed_stage="retain_or_recall", error_kind="interrupted")
                record.update(native_usage(args.receipt_dir / qid, interrupted=True))
                write_json(output_path, record)
                print(json.dumps({"question_id": qid, "status": "interrupted"}), flush=True)
                continue
            args.output_dir.mkdir(parents=True, exist_ok=True)
            with marker.open("x") as handle:
                json.dump({key: record[key] for key in
                           ("question_id", "manifest_sha256", "input_sha256", "configuration_sha256")}, handle)
            stage = "retain"
            started = time.monotonic()
            receipt_token = CASE_RECEIPT_DIR.set(args.receipt_dir / qid)
            try:
                unit_ids, usage = await engine.retain_batch_async(
                    bank, contents, request_context=context, return_usage=True,
                )
                record["stage_seconds"]["retain"] = round(time.monotonic() - started, 6)
                record["retained_fact_count"] = sum(map(len, unit_ids))
                record["retain_reported_usage"] = usage.model_dump(mode="json")
                stage = "recall"
                started = time.monotonic()
                result = await engine.recall_async(
                    bank, case["question"], question_date=timestamp(case["question_date"]),
                    request_context=context, prefer_observations=None,
                )
                record["stage_seconds"]["recall"] = round(time.monotonic() - started, 6)
                # Preserve upstream fact rank and text. All native timing/source
                # metadata remains available without selecting against gold.
                record["candidate_texts"] = [candidate_text(fact) for fact in result.results]
                record["candidate_metadata"] = [fact.model_dump(mode="json") for fact in result.results]
                record["native_recall"] = result.model_dump(mode="json")
                record["status"] = "completed"
            except Exception as exc:
                record["stage_seconds"][stage] = round(time.monotonic() - started, 6)
                record["failed_stage"] = stage
                record["error_kind"] = type(exc).__name__
                traceback.print_exc()
            finally:
                CASE_RECEIPT_DIR.reset(receipt_token)
            record.update(native_usage(args.receipt_dir / qid))
            write_json(output_path, record)
            print(json.dumps({"question_id": qid, "status": record["status"],
                              "stage_seconds": record["stage_seconds"],
                              "retained_fact_count": record.get("retained_fact_count"),
                              "candidate_count": len(record["candidate_texts"])}), flush=True)
    finally:
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--receipt-dir", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--dsn", default=os.getenv("HINDSIGHT_COMPARISON_DSN"))
    parser.add_argument("--database-container", default="mnemosyne-hindsight-controlled")
    parser.add_argument("--environment", type=Path, help="Frozen native runtime fingerprint")
    parser.add_argument("--initialize-only", action="store_true")
    args = parser.parse_args()
    if not args.dsn:
        parser.error("set HINDSIGHT_COMPARISON_DSN or --dsn")
    if not args.initialize_only and (args.input is None or args.manifest is None or args.environment is None):
        parser.error("--input, --manifest and --environment required unless --initialize-only")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
