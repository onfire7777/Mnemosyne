"""Native kernel crate packaging contract (spec §4.1; Phase-1 plan Task 1).

The native module is an OPTIONAL accelerator: absent => pure Python runs
(byte-identical results). These tests only run when it is installed.
"""
from __future__ import annotations

import pytest

native = pytest.importorskip("mnemosyne_native")


def test_native_module_exposes_contract_surface():
    assert isinstance(native.__version__, str) and native.__version__
    assert native.parity_marker() == "strict-ieee-scalar-v1"
