"""Single learning write path, atomic audit and automatic defect containment."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from mnemosyne.ids import new_id

from .guards import LearningGuardError, validate
from .receipts import digest
from .store import LearningStore


class LearningWriter:
    def __init__(self, engine):
        self.store = LearningStore(engine)

    def read(self, tenant: str) -> dict:
        return self.store.read(tenant)

    def apply(
        self,
        tenant: str,
        operation: str,
        mutation,
        *,
        expected_revision: int | None = None,
        erasure_terms: list[str] | None = None,
    ):
        error = None
        with self.store.transaction(tenant) as (state, handle):
            before = copy.deepcopy(state)
            revision = state["policy"].get("revision", 0)
            if expected_revision is not None and revision != expected_revision:
                raise ValueError("learning revision conflict")
            try:
                result = mutation(state)
                validate(
                    before,
                    state,
                    operation,
                    source_lookup=lambda cid: self.store.engine.get_evidence(
                        tenant, cid
                    ),
                )
            except LearningGuardError as caught:
                attempted = copy.deepcopy(state)
                state = copy.deepcopy(before)
                state["policy"]["frozen"] = True
                defect_id = new_id()
                state["defects"][defect_id] = {
                    "id": defect_id,
                    "class": caught.code,
                    "guard": str(caught),
                    "status": "open",
                    "severity": "release-blocking",
                    "operation": operation,
                    "reproduction_seed": digest([tenant, operation, revision]),
                    "created_at": datetime.now(UTC).isoformat(),
                    "fixing_commit": None,
                    "before": before,
                    "attempted": attempted,
                }
                error, result = caught, None
                operation = "defect"
            if state == before:
                return copy.deepcopy(result)
            state["policy"]["revision"] = revision + 1
            changes = []
            for collection in state:
                for key in sorted(before[collection].keys() | state[collection].keys()):
                    old, new = before[collection].get(key), state[collection].get(key)
                    if old != new:
                        changes.append(
                            {
                                "collection": collection,
                                "key": key,
                                "before": old,
                                "after": new,
                            }
                        )
            event = {
                "id": new_id(),
                "op": "learning." + operation,
                "changes": changes,
                "revision": revision + 1,
                "created_at": datetime.now(UTC).isoformat(),
            }
            self.store.save(
                tenant, before, state, handle, event, erasure_terms=erasure_terms
            )
        if error:
            raise error
        return copy.deepcopy(result)

    def rollback(self, tenant: str, audit_id: str) -> dict:
        event = next(
            (row for row in self.store.history(tenant) if row["id"] == audit_id), None
        )
        if event is None:
            raise KeyError("learning audit event not found")
        if event.get("erased") or event["op"] in {
            "learning.capture",
            "learning.observe",
            "learning.erasure",
            "learning.defect",
        }:
            raise ValueError("capture, erasure and defect records are immutable")

        def revert(state):
            restored_candidates = []
            for change in reversed(event["changes"]):
                collection, key = change["collection"], change["key"]
                if collection == "policy" and key == "revision":
                    continue
                if state[collection].get(key) != change["after"]:
                    raise ValueError("rollback conflicts with later learning")
                if (
                    collection == "artifacts"
                    and isinstance(change["after"], dict)
                    and change["after"].get("state")
                    in {"retired", "archived", "rejected"}
                    and isinstance(change["before"], dict)
                ):
                    candidate = copy.deepcopy(change["before"])
                    candidate.update(
                        id=new_id(),
                        revision=candidate["revision"] + 1,
                        parent_revision=key,
                        state="candidate",
                        gate_passed=False,
                    )
                    candidate.pop("gate_evidence", None)
                    state[collection][candidate["id"]] = candidate
                    restored_candidates.append(candidate["id"])
                elif change["before"] is None:
                    state[collection].pop(key, None)
                else:
                    state[collection][key] = copy.deepcopy(change["before"])
            from .revisions import propagate_children
            propagate_children(state)
            return {"rolled_back": audit_id, "restored_candidates": restored_candidates}

        return self.apply(tenant, "rollback", revert)
