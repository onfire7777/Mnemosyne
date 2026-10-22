from __future__ import annotations

import copy
import hashlib
from collections import Counter

import pytest

from eval.comparison_protocol import (
    ARMS,
    BOOTSTRAP_SEED,
    MODEL,
    QUESTION_TYPES,
    REASONING_EFFORT,
    STRATA,
    canonical_sha256,
    inference_payload,
    pack_context,
    score_comparison,
    select_question_ids,
    selection_manifest,
    validate_manifest,
)


@pytest.fixture
def metadata():
    return [
        {"question_id": f"question_{i}", "question_type": QUESTION_TYPES[i % 6]}
        for i in range(480)
    ] + [
        {"question_id": f"question_{i}_abs", "question_type": QUESTION_TYPES[i % 6]}
        for i in range(20)
    ]


@pytest.fixture
def manifest(metadata):
    return selection_manifest(metadata, "d" * 64, source_config_sha256="c" * 64)


def reseal(manifest):
    manifest["manifest_sha256"] = canonical_sha256({
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    })


def record(manifest, qid, arm, correct=True):
    return {
        "question_id": qid, "arm": arm, "status": "completed",
        "manifest_sha256": manifest["manifest_sha256"], "judge_label": correct,
        "stage_seconds": {"retain": 1., "recall": 2., "reader": 3., "judge": 4., "total": 10.},
        "started_at": "2026-10-22T00:00:00Z", "finished_at": "2026-10-22T00:00:10+00:00",
        "usage": {"input_tokens": 120, "output_tokens": None}, "cost_usd": None,
        "receipts": {role: {
            "answer": "A grounded response" if role == "reader" else "yes" if correct else "no",
            "prompt_sha256": ("a" if role == "reader" else "b") * 64,
            "requested_model": MODEL, "requested_reasoning_effort": REASONING_EFFORT,
            "resolved_model": None,
        } for role in ("reader", "judge")},
    }


def full_records(manifest):
    return [record(manifest, qid, arm) for qid in manifest["question_ids"] for arm in ARMS]


def test_selection_is_order_independent_and_excludes_prior_development_set(metadata):
    selected = select_question_ids(metadata)
    assert selected == select_question_ids(list(reversed(metadata)))
    assert len(selected) == len(set(selected)) == 14
    dev = set(sorted((r["question_id"] for r in metadata),
                     key=lambda q: hashlib.sha256(q.encode()).hexdigest())[:100])
    assert not dev.intersection(selected)
    kinds = {r["question_id"]: r["question_type"] for r in metadata}
    strata = Counter("abstention" if q.endswith("_abs") else kinds[q] for q in selected)
    assert strata == Counter({stratum: 2 for stratum in STRATA})


def test_selection_reads_only_metadata(metadata):
    class MetadataOnly(dict):
        def get(self, key, default=None):
            assert key in ("question_id", "question_type"), "selection accessed inference or gold data"
            return super().get(key, default)

    guarded = [MetadataOnly(row, answer=object(), haystack_sessions=object()) for row in metadata]
    assert select_question_ids(guarded) == select_question_ids(metadata)


@pytest.mark.parametrize("corruption", ["count", "duplicate", "unknown_type", "unsafe_id", "no_abstentions"])
def test_selection_rejects_invalid_metadata(metadata, corruption):
    if corruption == "count":
        metadata.pop()
    elif corruption == "duplicate":
        metadata[0]["question_id"] = metadata[1]["question_id"]
    elif corruption == "unknown_type":
        metadata[0]["question_type"] = "other"
    elif corruption == "unsafe_id":
        metadata[0]["question_id"] = "../question"
    else:
        for row in metadata:
            row["question_id"] = row["question_id"].replace("_abs", "_ordinary")
    with pytest.raises(ValueError):
        select_question_ids(metadata)


@pytest.fixture
def raw_question():
    return {
        "question_id": "secret_abs", "question_type": "single-session-user",
        "question": "Which destination?", "question_date": "2024/01/03 (Wed) 12:00",
        "answer": "GOLD MUST NOT LEAK", "answer_session_ids": ["s1"],
        "haystack_session_ids": ["s1"], "haystack_dates": ["2024/01/01 (Mon) 12:00"],
        "haystack_sessions": [[
            {"role": "user", "content": "I went to Paris.", "has_answer": True, "gold": "LEAK"},
            {"role": "assistant", "content": "How was the visit?", "has_answer": False},
        ]],
    }


def test_inference_allowlist_removes_all_labels_and_detaches_mutable_data(raw_question):
    clean = inference_payload(raw_question)
    assert set(clean) == {"question", "question_date", "sessions"}
    assert clean["sessions"] == [{
        "session_id": "s1", "date": "2024/01/01 (Mon) 12:00",
        "turns": [{"role": "user", "content": "I went to Paris."},
                  {"role": "assistant", "content": "How was the visit?"}],
    }]
    clean["sessions"][0]["turns"][0]["content"] = "edited"
    assert raw_question["haystack_sessions"][0][0]["content"] == "I went to Paris."


@pytest.mark.parametrize("corruption", ["alignment", "duplicate", "role", "empty_turn", "empty_session"])
def test_inference_rejects_malformed_corpus(raw_question, corruption):
    if corruption == "alignment":
        raw_question["haystack_dates"] = []
    elif corruption == "duplicate":
        for field in ("haystack_session_ids", "haystack_dates", "haystack_sessions"):
            raw_question[field] *= 2
    elif corruption == "role":
        raw_question["haystack_sessions"][0][0]["role"] = "system"
    elif corruption == "empty_turn":
        raw_question["haystack_sessions"][0][0]["content"] = " "
    else:
        raw_question["haystack_sessions"][0] = []
    with pytest.raises(ValueError):
        inference_payload(raw_question)


def test_pack_context_uses_identical_ranked_budget_including_separators():
    texts = ["First", "中" * 20000, "UNSEEN"]
    packed = pack_context(texts)
    assert packed["text"].startswith("[Memory 1]\nFirst\n\n[Memory 2]\n")
    assert packed["text"].endswith("中")
    assert "UNSEEN" not in packed["text"]
    assert packed["characters"] == 16000
    assert packed["estimated_tokens"] == 4000
    assert packed["included_items"] == 2 and packed["offered_items"] == 3 and packed["truncated"]
    assert packed["sha256"] == hashlib.sha256(packed["text"].encode()).hexdigest()
    assert texts[1] == "中" * 20000


def test_pack_context_empty_and_exact_boundary():
    assert pack_context([])["estimated_tokens"] == 0
    assert pack_context([""])["included_items"] == 0
    exact = pack_context(["x" * (16000 - len("[Memory 1]\n"))])
    assert exact["characters"] == 16000 and not exact["truncated"]
    assert pack_context(["", "evidence"])["text"] == "[Memory 2]\nevidence"


@pytest.mark.parametrize("bad", ["text", [1], [None], {"text": "x"}])
def test_pack_context_rejects_invalid_inputs(bad):
    with pytest.raises(ValueError):
        pack_context(bad)


def test_manifest_hash_freezes_dataset_config_and_question_order(metadata, manifest):
    assert manifest == selection_manifest(list(reversed(metadata)), "d" * 64, source_config_sha256="c" * 64)
    assert manifest["manifest_sha256"] != selection_manifest(metadata, "e" * 64, source_config_sha256="c" * 64)["manifest_sha256"]
    manifest["questions"][0]["question_id"] = "changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        score_comparison(manifest, [], bootstrap_iterations=1000)


@pytest.mark.parametrize("field,value", [("reader_model", "other"), ("reader_context_estimated_tokens", 8000),
                                        ("failures_and_missing_score", False),
                                        ("generation_token_caps_enforced", True)])
def test_even_resealed_incompatible_configuration_is_rejected(manifest, field, value):
    manifest["configuration"][field] = value
    reseal(manifest)
    with pytest.raises(ValueError, match="frozen protocol"):
        score_comparison(manifest, [], bootstrap_iterations=1000)


def test_validate_manifest_is_available_before_inference_and_detaches_map(manifest):
    selected = validate_manifest(manifest)
    assert list(selected) == manifest["question_ids"]
    selected.clear()
    assert len(validate_manifest(manifest)) == 14
    manifest["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_manifest(manifest)


def test_failed_and_missing_cases_stay_in_fixed_denominator(manifest):
    first, second = manifest["question_ids"][:2]
    good = record(manifest, first, "mnemosyne")
    failed = record(manifest, second, "mnemosyne")
    failed.update(status="failed", judge_label=None, receipts={}, stage_seconds={"total": 30.})
    result = score_comparison(manifest, [good, failed], bootstrap_iterations=1000)
    arm = result["arms"]["mnemosyne"]
    assert not result["complete"] and not result["all_inference_completed"]
    assert arm["correct"] == 1 and arm["accuracy"] == 1 / 14
    assert (arm["completed"], arm["failed"], arm["missing"]) == (1, 1, 12)
    assert arm["stage_seconds"]["total"] == {"measured": 2, "mean": 20., "p50": 20., "p95": 29.}
    assert result["arms"]["hindsight"]["missing"] == 14
    assert result["pairs"][1]["mnemosyne"]["status"] == "failed"


def test_completed_report_can_include_terminal_failures(manifest):
    records = full_records(manifest)
    records[0].update(status="failed", judge_label=None, receipts={})
    result = score_comparison(manifest, records, bootstrap_iterations=1000)
    assert result["complete"] and not result["all_inference_completed"]
    assert result["arms"]["mnemosyne"]["correct"] == 13


def test_stratified_pairing_is_reproducible_and_independent_of_record_order(manifest):
    records = [record(manifest, qid, arm, correct=(arm == "mnemosyne" or i % 2 == 0))
               for i, qid in enumerate(manifest["question_ids"]) for arm in ARMS]
    result = score_comparison(manifest, records, bootstrap_iterations=1000)
    assert result == score_comparison(manifest, list(reversed(records)), bootstrap_iterations=1000)
    assert result["paired"]["difference"] == .5
    assert result["paired"]["both_correct"] == 7
    assert result["paired"]["mnemosyne_only_correct"] == 7
    assert result["paired"]["mcnemar_exact_two_sided_p"] == 2 / 128
    interval = result["paired"]["bootstrap_95"]
    assert interval["seed"] == BOOTSTRAP_SEED
    assert interval["low"] < .5 < interval["high"]


def test_all_ties_retains_conservative_uncertainty_despite_degenerate_bootstrap(manifest):
    result = score_comparison(manifest, full_records(manifest), bootstrap_iterations=1000)
    assert result["complete"] and result["all_inference_completed"]
    assert result["paired"]["bootstrap_95"]["degenerate"]
    assert result["paired"]["hoeffding_95"]["low"] < 0 < result["paired"]["hoeffding_95"]["high"]
    assert result["paired"]["mcnemar_exact_two_sided_p"] == 1.


def test_unknown_costs_are_not_reported_as_zero_and_observed_models_are_retained(manifest):
    rows = full_records(manifest)
    rows[0]["cost_usd"] = .5
    rows[0]["receipts"]["reader"]["resolved_model"] = "observed-model-version"
    result = score_comparison(manifest, rows, bootstrap_iterations=1000)
    assert result["arms"]["mnemosyne"]["known_cost_usd"] == .5
    assert result["arms"]["mnemosyne"]["cost_usd"] is None
    assert result["arms"]["mnemosyne"]["resolved_models"]["reader"] == ["observed-model-version"]
    for row in rows:
        row["cost_usd"] = .5
    assert score_comparison(manifest, rows, bootstrap_iterations=1000)["arms"]["hindsight"]["cost_usd"] == 7.


@pytest.mark.parametrize("corruption", [
    "unknown_id", "unknown_arm", "manifest", "status", "timing_missing", "timing_negative",
    "timing_nan", "timing_bool", "label_number", "label_mismatch", "judge_text", "model",
    "effort", "prompt_digest", "missing_reader", "empty_answer", "cost", "usage_bool",
    "timestamp_naive", "timestamp_order", "timestamp_incomplete", "failed_positive",
])
def test_malformed_or_incompatible_records_are_rejected(manifest, corruption):
    row = record(manifest, manifest["question_ids"][0], "mnemosyne")
    if corruption == "unknown_id":
        row["question_id"] = "elsewhere"
    elif corruption == "unknown_arm":
        row["arm"] = "other"
    elif corruption == "manifest":
        row["manifest_sha256"] = "f" * 64
    elif corruption == "status":
        row["status"] = "retry"
    elif corruption.startswith("timing_"):
        value = {"timing_negative": -1, "timing_nan": float("nan"), "timing_bool": True}
        if corruption == "timing_missing":
            del row["stage_seconds"]["retain"]
        else:
            row["stage_seconds"]["retain"] = value[corruption]
    elif corruption == "label_number":
        row["judge_label"] = 1
    elif corruption == "label_mismatch":
        row["judge_label"] = False
    elif corruption == "judge_text":
        row["receipts"]["judge"]["answer"] = "yes, correct"
    elif corruption == "model":
        row["receipts"]["reader"]["requested_model"] = "different-model"
    elif corruption == "effort":
        row["receipts"]["judge"]["requested_reasoning_effort"] = "high"
    elif corruption == "prompt_digest":
        row["receipts"]["reader"]["prompt_sha256"] = "A" * 64
    elif corruption == "missing_reader":
        del row["receipts"]["reader"]
    elif corruption == "empty_answer":
        row["receipts"]["reader"]["answer"] = " "
    elif corruption == "cost":
        row["cost_usd"] = -1
    elif corruption == "usage_bool":
        row["usage"]["input_tokens"] = True
    elif corruption == "timestamp_naive":
        row["started_at"] = "2026-10-22T00:00:00"
    elif corruption == "timestamp_order":
        row["finished_at"] = "2026-10-21T00:00:00Z"
    elif corruption == "timestamp_incomplete":
        del row["finished_at"]
    else:
        row["status"] = "failed"
    with pytest.raises(ValueError):
        score_comparison(manifest, [row], bootstrap_iterations=1000)


def test_retries_and_duplicate_results_cannot_replace_first_attempt(manifest):
    row = record(manifest, manifest["question_ids"][0], "mnemosyne")
    with pytest.raises(ValueError, match="duplicate"):
        score_comparison(manifest, [row, copy.deepcopy(row)], bootstrap_iterations=1000)
