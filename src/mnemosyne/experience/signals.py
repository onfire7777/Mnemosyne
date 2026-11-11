"""External signal allowlist. Assistant text and zero exits carry no reward."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from collections import Counter

from .receipts import digest

VERIFIED_KINDS = frozenset({"verifier", "tests", "critic", "rating"})
OUTCOME_VERSION = 3

WEIGHTS = {
    "verifier": 1.0,
    "tests": 0.9,
    "exit_code": 0.4,
    "critic": 0.8,
    "correction": 0.7,
    "reask": 0.5,
    "acceptance": 0.3,
    "rating": 0.9,
}
FEEDBACK_PREFIX = r"(?:(?:no|actually)(?:[,!.]\s*|\s+))?"
CORRECTIONS = (
    r"(?:wrong|incorrect)[.!]*$",
    FEEDBACK_PREFIX
    + r"(?:(?:that|this|it|your (?:answer|response|solution|code|result)) (?:is|was)|that's|it's|you're|you are) "
    + r"(?:(?:still|actually) )?(?:wrong|incorrect|mistaken|not (?:right|correct|what i (?:asked|meant)))\b",
    FEEDBACK_PREFIX
    + r"(?:this|that|it)(?: still)? (?:doesn't|does not|didn't|did not) work\b",
    FEEDBACK_PREFIX + r"(?:this|that|it)(?: still)? failed\b",
    r"no[,!.]\s*(?:please )?(?:use|return|respond|format|do not|don't)\b",
    FEEDBACK_PREFIX
    + r"(?:please )?(?:use|return|respond with|format)\b[^\n]*\binstead\b",
    FEEDBACK_PREFIX
    + r"(?:please )?(?:correct|fix|revise) (?:it|that|your (?:answer|response|solution|code)|the (?:previous|last) (?:answer|response|solution|code))\b(?!\s*,?\s*(?:if|unless)\b)",
    r"(?:no[,!.]\s*|correction:\s*)i meant\b(?!\s+to\b)",
)
REASKS = (
    r"(?:please )?try again(?:[.!]|$|,\s*(?:(?:that|this|it) )?(?:failed|didn't work|did not work)\b)",
    r"you (?:didn't|did not|haven't|have not) answer (?:my|the|that|previous) question\b",
)
ACCEPTANCE = r"^(?:thanks|thank you|great|perfect|that works|correct)[.!\s]*$"


def signal(kind: str, value: float, evidence: str = "") -> dict:
    if kind not in WEIGHTS:
        raise ValueError("reward source is not allowlisted")
    if isinstance(value, bool):
        value = 1.0 if value else -1.0
    if (
        not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not -1 <= value <= 1
    ):
        raise ValueError("signal value must be finite and within [-1, 1]")
    return {
        "kind": kind,
        "value": float(value),
        "weight": WEIGHTS[kind],
        "evidence": str(evidence),
    }


def tool_signals(events: list[dict]) -> list[dict]:
    result = []
    for event in events:
        if event.get("source") in {
            "assistant",
            "self_generated",
            "provider_self_grade",
        }:
            continue
        before = len(result)
        counts = None
        if "passed" in event and "failed" in event:
            passed, failed = event["passed"], event["failed"]
            if type(passed) is not int or type(failed) is not int or min(passed, failed) < 0:
                raise ValueError("test counts must be nonnegative integers")
            counts = (passed, failed)
        # A partially passing suite is a failed check. Keep progress as a
        # metric, never as a positive correctness label. Counts also prevent
        # an inconsistent positive envelope from masking an observed failure.
        if counts and sum(counts) and (counts[1] or "verdict" not in event):
            passed, failed = counts
            item = signal("tests", -1 if failed else 1, event.get("evidence", ""))
            item.update(passed=passed, failed=failed,
                        pass_fraction=passed / (passed + failed),
                        progress=(passed - failed) / (passed + failed))
            result.append(item)
        elif "verdict" in event or (
            event.get("name") == "benchmark_verifier"
            and isinstance(event.get("success"), bool)
        ):
            verdict = event.get("verdict", event.get("success"))
            if verdict in (True, "pass", "passed", "success"):
                result.append(signal("verifier", 1, event.get("evidence", "")))
            elif verdict in (False, "fail", "failed", "failure"):
                result.append(signal("verifier", -1, event.get("evidence", "")))
        elif (type(event.get("exit_code")) is int and event["exit_code"] != 0
              and event.get("outcome_scope") == "task" and event.get("final") is True):
            result.append(signal("exit_code", -1, event.get("evidence", "")))
        elif isinstance(event.get("claim"), dict):
            from mnemosyne.learning import LocalCritic

            claim = event["claim"]
            if claim.get("category", "fact") in {"fact", "math", "code"}:
                try:
                    verdict = LocalCritic().verify(claim)
                    result.append(
                        signal("critic", 1 if verdict.verified else -1, verdict.detail)
                    )
                except (TypeError, ValueError, OverflowError):
                    result.append(
                        signal("critic", -1, "invalid externally supplied claim")
                    )
        if len(result) == before:
            continue
        item = result[-1]
        check = event.get("check_id")
        if not check and event.get("command") is not None:
            check = "command-" + digest([event.get("command"), event.get("cwd")])
        if isinstance(check, str) and check:
            item["check_id"] = check
        targets = event.get("target_ids", [])
        if isinstance(targets, list) and all(isinstance(target, str) and target for target in targets):
            if targets:
                item["target_ids"] = sorted(set(targets))
        if event.get("outcome_scope") == "task" and event.get("final") is True:
            item.update(outcome_scope="task", final=True)
        elif event.get("outcome_scope") == "diagnostic":
            item["outcome_scope"] = "diagnostic"
        call_id = event.get("call_id", event.get("source_call_id"))
        if isinstance(call_id, str):
            item["call_id"] = call_id
        checked = event.get("checked_call_ids")
        if isinstance(checked, list) and checked and all(isinstance(value, str) and value for value in checked):
            item["checked_call_ids"] = list(checked)
        tested = event.get("tested_steps")
        if isinstance(tested, list) and tested and all(isinstance(value, str) and value for value in tested):
            item["tested_steps"] = list(tested)
    return _current_checks(result)


def _current_checks(signals: list[dict]) -> list[dict]:
    """A retry replaces its own check; independent failed checks remain evidence."""
    latest = {}
    unkeyed = []
    for index, item in enumerate(signals):
        if item.get("check_id"):
            key = (item["check_id"], tuple(item.get("target_ids", [])))
            latest[key] = (index, item)
        else:
            unkeyed.append((index, item))
    return [item for _, item in sorted([*unkeyed, *latest.values()])]


def user_signals(text: str, previous_text: str = "") -> list[dict]:
    normalized = text.strip().lower().replace("’", "'")
    # Quoted examples are data, not feedback about the prior response. The
    # boundaries preserve apostrophes in contractions such as "doesn't".
    feedback = re.sub(
        r""""[^"\n]*"|“[^”\n]*”|(?<!\w)'[^'\n]*'(?!\w)""", "", normalized
    ).strip()
    if any(re.match(pattern, feedback) for pattern in CORRECTIONS):
        return [signal("correction", -1, text)]
    if re.fullmatch(ACCEPTANCE, normalized):
        return [signal("acceptance", 0.6, text)]
    if previous_text and any(re.match(pattern, feedback) for pattern in REASKS):
        return [signal("reask", -0.6, text)]
    return []


def reward(signals: list[dict], *, include_diagnostics: bool = False) -> float | None:
    signals = _current_checks(signals)
    if not include_diagnostics:
        signals = [item for item in signals if item.get("outcome_scope") != "diagnostic"]
    final = [item for item in signals if item.get("outcome_scope") == "task" and item.get("final")]
    if final:
        # Only an explicit external final verdict can supersede attempted checks.
        # Later human feedback still contributes independently.
        signals = [final[-1], *[item for item in signals if item is not final[-1]
                              and item["kind"] in {"correction", "acceptance", "reask", "rating"}]]
    failures = [item["value"] for item in signals
                if item["kind"] in {"tests", "verifier", "critic"} and item["value"] < 0]
    if failures:
        # Independent unresolved failures cannot be outvoted by unrelated
        # passing checks. A retry of the same check was already reconciled.
        return min(failures)
    total = math.fsum(item["weight"] for item in signals)
    return (
        math.fsum(item["value"] * item["weight"] for item in signals) / total
        if total >= 0.3
        else None
    )


def receipt_target(item: dict, artifacts: dict) -> dict | None:
    """Resolve the frozen receipt identity, including non-artifact recall items."""
    if item["kind"] == "item":
        return {"id": item["item_id"], "kind": "item", "revision": item["revision"]}
    artifact = artifacts.get(item["item_id"])
    return artifact if artifact and artifact.get("revision") == item["revision"] else None


def verified_target_outcome(artifact: dict, episode: dict) -> float | None:
    """Separate observed task benefit from verification of a particular memory."""
    verified = [item for item in episode.get("signals", []) if item["kind"] in VERIFIED_KINDS]
    targeted = [item for item in verified if artifact["id"] in item.get("target_ids", [])]
    if targeted:
        return reward(targeted, include_diagnostics=True)
    if artifact.get("strategy_contract", {}).get("kind") == "observed_conditional_roles":
        from .strategy_roles import abstract_score
        score = abstract_score(artifact, episode)
        return None if score is None else 2 * score - 1
    if artifact.get("content_kind", artifact.get("kind")) in {"lesson", "item"}:
        return None
    general = [item for item in verified if not item.get("target_ids")]
    if not general:
        return None
    from .candidates import (
        EXCLUDED_SOURCES, action_occurrence, expected_steps, compatible_observed_steps,
        observed_action, sequence_occurrence,
    )
    steps = artifact.get("steps", [])
    expected = expected_steps(episode)
    if expected:
        matches = any(len(steps) == len(sequence)
                      and sequence_occurrence(steps, sequence) is not None
                      for sequence in expected)
        return reward(general) if matches else -1.0
    occurrence = action_occurrence(artifact, episode)
    if occurrence is None:
        return None
    observed = compatible_observed_steps(steps, episode)
    if len(steps) == len(observed):
        return reward(general)

    # An embedded routine needs a checker associated with its actual calls.
    # Proximity to an unrelated successful test run is not verification.
    observed_events = episode.get("tool_events", [])
    if episode.get("event_parser_version", 0) >= 2:
        from mnemosyne.hosts.codex import reparse_retained_events
        observed_events = reparse_retained_events(observed_events)
    events = [event for event in observed_events
              if event.get("source") not in EXCLUDED_SOURCES]
    outcomes = []
    prior = []
    for event in events:
        checks = [item for item in tool_signals([event])
                  if item in general and item["kind"] in {"tests", "verifier"}]
        if checks:
            checked = checks[0].get("checked_call_ids", [])
            ids = [row.get("call_id", row.get("source_call_id")) for row in prior]
            if (checked and len(checked) == len(set(checked))
                    and all(ids.count(key) == 1 for key in checked)):
                selected = [row for row, key in zip(prior, ids, strict=True) if key in checked]
                if action_occurrence(artifact, {"tool_events": selected}) is not None:
                    outcomes.extend(checks)
            elif checks[0].get("tested_steps"):
                tested = checks[0]["tested_steps"]
                actual = compatible_observed_steps(steps, {"tool_events": prior})
                if (sequence_occurrence(tested, actual) is not None
                        and sequence_occurrence(steps, tested,
                                                contiguous=artifact.get("kind") == "chunk") is not None):
                    outcomes.extend(checks)
        if event.get("name") != "benchmark_verifier" and observed_action(event) is not None:
            prior.append(event)
    # A checker may be part of the operation itself (for example a test runner).
    operation_checks = [
        [item for item in tool_signals([prior[index]]) if item in general
         and item["kind"] in {"tests", "verifier"}]
        for index in occurrence
    ]
    if all(operation_checks):
        outcomes.extend(item for checked in operation_checks for item in checked)
    return reward(_current_checks(outcomes)) if outcomes else None


def _repaired_signals(episode: dict, events: list[dict]) -> list[dict]:
    """Recompute automatic signals from retained events; keep manual feedback."""
    automatic = Counter()
    def core(item):
        return item["kind"], item["value"], item["weight"], item.get("evidence", "")
    for event in episode.get("tool_events", []):
        legacy = dict(event)
        if episode.get("outcome_version", 1) < 2 and type(legacy.get("exit_code")) is int and legacy["exit_code"] != 0:
            legacy.update(outcome_scope="task", final=True)
        for item in tool_signals([legacy]):
            automatic[core(item)] += 1
            if (episode.get("outcome_version", 1) < 3 and item["kind"] == "tests"
                    and "passed" in legacy and "failed" in legacy
                    and legacy["passed"] + legacy["failed"]):
                verdict = legacy.get("verdict", legacy.get("success") if legacy.get("name") == "benchmark_verifier" else None)
                if verdict in (True, "pass", "passed", "success", False, "fail", "failed", "failure"):
                    old = signal("verifier", 1 if verdict in (True, "pass", "passed", "success") else -1,
                                 legacy.get("evidence", ""))
                else:
                    old = {**item, "value": (legacy["passed"] - legacy["failed"]) /
                           (legacy["passed"] + legacy["failed"])}
                if core(old) != core(item):
                    automatic[core(old)] += 1
    manual = []
    for item in episode.get("signals", []):
        key = core(item)
        if automatic[key]:
            automatic[key] -= 1
        else:
            manual.append(deepcopy(item))
    return [*tool_signals(events), *manual]


def current_signals(episode: dict) -> list[dict]:
    """Signals for an unresolved episode whose stored values predate a scoring fix."""
    from mnemosyne.hosts.codex import reparse_retained_events
    return _repaired_signals(episode, reparse_retained_events(episode.get("tool_events", [])))


def reprocessed_episode(episode: dict, artifacts: dict, receipts: dict) -> dict:
    """Recompute derived outcome fields from retained observations, never from prose.

    This explicit maintenance path preserves manual feedback and all original
    source/receipt identities. LearningWriter retains the original row in its
    encrypted audit. Erased and imported histories are never reconstructed.
    """
    if episode.get("status") not in {"resolved", "unknown"}:
        return deepcopy(episode)
    from mnemosyne.hosts.codex import reparse_retained_events
    original_events = episode.get("tool_events", [])
    events = reparse_retained_events(original_events)
    if episode.get("outcome_version", 1) >= OUTCOME_VERSION and (
        episode.get("event_parser_version", 0) >= 2 or events == original_events
    ):
        return deepcopy(episode)
    updated = deepcopy(episode)
    updated["signals"] = _repaired_signals(episode, events)
    updated["outcome_version"] = OUTCOME_VERSION
    updated["event_parser_version"] = 2
    value = reward(updated["signals"])
    updated.update(reward=value, rpe=None if value is None else value - (2 * episode["prediction"] - 1),
                   status="unknown" if value is None else "resolved", target_outcomes={})
    if value is not None:
        for rid in episode.get("receipt_ids", []):
            for item in receipts[rid]["items"]:
                artifact = receipt_target(item, artifacts)
                if not artifact:
                    continue
                target = verified_target_outcome(artifact, updated)
                if target is not None:
                    updated["target_outcomes"][artifact["id"]] = {
                        "value": target, "rpe": target - (2 * episode["prediction"] - 1),
                    }
    return updated
