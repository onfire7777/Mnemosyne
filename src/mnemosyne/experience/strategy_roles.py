"""Ground abstract workflow stages in independently observed concrete actions."""

from __future__ import annotations

from collections import defaultdict
import json
import re
import shlex

from .receipts import digest

INSTRUCTIONS = {
    "inspect": "Inspect the current target and relevant evidence using the available read tools.",
    "modify": "Apply the smallest change to the current target that addresses the inspected cause.",
    "verify": "Run the relevant independent check against the current target and inspect its result.",
    "reproduce": "Reproduce the reported failure with an independent check before changing the target.",
}


def action_role(event):
    from .signals import tool_signals
    if event.get("source") in {"assistant", "self_generated", "provider_self_grade"}:
        return None
    name = re.split(r"\.|__", str(event.get("name", "")))[-1].casefold()
    checks = [row for row in tool_signals([event]) if row["kind"] in {"tests", "verifier"}]
    if checks and (event.get("output") or event.get("evidence")):
        return "verify"
    if name in {"read_file", "read", "search", "rg", "grep", "list_files", "view_file"}:
        return "inspect"
    if name in {"apply_patch", "edit_file", "write_file", "replace_in_file"}:
        return "modify"
    command = event.get("command")
    if not isinstance(command, str):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts or any(token in {";", "&&", "||", "|", ">", ">>", "<"} for token in parts):
        return None
    if parts[0] in {"rg", "grep", "cat", "head", "tail", "ls", "find"}:
        return "inspect"
    if parts[:2] in (["git", "status"], ["git", "diff"], ["git", "show"], ["git", "log"]):
        return "inspect"
    return None


def trace_roles(episode):
    """Unknown operations are not silently assumed to be safe workflow stages."""
    from .candidates import observed_action
    stages = []
    for index, event in enumerate(episode.get("tool_events", [])):
        if event.get("source") in {"assistant", "self_generated", "provider_self_grade", "host"}:
            continue
        action = observed_action(event)
        role = action_role(event)
        if not action or not role:
            return None
        if stages and stages[-1]["role"] == role:
            stages[-1]["indices"].append(index)
            stages[-1]["actions"].append(action)
        else:
            stages.append({"role": role, "indices": [index], "actions": [action]})
    if stages and stages[0]["role"] == "verify" and len(stages) > 1:
        from .signals import tool_signals
        initial = [signal for index in stages[0]["indices"]
                   for signal in tool_signals([episode["tool_events"][index]])]
        if any(signal["value"] < 0 for signal in initial):
            stages[0]["role"] = "reproduce"
    roles = [stage["role"] for stage in stages]
    if roles not in (["inspect", "modify", "verify"], ["reproduce", "inspect", "modify", "verify"]):
        return None
    return stages


def canonical_steps(roles):
    conditional = roles[0] == "reproduce"
    return [json.dumps({"type": "strategy_stage", "role": role,
                        "when": "initial_check_failed" if conditional and i else "always",
                        "instruction": INSTRUCTIONS[role]}, sort_keys=True)
            for i, role in enumerate(roles)]


def abstract_proof(episodes, receipts):
    from .strategies import _contract, _shape
    owners = {(row.get("tenant_id"), row.get("user_id")) for row in episodes}
    if len(owners) != 1 or len(episodes) < 2:
        return None
    evidence = []
    for row in sorted(episodes, key=lambda row: row["id"]):
        if row.get("status") != "resolved" or (row.get("reward") or 0) <= 0:
            return None
        contract = _contract(row, receipts)
        stages = trace_roles(row)
        if not contract or not stages:
            return None
        from .signals import tool_signals
        if not all(signal["value"] > 0 for index in stages[-1]["indices"]
                   for signal in tool_signals([row["tool_events"][index]])):
            return None
        evidence.append({"episode_id": row["id"], "contract": contract, "stages": stages})
    roles = [stage["role"] for stage in evidence[0]["stages"]]
    if (any([stage["role"] for stage in row["stages"]] != roles for row in evidence)
            or len({digest(_shape(row["contract"])) for row in evidence}) != 1
            or len({row["contract"]["entity"] for row in evidence}) < 2):
        return None
    return {"version": 2, "kind": "observed_conditional_roles", "variable": "current_target",
            "shape": _shape(evidence[0]["contract"]), "roles": roles, "evidence": evidence,
            "steps_hash": digest(canonical_steps(roles)), "binding_required": True,
            "instruction_authority": "none"}


def abstract_score(artifact, episode):
    proof = artifact.get("strategy_contract", {})
    stages = trace_roles(episode)
    if not stages or [row["role"] for row in stages] != proof.get("roles"):
        return None
    from .signals import reward, tool_signals
    checks = [signal for index in stages[-1]["indices"]
              for signal in tool_signals([episode["tool_events"][index]])
              if signal["kind"] in {"tests", "verifier"}]
    value = reward(checks)
    return None if value is None else float(value > 0)


def abstract_occurrence(artifact, episode):
    stages = trace_roles(episode)
    if stages and [stage["role"] for stage in stages] == artifact.get("strategy_contract", {}).get("roles"):
        return [index for stage in stages for index in stage["indices"]]
    return None


def role_tools_available(roles, tools):
    names = {re.split(r"\.|__", str(tool))[-1].casefold() for tool in tools}
    shell = bool(names & {"exec", "exec_command", "shell", "bash", "python", "run_command"})
    return all({
        "inspect": shell or bool(names & {"read", "read_file", "search", "rg", "grep", "view_file"}),
        "modify": bool(names & {"apply_patch", "edit_file", "write_file", "replace_in_file"}),
        "verify": shell or bool(names & {"checker", "external_checker", "run_tests", "verifier"}),
        "reproduce": shell or bool(names & {"checker", "external_checker", "run_tests", "verifier"}),
    }.get(role, False) for role in roles)


def propose_abstract_strategies(state, limit=8):
    from .strategies import _contract, _shape
    from .sleep import _candidate
    if limit <= 0:
        return []
    groups = defaultdict(list)
    for episode in state["episodes"].values():
        contract, stages = _contract(episode, state["receipts"]), trace_roles(episode)
        if not contract or not stages or episode.get("status") != "resolved" or (episode.get("reward") or 0) <= 0:
            continue
        key = digest([episode.get("tenant_id"), episode.get("user_id"), _shape(contract),
                      [stage["role"] for stage in stages]])
        groups[key].append(episode)
    result = []
    for key, rows in sorted(groups.items()):
        proof = abstract_proof(rows, state["receipts"])
        if not proof:
            continue
        steps = canonical_steps(proof["roles"])
        first = min(rows, key=lambda row: (row["created_at"], row["id"]))
        candidate = _candidate(first["task_class"], steps, rows)
        candidate.update(id=digest(["abstract-strategy", key]), strategy_contract=proof, scope_match=None,
                         conditions=proof["shape"]["constraints"], needs=[],
                         explanation="These conditional workflow stages were independently observed on distinct targets; bind every stage to the current target and inspect the new results.")
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def grounded_abstract_steps(artifact, episodes, quotes):
    from .candidates import observed_action
    proof = artifact.get("strategy_contract", {})
    if artifact.get("steps") != canonical_steps(proof.get("roles", [])):
        return False
    for episode in episodes:
        indices = abstract_occurrence(artifact, episode)
        if not indices:
            return False
        for index in indices:
            action = observed_action(episode["tool_events"][index])
            if not any(quote.get("episode_id") == episode["id"]
                       and quote.get("cid") in episode.get("source_cids", [])
                       and quote.get("quote") == action for quote in quotes):
                return False
    return True
