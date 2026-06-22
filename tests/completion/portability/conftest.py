"""Pytest config for the portability suite.

Ensures this directory is importable so ``from _portability import ...`` resolves when
the suite is collected from the repository root (where ``rootdir`` is the project, not
this folder).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
