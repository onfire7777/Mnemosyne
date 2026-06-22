"""Local pytest config for the calibration eval (net-new, calibration dir only).

Registers the ``slow`` marker so the CLI-subprocess-driven calibration test does
not emit ``PytestUnknownMarkWarning``. Scoped to this directory; does not touch
repo-level pyproject config.
"""

from __future__ import annotations


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: drives the real engine via CLI subprocesses (calibration ECE measurement).",
    )
