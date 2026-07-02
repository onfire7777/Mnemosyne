"""Import-time regression guards for the CLI (Phase 1 Task 9 / A4 lazy imports).

``import mnemosyne.cli`` must stay light: the heavy engine/retrieval/crypto
stack may only load when a subcommand actually needs it. These tests run in a
subprocess so the assertion sees a pristine ``sys.modules``.
"""

from __future__ import annotations

import json
import subprocess
import sys

# Modules that must NOT be imported as a side effect of `import mnemosyne.cli`.
FORBIDDEN_AFTER_CLI_IMPORT = (
    "cryptography.x509",
    "mnemosyne.consolidation",
    "mnemosyne.engine",
    "mnemosyne.retrieval",
    "mnemosyne.ingestion",
    "mnemosyne.media",
)


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_import_does_not_load_heavy_modules() -> None:
    proc = _run(
        "import json, sys\n"
        "import mnemosyne.cli\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    assert proc.returncode == 0, proc.stderr
    loaded = set(json.loads(proc.stdout))
    offenders = [name for name in FORBIDDEN_AFTER_CLI_IMPORT if name in loaded]
    assert not offenders, f"import mnemosyne.cli eagerly loaded: {offenders}"


def test_package_import_stays_light() -> None:
    proc = _run(
        "import sys\n"
        "import mnemosyne\n"
        "assert 'mnemosyne.engine' not in sys.modules, 'package import pulled engine'\n"
    )
    assert proc.returncode == 0, proc.stderr


def test_package_lazy_exports_all_resolve() -> None:
    """Every name in mnemosyne.__all__ must still resolve (PEP 562 lazy)."""
    proc = _run(
        "import mnemosyne\n"
        "missing = [n for n in mnemosyne.__all__ if getattr(mnemosyne, n, None) is None]\n"
        "assert not missing, f'unresolvable exports: {missing}'\n"
        "from mnemosyne import LocalMemoryEngine, route, semantic_entropy\n"
        "assert 'LocalMemoryEngine' in dir(mnemosyne)\n"
    )
    assert proc.returncode == 0, proc.stderr


def test_package_unknown_attribute_raises() -> None:
    proc = _run(
        "import mnemosyne\n"
        "try:\n"
        "    mnemosyne.definitely_not_a_real_export\n"
        "except AttributeError:\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit('AttributeError not raised')\n"
    )
    assert proc.returncode == 0, proc.stderr
