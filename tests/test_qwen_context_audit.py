"""Optional, real-artifact context diagnostic checks; no model execution."""

import json
import os
from pathlib import Path

import pytest

from eval.compact_answering.qwen_context_audit import audit


@pytest.fixture
def artifacts():
    root = os.environ.get("MNEMOSYNE_QWEN_CONTEXT_ARTIFACTS")
    if not root:
        pytest.skip("requires locally captured Qwen metadata and pinned tokenizer")
    pytest.importorskip("tokenizers")
    path = Path(root)
    return path / "show.json", path / "tokenizer.json", path / "prompts.json"


def test_actual_reference_counts_match_retained_probe(artifacts):
    report = audit(*artifacts)
    assert report["prompts"]["user"]["reference_tokens"] == 3989
    assert report["prompts"]["system"]["reference_tokens"] == 25
    assert report["matched_vocabulary_entries"] == 151643
    assert report["matched_merge_rules"] == 151387
    assert report["matched_added_token_ids"] == 26
    assert report["runtime_tokenizer_equivalence_verified"] is False
    assert report["full_context_coverage_verified"] is False
    assert report["model_execution_performed"] is False


@pytest.mark.parametrize("field,index", [
    ("tokenizer.ggml.tokens", 0),
    ("tokenizer.ggml.tokens", 151644),
    ("tokenizer.ggml.merges", 0),
])
def test_rejects_changed_model_tokenization(artifacts, tmp_path, field, index):
    metadata, tokenizer, prompts = artifacts
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["model_info"][field][index] = "changed"
    changed = tmp_path / "show.json"
    changed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="differ"):
        audit(changed, tokenizer, prompts)


def test_rejects_unpinned_tokenizer(artifacts, tmp_path):
    metadata, tokenizer, prompts = artifacts
    changed = tmp_path / "tokenizer.json"
    changed.write_bytes(tokenizer.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="pinned artifact"):
        audit(metadata, changed, prompts)


def test_rejects_non_ascii_scope_expansion(artifacts, tmp_path):
    metadata, tokenizer, prompts = artifacts
    value = json.loads(prompts.read_text(encoding="utf-8"))
    value["user"] += "café"
    changed = tmp_path / "prompts.json"
    changed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="ASCII"):
        audit(metadata, tokenizer, changed)
