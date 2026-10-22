"""Publish compact, text-free native receipts after a comparison has finished.

Run from the repository root with `uv run python <this-file> --run <run-dir>`.
The original context and attempt files remain local; their hashes bind the
published projections to the exact inputs used by the common reader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from eval.comparison_protocol import ARMS, canonical_sha256, validate_manifest  # noqa: E402
from eval.controlled_comparison import read_json, write_new  # noqa: E402

ATTEMPT_FIELDS = (
    "schema", "attempt_id", "scope", "status", "started_at", "finished_at",
    "requested_model", "requested_reasoning_effort", "resolved_model",
    "prompt_sha256", "prompt_chars", "response_sha256", "requested_max_tokens",
    "requested_temperature", "generation_token_cap_enforced", "temperature_enforced",
    "cost_usd", "cost_basis", "usage", "elapsed_seconds", "total_seconds",
    "codex_version", "native_validation", "error_kind",
)
CONTEXT_FIELDS = (
    "question_id", "arm", "status", "manifest_sha256", "stage_seconds",
    "session_count", "retained_fact_count", "retained_rounds", "failed_stage",
    "error_kind", "native_attempt_count", "native_attempt_ids", "native_receipt_sha256",
    "native_usage", "native_usage_incomplete", "native_attempt_status_counts",
)


def add_usage(total: dict, usage: dict) -> None:
    for key, value in usage.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid usage counter: {key}")
        total[key] = total.get(key, 0) + value


def export(run: Path) -> None:
    manifest = read_json(run / "manifest.json")
    validate_manifest(manifest)
    summary = read_json(run / "summary.json")
    if not summary["complete"] or summary["manifest_sha256"] != manifest["manifest_sha256"]:
        raise ValueError("publish only a complete, compatible terminal run")
    projections, resources = [], {}
    for arm in ARMS:
        native_tokens, answer_tokens = {}, {}
        unknown_native, unknown_answer, attempt_count = 0, 0, 0
        for qid in manifest["question_ids"]:
            context = read_json(run / "contexts" / arm / f"{qid}.json")
            answer = read_json(run / "answers" / f"{qid}-{arm}.json")
            for obj in (context, answer):
                if (obj["manifest_sha256"] != manifest["manifest_sha256"]
                        or obj["question_id"] != qid or obj["arm"] != arm):
                    raise ValueError("case identity mismatch")
            digest = canonical_sha256(context)
            if answer.get("context_sha256") != digest:
                raise ValueError("answer is not bound to this native context")
            projected = {key: context[key] for key in CONTEXT_FIELDS if key in context}
            projected.update(context_sha256=digest, candidate_count=len(context["candidate_texts"]),
                             candidate_sha256=[hashlib.sha256(text.encode()).hexdigest()
                                               for text in context["candidate_texts"]], attempts=[])
            if arm == "hindsight":
                computed_usage = {}
                receipts = context["native_receipt_sha256"]
                local = run / "native-receipts" / arm / qid
                if set(receipts) != {path.name for path in local.glob("*.json")}:
                    raise ValueError("native receipt inventory changed after recall")
                for name, expected in sorted(receipts.items()):
                    raw = (local / name).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != expected:
                        raise ValueError("native receipt changed after recall")
                    attempt = json.loads(raw)
                    safe = {key: attempt[key] for key in ATTEMPT_FIELDS if key in attempt}
                    safe["original_receipt_sha256"] = expected
                    projected["attempts"].append(safe)
                    if isinstance(attempt.get("usage"), dict):
                        add_usage(computed_usage, attempt["usage"])
                if computed_usage != context["native_usage"]:
                    raise ValueError("native usage aggregate does not match its receipts")
                add_usage(native_tokens, computed_usage)
                unknown_native += bool(context["native_usage_incomplete"])
                attempt_count += len(receipts)
            receipts = answer.get("receipts", {})
            for stage in ("reader", "judge"):
                usage = receipts.get(stage, {}).get("usage")
                if isinstance(usage, dict):
                    add_usage(answer_tokens, usage)
                else:
                    # A missing stage is not proof of a zero-cost invocation.
                    unknown_answer += 1
            projections.append(projected)
        combined = dict(native_tokens)
        add_usage(combined, answer_tokens)
        resources[arm] = {
            "native_llm_attempts_recorded": attempt_count,
            "native_known_tokens": native_tokens,
            "reader_judge_known_tokens": answer_tokens,
            "combined_known_tokens": combined,
            "native_cases_with_incomplete_usage": unknown_native,
            "reader_judge_stages_without_usage": unknown_answer,
            "cost_usd": None,
            "cost_basis": "Existing Codex account quota; monetary cost not measured",
        }
    write_new(run / "native-receipts-public.json", {
        "manifest_sha256": manifest["manifest_sha256"], "cases": projections,
        "note": "Projections omit source text and model output; original receipts are bound by SHA-256.",
    })
    write_new(run / "resource-summary.json", {
        "manifest_sha256": manifest["manifest_sha256"], "arms": resources,
        "note": "Counters are separate measurements: cached input is a subset of input, reasoning output a subset of output. Do not add those subsets again. Unknown usage is not zero.",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    export(parser.parse_args().run)
