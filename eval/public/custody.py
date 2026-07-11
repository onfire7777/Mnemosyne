"""Public eval custody helpers that keep adapters off engine internals."""

from typing import Any, Mapping

from mnemosyne.ids import evidence_cid


def capture_cid(capture: Mapping[str, Any]) -> str:
    return evidence_cid(
        str(capture["content"]), tenant_id=str(capture["tenant_id"]),
        user_id=str(capture["user_id"]), source_type=str(capture["source_type"]),
        content_pointer=capture.get("content_pointer"), modality=str(capture["modality"]),
        sensitivity=int(capture["sensitivity"]),
    )


def first_hop_rows(
    hops: list[dict[str, Any]], captures: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Project each authorized CID once, at its first observed hop."""
    seen: set[str] = set()
    projected = []
    for hop in hops:
        rows = []
        for cid in hop.get("retrieved_cids", []):
            if cid in captures and cid not in seen:
                seen.add(cid)
                rows.append({"capture": captures[cid], "cid": cid})
        projected.append({"hop": hop["index"], "rows": rows})
    return projected or [{"hop": 0, "rows": []}]
