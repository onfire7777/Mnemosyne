#!/usr/bin/env python3
"""Standalone, dependency-free runner for FR-20/FR-21 scope-conformance.

Measures the CURRENT ``src/mnemosyne`` against the INTENTIONALLY-LIMITED v1 bar
for the two P2 future-considerations FRs:

  - FR-20 multimodal (blueprint non-goal N5, "post-v1"): media.py + the substrate
    accept image/audio modalities behind the SAME interfaces; full multimodal is
    correctly deferred.
  - FR-21 parametric/LoRA (blueprint non-goal N2, "optional advanced tier"): the
    command-backed parametric boundary enforces operator-grade auth + structural
    local rails (mutation-rate / reward / sink / gate) + rollback, WITHOUT a real
    GPU trainer.

This runner needs NO pytest and NO network — only stdlib + mnemosyne on the path.
It is a forcing function: it reports the honest pass/fail of the v1 bar AND prints
the deferred real-deployment validation that remains out of scope for v1.

Usage (reusing the ready eval venv with torch + sentence-transformers):

    cd /Users/admin/Projects/Mnemosyne-completion
    PYTHONPATH=src .venv-eval/bin/python \
        tests/completion/scope/run_scope_conformance.py

Add ``--json <path>`` to also write a machine-readable evidence artifact.
Exit code 0 iff every v1-bar check passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow ``python tests/completion/scope/run_scope_conformance.py`` directly by
# putting ``tests/`` on the path so ``completion.scope.*`` imports resolve.
_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from completion.scope import fr20_multimodal, fr21_parametric  # noqa: E402
from completion.scope._scope_harness import SuiteReport, run_checks  # noqa: E402


def _render(report: SuiteReport, fr: str, deferred: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    results = report.by_fr(fr)
    passed = sum(1 for r in results if r.passed)
    lines.append(f"## {fr}  —  {passed}/{len(results)} v1-bar checks pass")
    lines.append("")
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(f"  [{mark}] {r.check.name}")
        lines.append(f"         bar: {r.check.bar}")
        if r.passed and r.note:
            lines.append(f"         ->  {r.note}")
        if not r.passed:
            for ln in r.error.splitlines():
                lines.append(f"         !!  {ln}")
    lines.append("")
    lines.append(f"  Deferred to real deployment (OUT OF SCOPE for v1 — {fr}):")
    for item in deferred:
        lines.append(f"    - {item}")
    lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write a JSON evidence artifact")
    parser.add_argument("--quiet", action="store_true", help="suppress the human report")
    args = parser.parse_args(argv)

    checks = list(fr20_multimodal.CHECKS) + list(fr21_parametric.CHECKS)
    report = run_checks(checks)

    out: list[str] = []
    out.append("=" * 78)
    out.append("Mnemosyne scope-conformance — FR-20 (N5) multimodal / FR-21 (N2) parametric")
    out.append("Holding the two INTENTIONALLY-LIMITED P2 FRs to their v1 bar (not full P2).")
    out.append("=" * 78)
    out.append("")
    out += _render(report, "FR-20", fr20_multimodal.REAL_DEPLOYMENT_VALIDATION)
    out += _render(report, "FR-21", fr21_parametric.REAL_DEPLOYMENT_VALIDATION)
    out.append("-" * 78)
    verdict = "ALL GREEN" if report.all_pass else "SEE FAILURES"
    out.append(f"OVERALL: {report.passed}/{report.total} v1-bar checks pass  —  {verdict}")
    out.append("-" * 78)

    if not args.quiet:
        print("\n".join(out))

    if args.json is not None:
        artifact = {
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "component": "scope-conformance/FR-20+FR-21",
                "measures": "current src/mnemosyne against the INTENTIONALLY-LIMITED v1 bar",
                "blueprint_refs": [
                    "FR-20 multimodal (N5 post-v1)",
                    "FR-21 parametric (N2 optional advanced tier)",
                    "§23.5 immutable invariant",
                    "§23.6 optional parametric tier",
                ],
            },
            "overall": {
                "passed": report.passed,
                "total": report.total,
                "all_pass": report.all_pass,
            },
            "frs": {},
        }
        for fr, mod in (("FR-20", fr20_multimodal), ("FR-21", fr21_parametric)):
            results = report.by_fr(fr)
            artifact["frs"][fr] = {
                "passed": sum(1 for r in results if r.passed),
                "total": len(results),
                "checks": [
                    {
                        "name": r.check.name,
                        "bar": r.check.bar,
                        "passed": r.passed,
                        "note": r.note,
                        "error": r.error,
                    }
                    for r in results
                ],
                "deferred_real_deployment_validation": list(mod.REAL_DEPLOYMENT_VALIDATION),
            }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(artifact, indent=2))
        if not args.quiet:
            print(f"\nJSON evidence artifact -> {args.json}")

    return 0 if report.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
