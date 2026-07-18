"""Fail-closed marker for unsupported public PM/Trigger execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PM_TRIGGER_UNAVAILABLE_REASON = (
    "PM-Bench/TriggerBench are non-runnable: authenticated intention schedule, "
    "cancel, evaluate, and list commands exist, but the production CLI does not "
    "yet expose atomic update/reschedule/override/recurring semantics; stable "
    "fixture identity and session scope or query-without-firing where required; "
    "and explicit action selection or an approved deterministic-selection contract"
)


@dataclass
class ActionCLI:
    """Reject the retired fixture-aware simulator at its former public seam."""

    state: Path

    def run(self, command: str, *args: Mapping[str, Any]) -> dict[str, Any]:
        del command, args
        raise RuntimeError(PM_TRIGGER_UNAVAILABLE_REASON)
