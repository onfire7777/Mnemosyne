"""Transfer independently observed procedures without merging task identities.

Only the task's entity is variable. Actions, constraints, risk, and capabilities
remain explicit. Every proof is regenerated from its retained source episodes.
"""

from __future__ import annotations

from collections import defaultdict
import json
import re

from mnemosyne.local_paths import normalize_workspace

from .receipts import digest
from .task_class import semantic_contract, scope_query


def _contract(episode, receipts):
    rows = [receipts[key] for key in episode.get("receipt_ids", []) if key in receipts]
    risks = {row.get("risk_level", "normal") for row in rows}
    if not rows or len(risks) != 1:
        return None
    return semantic_contract(scope_query(episode), (), risks.pop())


def _shape(contract):
    return {key: contract[key] for key in ("version", "intent", "constraints", "risk")}


def _independent_entity(entity, steps):
    # An operation mentioning an old subject is not a reusable variable binding.
    # Refuse quoted/path/flag entities: their types need a stronger binder.
    if not re.fullmatch(r"[a-z][a-z ]*", entity):
        return False
    words = set(entity.split()) - {"defect", "bug", "issue", "problem", "the", "a", "an"}
    action_text = " ".join(steps).casefold()
    return bool(words) and not any(re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", action_text)
                                   for word in words)


def _proof(steps, episodes, receipts):
    from .candidates import action_occurrence, candidate_score, has_workspace_template, portable_observed_steps, _action_data
    from .signals import tool_signals
    owners = {(row.get("tenant_id"), row.get("user_id")) for row in episodes}
    if len(owners) != 1 or len(episodes) < 2:
        return None
    if has_workspace_template(steps):
        roots = {portable_observed_steps(row)[1] for row in episodes}
        if None in roots or len(roots) < 2:
            return None
    workspaces = [_action_data(step).get("cwd") for step in steps if _action_data(step).get("cwd")]
    normalized_workspaces = [value if value == {"variable": "workspace"} else normalize_workspace(value)
                            for value in workspaces]
    if (None in normalized_workspaces or normalized_workspaces
            and any(value != normalized_workspaces[0] for value in normalized_workspaces)):
        return None
    roles = []
    needs = set()
    for episode in sorted(episodes, key=lambda row: row["id"]):
        if (episode.get("status") != "resolved" or (episode.get("reward") or 0) <= 0
                or not any(signal.get("kind") in {"tests", "verifier"} and signal.get("value", 0) > 0
                           for signal in episode.get("signals", []))):
            return None
        if any(signal.get("value", 0) < 0 for event in episode.get("tool_events", [])
               for signal in tool_signals([event])):
            return None  # Do not prescribe failed attempts preceding a recovery.
        contract = _contract(episode, receipts)
        if not contract or not _independent_entity(contract["entity"], steps):
            return None
        probe = {"kind": "procedure", "steps": steps}
        if action_occurrence(probe, episode) is None or candidate_score(probe, episode) != 1:
            return None
        roles.append({"episode_id": episode["id"], "contract": contract})
        for step in steps:
            try:
                action = json.loads(step)
            except (ValueError, TypeError):
                return None  # Name-only traces do not prove entity independence.
            if action.get("type") != "tool_action" or not action.get("tool"):
                return None
            needs.add(action["tool"])
    shapes = {digest(_shape(role["contract"])) for role in roles}
    entities = {role["contract"]["entity"] for role in roles}
    if len(shapes) != 1 or len(entities) < 2:
        return None
    return {"version": 1, "kind": "observed_entity_independent_procedure",
            "variable": "entity", "shape": _shape(roles[0]["contract"]),
            "roles": roles, "required_tools": sorted(needs), "steps_hash": digest(steps),
            "workspace": workspaces[0] if workspaces else None,
            "instruction_authority": "none"}


def validated_strategy(artifact, episodes, receipts):
    contract = artifact.get("strategy_contract")
    if not contract or artifact.get("kind") != "procedure" or artifact.get("scope_match"):
        return False
    rows = [episodes.get(key) for key in artifact.get("source_episode_ids", [])]
    if not rows or any(row is None for row in rows):
        return False
    if any((row.get("tenant_id"), row.get("user_id")) !=
           (artifact.get("tenant_id"), artifact.get("user_id")) for row in rows):
        return False
    if contract.get("kind") == "observed_conditional_roles":
        from .strategy_roles import abstract_proof, canonical_steps
        expected = abstract_proof(rows, receipts)
        if not expected or artifact.get("steps") != canonical_steps(expected["roles"]):
            return False
    else:
        expected = _proof(artifact.get("steps", []), rows, receipts)
    return bool(expected and contract == expected and
                artifact.get("conditions", []) == expected["shape"]["constraints"])


def strategy_applies(artifact, query, *, tools=None, risk=None, workspace=None, require_workspace=False):
    proof = artifact.get("strategy_contract") or {}
    shape = proof.get("shape")
    if proof.get("version") not in {1, 2} or not isinstance(shape, dict):
        return False
    contract = semantic_contract(query, (), risk or shape.get("risk"))
    abstract = proof.get("kind") == "observed_conditional_roles"
    if not contract or _shape(contract) != shape or (not abstract and not _independent_entity(contract["entity"], artifact.get("steps", []))):
        return False
    if proof.get("steps_hash") != digest(artifact.get("steps", [])):
        return False
    if abstract:
        from .strategy_roles import role_tools_available
        return tools is None or role_tools_available(proof.get("roles", []), tools)
    if require_workspace and proof.get("workspace") is not None:
        from .candidates import WORKSPACE_VARIABLE, _workspace
        if proof["workspace"] == WORKSPACE_VARIABLE:
            if not _workspace(workspace):
                return False
        elif not normalize_workspace(workspace) or normalize_workspace(workspace) != normalize_workspace(proof["workspace"]):
            return False
    return tools is None or set(proof.get("required_tools", [])) <= set(tools)


def propose_strategies(state, *, limit=8):
    """Mine identical successful operations across independently named entities.

    A new entity never inherits a successful task label. The proposal enters the
    same protected regression and local probation gates as every procedure.
    """
    from .candidates import observed_steps, portable_observed_steps, _canonical_workspace_step
    from .sleep import _candidate
    groups = defaultdict(dict)
    for episode in state["episodes"].values():
        contract = _contract(episode, state["receipts"])
        if not contract or episode.get("status") != "resolved" or (episode.get("reward") or 0) <= 0:
            continue
        for steps in (observed_steps(episode), portable_observed_steps(episode)[0]):
            if steps:
                key = digest([episode.get("tenant_id"), episode.get("user_id"), _shape(contract),
                              [_canonical_workspace_step(step) for step in steps]])
                groups[key][episode["id"]] = (steps, episode)
    proposals = []
    for key in sorted(groups):
        values = list(groups[key].values())
        steps, _ = values[0]
        episodes = [row for _, row in values]
        proof = _proof(steps, episodes, state["receipts"])
        if not proof:
            continue
        # Keep each concrete task's outcomes separate; transfer is an artifact
        # contract, never a task-class alias or a claimed success on a new task.
        first = min(episodes, key=lambda row: (row["created_at"], row["id"]))
        artifact = _candidate(first["task_class"], steps, episodes)
        artifact.update(strategy_contract=proof, scope_match=None,
                        conditions=proof["shape"]["constraints"],
                        explanation="Identical verified operations worked for distinct entities under these exact constraints.")
        artifact["id"] = digest(["strategy", artifact["tenant_id"], artifact["user_id"], proof["shape"], steps])
        proposals.append(artifact)
        if len(proposals) >= limit:
            break
    from .strategy_roles import propose_abstract_strategies
    return [*proposals, *propose_abstract_strategies(state, max(0, limit - len(proposals)))]
