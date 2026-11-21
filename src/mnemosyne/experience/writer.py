"""Single learning write path, atomic audit and automatic defect containment."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from mnemosyne.ids import new_id

from .guards import LearningGuardError, validate
from .receipts import digest
from .store import LearningStore, _CowDict, _CowList, _to_plain, _wrap_state_cow

_MISSING = object()
_IMMUTABLE_AUDIT_OPS = frozenset({"observe", "capture"})
_TOOL_RAW_OUTPUT_KEYS = frozenset({"output", "stdout", "stderr", "aggregated_output"})
_TERMINAL_ARTIFACT_STATES = frozenset({"retired", "archived", "rejected"})


def _slim_immutable_audit_value(collection: str, value):
    """Strip duplicated raw tool output from immutable observe/capture audit copies.

    The raw tool output is already content-addressed in the ``evidence`` table.
    All structured fields and IDs remain intact so reference-based crypto-shredding
    and audit verification stay unchanged.
    """
    if collection != "episodes" or not isinstance(value, dict):
        return value
    events = value.get("tool_events")
    if not isinstance(events, list) or not any(
        isinstance(ev, dict) and (_TOOL_RAW_OUTPUT_KEYS & ev.keys()) for ev in events
    ):
        return value
    slim_events = []
    for ev in events:
        if not isinstance(ev, dict):
            slim_events.append(ev)
            continue
        slim_ev = {k: v for k, v in ev.items() if k not in _TOOL_RAW_OUTPUT_KEYS}
        if "output_sha256" not in slim_ev:
            raw = ev.get("output") or ev.get("stdout") or ev.get("stderr") or ev.get("aggregated_output")
            if isinstance(raw, str) and raw:
                slim_ev["output_sha256"] = digest(raw)
        slim_events.append(slim_ev)
    return {**value, "tool_events": slim_events}


class LearningWriter:
    def __init__(self, engine):
        self.store = LearningStore(engine)
        self._migrated = set()

    def read(self, tenant: str) -> dict:
        state = self.store.read(tenant)
        if "legacy_learning" in state["policy"] or any("legacy_trajectory" in row for row in state["episodes"].values()):
            from mnemosyne.learning import merge_legacy_learning
            self.apply(tenant, "legacy_migration",
                       lambda current: merge_legacy_learning(current, self.store.engine, tenant))
            state = self.store.read(tenant)
        self._migrated.add(tenant)
        return state

    def apply(
        self,
        tenant: str,
        operation: str,
        mutation,
        *,
        expected_revision: int | None = None,
        erasure_terms: list[str] | None = None,
    ):
        # The pre-read only triggers legacy migration; once per writer and tenant is enough.
        if operation != "legacy_migration" and tenant not in self._migrated:
            self.read(tenant)
        error = None
        with self.store.transaction(tenant) as (state, handle):
            is_cow = all(isinstance(col, _CowDict) for col in state.values())
            before = (
                {col: state[col]._origin for col in state}
                if is_cow
                else copy.deepcopy(state)
            )
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
                state = (
                    _wrap_state_cow(before) if is_cow else copy.deepcopy(before)
                )
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
                    "before": copy.deepcopy(before),
                    "attempted": attempted,
                }
                error, result = caught, None
                operation = "defect"
            if state == before:
                return copy.deepcopy(result)
            state["policy"]["revision"] = revision + 1
            changes = []
            for collection in state:
                col_state = state[collection]
                col_before = before[collection]
                if (
                    isinstance(col_state, _CowDict)
                    and not col_state._dirty
                    and col_state._origin is col_before
                ):
                    continue
                for key in sorted(col_before.keys() | col_state.keys()):
                    old = col_before.get(key)
                    new = dict.get(col_state, key) if isinstance(col_state, _CowDict) else col_state.get(key)
                    if (
                        isinstance(new, (_CowDict, _CowList))
                        and not new._dirty
                        and new._origin is old
                    ):
                        continue
                    if old is new or old == new:
                        continue
                    plain_new = _to_plain(new)
                    audit_old = old
                    audit_new = plain_new
                    if operation in _IMMUTABLE_AUDIT_OPS:
                        audit_old = _slim_immutable_audit_value(collection, audit_old)
                        audit_new = _slim_immutable_audit_value(collection, audit_new)
                    changes.append(
                        {
                            "collection": collection,
                            "key": key,
                            "before": audit_old,
                            "after": audit_new,
                        }
                    )
                    if isinstance(audit_old, dict) and isinstance(audit_new, dict):
                        # Audit only mutated top-level fields across all dict
                        # collections (policy, episodes, receipts, artifacts,
                        # credit, stats, defects) so unchanged multi-MB subtrees
                        # such as episode tool_events are never re-logged.
                        names = [
                            name
                            for name in audit_old.keys() | audit_new.keys()
                            if audit_old.get(name, _MISSING) != audit_new.get(name, _MISSING)
                        ]
                        changes[-1].update(
                            before={name: audit_old[name] for name in names if name in audit_old},
                            after={name: audit_new[name] for name in names if name in audit_new},
                            partial=True,
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
            "learning.legacy_archive",
            "learning.legacy_migration",
        }:
            raise ValueError("capture, erasure, migration and defect records are immutable")

        def revert(state):
            restored_candidates = []
            for change in reversed(event["changes"]):
                collection, key = change["collection"], change["key"]
                if collection == "policy" and key == "revision":
                    continue
                if change.get("partial"):
                    current = state[collection].get(key)
                    names = change["before"].keys() | change["after"].keys()
                    if not isinstance(current, dict) or any(
                        current.get(name, _MISSING) != change["after"].get(name, _MISSING) for name in names
                    ):
                        raise ValueError("rollback conflicts with later learning")
                    if (
                        collection == "artifacts"
                        and change["after"].get("state") in _TERMINAL_ARTIFACT_STATES
                    ):
                        prior = copy.deepcopy(current)
                        for name in names:
                            if name in change["before"]:
                                prior[name] = copy.deepcopy(change["before"][name])
                            else:
                                prior.pop(name, None)
                        candidate = copy.deepcopy(prior)
                        candidate.update(
                            id=new_id(),
                            revision=candidate["revision"] + 1,
                            parent_revision=key,
                            state="candidate",
                            gate_passed=False,
                        )
                        candidate.pop("gate_evidence", None)
                        from .revisions import inherit_library_lineage
                        inherit_library_lineage(candidate, prior)
                        state[collection][candidate["id"]] = candidate
                        restored_candidates.append(candidate["id"])
                        continue
                    for name in names:
                        if name in change["before"]:
                            current[name] = copy.deepcopy(change["before"][name])
                        else:
                            current.pop(name, None)
                    continue
                if state[collection].get(key) != change["after"]:
                    raise ValueError("rollback conflicts with later learning")
                if (
                    collection == "artifacts"
                    and isinstance(change["after"], dict)
                    and change["after"].get("state") in _TERMINAL_ARTIFACT_STATES
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
                    from .revisions import inherit_library_lineage
                    inherit_library_lineage(candidate, change["before"])
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
