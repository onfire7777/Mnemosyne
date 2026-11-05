"""Write-once records of what a decision had available."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

ROUTE_OF_CHANNEL = {
    "lexical": "lexical",
    "postgres_fts": "lexical",
    "command_lexical": "lexical",
    "postgres_lexical_fallback": "lexical",
    "dense": "vector",
    "vector": "vector",
    "postgres_pgvector": "vector",
    "postgres_dense_fallback": "vector",
    "graph_ppr": "graph",
    "postgres_graph_ppr": "graph",
    "command_graph_ppr": "graph",
    "passage_graph": "graph",
    "working_memory": "working",
    "prospective_memory": "prospective",
}


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ServedItem:
    kind: str
    item_id: str
    routes: tuple[str, ...]
    rank: int
    revision: int = 1


@dataclass(frozen=True)
class ContextReceipt:
    id: str
    tenant_id: str
    user_id: str
    session_id: str
    task_class: str
    prediction: float
    policy_version: str
    created_at: str
    turn_index: int
    items: tuple[ServedItem, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["prediction_hash"] = digest(self.prediction)
        return result
