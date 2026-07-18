"""Fail-closed marker for unsupported public PM/Trigger execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PM_TRIGGER_UNAVAILABLE_REASON = (
    "PM-Bench/TriggerBench are non-runnable: MnemoCLI does not expose authenticated "
    "public subprocess commands for the complete task create/update, clock, event, "
    "dependency-aware intention query, and action-selection fixture contract"
)


@dataclass
class ActionCLI:
    """Reject the retired fixture-aware simulator at its former public seam."""

    state: Path

    def run(self, command: str, *args: Mapping[str, Any]) -> dict[str, Any]:
        del command, args
        raise RuntimeError(PM_TRIGGER_UNAVAILABLE_REASON)
