"""Mnemosyne §33 evaluation / SLO measurement harness.

Drives ONLY the public CLI (``python -m mnemosyne.cli``). See README in
``eval/README.md`` for the full design and how it sharpens once the real
embedding/cross-encoder service is wired (blueprint FR-3).
"""

from __future__ import annotations

__all__ = [
    "cli_driver",
    "metrics",
    "synthetic",
    "answer_quality",
    "test_classes",
    "suites",
    "ignition",
    "report",
]
