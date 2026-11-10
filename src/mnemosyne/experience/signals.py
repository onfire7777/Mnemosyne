"""External signal allowlist. Assistant text and zero exits carry no reward."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from collections import Counter

from .receipts import digest

VERIFIED_KINDS = frozenset({"verifier", "tests", "critic", "rating"})

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
        if "verdict" in event or (
            event.get("name") == "benchmark_verifier"
            and isinstance(event.get("success"), bool)
        ):
            verdict = event.get("verdict", event.get("success"))
            if verdict in (True, "pass", "passed", "success"):
                result.append(signal("verifier", 1, event.get("evidence", "")))
            elif verdict in (False, "fail", "failed", "failure"):
                result.append(signal("verifier", -1, event.get("evidence", "")))
        elif "passed" in event and "failed" in event:
            passed, failed = event["passed"], event["failed"]
            if (
                type(passed) is not int
                or type(failed) is not int
                or min(passed, failed) < 0
            ):
                raise ValueError("test counts must be nonnegative integers")
            if passed + failed:
                result.append(
                    signal(
                        "tests",
                        (passed - failed) / (passed + failed),
                        event.get("evidence", ""),
                    )
                )
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
        call_id = event.get("call_id", event.get("source_call_id"))
        if isinstance(call_id, str):
            item["call_id"] = call_id
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


def reward(signals: list[dict]) -> float | None:
    signals = _current_checks(signals)
    final = [item for item in signals if item.get("outcome_scope") == "task" and item.get("final")]
    if final:
        # Only an explicit external final verdict can supersede attempted checks.
        # Later human feedback still contributes independently.
        signals = [final[-1], *[item for item in signals if item is not final[-1]
                              and item["kind"] in {"correction", "acceptance", "reask", "rating"}]]
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
        return reward(targeted)
    if artifact.get("content_kind", artifact.get("kind")) in {"lesson", "item"}:
        return None
    general = [item for item in verified if not item.get("target_ids")]
    if not general:
        return None
    from .candidates import expected_steps, compatible_observed_steps, ordered_subset
    steps = artifact.get("steps", [])
    expected = expected_steps(episode)
    if expected:
        matches = any(steps == sequence for sequence in expected)
    else:
        observed = compatible_observed_steps(steps, episode)
        matches = bool(steps) and (ordered_subset(steps, observed) if artifact.get("kind") == "chunk" else steps == observed)
    if not matches:
        return -1.0 if expected else None
    return reward(general)


def reprocessed_episode(episode: dict, artifacts: dict, receipts: dict) -> dict:
    """Recompute derived outcome fields from retained observations, never from prose.

    This explicit maintenance path preserves manual feedback and all original
    source/receipt identities. LearningWriter retains the original row in its
    encrypted audit. Erased and imported histories are never reconstructed.
    """
    if episode.get("outcome_version", 1) >= 2 or episode.get("status") not in {"resolved", "unknown"}:
        return deepcopy(episode)
    events = episode.get("tool_events", [])
    automatic = Counter()
    def core(item):
        return item["kind"], item["value"], item["weight"], item.get("evidence", "")
    for event in events:
        legacy = dict(event)
        if type(legacy.get("exit_code")) is int and legacy["exit_code"] != 0:
            legacy.update(outcome_scope="task", final=True)
        for item in tool_signals([legacy]):
            automatic[core(item)] += 1
    manual = []
    for item in episode.get("signals", []):
        key = core(item)
        if automatic[key]:
            automatic[key] -= 1
        else:
            manual.append(deepcopy(item))
    updated = deepcopy(episode)
    updated["signals"] = [*tool_signals(events), *manual]
    updated["outcome_version"] = 2
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
