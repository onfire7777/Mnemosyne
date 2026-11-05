"""External signal allowlist. Assistant text and zero exits carry no reward."""

from __future__ import annotations

import math
import re

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
CORRECTIONS = (
    r"\bno[,! ]",
    r"\b(?:wrong|incorrect|actually|instead|i meant|please correct)\b",
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
        elif isinstance(event.get("exit_code"), int) and event["exit_code"] != 0:
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
    return result


def user_signals(text: str, previous_text: str = "") -> list[dict]:
    normalized = text.strip().lower()
    if any(re.search(pattern, normalized) for pattern in CORRECTIONS):
        return [signal("correction", -1, text)]
    if re.fullmatch(ACCEPTANCE, normalized):
        return [signal("acceptance", 0.6, text)]
    if previous_text:
        a, b = (
            set(re.findall(r"\w+", normalized)),
            set(re.findall(r"\w+", previous_text.lower())),
        )
        if a and b and len(a & b) / len(a | b) >= 0.6:
            return [signal("reask", -0.6, text)]
    return []


def reward(signals: list[dict]) -> float | None:
    total = math.fsum(item["weight"] for item in signals)
    return (
        math.fsum(item["value"] * item["weight"] for item in signals) / total
        if total >= 0.3
        else None
    )
