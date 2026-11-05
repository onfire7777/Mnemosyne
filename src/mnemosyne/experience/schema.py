"""Schema matching changes probation length, never source content."""

from __future__ import annotations

from copy import deepcopy

NODE_TYPES = {"step", "warning", "constraint", "case"}


def assimilate(candidate: dict, artifacts: list[dict]) -> dict:
    result = deepcopy(candidate)
    quotes = candidate.get("source_quotes", [])
    if not quotes or not all(
        any(step in quote["quote"] for quote in quotes) for step in candidate["steps"]
    ):
        return result
    for schema in sorted(artifacts, key=lambda row: row["id"]):
        if schema["state"] != "active" or schema.get("locked") or schema.get("pinned"):
            continue
        if schema["kind"] != "skill" or schema["task_class"] != candidate["task_class"]:
            continue
        if (
            schema.get("user_id") != candidate.get("user_id")
            or schema.get("scope_match") != candidate.get("scope_match")
            or schema.get("conditions", []) != candidate.get("conditions", [])
        ):
            continue
        nodes = schema.get("framework", {}).get("nodes", [])
        types = {node.get("type") for node in nodes} & NODE_TYPES
        node_type = candidate.get("node_type", "step")
        if node_type not in types:
            continue
        result["schema_ref"] = {
            "id": schema["id"],
            "revision": schema["revision"],
            "node_type": node_type,
        }
        result["framework_node"] = {
            "type": node_type,
            "content": candidate["content"],
            "source_quotes": deepcopy(quotes),
        }
        result["probation_outcomes"] = 5
        return result
    return result
