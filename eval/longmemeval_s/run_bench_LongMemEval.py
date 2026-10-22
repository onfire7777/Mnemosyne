"""LongMemEval-S development answer evaluation for Mnemosyne.

For each of the 500 questions: load that question's own chat sessions into a fresh in-memory
Mnemosyne, retrieve the best sessions for the question, let a READER model answer from them, then
let a JUDGE model mark the answer right or wrong. Use OpenRouter or isolated Codex CLI calls.
Codex runs consume account quota; monetary cost and generation token caps are not measured.
Codex uses the benchmark's grading prompts with a different judge backend; its results are
development evidence, not directly comparable to published scores with other model settings.

The reader prompt (sessions sorted by date, JSON turns, step by step) and the judge prompts are
copied verbatim from the official repo, github.com/xiaowu0162/LongMemEval:
src/generation/run_generation.py and src/evaluation/evaluate_qa.py (yes/no, temperature 0,
max 10 tokens, gpt-4o-mini = gpt-4o-mini-2024-07-18).

--context rounds stores each ROUND (a user turn and the replies after it) as its own memory instead
of each whole session, hands the reader the best-ranked rounds that fit --budget tokens, grouped by
session and sorted by date, in the same official prompt. With --dry-run, --budget takes a comma list
and every budget is scored from one retrieval.
Dense retrieval does not support --dry-run because missing cached vectors require a model call.
Use default or passages mode for a run that never calls models or opens an embedding cache.

    set OPENROUTER_API_KEY=sk-or-...
    Mnemosyne\\Repository\\.venv\\Scripts\\python.exe run_bench_LongMemEval.py --limit 5     (smoke test)
    Mnemosyne\\Repository\\.venv\\Scripts\\python.exe run_bench_LongMemEval.py              (all 500)
    ... --dry-run   retrieve and build the prompts only, call no model, spend nothing
    ... --mode passages --context rounds --budget 2000,4000,8000 --dry-run   (round coverage sweep)

Results: LongMemEval-results\\<run>.jsonl (one line per question; run again with the same --run to
resume) and <run>.summary.json. Each line carries question_id + hypothesis, so the file can also
be fed unchanged to the official evaluate_qa.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "src")]

from eval.codex_reader import read_with_codex  # noqa: E402
from eval.harness.metrics import wilson_interval  # noqa: E402
from eval.longmemeval_recall import benchmark_timestamp, split_of  # noqa: E402
from eval.longmemeval_s.lme_embeddings import CachedProvider, open_cache, query_text  # noqa: E402
from mnemosyne.engine import LocalMemoryEngine  # noqa: E402
from mnemosyne.models import Evidence  # noqa: E402
from mnemosyne.policy import OperatingPolicy  # noqa: E402
from mnemosyne.retrieval import RetrievalAdapters  # noqa: E402

# --mode dense: the embedding provider (cloud or local, vectors cached on disk) Mnemosyne ranks with.
EMBEDDER: CachedProvider | None = None

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
GPT_4O_MINI = "openai/gpt-4o-mini-2024-07-18"
# Rounds Mnemosyne ranks per question in --context rounds; the budget then takes what fits.
ROUND_POOL = 200

# Official reader prompts (run_generation.py, retrieval-augmented, no fact expansion).
READER_COT = (
    "I will give you several history chats between you and a user. Please answer the question based on the "
    "relevant chat history. Answer the question step by step: first extract all the relevant information, and "
    "then reason over the information to get the answer.\n\n\nHistory Chats:\n\n{}\n\nCurrent Date: {}\n"
    "Question: {}\nAnswer (step by step):"
)
READER_PLAIN = (
    "I will give you several history chats between you and a user. Please answer the question based on the "
    "relevant chat history.\n\n\nHistory Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:"
)

# Official judge prompts (evaluate_qa.py get_anscheck_prompt), byte for byte.
_CHECK = (
    "I will give you a question, a correct answer, and a response from a model. Please answer yes if the "
    "response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct "
    "answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the "
    "response only contains a subset of the information required by the answer, answer no. "
)
_TAIL = "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
JUDGE = {
    "single-session-user": _CHECK + _TAIL,
    "single-session-assistant": _CHECK + _TAIL,
    "multi-session": _CHECK + _TAIL,
    "temporal-reasoning": _CHECK
    + "In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number "
    "of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is "
    "18), the model's response is still correct. "
    + _TAIL,
    "knowledge-update": "I will give you a question, a correct answer, and a response from a model. Please answer "
    "yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous "
    "information along with an updated answer, the response should be considered as correct as long as the updated "
    "answer is the required answer." + _TAIL,
    "single-session-preference": "I will give you a question, a rubric for desired personalized response, and a "
    "response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
    "The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls "
    "and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only.",
}
ABSTENTION = (
    "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if "
    "the model correctly identifies the question as unanswerable. The model could say that the information is "
    "incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\n"
    "Explanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? "
    "Answer yes or no only."
)


def openrouter(model: str, prompt: str, max_tokens: int, key: str) -> tuple[str, float, str | None]:
    """One chat call at temperature 0; returns (text, cost in USD as OpenRouter bills it, finish reason).

    A finish reason of 'length' means the answer hit max_tokens and was cut off - a model that
    thinks before it answers spends part of that budget on the thinking.
    """
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "usage": {"include": True},
    }).encode("utf-8")
    error: object = None
    for attempt in range(6):
        request = urllib.request.Request(OPENROUTER, data=body, headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "Mnemosyne LongMemEval",
        })
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                reply = json.load(response)
            if reply.get("choices"):
                usage = reply.get("usage") or {}
                choice = reply["choices"][0]
                return (choice["message"].get("content") or "", float(usage.get("cost") or 0),
                        choice.get("finish_reason"))
            error = reply.get("error")
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 402, 403, 404):  # bad key, no credit, unknown model: retrying cannot help
                raise SystemExit(f"OpenRouter refused {model}: {exc.code} {exc.read().decode(errors='replace')[:300]}")
            error = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            error = exc
        time.sleep(2 ** attempt)
    raise RuntimeError(f"OpenRouter kept failing for {model}: {error}")


def _filter(mode: str, row: dict) -> dict:
    return {
        "role": "reader", "query_timezone": "UTC",
        "evaluated_at": benchmark_timestamp(row["question_date"], "question_date").isoformat(),
    } | ({"query_mode": "passages"} if mode == "passages" else {})


def retrieve(row: dict, top_k: int, mode: str) -> list[int]:
    """Positions of the top_k haystack sessions Mnemosyne ranks for the question.

    default and passages go through Mnemosyne's search pipeline; dense asks its dense channel
    alone (engine.vector_search), with a real embedding model in place of the built-in hash.
    """
    tenant = f"longmemeval:{row['question_id']}"
    adapters = {"adapters": RetrievalAdapters(embedding=EMBEDDER)} if mode == "dense" else {}
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=24, token_budget=262_144), **adapters)
    position_of: dict[str, int] = {}
    for index, (session_id, session) in enumerate(zip(row["haystack_session_ids"], row["haystack_sessions"])):
        text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in session)
        if not text:
            continue
        cid = engine.append_evidence(Evidence(
            tenant_id=tenant, user_id="longmemeval", actor="user",
            source_type=f"longmemeval:{session_id}", source_identity=session_id,
            content=text, access_policy={"tenant": tenant},
            created_at=benchmark_timestamp(row["haystack_dates"][index], f"haystack_dates[{index}]"),
        ))
        position_of.setdefault(cid, index)
    if mode == "dense":
        hits = engine.vector_search(row["question"], top_k * 3, {"tenant_id": tenant, "branch": "main", "role": "reader"})
    else:
        hits = engine.retrieve(row["question"], tenant_id=tenant, filt=_filter(mode, row), record_access=False).hits
    return list(dict.fromkeys(position_of[hit.id] for hit in hits if hit.id in position_of))[:top_k]


def rounds_of(session: list[dict]) -> list[list[int]]:
    """Turn indices of each round: a user turn and the replies after it, up to the next user turn."""
    rounds: list[list[int]] = []
    for index, turn in enumerate(session):
        if turn["role"] == "user" or not rounds:
            rounds.append([index])
        else:
            rounds[-1].append(index)
    return rounds


def retrieve_rounds(row: dict, mode: str) -> list[tuple[int, list[int]]]:
    """(session position, turn indices) of the rounds Mnemosyne ranks for the question, best first."""
    tenant = f"longmemeval:{row['question_id']}"
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=ROUND_POOL, token_budget=262_144))
    unit_of: dict[str, tuple[int, list[int]]] = {}
    for index, (session_id, session) in enumerate(zip(row["haystack_session_ids"], row["haystack_sessions"])):
        for number, turns in enumerate(rounds_of(session)):
            text = "\n".join(f"{session[i]['role']}: {session[i]['content']}" for i in turns)
            if not text.strip():
                continue
            cid = engine.append_evidence(Evidence(
                tenant_id=tenant, user_id="longmemeval", actor="user",
                source_type=f"longmemeval:{session_id}", source_identity=f"{session_id}#round-{number}",
                content=text, access_policy={"tenant": tenant},
                created_at=benchmark_timestamp(row["haystack_dates"][index], f"haystack_dates[{index}]"),
            ))
            unit_of.setdefault(cid, (index, turns))
    result = engine.retrieve(row["question"], tenant_id=tenant, filt=_filter(mode, row), record_access=False)
    ranked, seen = [], set()
    for hit in result.hits:
        if hit.id in unit_of and hit.id not in seen:
            seen.add(hit.id)
            ranked.append(unit_of[hit.id])
    return ranked


def _turns_json(row: dict, index: int, turns: list[int]) -> str:
    session = row["haystack_sessions"][index]
    return json.dumps([{"role": session[i]["role"], "content": session[i]["content"]} for i in turns])


def select_rounds(row: dict, ranked: list[tuple[int, list[int]]], budget: int) -> tuple[list[tuple[int, list[int]]], int]:
    """Best-ranked rounds that fit the token budget (estimated at 4 characters a token)."""
    picked, used = [], 0
    for index, turns in ranked:
        cost = len(_turns_json(row, index, turns)) // 4 + 1
        if used + cost > budget:
            continue
        picked.append((index, turns))
        used += cost
    return picked, used


def _history(row: dict, chunks: dict[int, list[int]]) -> str:
    # As the official reader: sessions sorted by date, turns as JSON, has_answer never shown.
    ordered = sorted((row["haystack_dates"][index], index) for index in chunks)
    return "".join(
        "\n### Session {}:\nSession Date: {}\nSession Content:\n{}\n".format(
            number, date, "\n" + _turns_json(row, index, chunks[index]),
        )
        for number, (date, index) in enumerate(ordered, 1)
    )


def reader_prompt(row: dict, chunks: dict[int, list[int]], cot: bool) -> str:
    """chunks: session position -> the turn indices handed over from it, in turn order."""
    return (READER_COT if cot else READER_PLAIN).format(_history(row, chunks), row["question_date"], row["question"])


def judge_prompt(row: dict, hypothesis: str) -> str:
    template = ABSTENTION if "_abs" in row["question_id"] else JUDGE[row["question_type"]]
    return template.format(row["question"], row["answer"], hypothesis)


def coverage(row: dict, chunks: dict[int, list[int]], evidence: set[tuple[str, int]]) -> dict:
    """Gold sessions touched, and has_answer turns actually handed over."""
    ids = row["haystack_session_ids"]
    gold = set(row.get("answer_session_ids") or [])
    got = {ids[index] for index in chunks}
    shown = {(ids[index], turn) for index, turns in chunks.items() for turn in turns}
    covered = len(evidence & shown)
    return {
        "evidence_recall": round(len(gold & got) / len(gold), 4) if gold else None,
        "evidence_turns": len(evidence),
        "evidence_turn_coverage": round(covered / len(evidence), 4) if evidence else None,
        "all_evidence_turns": covered == len(evidence) if evidence else None,
    }


def _codex_answer(row: dict, prompt: str, record: dict, args: argparse.Namespace) -> dict:
    """Retain both independent attempts; invalid grades are failures, not negative labels."""
    receipts: dict[str, dict] = {}
    result = record | {
        "inference_provider": "codex", "inference_receipts": receipts,
        "cost_usd": None, "cost_basis": "Codex account quota; monetary cost not measured",
        "reader_tokens": None, "reader_tokens_enforced": False,
        "judge_tokens": None, "judge_tokens_enforced": False, "finish_reason": None,
    }
    try:
        reader = read_with_codex(
            prompt, model=args.codex_model, reasoning_effort=args.codex_reasoning_effort,
        )
        receipts["reader"] = reader | {"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        hypothesis = reader["answer"]
        result["hypothesis"] = hypothesis
        result["reader"] = reader.get("resolved_model")
        grading_prompt = judge_prompt(row, hypothesis)
        judge = read_with_codex(
            grading_prompt, model=args.codex_model, reasoning_effort=args.codex_reasoning_effort,
        )
        receipts["judge"] = judge | {"prompt_sha256": hashlib.sha256(grading_prompt.encode()).hexdigest()}
        verdict = judge["answer"].strip().lower()
        result["judge_reply"] = judge["answer"]
        if verdict not in {"yes", "no"}:
            raise ValueError("Codex judge must return exactly yes or no")
        result["autoeval_label"] = {
            "model": judge.get("resolved_model"), "requested_model": args.codex_model, "label": verdict == "yes",
        }
        result["status"] = "completed"
    except Exception as exc:
        result.update({
            "status": "failed", "error_type": type(exc).__name__,
            "error_kind": getattr(exc, "kind", None), "error": str(exc),
        })
    return result


def run_one(row: dict, split: str, args: argparse.Namespace, key: str) -> dict:
    started = time.perf_counter()
    record = {
        "question_id": row["question_id"],
        "question_type": row["question_type"],
        "split": split,
        "question": row["question"],
        "answer": row["answer"],
    }
    evidence = row["_evidence_turns"]
    if args.context == "rounds":
        ranked = retrieve_rounds(row, args.mode)
        if args.dry_run:
            per_budget = {}
            for budget in args.budgets:
                picked, used = select_rounds(row, ranked, budget)
                chunks: dict[int, list[int]] = defaultdict(list)
                for index, turns in picked:
                    chunks[index].extend(turns)
                chunks = {index: sorted(set(turns)) for index, turns in chunks.items()}
                prompt = reader_prompt(row, chunks, not args.no_cot)
                per_budget[budget] = coverage(row, chunks, evidence) | {
                    "rounds": len(picked), "sessions": len(chunks), "prompt_tokens_est": len(prompt) // 4,
                }
            return record | {"budgets": per_budget, "seconds": round(time.perf_counter() - started, 2)}
        picked, used = select_rounds(row, ranked, args.budgets[0])
        chunks = defaultdict(list)
        for index, turns in picked:
            chunks[index].extend(turns)
        chunks = {index: sorted(set(turns)) for index, turns in chunks.items()}
        record["retrieved_sessions"] = [row["haystack_session_ids"][index] for index in chunks]
        record["rounds"] = len(picked)
    else:
        picked_sessions = retrieve(row, args.top_k, args.mode)
        chunks = {index: list(range(len(row["haystack_sessions"][index]))) for index in picked_sessions}
        record["retrieved_sessions"] = [row["haystack_session_ids"][index] for index in picked_sessions]
    record |= coverage(row, chunks, evidence)
    prompt = reader_prompt(row, chunks, not args.no_cot)
    record["prompt_tokens_est"] = len(prompt) // 4
    if args.dry_run:
        return record | {"reader_prompt_chars": len(prompt), "seconds": round(time.perf_counter() - started, 2)}
    if args.inference_provider == "codex":
        return _codex_answer(row, prompt, record, args) | {"seconds": round(time.perf_counter() - started, 2)}
    hypothesis, reader_cost, finish = openrouter(args.reader, prompt, args.reader_tokens, key)
    verdict, judge_cost, _ = openrouter(args.judge, judge_prompt(row, hypothesis), 10, key)
    return record | {
        "hypothesis": hypothesis,
        "finish_reason": finish,
        "autoeval_label": {"model": args.judge, "label": "yes" in verdict.lower()},
        "judge_reply": verdict.strip(),
        "reader": args.reader,
        "cost_usd": round(reader_cost + judge_cost, 6),
        "seconds": round(time.perf_counter() - started, 2),
    }


def evidence_turns(oracle: list[dict]) -> dict[str, set[tuple[str, int]]]:
    """question_id -> (session id, turn index) of every has_answer turn, from the oracle file."""
    marks: dict[str, set[tuple[str, int]]] = {}
    for row in oracle:
        sessions = row.get("haystack_sessions") or []
        ids = row.get("haystack_session_ids") or row.get("answer_session_ids") or []
        found: set[tuple[str, int]] = set()
        if len(ids) == len(sessions):
            for session_id, session in zip(ids, sessions):
                for index, turn in enumerate(session):
                    if isinstance(turn, dict) and turn.get("has_answer") is True:
                        found.add((session_id, index))
        marks[row["question_id"]] = found
    return marks


def _mean(values: list) -> float | None:
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: list[dict], args: argparse.Namespace) -> dict:
    labels = [1 if row["autoeval_label"]["label"] else 0 for row in rows]
    if not labels:
        raise ValueError("Cannot summarize an empty answer evaluation")
    interval = wilson_interval(sum(labels), len(labels))
    by_type: dict[str, list[int]] = defaultdict(list)
    for row, label in zip(rows, labels):
        by_type[row["question_type"]].append(label)
    abstention = [label for row, label in zip(rows, labels) if "_abs" in row["question_id"]]
    return {
        "questions": len(rows),
        "accuracy": round(sum(labels) / len(labels), 4),
        "accuracy_ci95": [round(interval.low, 4), round(interval.high, 4)],
        "accuracy_ci_method": interval.method,
        "task_averaged_accuracy": round(sum(sum(v) / len(v) for v in by_type.values()) / len(by_type), 4),
        "by_type": {t: {"accuracy": round(sum(v) / len(v), 4), "n": len(v)} for t, v in sorted(by_type.items())},
        "abstention": {"accuracy": round(sum(abstention) / len(abstention), 4), "n": len(abstention)} if abstention else None,
        "evidence_recall_at_k": _mean([row.get("evidence_recall") for row in rows]),
        "evidence_turn_coverage": _mean([row.get("evidence_turn_coverage") for row in rows]),
        "avg_prompt_tokens_est": _mean([row.get("prompt_tokens_est") for row in rows]),
        "cost_usd": None if args.inference_provider == "codex" else round(sum(row.get("cost_usd", 0) for row in rows), 4),
        "cost_basis": "Codex account quota; monetary cost not measured" if args.inference_provider == "codex" else "provider-reported USD",
        "answers_cut_off": sum(1 for row in rows if row.get("finish_reason") == "length"),
        "answers_empty": sum(1 for row in rows if not (row.get("hypothesis") or "").strip()),
        "reader_tokens": None if args.inference_provider == "codex" else args.reader_tokens,
        "reader_tokens_enforced": args.inference_provider != "codex",
        "judge_tokens": None if args.inference_provider == "codex" else 10,
        "judge_tokens_enforced": args.inference_provider != "codex",
        "reader": args.codex_model if args.inference_provider == "codex" else args.reader,
        "judge": args.codex_model if args.inference_provider == "codex" else args.judge,
        "inference_provider": args.inference_provider,
        "model_names_are_requested": args.inference_provider == "codex",
        "mode": args.mode,
        "embedding": f"{args.embed}:{args.embed_model}" if args.mode == "dense" else None,
        "context": args.context,
        "top_k": args.top_k if args.context == "sessions" else None,
        "budget": args.budgets[0] if args.context == "rounds" else None,
        "cot": not args.no_cot,
        "split": args.split,
    }


def _codex_manifest(args: argparse.Namespace, selected: list[dict], hashes: dict[str, str]) -> dict:
    sources = [
        Path(__file__), REPO / "eval/codex_reader.py", REPO / "eval/longmemeval_recall.py",
        REPO / "eval/harness/metrics.py", REPO / "pyproject.toml", REPO / "uv.lock",
    ]
    sources.extend(sorted((REPO / "src/mnemosyne").rglob("*.py")))
    return {
        "schema": "mnemosyne.longmemeval.codex-run.v1",
        "runtime": {"python": sys.version, "platform": sys.platform},
        "dataset": {
            "reference_source": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned",
            "input_directory": str(args.data.parent.resolve()), "sha256": hashes,
        },
        "source_sha256": {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "configuration": {
            "inference_provider": "codex", "model": args.codex_model,
            "reasoning_effort": args.codex_reasoning_effort, "timeout_seconds": 180,
            "mode": args.mode, "context": args.context, "top_k": args.top_k,
            "budgets": args.budgets, "cot": not args.no_cot, "split": args.split,
            "limit": args.limit, "workers": args.workers, "only_wrong_from": args.only_wrong_from,
            "timestamp_timezone": "UTC", "reader_tokens": None, "judge_tokens": None,
            "generation_token_caps_enforced": False, "temperature": None,
            "cost_usd": None, "cost_basis": "Codex account quota; monetary cost not measured",
            "judge_rule": "exact yes/no after trimming whitespace and ignoring case",
        },
        "selected_question_ids": [row["question_id"] for row in selected],
    }


def _bind_codex_manifest(out: Path, manifest: dict) -> str:
    path = out.with_suffix(".manifest.json")
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Codex resume manifest differs from data, code or settings; use a new --run")
    else:
        if any(out.with_suffix(suffix).exists() for suffix in (".jsonl", ".summary.json", ".failures.jsonl")):
            raise ValueError("Codex refuses to resume existing results without a matching manifest; use a new --run")
        out.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_codex_resume(rows: list[dict], selected: list[dict], manifest_hash: str) -> None:
    allowed = {row["question_id"] for row in selected}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Codex result must be an object")
        qid = row.get("question_id")
        receipts = row.get("inference_receipts", {})
        if not isinstance(receipts, dict) or not isinstance(receipts.get("judge"), dict):
            raise ValueError("Codex result lacks verified inference receipts")
        verdict = receipts["judge"].get("answer")
        grading = row.get("autoeval_label", {})
        label = grading.get("label") if isinstance(grading, dict) else None
        if (
            not isinstance(qid, str) or qid not in allowed or qid in seen or row.get("manifest_sha256") != manifest_hash
            or row.get("inference_provider") != "codex" or row.get("status") != "completed"
            or not isinstance(receipts.get("reader"), dict)
            or not isinstance(verdict, str) or verdict.strip().lower() not in {"yes", "no"}
            or type(label) is not bool or label != (verdict.strip().lower() == "yes")
        ):
            raise ValueError("Codex result is unverified, duplicated, or outside its manifest; use a new --run")
        seen.add(qid)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path,
                    default=HERE / "Mnemosyne" / "_scratch" / "benchmark-data" / "longmemeval_s_cleaned.json")
    ap.add_argument("--reader", default=GPT_4O_MINI, help="OpenRouter model that writes the answers")
    ap.add_argument("--judge", default=GPT_4O_MINI, help="OpenRouter model that grades them (official: gpt-4o-mini)")
    ap.add_argument("--inference-provider", choices=("openrouter", "codex"), default="openrouter")
    ap.add_argument("--codex-model", default=None, help="Codex model for independent reader and judge calls")
    ap.add_argument("--codex-reasoning-effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"))
    ap.add_argument("--out-dir", type=Path, default=None, help="local directory for results, receipts and run manifest")
    ap.add_argument("--top-k", type=int, default=10, help="sessions handed to the reader (default 10)")
    ap.add_argument("--mode", choices=("default", "passages", "dense"), default="default",
                    help="Mnemosyne retrieval: default search, BM25 passages, or the dense channel with --embed")
    ap.add_argument("--embed", choices=("cloud", "local"), default="cloud",
                    help="embedding model for --mode dense: OpenRouter qwen3-embedding-8b, or Ollama on this PC")
    ap.add_argument("--embed-max-usd", type=float, default=0.50, help="refuse to embed more than this (estimate)")
    ap.add_argument("--context", choices=("sessions", "rounds"), default="sessions",
                    help="store and hand over whole sessions (default) or single rounds")
    ap.add_argument("--budget", default="4000",
                    help="reader context in tokens for --context rounds (a comma list with --dry-run)")
    ap.add_argument("--no-cot", action="store_true", help="plain reader prompt instead of step by step")
    ap.add_argument("--reader-tokens", type=int, default=4000,
                    help="OpenRouter maximum answer length; Codex generation caps are not enforced")
    ap.add_argument("--only-wrong-from", default="",
                    help="only the questions an earlier run (its --run name) got wrong")
    ap.add_argument("--split", choices=("all", "dev", "heldout"), default="all")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions (smoke test)")
    ap.add_argument("--workers", type=int, default=4, help="questions in flight at once")
    ap.add_argument("--run", default="", help="run name; give the same one to resume")
    ap.add_argument("--dry-run", action="store_true",
                    help="retrieve and build prompts only, call no model (default/passages modes only)")
    args = ap.parse_args()
    if args.dry_run and args.mode == "dense":
        raise SystemExit(
            "--mode dense does not support --dry-run: missing vectors require model calls. "
            "Use --mode default or --mode passages for a dry run."
        )
    if args.inference_provider == "codex" and args.mode == "dense":
        raise SystemExit("Codex inference supports --mode default or passages; dense embeddings require a separate provider")
    if args.limit < 0 or args.top_k < 1 or args.workers < 1:
        ap.error("--limit must be non-negative; --top-k and --workers must be positive")
    args.budgets = [int(value) for value in str(args.budget).split(",") if value.strip()]
    if not args.budgets or min(args.budgets) < 1:
        raise SystemExit("--budget must be positive token counts")
    if len(args.budgets) > 1 and not args.dry_run:
        raise SystemExit("several budgets only work with --dry-run")

    key = os.environ.get("OPENROUTER_API_KEY", "") if args.inference_provider == "openrouter" else ""
    if args.inference_provider == "openrouter" and not key and not args.dry_run:
        raise SystemExit("Set OPENROUTER_API_KEY first (or use --dry-run).")
    data_bytes = args.data.read_bytes()
    oracle_bytes = (args.data.parent / "longmemeval_oracle.json").read_bytes()
    hashes = {args.data.name: hashlib.sha256(data_bytes).hexdigest(),
              "longmemeval_oracle.json": hashlib.sha256(oracle_bytes).hexdigest()}
    rows = json.loads(data_bytes)
    oracle = evidence_turns(json.loads(oracle_bytes))
    for row in rows:
        row["_evidence_turns"] = oracle.get(row["question_id"], set())
    splits = split_of([row["question_id"] for row in rows])
    todo = [row for row in rows if args.split == "all" or splits[row["question_id"]] == args.split]
    out_dir = args.out_dir if args.out_dir is not None else HERE / "LongMemEval-results"
    if args.only_wrong_from:
        earlier = out_dir / f"{args.only_wrong_from}.jsonl"
        wrong = {
            record["question_id"]
            for record in (json.loads(line) for line in earlier.read_text(encoding="utf-8").splitlines() if line.strip())
            if not record["autoeval_label"]["label"]
        }
        todo = [row for row in todo if row["question_id"] in wrong]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        raise SystemExit("No questions selected")
    for row in todo:
        benchmark_timestamp(row["question_date"], "question_date")
        if len(row["haystack_dates"]) != len(row["haystack_sessions"]) or len(row["haystack_session_ids"]) != len(row["haystack_sessions"]):
            raise ValueError("haystack_dates, haystack_session_ids and haystack_sessions must align")
        for date in row["haystack_dates"]:
            benchmark_timestamp(date, "haystack_dates")

    shape = f"top{args.top_k}" if args.context == "sessions" else f"rounds{args.budgets[0]}"
    model_name = (args.codex_model or "codex-default") if args.inference_provider == "codex" else args.reader
    run = args.run or f"{args.mode}-{shape}-{model_name.split('/')[-1]}-{args.split}"
    if Path(run).name != run or run in {".", ".."}:
        ap.error("--run must be a filename, not a path")
    out = out_dir / f"{run}.jsonl"
    manifest_hash = None
    if args.inference_provider != "codex" and not args.dry_run and out.with_suffix(".manifest.json").exists():
        raise ValueError("This run has a Codex manifest; use a new --run for a different inference provider")
    if args.inference_provider == "codex" and not args.dry_run:
        manifest_hash = _bind_codex_manifest(out, _codex_manifest(args, todo, hashes))
        failures_path = out.with_suffix(".failures.jsonl")
        if failures_path.exists() and failures_path.stat().st_size:
            raise ValueError("Codex run contains failed attempts; retained receipts require a new --run")
    done: list[dict] = []
    if not args.dry_run and out.exists():
        done = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        if args.inference_provider == "codex":
            _validate_codex_resume(done, todo, manifest_hash)
        finished = {row["question_id"] for row in done}
        todo = [row for row in todo if row["question_id"] not in finished]
        print(f"resuming {run}: {len(done)} done, {len(todo)} to go", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "dense":
        if args.context != "sessions":
            raise SystemExit("--mode dense ranks whole sessions; use it with --context sessions")
        global EMBEDDER
        cache = open_cache(args.embed, out_dir, key)
        texts = [query_text(row["question"]) for row in todo] + [
            "\n".join(f"{turn['role']}: {turn['content']}" for turn in session)
            for row in todo for session in row["haystack_sessions"]
        ]
        count, usd = cache.estimate_usd(texts)
        print(f"embeddings ({args.embed}, {cache.model}): {count:,} texts to embed, estimated ${usd:.2f}", flush=True)
        if usd > args.embed_max_usd:
            raise SystemExit(f"embedding estimate ${usd:.2f} is above --embed-max-usd {args.embed_max_usd}")
        cache.ensure(texts, label="embedding")
        print(f"embedded {cache.tokens / 1e6:.2f} M tokens for ${cache.cost:.3f}", flush=True)
        EMBEDDER = CachedProvider(cache)
        args.embed_model = cache.model

    started, new, failures = time.perf_counter(), [], []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(run_one, row, splits[row["question_id"]], args, key) for row in todo]
        for count, future in enumerate(as_completed(futures), 1):
            record = future.result()
            if args.dry_run:
                new.append(record)
                if count % 50 == 0 or count == len(todo):
                    print(f"{count}/{len(todo)} {time.perf_counter() - started:.0f}s", flush=True)
                continue
            if manifest_hash is not None:
                record["manifest_sha256"] = manifest_hash
            if record.get("status") == "failed":
                failures.append(record)
                with out.with_suffix(".failures.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"{record['question_id']}: failed ({record['error_type']}); receipts retained", flush=True)
                continue
            new.append(record)
            with out.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            scored = done + new
            right = sum(1 for row in scored if row["autoeval_label"]["label"])
            cost = "Codex account quota; cost not measured" if args.inference_provider == "codex" else (
                f"spent ${sum(row.get('cost_usd', 0) for row in scored):.3f}"
            )
            print(f"{len(scored)}/{len(done) + len(todo)} accuracy {right / len(scored):.3f} "
                  f"{cost} "
                  f"{time.perf_counter() - started:.0f}s", flush=True)

    if args.dry_run:
        if args.context == "rounds":
            report = {
                str(budget): {
                    "gold_session_coverage": _mean([row["budgets"][budget]["evidence_recall"] for row in new]),
                    "evidence_turn_coverage": _mean([row["budgets"][budget]["evidence_turn_coverage"] for row in new]),
                    "all_evidence_turns_share": _mean([
                        None if row["budgets"][budget]["all_evidence_turns"] is None
                        else float(row["budgets"][budget]["all_evidence_turns"]) for row in new
                    ]),
                    "avg_rounds": _mean([row["budgets"][budget]["rounds"] for row in new]),
                    "avg_sessions": _mean([row["budgets"][budget]["sessions"] for row in new]),
                    "avg_prompt_tokens_est": _mean([row["budgets"][budget]["prompt_tokens_est"] for row in new]),
                }
                for budget in args.budgets
            }
        else:
            report = {
                "gold_session_coverage": _mean([row["evidence_recall"] for row in new]),
                "evidence_turn_coverage": _mean([row["evidence_turn_coverage"] for row in new]),
                "all_evidence_turns_share": _mean([
                    None if row["all_evidence_turns"] is None else float(row["all_evidence_turns"]) for row in new
                ]),
                "avg_prompt_tokens_est": _mean([row["prompt_tokens_est"] for row in new]),
            }
        report = {"questions": len(new), "context": args.context, "mode": args.mode, "split": args.split,
                  "seconds": round(time.perf_counter() - started, 1), "coverage": report}
        if args.run:
            out.with_suffix(".dryrun.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(json.dumps(report, indent=1))
        return
    if failures:
        raise SystemExit(f"{len(failures)} Codex attempts failed; no aggregate score published; inspect {out.with_suffix('.failures.jsonl')}")
    summary = summarize(done + new, args)
    if manifest_hash is not None:
        summary["manifest_sha256"] = manifest_hash
        summary["complete"] = True
    out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
