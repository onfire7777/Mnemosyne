from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from mnemosyne.ids import evidence_cid

from eval.public.adapters.longmemeval_qa import normalize, run


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
