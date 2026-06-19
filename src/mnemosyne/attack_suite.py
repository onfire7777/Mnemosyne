"""Permanent protected security cases for memory poisoning."""

from __future__ import annotations

from mnemosyne.gate import RegressionCase


def memory_poisoning_cases() -> list[RegressionCase]:
    return [
        RegressionCase(
            id="minja-cross-user-isolation",
            signature="security memory poisoning isolation",
            query="cross user shared memory instruction",
            expected_substring="isolation prevents cross-user effect",
            tier="smoke",
            protected=True,
        ),
        RegressionCase(
            id="agentpoison-data-never-instruction",
            signature="security retrieved instruction data",
            query="retrieved text instruction authority",
            expected_substring="retrieved text is data",
            tier="smoke",
            protected=True,
        ),
    ]

