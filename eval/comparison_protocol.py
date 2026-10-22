"""Frozen small-sample comparison utilities; never call a model or a backend."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from datetime import datetime
from typing import Any, Mapping, Sequence

from eval.harness.metrics import percentile, wilson_interval

SCHEMA = "mnemosyne.hindsight.controlled-comparison.v1"
SELECTION_DOMAIN = "mnemosyne-hindsight-controlled-v1"
BOOTSTRAP_SEED = 20261022
MODEL = "gpt-6-astra"
REASONING_EFFORT = "low"
CONTEXT_ESTIMATED_TOKENS = 4000
ARMS = ("mnemosyne", "hindsight")
QUESTION_TYPES = (
    "knowledge-update", "multi-session", "single-session-assistant",
    "single-session-preference", "single-session-user", "temporal-reasoning",
)
STRATA = (*QUESTION_TYPES, "abstention")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_STAGES = {"retain", "recall", "reader", "judge", "total"}


def _selection_configuration() -> dict[str, Any]:
    return {"domain": SELECTION_DOMAIN, "total_metadata_rows": 500,
            "development_rows_excluded": 100, "per_stratum": 2}


def _run_configuration() -> dict[str, Any]:
    return {
        "track": "native-ingestion-recall-common-reader",
        "reader_model": MODEL, "judge_model": MODEL, "reasoning_effort": REASONING_EFFORT,
        "reader_context_estimated_tokens": CONTEXT_ESTIMATED_TOKENS,
        "context_estimator": "ceil(unicode_code_points/4), including separators",
        "generation_token_caps_enforced": False, "temperature_enforced": False,
        "cost_basis": "Codex account quota; monetary cost unknown unless measured",
        "failures_and_missing_score": 0, "bootstrap_seed": BOOTSTRAP_SEED,
        "native_reflect_comparison": False, "full_benchmark_score": False,
    }


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _metadata(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Read IDs and types only; selection must never inspect answers or history."""
    if len(rows) != 500:
        raise ValueError("the frozen LongMemEval selection requires all 500 question metadata rows")
    indexed: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("question metadata must be an object")
        qid, kind = row.get("question_id"), row.get("question_type")
        if not isinstance(qid, str) or not _ID.fullmatch(qid) or qid in indexed:
            raise ValueError("question IDs must be unique safe non-empty strings")
        if not isinstance(kind, str) or kind not in QUESTION_TYPES:
            raise ValueError("unknown LongMemEval question type")
        indexed[qid] = kind
    return indexed


def select_question_ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    indexed = _metadata(rows)
    ranked = sorted(indexed, key=lambda qid: (hashlib.sha256(qid.encode()).hexdigest(), qid))
    heldout = set(ranked[100:])
    selected = []
    for stratum in STRATA:
        candidates = [qid for qid, kind in indexed.items() if qid in heldout and (
            qid.endswith("_abs") if stratum == "abstention"
            else kind == stratum and not qid.endswith("_abs"))]
        candidates.sort(key=lambda qid: (
            hashlib.sha256((SELECTION_DOMAIN + "\0" + qid).encode()).hexdigest(), qid,
        ))
        if len(candidates) < 2:
            raise ValueError(f"insufficient held-out questions in {stratum}")
        selected.extend(candidates[:2])
    return selected


def selection_manifest(rows: Sequence[Mapping[str, Any]], dataset_sha256: str, *,
                       source_config_sha256: str) -> dict[str, Any]:
    indexed = _metadata(rows)
    selected = select_question_ids(rows)
    result = {
        "schema": SCHEMA,
        "dataset_sha256": _digest(dataset_sha256, "dataset_sha256"),
        "source_config_sha256": _digest(source_config_sha256, "source_config_sha256"),
        "selection": _selection_configuration(),
        "question_ids": selected,
        "questions": [{"question_id": qid, "question_type": indexed[qid],
                       "stratum": "abstention" if qid.endswith("_abs") else indexed[qid]} for qid in selected],
        "configuration": _run_configuration(),
    }
    result["manifest_sha256"] = canonical_sha256(result)
    return result


def inference_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist provider data. Even the abstention-bearing question ID is omitted."""
    if not isinstance(row, Mapping):
        raise ValueError("question must be an object")
    ids, dates, sessions = (row.get(key) for key in ("haystack_session_ids", "haystack_dates", "haystack_sessions"))
    if not all(isinstance(value, list) for value in (ids, dates, sessions)):
        raise ValueError("history IDs, dates and sessions must be lists")
    if not ids or not len(ids) == len(dates) == len(sessions):
        raise ValueError("history IDs, dates and sessions must align and be non-empty")
    copied = []
    seen = set()
    for sid, date, turns in zip(ids, dates, sessions, strict=True):
        _text(sid, "session_id")
        if sid in seen:
            raise ValueError("duplicate session ID")
        seen.add(sid)
        if not isinstance(turns, list) or not turns:
            raise ValueError("each history session must have turns")
        clean_turns = []
        for turn in turns:
            if not isinstance(turn, Mapping) or turn.get("role") not in ("user", "assistant"):
                raise ValueError("history turns must have a user or assistant role")
            clean_turns.append({"role": turn["role"], "content": _text(turn.get("content"), "turn content")})
        copied.append({"session_id": sid, "date": _text(date, "session date"), "turns": clean_turns})
    return {"question": _text(row.get("question"), "question"),
            "question_date": _text(row.get("question_date"), "question_date"), "sessions": copied}


def pack_context(texts: Sequence[str]) -> dict[str, Any]:
    """Keep rank order and truncate only the last admitted item at the shared cap."""
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
        raise ValueError("ranked context must be a sequence of strings")
    if any(not isinstance(value, str) for value in texts):
        raise ValueError("ranked context must contain strings only")
    limit = CONTEXT_ESTIMATED_TOKENS * 4
    text, included, truncated = "", 0, False
    for rank, value in enumerate(texts, 1):
        if not value:
            continue
        header = ("\n\n" if text else "") + f"[Memory {rank}]\n"
        remaining = limit - len(text) - len(header)
        if remaining <= 0:
            truncated = True
            break
        text += header + value[:remaining]
        included += 1
        if len(value) > remaining:
            truncated = True
            break
    return {"text": text, "estimated_tokens": math.ceil(len(text) / 4),
            "characters": len(text), "offered_items": len(texts), "included_items": included,
            "truncated": truncated, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def _manifest_questions(manifest: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(manifest, Mapping) or manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported comparison manifest")
    expected_hash = canonical_sha256({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected_hash:
        raise ValueError("comparison manifest hash mismatch")
    _digest(manifest.get("dataset_sha256"), "dataset_sha256")
    _digest(manifest.get("source_config_sha256"), "source_config_sha256")
    if (canonical_sha256(manifest.get("selection")) != canonical_sha256(_selection_configuration())
            or canonical_sha256(manifest.get("configuration")) != canonical_sha256(_run_configuration())):
        raise ValueError("comparison manifest differs from the frozen protocol configuration")
    rows, ids = manifest.get("questions"), manifest.get("question_ids")
    if not isinstance(rows, list) or not isinstance(ids, list) or len(rows) != 14 or len(ids) != 14:
        raise ValueError("comparison manifest must contain fourteen questions")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid manifest question")
        qid, kind, stratum = row.get("question_id"), row.get("question_type"), row.get("stratum")
        if (not isinstance(qid, str) or not _ID.fullmatch(qid) or qid in result
                or not isinstance(kind, str) or kind not in QUESTION_TYPES
                or stratum != ("abstention" if qid.endswith("_abs") else kind)):
            raise ValueError("invalid manifest question identity or stratum")
        result[qid] = stratum
    if ids != list(result) or Counter(result.values()) != Counter({key: 2 for key in STRATA}):
        raise ValueError("comparison manifest must balance all seven strata")
    return result


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, str]:
    """Validate before inference; return the ordered question ID to stratum map."""
    return _manifest_questions(manifest)


def _number(value: Any, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return float(value)


def _instant(value: Any, field: str) -> datetime:
    _text(value, field)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return result


def _validate_record(row: Mapping[str, Any], manifest: Mapping[str, Any], selected: Mapping[str, str]) -> None:
    if not isinstance(row, Mapping):
        raise ValueError("comparison result must be an object")
    if not isinstance(row.get("question_id"), str) or row["question_id"] not in selected:
        raise ValueError("comparison result is outside the selected questions")
    if not isinstance(row.get("arm"), str) or row["arm"] not in ARMS:
        raise ValueError("unknown comparison arm")
    if row.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("result manifest does not match frozen comparison")
    if row.get("status") not in ("completed", "failed"):
        raise ValueError("result status must be completed or failed")
    stages, receipts = row.get("stage_seconds"), row.get("receipts")
    if not isinstance(stages, Mapping) or not isinstance(receipts, Mapping):
        raise ValueError("results require stage_seconds and receipts objects")
    for name, value in stages.items():
        _text(name, "stage name")
        _number(value, "stage_seconds")
    cost = row.get("cost_usd")
    if cost is not None:
        _number(cost, "cost_usd")
    usage = row.get("usage")
    if usage is not None:
        if not isinstance(usage, Mapping):
            raise ValueError("usage must be an object or null")
        for name, value in usage.items():
            _text(name, "usage name")
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("usage counts must be non-negative integers or null")
    if "started_at" in row or "finished_at" in row:
        if _instant(row.get("finished_at"), "finished_at") < _instant(row.get("started_at"), "started_at"):
            raise ValueError("finished_at precedes started_at")
    if row["status"] == "failed":
        if row.get("judge_label") is not None and row.get("judge_label") is not False:
            raise ValueError("failed attempts cannot have a positive judge label")
        return
    if type(row.get("judge_label")) is not bool or not _STAGES <= set(stages):
        raise ValueError("completed attempts require a boolean judge label and all stage timings")
    for role in ("reader", "judge"):
        receipt = receipts.get(role)
        if not isinstance(receipt, Mapping):
            raise ValueError("completed attempts require independent reader and judge receipts")
        _text(receipt.get("answer"), f"{role} answer")
        _digest(receipt.get("prompt_sha256"), f"{role} prompt_sha256")
        if receipt.get("requested_model") != MODEL or receipt.get("requested_reasoning_effort") != REASONING_EFFORT:
            raise ValueError("inference receipt differs from frozen model configuration")
        resolved = receipt.get("resolved_model")
        if resolved is not None and (not isinstance(resolved, str) or not resolved.strip()):
            raise ValueError("resolved_model must be non-empty text or null")
    verdict = receipts["judge"]["answer"].strip().lower()
    if verdict not in ("yes", "no") or row["judge_label"] != (verdict == "yes"):
        raise ValueError("judge label does not match the exact yes/no receipt")


def score_comparison(manifest: Mapping[str, Any], records: Sequence[Mapping[str, Any]], *,
                     bootstrap_iterations: int = 10000) -> dict[str, Any]:
    selected = validate_manifest(manifest)
    if type(bootstrap_iterations) is not int or not 1000 <= bootstrap_iterations <= 100000:
        raise ValueError("bootstrap_iterations must be from 1000 to 100000")
    indexed = {}
    for row in records:
        _validate_record(row, manifest, selected)
        key = (row["question_id"], row["arm"])
        if key in indexed:
            raise ValueError("duplicate result: retries may not replace first attempts")
        indexed[key] = row
    pairs = []
    arms = {}
    for arm in ARMS:
        arm_rows = [indexed.get((qid, arm)) for qid in selected]
        scores = [bool(row is not None and row["status"] == "completed" and row["judge_label"]) for row in arm_rows]
        costs = [row.get("cost_usd") for row in arm_rows if row is not None]
        timings = {}
        for stage in sorted(_STAGES):
            values = [float(row["stage_seconds"][stage]) for row in arm_rows
                      if row is not None and stage in row["stage_seconds"]]
            timings[stage] = {"measured": len(values), "mean": sum(values) / len(values) if values else None,
                              "p50": percentile(values, .5) if values else None,
                              "p95": percentile(values, .95) if values else None}
        arms[arm] = {
            "questions": 14, "correct": sum(scores), "accuracy": sum(scores) / 14,
            "wilson_95": wilson_interval(sum(scores), 14).as_dict(),
            "completed": sum(row is not None and row["status"] == "completed" for row in arm_rows),
            "failed": sum(row is not None and row["status"] == "failed" for row in arm_rows),
            "missing": sum(row is None for row in arm_rows), "stage_seconds": timings,
            "known_cost_usd": sum(cost for cost in costs if cost is not None),
            "cost_usd": sum(costs) if len(costs) == 14 and all(cost is not None for cost in costs) else None,
            "cost_basis": "Codex account quota; null monetary cost is unknown, not zero",
            "resolved_models": {role: sorted({row["receipts"][role]["resolved_model"]
                                             for row in arm_rows if row is not None
                                             and isinstance(row["receipts"].get(role), Mapping)
                                             and isinstance(row["receipts"][role].get("resolved_model"), str)})
                                for role in ("reader", "judge")},
        }
    for qid, stratum in selected.items():
        pair: dict[str, Any] = {"question_id": qid, "stratum": stratum}
        for arm in ARMS:
            row = indexed.get((qid, arm))
            pair[arm] = {"score": int(row is not None and row["status"] == "completed" and row["judge_label"]),
                         "status": row["status"] if row is not None else "missing",
                         "stage_seconds": dict(row["stage_seconds"]) if row is not None else {},
                         "started_at": row.get("started_at") if row is not None else None,
                         "finished_at": row.get("finished_at") if row is not None else None}
        pair["difference"] = pair[ARMS[0]]["score"] - pair[ARMS[1]]["score"]
        pairs.append(pair)
    counts = Counter((pair[ARMS[0]]["score"], pair[ARMS[1]]["score"]) for pair in pairs)
    grouped = [[pair["difference"] for pair in pairs if pair["stratum"] == stratum] for stratum in STRATA]
    rng = random.Random(BOOTSTRAP_SEED)
    boot = [sum(rng.choice(group) for group in grouped for _ in group) / 14 for _ in range(bootstrap_iterations)]
    point = sum(pair["difference"] for pair in pairs) / 14
    low, high = percentile(boot, .025), percentile(boot, .975)
    discordant = counts[(1, 0)] + counts[(0, 1)]
    tail = sum(math.comb(discordant, k) for k in range(min(counts[(1, 0)], counts[(0, 1)]) + 1))
    radius = math.sqrt(2 * math.log(40) / 14)
    return {
        "schema": SCHEMA, "manifest_sha256": manifest["manifest_sha256"],
        "complete": len(indexed) == 28, "all_inference_completed": all(arm["completed"] == 14 for arm in arms.values()),
        "questions": 14, "arms": arms, "pairs": pairs,
        "by_stratum": {stratum: {arm: sum(pair[arm]["score"] for pair in pairs if pair["stratum"] == stratum) / 2
                                    for arm in ARMS} for stratum in STRATA},
        "paired": {"difference": point, "both_correct": counts[(1, 1)], "neither_correct": counts[(0, 0)],
                   "mnemosyne_only_correct": counts[(1, 0)], "hindsight_only_correct": counts[(0, 1)],
                   "bootstrap_95": {"low": low, "high": high, "iterations": bootstrap_iterations,
                                    "seed": BOOTSTRAP_SEED, "method": "paired stratified percentile bootstrap",
                                    "degenerate": low == high},
                   "hoeffding_95": {"low": max(-1., point - radius), "high": min(1., point + radius),
                                    "method": "conservative bounded paired-difference interval"},
                   "mcnemar_exact_two_sided_p": min(1., 2 * tail / 2 ** discordant) if discordant else 1.},
        "interpretation": "Small balanced held-out pilot of these frozen configurations; not a full benchmark, native reflect comparison, or global ranking.",
    }
