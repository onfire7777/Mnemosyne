from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters.longmemeval import run


class FakeCLI:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def capture_batch(self, input_jsonl: Path | str) -> dict[str, Any]:
        incoming = [
            json.loads(line) for line in Path(input_jsonl).read_text().splitlines()
        ]
        offset = len(self.rows)
        self.rows.extend(incoming)
        return {
            "ok": True,
            "count": len(incoming),
            "results": [
                {"cid": f"cid-{index}"}
                for index in range(offset, offset + len(incoming))
            ],
        }

    def search(self, tenant: str, query: str) -> dict[str, Any]:
        indexes = [
            index for index, row in enumerate(self.rows) if row["tenant"] == tenant
        ]
        # Rank the support session first while still returning a realistic CID.
        indexes.sort(
            key=lambda index: (
                "support" not in self.rows[index]["source_identity"],
                index,
            )
        )
        return {"hits": [{"id": f"cid-{index}"} for index in indexes]}


def _assets() -> dict[str, Any]:
    cleaned = [
        {
            "question_id": "q-1",
            "question_type": "single-session-user",
            "question": "Where did Alice leave the brass key?",
            "answer": "In the orchard shed.",
            "question_date": "2024/01/03 (Wed) 10:00",
            "haystack_dates": ["2024/01/01 (Mon) 10:00", "2024/01/02 (Tue) 10:00"],
            "haystack_session_ids": ["q1-noise", "q1-support"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "The blue bicycle is repaired."},
                    {"role": "assistant", "content": "Noted."},
                ],
                [
                    {
                        "role": "user",
                        "content": "I left the brass key in the orchard shed.",
                    },
                    {"role": "assistant", "content": "I will remember that."},
                ],
            ],
            "answer_session_ids": ["q1-support"],
        },
        {
            "question_id": "q-2",
            "question_type": "single-session-assistant",
            "question": "Which room contains Bob's atlas?",
            "answer": "The attic.",
            "question_date": "2024/02/03 (Sat) 10:00",
            "haystack_dates": ["2024/02/01 (Thu) 10:00", "2024/02/02 (Fri) 10:00"],
            "haystack_session_ids": ["q2-support", "q2-noise"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "Where is the atlas?"},
                    {"role": "assistant", "content": "Bob's atlas is in the attic."},
                ],
                [
                    {"role": "user", "content": "The garden gate is green."},
                    {"role": "assistant", "content": "Understood."},
                ],
            ],
            "answer_session_ids": ["q2-support"],
        },
    ]
    oracle = []
    answer_indexes = {"q-1": 0, "q-2": 1}
    for item in cleaned:
        sessions = []
        for session_id, turns in zip(
            item["haystack_session_ids"], item["haystack_sessions"], strict=True
        ):
            sessions.append(
                [
                    {
                        **turn,
                        "has_answer": session_id in item["answer_session_ids"]
                        and index == answer_indexes[item["question_id"]],
                    }
                    for index, turn in enumerate(turns)
                ]
            )
        oracle.append(
            {
                "question_id": item["question_id"],
                "haystack_session_ids": item["haystack_session_ids"],
                "haystack_sessions": sessions,
            }
        )
    return {
        "assets": {
            "longmemeval_s_cleaned.json": cleaned,
            "longmemeval_oracle.json": oracle,
        }
    }


def test_adapter_preserves_session_and_turn_golds_with_isolated_tenants() -> None:
    cli = FakeCLI()
    benchmark, traces, metrics = run(_assets(), cli)  # type: ignore[arg-type]

    assert benchmark["k"] == 5
    assert [trace["question_id"] for trace in traces] == ["q-1", "q-2"]
    assert traces[0]["answer_session_ids"] == ["q1-support"]
    assert traces[0]["oracle_has_answer_turns"]["q1-support"] == [0]
    assert traces[1]["oracle_has_answer_turns"]["q2-support"] == [1]
    assert traces[0]["ranked_retrieved_hits"][0] == "q1-support"
    assert traces[1]["ranked_retrieved_hits"][0] == "q2-support"
    assert {row["tenant"] for row in cli.rows} == {"longmemeval:q-1", "longmemeval:q-2"}
    assert all(trace["scoring_family"] == "deterministic-retrieval" for trace in traces)
    assert metrics["profile"] == "longmemeval-retrieval-v1"
    assert metrics["metrics"] == {"recall_at_5": 1.0, "ndcg_at_5": 1.0}
    assert metrics["interval"]["method"] == "bootstrap"
    assert "judge" not in metrics and "reader" not in metrics


def test_normalized_benchmark_reproduction_is_canonical() -> None:
    benchmark, first_traces, first_metrics = run(_assets(), FakeCLI())  # type: ignore[arg-type]
    reproduced, traces, metrics = run(benchmark, FakeCLI())  # type: ignore[arg-type]
    assert reproduced == benchmark
    assert traces == first_traces
    assert metrics == first_metrics


def test_oracle_may_be_the_official_answer_session_subset() -> None:
    value = _assets()
    for row in value["assets"]["longmemeval_oracle.json"]:
        keep = [
            index
            for index, session_id in enumerate(row["haystack_session_ids"])
            if "support" in session_id
        ]
        row["haystack_session_ids"] = [
            row["haystack_session_ids"][index] for index in keep
        ]
        row["haystack_sessions"] = [row["haystack_sessions"][index] for index in keep]
    benchmark, traces, _ = run(value, FakeCLI())  # type: ignore[arg-type]
    assert len(benchmark["questions"]) == 2
    assert all(any(trace["oracle_has_answer_turns"].values()) for trace in traces)


def test_adapter_uses_real_public_cli_subprocess_seam(tmp_path: Path) -> None:
    aggregate_store = tmp_path / "store.json"
    benchmark, traces, metrics = run(
        _assets(), MnemoCLI(store=str(aggregate_store))
    )
    assert len(benchmark["questions"]) == len(traces) == metrics["trace_count"] == 2
    assert all(trace["ranked_retrieved_hits"] for trace in traces)
    assert not aggregate_store.exists()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["assets"].pop("longmemeval_oracle.json"),
            "exact cleaned and oracle",
        ),
        (
            lambda value: value["assets"]["longmemeval_s_cleaned.json"][0].update(
                answer_session_ids=["unknown"]
            ),
            "unknown answer sessions",
        ),
        (
            lambda value: value["assets"]["longmemeval_oracle.json"].pop(),
            "missing question",
        ),
    ],
)
def test_adapter_rejects_incomplete_or_ambiguous_upstream_labels(
    mutate: Any, message: str
) -> None:
    value = _assets()
    mutate(value)
    with pytest.raises(ValueError, match=message):
        run(value, FakeCLI())  # type: ignore[arg-type]


def test_search_results_cannot_cross_question_tenant_boundary() -> None:
    class ContaminatingCLI(FakeCLI):
        def search(self, tenant: str, query: str) -> dict[str, Any]:
            own = super().search(tenant, query)["hits"]
            return {"hits": [{"id": "foreign-or-unknown-cid"}, *own]}

    _, traces, _ = run(_assets(), ContaminatingCLI())  # type: ignore[arg-type]
    assert all(
        all(
            hit.startswith(trace["question_id"].replace("-", ""))
            for hit in trace["ranked_retrieved_hits"]
        )
        for trace in traces
    )


def test_adapter_fails_closed_when_batch_capture_omits_records() -> None:
    class ShortBatch(FakeCLI):
        def capture_batch(self, input_jsonl: Path | str) -> dict[str, Any]:
            result = super().capture_batch(input_jsonl)
            result["results"].pop()
            return result

    with pytest.raises(ValueError, match="invalid result count"):
        run(_assets(), ShortBatch())  # type: ignore[arg-type]


def test_duplicate_noise_session_ids_get_stable_record_ids() -> None:
    value = _assets()
    cleaned = value["assets"]["longmemeval_s_cleaned.json"][0]
    cleaned["haystack_session_ids"][0] = "duplicate-noise"
    cleaned["haystack_session_ids"].insert(1, "duplicate-noise")
    cleaned["haystack_sessions"].insert(1, cleaned["haystack_sessions"][0])
    oracle = value["assets"]["longmemeval_oracle.json"][0]
    oracle["haystack_sessions"].insert(1, oracle["haystack_sessions"][0])
    benchmark, _, _ = run(value, FakeCLI())  # type: ignore[arg-type]
    ids = [
        row["session_id"] for row in benchmark["corpus"] if row["question_id"] == "q-1"
    ]
    assert "duplicate-noise#occurrence-0" in ids
    assert "duplicate-noise#occurrence-1" in ids


def test_empty_upstream_turn_content_is_preserved() -> None:
    value = _assets()
    value["assets"]["longmemeval_s_cleaned.json"][0]["haystack_sessions"][0][0][
        "content"
    ] = ""
    benchmark, _, _ = run(value, FakeCLI())  # type: ignore[arg-type]
    content = next(
        row["content"]
        for row in benchmark["corpus"]
        if row["question_id"] == "q-1" and row["source_session_id"] == "q1-noise"
    )
    assert content.startswith("user: \n")


def test_extra_oracle_question_is_rejected() -> None:
    value = _assets()
    extra = dict(value["assets"]["longmemeval_oracle.json"][0])
    extra["question_id"] = "extra"
    value["assets"]["longmemeval_oracle.json"].append(extra)

    with pytest.raises(ValueError, match="question set does not match"):
        run(value, FakeCLI())  # type: ignore[arg-type]


def test_duplicate_capture_cid_is_rejected() -> None:
    class DuplicateCIDCLI(FakeCLI):
        def capture_batch(self, input_jsonl: Path | str) -> dict[str, Any]:
            import json

            rows = [
                json.loads(line) for line in Path(input_jsonl).read_text().splitlines()
            ]
            return {"results": [{"cid": "same"} for _ in rows]}

    with pytest.raises(ValueError, match="duplicate CID"):
        run(_assets(), DuplicateCIDCLI())  # type: ignore[arg-type]
