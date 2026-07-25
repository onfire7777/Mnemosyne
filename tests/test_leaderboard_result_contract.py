from leaderboard.validate import validate_record


def _retrieval_record() -> dict[str, object]:
    return {
        "schema_version": "mnemosyne.leaderboard.result/v1",
        "record_id": "synthetic-retrieval-001",
        "system": "mnemosyne",
        "track": "development",
        "benchmark": "synthetic-retrieval",
        "benchmark_version": "1",
        "run_commit": "0123456789abcdef0123456789abcdef01234567",
        "build_fingerprint": f"sha256:{'1' * 64}",
        "config_digest": f"sha256:{'2' * 64}",
        "bundle_digest": f"sha256:{'3' * 64}",
        "trace_index_digest": f"sha256:{'4' * 64}",
        "metrics": [
            {
                "name": "recall_at_10",
                "family": "retrieval",
                "value": 0.75,
                "unit": "ratio",
                "confidence_interval": {"low": 0.60, "high": 0.85},
            }
        ],
        "publication": {"publishable": False, "label": "operator-run"},
        "operator_entry": {"operator": "synthetic-test", "disclosed": True},
        "history": {"supersedes": None},
    }


def _judged_qa_record() -> dict[str, object]:
    record = _retrieval_record()
    record.update(
        {
            "record_id": "synthetic-judged-qa-001",
            "benchmark": "synthetic-judged-qa",
            "metrics": [
                {
                    "name": "answer_quality",
                    "family": "judged_qa",
                    "value": 0.80,
                    "unit": "ratio",
                    "confidence_interval": {"low": 0.70, "high": 0.90},
                    "judge": {
                        "model": "synthetic-judge-v1",
                        "prompt_digest": f"sha256:{'5' * 64}",
                        "config_digest": f"sha256:{'6' * 64}",
                    },
                }
            ],
        }
    )
    return record


def test_accepts_minimal_deterministic_retrieval_record() -> None:
    assert validate_record(_retrieval_record()) == []


def test_accepts_minimal_disclosed_judged_qa_record() -> None:
    assert validate_record(_judged_qa_record()) == []
