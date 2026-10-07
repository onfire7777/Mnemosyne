"""Thin canary branches for the in-memory engine: copy on write, exact merge.

The promotion gate tries every fact candidate on a canary branch. ``LocalMemoryEngine.branch``
used to deep-copy every evidence row, assertion and relation of the tenant into each canary,
and ``merge`` replayed every copy back into main. With one canary per extracted fact, batch
consolidation was quadratic.

A canary created by the gate (kind ``canary`` from ``main`` for one tenant, while persistence
is deferred or in memory) is an *overlay* here: the branch exists, but nothing is copied. An
overlay reads through to main. A whole assertion group (tenant, subject, predicate) is copied
into the overlay the moment an upsert on the overlay touches it, so the upsert runs the
unchanged engine code against exactly the copies a full branch would hold.

MERGE replays what the legacy merge replays, in the same order within each group:

* every group the canary touched, every group holding a fact born at the previous merge (its
  first replay normalises it), and every *unstable* group - one whose replay rewrites another
  fact - is replayed eagerly through the real upsert code;
* every other group would only be re-stamped by the replay (``last_accessed`` of an active fact,
  ``transaction_time`` of a superseded one, idempotent recomputations). Those replays are
  DEFERRED: they are run later through the same upsert code, with the merge's own time, before
  anything can observe them (``flush``). Replaying a stable group at the last merge only is
  identical to replaying it at every merge.

The two outcomes that legacy keeps forever and that nothing reads are not reproduced (approved
contract): the merged canary branch itself, and the per-merge audit rows of re-upserted copies.

SAFETY NET. The engine's public ``evidence``/``assertions``/``relations`` attributes settle
first whenever they are used outside an overlay-aware operation: deferred replays are flushed
and every live overlay is converted into the full physical branch legacy would have built, in
legacy order. Code that knows nothing about overlays therefore always sees exactly the legacy
state. ``MNEMOSYNE_THIN_CANARIES=0`` turns the whole mechanism off.
"""

from __future__ import annotations

import contextlib
import copy
import os
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

THIN_CANARIES_ENV = "MNEMOSYNE_THIN_CANARIES"
_ACTIVE = ("active", "contested")


def thin_canaries_enabled() -> bool:
    return os.environ.get(THIN_CANARIES_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class CanaryOverlay:
    tenant_id: str
    parent: str


@dataclass
class TenantMergeState:
    """What the overlay merges know about one tenant's main branch."""

    gen: int = 0
    time: datetime | None = None
    # True until a merge has replayed every group once since the state was (re)built.
    first: bool = True
    # Deferred replays of merge `gen` not yet applied.
    pending: bool = False
    # Assertion groups that already carry merge `gen`'s replay (eager or flushed).
    replayed_groups: set[tuple[str, str]] = field(default_factory=set)
    # Main keys inserted by merge `gen`: not replayed by it, replayed first by the next one.
    born_last: list[str] = field(default_factory=list)
    born_last_relations: list[str] = field(default_factory=list)
    # Assertion groups whose replay rewrites another fact, and relation keys with several
    # members: both are replayed eagerly at every merge.
    unstable: set[tuple[str, str]] = field(default_factory=set)
    multi_relations: set[tuple[str, str, str]] = field(default_factory=set)


class CanaryOverlayMixin:
    """Overlay canaries for ``LocalMemoryEngine`` (see the module docstring)."""

    _overlays: dict[str, CanaryOverlay] | None = None
    _overlay_states: dict[str, TenantMergeState] | None = None
    _overlay_depth: int = 0
    _overlay_flush_needed: bool = False

    def _overlay_init(self) -> None:
        self._overlays = {}
        self._overlay_states = {}
        self._overlay_depth = 0
        self._overlay_flush_needed = False
        # Candidate projections of parent rows, per access context: evidence entries carry the
        # fields they were built from, assertion entries are dropped when a merge touches them.
        self._overlay_projection: OrderedDict[Any, tuple[dict[str, Any], dict[str, Any]]] = OrderedDict()
        self.overlay_stats: dict[str, int] = {
            "created": 0, "merged": 0, "discarded": 0, "materialized": 0, "flushed": 0,
            "group_flushes": 0, "eager_groups": 0, "deferred_merges": 0,
        }

    @contextlib.contextmanager
    def _overlay_context(self) -> Iterator[None]:
        self._overlay_depth += 1
        try:
            yield
        finally:
            self._overlay_depth -= 1

    # ------------------------------------------------------------------ settling (safety net)

    def _overlay_settle(self, *, reset: bool) -> None:
        """Flush deferred replays and turn every overlay into the legacy physical branch."""
        if os.environ.get("MNEMOSYNE_OVERLAY_TRACE") and (
            self._overlays or self._overlay_flush_needed or (reset and self._overlay_states)
        ):
            import traceback

            frames = traceback.extract_stack(limit=6)[:-2]
            where = ("reset " if reset else "") + " < ".join(
                f"{frame.name}:{frame.lineno}" for frame in reversed(frames)
            )
            trace = self.overlay_stats.setdefault("settle_callers", {})  # type: ignore[assignment]
            trace[where] = trace.get(where, 0) + 1
        with self._lock:
            self._overlay_depth += 1
            try:
                # The caller may change anything next: no cached projection survives it.
                self._overlay_projection.clear()
                if self._overlay_flush_needed:
                    self._overlay_flush_all()
                for name in list(self._overlays or ()):
                    self._overlay_materialize(name)
                if reset and self._overlay_states:
                    # Unknown code may change main: rebuild the stability knowledge from scratch.
                    self._overlay_states.clear()
            finally:
                self._overlay_depth -= 1

    def _overlay_flush_all(self) -> None:
        for tenant_id, state in (self._overlay_states or {}).items():
            if state.pending:
                self._overlay_flush_tenant(tenant_id, state)
        self._overlay_flush_needed = False
        self.overlay_stats["flushed"] += 1

    def _overlay_forget_projections(self, keys: Any = None) -> None:
        """Drop cached assertion projections for ``keys`` (all of them when None)."""
        if keys is None:
            for _, assertion_cache in self._overlay_projection.values():
                assertion_cache.clear()
            return
        keys = list(keys)
        for _, assertion_cache in self._overlay_projection.values():
            for key in keys:
                assertion_cache.pop(key, None)

    def _overlay_group_snapshot(self, tenant_id: str, branch: str, subject: str, predicate: str) -> dict[str, Any]:
        """Private copies of a group's members, taken before any of them is replayed.

        Legacy replays the canary's copies, taken when the canary was created. Replaying one
        member can rewrite another (a re-upserted retracted fact supersedes the active one, whose
        own copy then restores it), so a later member must never be replayed from the live row.
        A group of one cannot rewrite itself before its replay: it needs no snapshot.
        """
        members = self._assertion_items.peers(tenant_id, branch, subject, predicate)
        if len(members) < 2:
            return {}
        return {key: copy.deepcopy(item) for key, item in members.items()}

    def _overlay_flush_tenant(self, tenant_id: str, state: TenantMergeState) -> None:
        self._overlay_forget_projections()
        born = set(state.born_last)
        snapshots: dict[tuple[str, str], dict[str, Any]] = {}
        for key, item in list(self._assertion_items.in_branch(tenant_id, "main").items()):
            group = (item.subject, item.predicate)
            if key in born or group in state.replayed_groups:
                continue
            snapshot = snapshots.get(group)
            if snapshot is None:
                snapshot = snapshots[group] = self._overlay_group_snapshot(tenant_id, "main", *group)
            own = snapshot.pop(key, None)
            self._overlay_replay(item if own is None else own, "main", now=state.time, audit=False,
                                 persist=False, owned=own is not None)
        state.pending = False
        state.replayed_groups = set()

    def _overlay_flush_group(self, tenant_id: str, subject: str, predicate: str) -> None:
        state = (self._overlay_states or {}).get(tenant_id)
        if state is None or not state.pending or (subject, predicate) in state.replayed_groups:
            return
        born = set(state.born_last)
        members = list(self._assertion_items.peers(tenant_id, "main", subject, predicate).items())
        snapshot = self._overlay_group_snapshot(tenant_id, "main", subject, predicate)
        for key, item in members:
            if key not in born:
                own = snapshot.get(key)
                self._overlay_replay(item if own is None else own, "main", now=state.time, audit=False,
                                     persist=False, owned=own is not None)
        self._overlay_forget_projections(key for key, _ in members)
        state.replayed_groups.add((subject, predicate))
        self.overlay_stats["group_flushes"] += 1

    def _overlay_replay(self, source: Any, into: str, *, now: datetime | None, audit: bool = True,
                        persist: bool = True, owned: bool = False) -> str:
        """Exactly the legacy merge's replay of one assertion: copy, re-branch, upsert.

        ``owned`` means ``source`` is already a private copy nobody else holds.
        """
        cloned = source if owned else copy.deepcopy(source)
        cloned.branch = into
        return self._upsert_assertion_core(cloned, into, now=now, audit=audit, persist=persist)

    def _overlay_materialize(self, name: str) -> None:
        """Build the physical branch legacy ``branch()`` would have built, in legacy order."""
        overlay = self._overlays.pop(name)
        tenant_id = overlay.tenant_id
        for store, attr in ((self._evidence_items, "cid"), (self._assertion_items, "id"),
                            (self._relation_items, "id")):
            keyed = self._evidence_key if attr == "cid" else self._branch_key
            local = list(store.in_branch(tenant_id, name).items())
            copied: set[str] = set()
            for item in list(store.in_branch(tenant_id, overlay.parent).values()):
                ident = getattr(item, attr)
                if attr == "cid" and not ident:
                    continue
                key = keyed(tenant_id, name, ident)
                copied.add(key)
                existing = dict.get(store, key)
                if existing is not None:
                    del store[key]
                    store[key] = existing
                else:
                    clone = copy.deepcopy(item)
                    clone.branch = name
                    store[key] = clone
            for key, item in local:
                if key not in copied and dict.get(store, key) is item:
                    del store[key]
                    store[key] = item
        self.overlay_stats["materialized"] += 1

    # ------------------------------------------------------------------ creation and writes

    def _overlay_create(self, name: str, frm: str, kind: str, tenant_id: str | None) -> bool:
        if (
            kind != "canary"
            or frm != "main"
            or tenant_id is None
            or self._overlays is None
            or name in self.branches
            or self._read_only
            or not thin_canaries_enabled()
            # A store written after every change must hold the legacy branch on disk.
            or (self.store_path is not None and not self._persistence_defer_depth)
        ):
            return False
        with self._lock, self._overlay_context():
            self._require_branch(frm)
            branch_meta = self.branches.setdefault(
                name,
                {"from": frm, "kind": kind, "created_at": self._overlay_now().isoformat(), "tenants": []},
            )
            branch_meta["tenants"] = sorted(set(branch_meta.get("tenants") or []) | {tenant_id})
            self._overlays[name] = CanaryOverlay(tenant_id=tenant_id, parent=frm)
            self._audit(tenant_id, "engine", "branch", name, {"from": frm, "kind": kind})
            self._persist()
        self.overlay_stats["created"] += 1
        return True

    @staticmethod
    def _overlay_now() -> datetime:
        from mnemosyne.engine import utc_now

        return utc_now()

    def _overlay_upsert_assertion(self, assertion: Any, branch: str) -> str:
        overlay = self._overlays[branch]
        with self._lock, self._overlay_context():
            if assertion.tenant_id == overlay.tenant_id:
                self._overlay_materialize_group(branch, overlay, assertion.subject, assertion.predicate)
            return self._upsert_assertion_core(assertion, branch)

    def _overlay_materialize_group(self, name: str, overlay: CanaryOverlay, subject: str, predicate: str) -> None:
        """Copy one assertion group into the overlay, exactly as a full branch holds it."""
        tenant_id = overlay.tenant_id
        self._overlay_flush_group(tenant_id, subject, predicate)
        for item in list(self._assertion_items.peers(tenant_id, overlay.parent, subject, predicate).values()):
            key = self._branch_key(tenant_id, name, item.id)
            if dict.get(self._assertion_items, key) is None:
                clone = copy.deepcopy(item)
                clone.branch = name
                self._assertion_items[key] = clone

    def evidence_rows_for_reading(self) -> Any:
        """The evidence map for code that only READS rows (no settling, no copies).

        Deferred merge replays never touch evidence, so reading rows directly is exact.
        Callers must not mutate what they get.
        """
        return self._evidence_items

    def _evidence_row(self, tenant_id: str, branch: str, cid: str) -> Any:
        """An evidence row for READING: an overlay answers with its parent's row."""
        item = dict.get(self._evidence_items, self._evidence_key(tenant_id, branch, cid))
        if item is None and self._overlays:
            overlay = self._overlays.get(branch)
            if overlay is not None and overlay.tenant_id == tenant_id:
                item = dict.get(self._evidence_items, self._evidence_key(tenant_id, overlay.parent, cid))
        return item

    def superseded_fact_ids_on_branch(self, tenant_id: str, branch: str, fact_ids: Any) -> set[str]:
        """The ids in ``fact_ids`` whose assertion on ``branch`` is superseded.

        Equal to filtering ``export_tenant(tenant_id)['assertions']`` for that branch, status
        ``superseded`` and id in ``fact_ids``, without exporting. An overlay answers for an
        assertion it never copied with the parent's status, which is the copy's status.
        """
        overlay = (self._overlays or {}).get(branch)
        found: set[str] = set()
        with self._overlay_context():
            for fact_id in fact_ids:
                item = dict.get(self._assertion_items, self._branch_key(tenant_id, branch, fact_id))
                if item is None:
                    if overlay is None or overlay.tenant_id != tenant_id:
                        continue
                    item = dict.get(self._assertion_items, self._branch_key(tenant_id, overlay.parent, fact_id))
                    if item is None or item.branch != overlay.parent:
                        continue
                elif item.branch != branch:
                    continue
                if item.tenant_id == tenant_id and item.status == "superseded" and str(item.id) == fact_id:
                    found.add(fact_id)
        return found

    # ------------------------------------------------------------------ stability

    def _overlay_group_unstable(self, tenant_id: str, group: tuple[str, str]) -> bool:
        """Would replaying this group at a merge change anything but each fact's own stamps?

        Mirrors ``_upsert_assertion_core``'s choice for a re-upserted copy of each member: an
        active member reinforces itself unless it has an active twin; a superseded or retracted
        member re-inserts itself unless it would reinforce, supersede or contest an active one.
        """
        members = list(self._assertion_items.peers(tenant_id, "main", *group).values())
        actives = [item for item in members if item.status in _ACTIVE]
        for item in members:
            if item.status == "candidate":
                return True
            peers = [other for other in actives if other.scope == item.scope]
            same = [other for other in peers if other.object == item.object]
            if item.status in _ACTIVE:
                if len(same) > 1:
                    return True
                continue
            if same:
                return True
            conflicts = [other for other in peers if other.object != item.object]
            if not conflicts:
                continue
            current = min(conflicts, key=lambda other: (other.trust_tier, -other.valid_from.timestamp()))
            if item.trust_tier < current.trust_tier:
                return True
            if item.trust_tier > current.trust_tier:
                continue
            if item.valid_from >= current.valid_from:
                return True
        return False

    # ------------------------------------------------------------------ merge and discard

    def _merge_overlay(self, frm: str, into: str, tenant_id: str | None) -> Any:
        from mnemosyne.engine import MergeReport, _merge_relation_overlap_component, new_id

        overlay = self._overlays[frm]
        tenant = overlay.tenant_id
        with self._lock, self._overlay_context():
            self._require_branch(frm)
            self._require_branch(into)
            state = self._overlay_states.setdefault(tenant, TenantMergeState())
            now = self._overlay_now()
            report = MergeReport(frm, into, 0, 0, 0, 0, [])
            evidence, assertions, relations = self._evidence_items, self._assertion_items, self._relation_items

            # Evidence: only rows written on the canary itself can be missing from main.
            for ev in [item for item in evidence.in_branch(tenant, frm).values() if not item.erased]:
                if not ev.cid:
                    continue
                target_key = self._evidence_key(ev.tenant_id, into, ev.cid)
                if target_key not in evidence:
                    cloned = copy.deepcopy(ev)
                    cloned.branch = into
                    evidence[target_key] = cloned
                    report.evidence_added += 1

            # Assertions: canary copies of main facts, then facts new on the canary.
            main_view = assertions.in_branch(tenant, into)
            sources_total = len(main_view)
            canary_items = list(assertions.in_branch(tenant, frm).values())
            copies = {item.id: item for item in canary_items
                      if dict.get(assertions, self._branch_key(tenant, into, item.id)) is not None}
            new_items = [item for item in canary_items if item.id not in copies]
            sources_total += len(new_items)
            touched = [(item.subject, item.predicate) for item in canary_items]
            if state.first:
                eager = [(item.subject, item.predicate) for item in main_view.values()] + touched
            else:
                dirty = [(item.subject, item.predicate) for key in state.born_last
                         if (item := dict.get(assertions, key)) is not None]
                eager = touched + dirty + sorted(state.unstable)
            eager_groups = list(dict.fromkeys(eager))
            id_map: dict[str, str] = {}
            added_keys: list[str] = []

            def replay(source: Any, owned: bool = False) -> None:
                before = len(assertions)
                actual = self._overlay_replay(source, into, now=now, owned=owned)
                id_map[source.id] = actual
                if len(assertions) > before:
                    report.assertions_added += 1
                    added_keys.append(self._branch_key(tenant, into, actual))

            touched_keys_main: list[str] = []
            for group in eager_groups:
                self._overlay_flush_group(tenant, *group)
                members = list(assertions.peers(tenant, into, *group).items())
                # The canary's copies of untouched members are main's rows as they stand now;
                # snapshot them before the first replay can rewrite one (see _overlay_group_snapshot).
                snapshot = ({} if all(member.id in copies for _, member in members)
                            else self._overlay_group_snapshot(tenant, into, *group))
                for key, member in members:
                    touched_keys_main.append(key)
                    canary_copy = copies.get(member.id)
                    if canary_copy is not None:
                        replay(canary_copy)
                    elif key in snapshot:
                        replay(snapshot[key], owned=True)
                    else:
                        replay(member)
            for item in new_items:
                replay(item)
            self._overlay_forget_projections(touched_keys_main + added_keys)
            report.assertions_merged = sources_total - report.assertions_added

            # Superseded-by chains through an absorbed id: the legacy pass, run only when needed.
            if any(source_id != dest_id for source_id, dest_id in id_map.items()):
                added = set(added_keys)
                sources = [item for key, item in main_view.items() if key not in added] + new_items
                source_ids = {item.id for item in sources}
                for source in sources:
                    dest = dict.get(assertions, self._branch_key(tenant, into, id_map.get(source.id, source.id)))
                    if dest is not None and dest.superseded_by in source_ids:
                        dest.superseded_by = id_map.get(dest.superseded_by, dest.superseded_by)
                self._overlay_forget_projections()
            report.assertion_id_map = id_map

            # Relations: replay what can change, members before the canary's own relations.
            canary_relations = list(relations.in_branch(tenant, frm).values())
            touched_keys = [(rel.source, rel.predicate, rel.target) for rel in canary_relations]
            if state.first:
                rel_eager = [(rel.source, rel.predicate, rel.target)
                             for rel in relations.in_branch(tenant, into).values()] + touched_keys
            else:
                rel_dirty = [(rel.source, rel.predicate, rel.target) for key in state.born_last_relations
                             if (rel := dict.get(relations, key)) is not None]
                rel_eager = touched_keys + rel_dirty + sorted(state.multi_relations)
            rel_keys = list(dict.fromkeys(rel_eager))
            added_rel_keys: list[str] = []

            def replay_relation(rel: Any) -> None:
                peers = [
                    item
                    for item in relations.peers(rel.tenant_id, into, rel.source, rel.predicate, rel.target).values()
                    if item.tenant_id == rel.tenant_id and item.branch == into and item.source == rel.source
                    and item.predicate == rel.predicate and item.target == rel.target
                ]
                winner, redundant = _merge_relation_overlap_component(rel, peers)
                if winner is not None:
                    for peer in redundant:
                        relations.pop(self._branch_key(peer.tenant_id, into, peer.id), None)
                    return
                cloned = copy.deepcopy(rel)
                cloned.branch = into
                target_key = self._branch_key(cloned.tenant_id, into, cloned.id)
                if target_key in relations:
                    cloned.id = new_id()
                    target_key = self._branch_key(cloned.tenant_id, into, cloned.id)
                relations[target_key] = cloned
                report.relations_added += 1
                added_rel_keys.append(target_key)

            for key3 in rel_keys:
                for member in list(relations.peers(tenant, into, *key3).values()):
                    replay_relation(copy.deepcopy(member))
            for rel in canary_relations:
                replay_relation(rel)

            self.merge_log.append(report.to_dict())
            self._audit(tenant_id or "*", "engine", "merge", frm, report.to_dict())
            self._persist()

            # What the next merge needs to know.
            new_groups = [(item.subject, item.predicate) for key in added_keys
                          if (item := dict.get(assertions, key)) is not None]
            for group in dict.fromkeys(eager_groups + new_groups):
                if self._overlay_group_unstable(tenant, group):
                    state.unstable.add(group)
                else:
                    state.unstable.discard(group)
            new_rel_keys = [(rel.source, rel.predicate, rel.target) for key in added_rel_keys
                            if (rel := dict.get(relations, key)) is not None]
            for key3 in dict.fromkeys(rel_keys + new_rel_keys):
                if len(relations.peers(tenant, into, *key3)) > 1:
                    state.multi_relations.add(key3)
                else:
                    state.multi_relations.discard(key3)
            state.gen += 1
            state.time = now
            state.first = False
            state.replayed_groups = set(eager_groups)
            state.born_last = added_keys
            state.born_last_relations = added_rel_keys
            state.pending = True
            self._overlay_flush_needed = True
            self.overlay_stats["eager_groups"] += len(eager_groups)
            self.overlay_stats["merged"] += 1

            # The merged canary is bookkeeping: drop it (approved contract).
            self._overlay_drop(frm, tenant)
            return report

    def _overlay_drop(self, name: str, tenant_id: str) -> None:
        for store in (self._evidence_items, self._assertion_items, self._relation_items):
            for key in list(store.in_branch(tenant_id, name)):
                del store[key]
        self.branches.pop(name, None)
        del self._overlays[name]

    def _discard_overlay(self, branch: str, tenant_id: str | None) -> None:
        overlay = self._overlays[branch]
        tenant = overlay.tenant_id
        if tenant_id is not None and tenant_id != tenant:
            # Another tenant's discard of this name: legacy semantics on the physical branch.
            self._overlay_settle(reset=True)
            return self.discard(branch, tenant_id)
        with self._lock, self._overlay_context():
            self._require_branch(branch)
            local_ids = {item.id for item in self._assertion_items.in_branch(tenant, branch).values()}
            for store in (self._evidence_items, self._assertion_items, self._relation_items):
                for key in list(store.in_branch(tenant, branch)):
                    del store[key]
            # Inherited ids are main's own ids and survive; only ids new on the canary can be
            # orphaned, exactly as with the legacy full branch.
            surviving = {item.id for item in self._assertion_items.of_tenant(tenant).values()} if local_ids else set()
            orphaned = local_ids - surviving
            if orphaned:
                self.justifications = {
                    key: item
                    for key, item in self.justifications.items()
                    if item.tenant_id != tenant
                    or (item.assertion_id not in orphaned and not (set(item.dependency_ids) & orphaned))
                }
                self.contradictions = {
                    key: item
                    for key, item in self.contradictions.items()
                    if item.tenant_id != tenant or (item.a not in orphaned and item.b not in orphaned)
                }
            self.branches.pop(branch, None)
            del self._overlays[branch]
            self._audit(tenant_id or "*", "engine", "discard", branch, {})
            self._persist()
        self.overlay_stats["discarded"] += 1
        return None

    # ------------------------------------------------------------------ reads on an overlay

    def _overlay_parent_row(self, store: Any, tenant_id: str, branch: str, ident: str, *, evidence: bool) -> Any:
        overlay = (self._overlays or {}).get(branch)
        if overlay is None or overlay.tenant_id != tenant_id:
            return None
        keyed = self._evidence_key if evidence else self._branch_key
        return dict.get(store, keyed(tenant_id, overlay.parent, ident))

    def _overlay_candidate_templates(self, filt: dict[str, Any], overlay: CanaryOverlay) -> Any:
        """The canary's candidates in legacy order without copying the parent's rows.

        A full branch lists the copies of the parent's evidence and assertions in the parent's
        order, then the canary's own new assertions, then preferences. Parent rows are projected
        once per access context (with the parent as branch - projection never reads the branch
        name) and reused; a copy the canary holds replaces its parent at the parent's position.
        Returns None for the rare shapes this does not cover, and the caller settles instead.
        """
        from mnemosyne.engine import _CandidateTemplates

        branch = filt.get("branch", "main")
        tenant = filt.get("tenant_id")
        if tenant != overlay.tenant_id or self._evidence_items.in_branch(tenant, branch):
            return None
        parent_filt = dict(filt)
        parent_filt["branch"] = overlay.parent
        context = (repr(sorted(parent_filt.items())), int(self.policy.max_trust_tier), int(self.policy.max_sensitivity))
        cached = self._overlay_projection.get(context)
        if cached is None:
            cached = ({}, {})
            self._overlay_projection[context] = cached
            while len(self._overlay_projection) > 4:
                self._overlay_projection.popitem(last=False)
        else:
            self._overlay_projection.move_to_end(context)
        evidence_cache, assertion_cache = cached
        out = _CandidateTemplates(branch_override=branch, engine=self, tenant_id=tenant)
        with self._overlay_context():
            for key, ev in self._evidence_items.in_branch(tenant, overlay.parent).items():
                entry = evidence_cache.get(key)
                if entry is None or not _same_evidence(entry[0], ev):
                    hits = self._candidate_hits_uncached(
                        parent_filt, evidence_items=(ev,), assertion_items=(), include_preferences=False
                    )
                    entry = (_evidence_fields(ev), hits[0] if hits else None)
                    if not _expires(ev.access_policy):
                        evidence_cache[key] = entry
                if entry[1] is not None:
                    out.append(entry[1])
            own = {item.id: item for item in self._assertion_items.in_branch(tenant, branch).values()}
            for key, item in self._assertion_items.in_branch(tenant, overlay.parent).items():
                copied = own.pop(item.id, None)
                if copied is not None:
                    hits = self._candidate_hits_uncached(
                        filt, evidence_items=(), assertion_items=(copied,), include_preferences=False
                    )
                    out.extend(hits)
                    continue
                entry = assertion_cache.get(key)
                if entry is None or entry[0] is not item:
                    hits = self._candidate_hits_uncached(
                        parent_filt, evidence_items=(), assertion_items=(item,), include_preferences=False
                    )
                    entry = (item, hits[0] if hits else None)
                    if not _expires(item.access_policy):
                        assertion_cache[key] = entry
                if entry[1] is not None:
                    out.append(entry[1])
                    out.inherited.add(id(entry[1]))
            if own:
                out.extend(self._candidate_hits_uncached(
                    filt, evidence_items=(), assertion_items=tuple(own.values()), include_preferences=False
                ))
            out.extend(self._candidate_hits_uncached(filt, evidence_items=(), assertion_items=(), include_preferences=True))
        return out

    def _overlay_patch_access(self, hit: Any, tenant_id: str) -> None:
        """Give a kept inherited assertion hit the access stamps its canary copy would carry."""
        key = self._branch_key(tenant_id, "main", hit.id)
        item = dict.get(self._assertion_items, key)
        if item is None:
            return
        last = item.last_accessed
        state = (self._overlay_states or {}).get(tenant_id)
        if (
            state is not None
            and state.pending
            and item.status in _ACTIVE
            and (item.subject, item.predicate) not in state.replayed_groups
            and key not in state.born_last
        ):
            last = state.time  # the deferred replay of the last merge re-stamps it
        hit.metadata["last_accessed"] = last.isoformat() if last else None
        hit.metadata["access_count"] = item.access_count

    def _graph_relation_rows(self, tenant_id: str | None, branch: str | None) -> list[tuple[Any, Any]]:
        """(relation, branch it belongs to) for graph_ppr; an overlay lists its parent's first."""
        overlay = (self._overlays or {}).get(branch) if branch is not None else None
        if overlay is not None and tenant_id == overlay.tenant_id:
            rows = [(rel, branch) for rel in self._relation_items.in_branch(tenant_id, overlay.parent).values()]
            rows += [(rel, branch) for rel in self._relation_items.in_branch(tenant_id, branch).values()]
            return rows
        return [(rel, rel.branch) for rel in self.relations.select(tenant_id, branch).values()]

    def _overlay_access_carries(self, tenant_id: str, item: Any) -> bool:
        """Would a merge carry the canary copy's access stamps of ``item`` into main?

        A replay that REINFORCES (an active fact whose own row is still active when its turn
        comes) ignores the copy's ``last_accessed``/``access_count``. Every other replay
        re-inserts the copy whole: a superseded or retracted fact, or an active one in a group
        whose earlier replays can knock it out first (an unstable group).
        """
        if item.status not in _ACTIVE:
            return True
        return self._overlay_group_unstable(tenant_id, (item.subject, item.predicate))

    def _overlay_record_access(self, hits: list[Any]) -> dict[str, int]:
        """``_record_retrieval_access`` for hits on a canary overlay.

        Counts exactly what the legacy full branch counts. An inherited row whose stamps a
        merge would ignore (it reinforces) is not written: on a full branch that write lands on
        a canary copy that no merge carries into main and a discard drops, so leaving the
        parent row untouched is observably the same. An inherited row whose copy a merge would
        re-insert has its group copied into the overlay first, and the copy is stamped.
        """
        from mnemosyne.engine import _bounded_float, utc_now

        if self._read_only:
            return {"assertions": 0, "evidence": 0}
        touched_assertions = 0
        touched_evidence = 0
        now = utc_now()
        with self._lock, self._overlay_context():
            evidence_cids: set[tuple[str, str, str]] = set()
            for hit in hits:
                if hit.kind == "working":
                    continue
                if hit.kind == "evidence" and hit.id:
                    evidence_cids.add((hit.tenant_id, hit.branch, hit.id))
                for cid in hit.provenance:
                    if cid:
                        evidence_cids.add((hit.tenant_id, hit.branch, str(cid)))
                if hit.kind == "assertion":
                    assertion = dict.get(self._assertion_items, self._branch_key(hit.tenant_id, hit.branch, hit.id))
                    branch_of_row = assertion.branch if assertion is not None else hit.branch
                    if assertion is None:
                        assertion = self._overlay_parent_row(
                            self._assertion_items, hit.tenant_id, hit.branch, hit.id, evidence=False
                        )
                        if assertion is None:
                            continue
                        overlay = self._overlays[hit.branch]
                        if self._overlay_access_carries(hit.tenant_id, assertion):
                            # The merge re-inserts this copy, access stamps and all: copy the
                            # group now and stamp the copy, exactly as on a full branch.
                            self._overlay_materialize_group(hit.branch, overlay, assertion.subject, assertion.predicate)
                            assertion = dict.get(self._assertion_items,
                                                 self._branch_key(hit.tenant_id, hit.branch, hit.id))
                            assertion.last_accessed = now
                            assertion.access_count += 1
                    else:
                        assertion.last_accessed = now
                        assertion.access_count += 1
                    touched_assertions += 1
                    for cid in assertion.source_evidence_cids:
                        if cid:
                            evidence_cids.add((assertion.tenant_id, branch_of_row, str(cid)))
            for tenant_id, branch, cid in sorted(evidence_cids):
                ev = dict.get(self._evidence_items, self._evidence_key(tenant_id, branch, cid))
                inherited = ev is None
                if inherited:
                    ev = self._overlay_parent_row(self._evidence_items, tenant_id, branch, cid, evidence=True)
                if ev is None or ev.erased:
                    continue
                if not inherited:
                    metadata = dict(ev.metadata)
                    lifecycle = metadata.get("lifecycle")
                    lifecycle = dict(lifecycle) if isinstance(lifecycle, dict) else {}
                    try:
                        access_count = int(lifecycle.get("access_count", 0))
                    except (TypeError, ValueError):
                        access_count = 0
                    access_count += 1
                    lifecycle["access_count"] = access_count
                    lifecycle["last_accessed"] = now.isoformat()
                    lifecycle["salience"] = min(1.0, _bounded_float(lifecycle.get("salience", 0.5), default=0.5) + 0.05)
                    metadata["lifecycle"] = lifecycle
                    ev.metadata = metadata
                touched_evidence += 1
            if touched_assertions or touched_evidence:
                self._persist()
        return {"assertions": touched_assertions, "evidence": touched_evidence}


def _expires(access_policy: Any) -> bool:
    """A row whose readability changes with time is never served from the projection cache."""
    return isinstance(access_policy, dict) and bool(access_policy.get("expires_at"))


def _evidence_fields(ev: Any) -> tuple[Any, ...]:
    """Everything a candidate projection reads from an evidence row (objects by identity)."""
    return (ev, ev.metadata, ev.access_policy, ev.content, ev.content_pointer, ev.embedding, ev.erased,
            ev.trust_tier, ev.sensitivity, ev.modality, ev.actor, ev.source_type, ev.cid, ev.tenant_id, ev.branch)


def _same_evidence(fields: tuple[Any, ...], ev: Any) -> bool:
    return (
        fields[0] is ev and fields[1] is ev.metadata and fields[2] is ev.access_policy and fields[3] is ev.content
        and fields[4] == ev.content_pointer and fields[5] is ev.embedding and fields[6] == ev.erased
        and fields[7] == ev.trust_tier and fields[8] == ev.sensitivity and fields[9] == ev.modality
        and fields[10] == ev.actor and fields[11] == ev.source_type and fields[12] == ev.cid
        and fields[13] == ev.tenant_id and fields[14] == ev.branch
    )
