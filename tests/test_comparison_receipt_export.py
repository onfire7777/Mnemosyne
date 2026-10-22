import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from eval.comparison_protocol import ARMS, QUESTION_TYPES, canonical_sha256, selection_manifest

_PATH = Path(__file__).resolve().parents[1] / "work/hindsight-comparison/controlled/export-run-receipts.py"
_SPEC = importlib.util.spec_from_file_location("comparison_receipt_export", _PATH)
exporter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(exporter)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def finished_run(tmp_path):
    rows = [{"question_id": f"q{i}", "question_type": QUESTION_TYPES[i % 6]} for i in range(480)]
    rows += [{"question_id": f"q{i}_abs", "question_type": QUESTION_TYPES[i % 6]} for i in range(20)]
    manifest = selection_manifest(rows, "d" * 64, source_config_sha256="c" * 64)
    write(tmp_path / "manifest.json", manifest)
    write(tmp_path / "summary.json", {"complete": True, "manifest_sha256": manifest["manifest_sha256"]})
    for qid in manifest["question_ids"]:
        for arm in ARMS:
            context = {"question_id": qid, "arm": arm, "status": "completed",
                       "manifest_sha256": manifest["manifest_sha256"],
                       "candidate_texts": ["PRIVATE_SOURCE_TEXT"], "stage_seconds": {"retain": 1., "recall": 2.}}
            if arm == "hindsight":
                receipt = {"attempt_id": "first", "status": "completed", "answer": "PRIVATE_MODEL_TEXT",
                           "usage": {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3}}
                path = tmp_path / "native-receipts" / arm / qid / "first.json"
                write(path, receipt)
                context.update(native_attempt_count=1, native_attempt_ids=["first"], native_usage=receipt["usage"],
                               native_usage_incomplete=False,
                               native_receipt_sha256={"first.json": hashlib.sha256(path.read_bytes()).hexdigest()})
            write(tmp_path / "contexts" / arm / f"{qid}.json", context)
            write(tmp_path / "answers" / f"{qid}-{arm}.json", {
                "question_id": qid, "arm": arm, "manifest_sha256": manifest["manifest_sha256"],
                "context_sha256": canonical_sha256(context),
                "receipts": {stage: {"usage": {"input_tokens": 4, "output_tokens": 1}}
                             for stage in ("reader", "judge")},
            })
    return tmp_path, manifest["question_ids"][0]


def test_export_preserves_cost_boundaries_and_omits_text(finished_run):
    run, _ = finished_run
    exporter.export(run)
    public = (run / "native-receipts-public.json").read_text()
    assert "PRIVATE" not in public
    resources = json.loads((run / "resource-summary.json").read_text())["arms"]
    assert resources["mnemosyne"]["native_llm_attempts_recorded"] == 0
    assert resources["hindsight"]["native_llm_attempts_recorded"] == 14
    assert resources["hindsight"]["combined_known_tokens"] == {
        "input_tokens": 252, "cached_input_tokens": 28, "output_tokens": 70,
    }
    assert resources["hindsight"]["cost_usd"] is None
    with pytest.raises(FileExistsError):
        exporter.export(run)


@pytest.mark.parametrize("corruption", ["context", "receipt", "missing_receipt", "incomplete"])
def test_export_rejects_changed_or_incomplete_evidence(finished_run, corruption):
    run, qid = finished_run
    if corruption == "context":
        path = run / "contexts/mnemosyne" / f"{qid}.json"
        value = json.loads(path.read_text())
        value["candidate_texts"] = ["CHANGED"]
        write(path, value)
    elif corruption == "receipt":
        path = run / "native-receipts/hindsight" / qid / "first.json"
        value = json.loads(path.read_text())
        value["usage"]["input_tokens"] += 1
        write(path, value)
    elif corruption == "missing_receipt":
        (run / "native-receipts/hindsight" / qid / "first.json").unlink()
    else:
        path = run / "summary.json"
        value = json.loads(path.read_text())
        value["complete"] = False
        write(path, value)
    with pytest.raises(ValueError):
        exporter.export(run)
    assert not (run / "native-receipts-public.json").exists()


def test_missing_reader_usage_is_reported_as_unknown(finished_run):
    run, qid = finished_run
    path = run / "answers" / f"{qid}-hindsight.json"
    value = json.loads(path.read_text())
    value["receipts"].pop("judge")
    write(path, value)
    exporter.export(run)
    resources = json.loads((run / "resource-summary.json").read_text())["arms"]
    assert resources["hindsight"]["reader_judge_stages_without_usage"] == 1
    assert resources["hindsight"]["reader_judge_known_tokens"] == {"input_tokens": 108, "output_tokens": 27}
