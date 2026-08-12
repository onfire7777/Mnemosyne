from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from mnemosyne.ids import evidence_cid

from eval.public.adapters.longmemeval_qa import normalize, run
import eval.public.runner as runner
from eval.public.runner import (
    build_candidate_manifest,
    load_qa_protocol,
    qa_protocol_digests,
    validate_candidate_manifest,
    write_candidate_manifest,
)


def _assets() -> dict[str, Any]:
    return {
        "assets": {
            "longmemeval_s_cleaned.json": [
                {
                    "question_id": "q1",
                    "question": "Where is the key?",
                    "answer": "orchard shed",
                    "answer_aliases": ["in the orchard shed"],
                    "haystack_session_ids": ["support"],
                    "haystack_sessions": [[{"role": "user", "content": "The key is in the orchard shed."}]],
                    "answer_session_ids": ["support"],
                }
            ],
            "longmemeval_oracle.json": [
                {
                    "question_id": "q1",
                    "haystack_session_ids": ["support"],
                    "haystack_sessions": [[{"role": "user", "content": "The key is in the orchard shed.", "has_answer": True}]],
                }
            ],
        }
    }


class RecordingCLI:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.cid = ""

    def capture_batch(self, path: Path) -> dict[str, Any]:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.payloads.extend(rows)
        row = rows[0]
        self.cid = evidence_cid(
            row["content"], tenant_id=row["tenant"], user_id=row["user"],
            source_type=row["source_type"], content_pointer=None,
            modality="text", sensitivity=0,
        )
        return {"results": [{"cid": self.cid}]}

    def eval_answer_batch(self, path: Path) -> dict[str, Any]:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.payloads.extend(rows)
        return {
            "results": [
                {
                    "question_id": "q1",
                    "answer": "orchard shed",
                    "abstained": False,
                    "claims": [{
                        "text": "orchard shed", "evidence_cids": [self.cid],
                        "spans": [{
                            "cid": self.cid, "start": 16, "end": 29,
                            "slice_sha256": hashlib.sha256(b"orchard shed").hexdigest(),
                        }],
                    }],
                    "hops": [{"index": 0, "queries": ["key"], "channels": ["lexical"], "retrieved_cids": [self.cid]}],
                    "reader": {"grounded_reader": {}, "query_decomposer": {}},
                }
            ]
        }


def test_longmemeval_qa_labels_are_anchored_and_never_reach_cli() -> None:
    cli = RecordingCLI()
    benchmark, traces, metrics = run(_assets(), cli)  # type: ignore[arg-type]
    assert benchmark["questions"][0]["answers"] == ["orchard shed", "in the orchard shed"]
    assert metrics["metrics"] == {"exact_match": 1.0, "token_f1": 1.0}
    assert traces[0]["claims"][0]["evidence_cids"] == [cli.cid]
    payload = json.dumps(cli.payloads)
    assert "answer" not in payload
    assert "orchard shed" in payload  # Evidence is data; the answer label field is not.


def test_longmemeval_qa_question_set_and_answer_labels_fail_closed() -> None:
    value = _assets()
    value["assets"]["longmemeval_s_cleaned.json"][0].pop("answer")
    value["assets"]["longmemeval_s_cleaned.json"][0].pop("answer_aliases")
    with pytest.raises(ValueError, match="answer is missing"):
        normalize(value)

    value = _assets()
    value["assets"]["longmemeval_s_cleaned.json"].append(
        {**value["assets"]["longmemeval_s_cleaned.json"][0], "question_id": "q2"}
    )
    with pytest.raises(ValueError):
        normalize(value)


def test_case_gold_answer_fields_never_enter_capture_or_reader_payloads() -> None:
    """Gold isolation: answer labels stay scorer-side; capture/eval payloads omit them."""
    cli = RecordingCLI()
    run(_assets(), cli)  # type: ignore[arg-type]
    for payload in cli.payloads:
        for banned in ("gold_answer", "gold_aliases", "answer_aliases", "answer"):
            assert banned not in payload


def test_external_candidate_manifest_freeze_is_immutable_and_schema_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """12-04-01 freeze: external no-overwrite manifest binds protocol digests once."""
    protocol = load_qa_protocol()
    git_sha = "a" * 40
    model_digest = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
    manifest = build_candidate_manifest(
        model_content_sha256=model_digest,
        git_sha=git_sha,
        created_at_utc="2026-07-11T00:00:00Z",
    )
    assert manifest["candidate_version"] == protocol["version"]
    assert manifest["git_sha"] == git_sha
    assert manifest["transport_retries"] == 0
    assert manifest["evidence_budget"] == protocol["evidence_budget"]
    assert manifest["abstention"] == protocol["abstention"]
    digests = qa_protocol_digests(protocol)
    for key, value in digests.items():
        assert manifest[key] == value
    validate_candidate_manifest(manifest, expected_git_sha=git_sha)
    monkeypatch.setattr(runner, "_current_clean_head", lambda _root: git_sha)
    external = tmp_path / "candidate-manifest.json"
    write_candidate_manifest(external, manifest)
    if os.name != "nt":
        assert stat.S_IMODE(external.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_candidate_manifest(external, manifest)
    forged = {**manifest, "git_sha": "b" * 40}
    with pytest.raises(ValueError, match="expected commit"):
        validate_candidate_manifest(forged, expected_git_sha=git_sha)
