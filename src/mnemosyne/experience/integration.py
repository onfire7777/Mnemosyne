"""Shared configuration and completed-turn lifecycle for learning hosts.

Authorization remains at each host boundary. Outcome interpretation and writes
remain in LearningRuntime; hosts only provide externally observed events.
"""

from __future__ import annotations

import os
import weakref
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from mnemosyne.gate import GATING_CASE_ORIGINS

from .runtime import LearningRuntime, now


def learning_skill_store(engine, skill_store=None, *, create=False):
    """Resolve the same skill library for SDK, MCP, jobs and host adapters."""
    store = skill_store
    if store is None:
        store = getattr(engine, "_learning_configuration", {}).get("skill_store")
    if store is None:
        store = getattr(engine, "_learning_skill_store", None)
    if store is None:
        configured = os.environ.get("MNEMOSYNE_SKILLS_DB")
        root = getattr(engine, "root_dir", None)
        path = getattr(engine, "store_path", None)
        path = (Path(configured).expanduser() if configured else
                Path(root) / "skills.sqlite" if root is not None else
                Path(path).parent / "skills.sqlite" if path else None)
        if path is None:
            if create:
                raise ValueError("skills need a store on disk (sqlite or local backend) or MNEMOSYNE_SKILLS_DB")
            return None
        if not create and not path.is_file():
            return None
        from mnemosyne.skills import SkillStore

        store = SkillStore.at(str(path))
    engine._learning_skill_store = store
    adapters = getattr(engine, "adapters", None)
    store.embedder = getattr(getattr(adapters, "passage_graph", None), "embedder", None) or getattr(adapters, "embedding", None)
    return store


def configure_learning(engine, **configuration):
    """Share explicit host dependencies without replacing them with defaults."""
    current = getattr(engine, "_learning_configuration", {})
    current.update({key: value for key, value in configuration.items() if value is not None})
    engine._learning_configuration = current


def _active_protected_cases(cases):
    return [case for case in cases if case.protected
            and case.origin in GATING_CASE_ORIGINS and case.mode == "active"]


def learning_dependency(runtime, name, fallback=None):
    """Factory-created runtimes read one live configuration owned by the engine.

    Directly constructed runtimes retain their local dependency assignments.
    Long-lived SDK sessions and old workers cannot restore superseded settings.
    """
    if not getattr(runtime, "_shared_configuration", False):
        return fallback
    configuration = getattr(runtime.engine, "_learning_configuration", {})
    if name == "protected_cases":
        cases = configuration.get(name)
        if cases is None:
            state = configuration.get("runtime_state")
            cases = state.load_gate_cases() if state is not None else fallback
        return _active_protected_cases(cases or [])
    if name == "skill_store":
        fallback = getattr(runtime.engine, "_learning_skill_store", fallback)
    return configuration.get(name, fallback)


def build_learning_runtime(engine, *, skill_store=None, lesson_distiller=None,
                           procedure_inducer=None, protected_cases=None,
                           runtime_state=None):
    configure_learning(engine, skill_store=skill_store, lesson_distiller=lesson_distiller,
                       procedure_inducer=procedure_inducer, protected_cases=protected_cases,
                       runtime_state=runtime_state)
    configuration = engine._learning_configuration
    tools = getattr(engine, "_learning_tools", None)
    if isinstance(tools, weakref.ReferenceType):
        tools = tools()
    runtime = LearningRuntime(engine, skill_store=learning_skill_store(engine))
    runtime._shared_configuration = True
    for name in ("lesson_distiller", "procedure_inducer"):
        setattr(runtime, name, configuration.get(name) or getattr(tools, name, None))
    cases = configuration.get("protected_cases")
    state = configuration.get("runtime_state") or getattr(tools, "runtime_state", None)
    if cases is None:
        cases = state.load_gate_cases() if state is not None else getattr(engine, "_learning_protected_cases", [])
    runtime.protected_cases = _active_protected_cases(cases)
    return runtime


def _after_outcomes(runtime, tenant_id, user_id):
    """Claim automatic triggers atomically; never hold a DB lock over providers."""
    token = uuid4().hex
    timestamp = now()

    def claim(state):
        if not runtime._enabled(state, "lessons"):
            return False
        resolved = [row for row in state["episodes"].values()
                    if row["user_id"] == user_id and row["status"] == "resolved"]
        triggers = {"failure:" + row["id"] for row in resolved if row["reward"] < 0}
        triggers.update("batch:" + str(index) for index in range(1, len(resolved) // 10 + 1))
        cadence = state["policy"].get("host_consolidation", {}).get(user_id, {})
        triggers.difference_update(cadence.get("completed", []))
        if not triggers:
            return False
        pending = cadence.get("pending")
        if pending and datetime.fromisoformat(pending["expires_at"]) > timestamp:
            return False
        cadence = state["policy"].setdefault("host_consolidation", {}).setdefault(user_id, {})
        cadence["pending"] = {"token": token, "triggers": sorted(triggers),
                              "expires_at": (timestamp + timedelta(minutes=10)).isoformat()}
        return True

    if not runtime.writer.apply(tenant_id, "host_consolidation_claim", claim):
        return None

    def finish(state, *, completed):
        cadence = state["policy"].get("host_consolidation", {}).get(user_id, {})
        pending = cadence.get("pending", {})
        if pending.get("token") != token:
            return
        if completed:
            cadence["completed"] = sorted(set(cadence.get("completed", [])) | set(pending["triggers"]))
        cadence.pop("pending", None)

    try:
        result = runtime.consolidate(tenant_id)
    except BaseException:
        runtime.writer.apply(tenant_id, "host_consolidation_release",
                             lambda state: finish(state, completed=False))
        raise
    runtime.writer.apply(tenant_id, "host_consolidation_complete",
                         lambda state: finish(state, completed=True))
    return result


def observe_completed_turn(runtime, tenant_id, user_id, session_id, user_text,
                           assistant_text, *, tool_events=None, receipt_ids=None,
                           used_skills=None, used_lessons=None, source_cids=None,
                           feedback=None, observation_id=None):
    """Capture once, resolve actual outcomes promptly, and run one cadence."""
    observed = runtime.observe_turn(
        tenant_id, user_id, session_id, user_text, assistant_text,
        tool_events=tool_events, receipt_ids=receipt_ids, used_skills=used_skills,
        used_lessons=used_lessons, source_cids=source_cids,
        observation_id=observation_id)
    if observed.get("erased"):
        return observed
    if feedback is not None and not runtime.writer.read(tenant_id)["policy"].get(
        "host_feedback_done", {}
    ).get(observed["episode_id"]):
        feedback(observed["episode_id"])
        runtime.writer.apply(
            tenant_id, "host_feedback_complete",
            lambda state: state["policy"].setdefault("host_feedback_done", {}).update(
                {observed["episode_id"]: True}
            ),
        )
    if tool_events:
        runtime.resolve(tenant_id, observed["episode_id"])
    consolidation = _after_outcomes(runtime, tenant_id, user_id)
    if consolidation is not None:
        observed["consolidation"] = consolidation
    return observed


def record_completed_signal(runtime, tenant_id, user_id, **signal):
    result = runtime.record_signal(tenant_id, **signal)
    _after_outcomes(runtime, tenant_id, user_id)
    return result


def end_learning_session(runtime, tenant_id, user_id, session_id, *, consolidate=True):
    matching = [row for row in runtime.writer.read(tenant_id)["episodes"].values()
                if row["session_id"] == session_id]
    if any(row["user_id"] != user_id for row in matching):
        raise PermissionError("session includes another learning owner")
    result = runtime.end_session(tenant_id, session_id)
    if consolidate:
        # One session-end pass also performs due lifecycle and revalidation work,
        # even when no new outcome has arrived since the last turn.
        result["consolidation"] = runtime.consolidate(tenant_id)
    return result
