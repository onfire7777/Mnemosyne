"""Helpers copied from the QA v2 runner (now Mnemetric's) for the white-box graph-PPR baseline."""

from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Any


_FROZEN_DATASET = Path(__file__).with_name("qa_hard_v2.json").resolve()


def load_dataset(path: Path, *, allow_frozen: bool = False) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("grounded QA dataset must be a real file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("corpus"), list) or not isinstance(value.get("queries"), list):
        raise ValueError("grounded QA dataset schema is invalid")
    if value.get("dataset_id") == "qa_hard_v2" and (
        not allow_frozen or path.resolve() != _FROZEN_DATASET
    ):
        raise ValueError("qa_hard_v2 is frozen and bound to its canonical path")
    if not value["corpus"] or not value["queries"]:
        raise ValueError("grounded QA dataset is empty")
    return value


def _retrieval_score(ranked: list[str], gold: list[str]) -> tuple[float, float]:
    recall = len(set(ranked) & set(gold)) / len(gold)
    dcg = sum(1 / math.log2(index + 2) for index, item in enumerate(ranked) if item in set(gold))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(5, len(gold))))
    return recall, dcg / ideal


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
