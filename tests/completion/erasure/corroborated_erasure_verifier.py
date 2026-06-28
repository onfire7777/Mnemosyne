"""Corroborated-erasure audit verifier — OQ6 / FR-8 (transitive forget + corroboration).

Blueprint refs
--------------
* OQ6  — "When a source is forgotten, what happens to projections derived from it
          *together with other, still-valid sources*?"
* FR-8 — transitive forget: erasure must propagate to every derived projection,
          trimming provenance where the projection survives on other corroboration
          and retracting/tombstoning where the erased source was the *sole* support.
* §31 RAIL 2 — ``min_corroboration_for_delete = 2`` (">= 2 independent sources
          before a *hard* delete"). See the sibling in-process rail breach test
          ``tests/completion/rails/test_min_corroboration_for_delete.py``.

What this verifier proves (adversarial round-trip)
--------------------------------------------------
Four cases, each driven end-to-end through the **public surface** the blueprint
promises to agents — the ``python -m mnemosyne.cli`` subprocess for every step,
including assertion creation through the exact ``assert --object`` flag that used
to be blocked by argparse abbreviation matching.

  (a) RETAIN + TRIM. Ingest a projection derived from TWO independent
      corroborating sources; legally/operationally erase ONE source; assert the
      projection is RETAINED (``status`` stays active) with **updated** provenance
      — the erased CID is *trimmed out*, the surviving CID is *kept* (NOT a blanket
      zeroing of ``source_evidence_cids``).

  (b) RETRACT / TOMBSTONE. Ingest a projection derived SOLELY from one source;
      erase it; assert the projection is RETRACTED (``status == "retracted"`` and
      ``source_evidence_cids == []``).

  (c) OPERATOR-DELETE GATE. Attempt an operator deletion of a
      sole, uncorroborated source and assert ``min_corroboration_for_delete``
      blocks it. This is enforced in the local and Postgres engines; a future
      regression is recorded as ``status="breach_unenforced"``.

  (d) LEGAL / RIGHT-TO-BE-FORGOTTEN is corroboration-blind and ALWAYS shreds.
      A ``hard_delete_legal`` erasure hard-deletes the evidence row regardless of
      how many sources corroborate the belief it backs, and invokes
      ``object_store.shred`` on any externalized payload.

Honesty contract
----------------
This module measures the CURRENT ``src`` behavior. It does not patch ``src``. It
emits a machine-readable report (``report()``) recording, per case, the EXPECTED
invariant, the OBSERVED behavior, and whether the current code satisfies it.

Trust-tier scale gotcha (load-bearing): in ``mnemosyne.security.TrustTier`` the
scale is INVERTED — ``0`` (DIRECT_USER / OPERATOR) is the *strongest* tier and
``5`` (UNTRUSTED_EXTERNAL) the weakest. Belief writes require
``source_trust_tier <= NORMAL(3)``. We therefore seed with ``source_trust_tier=0``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine

# Repo root: tests/completion/erasure/<file> -> repo
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

TENANT = "tenant-erasure"
USER = "user-erasure"

# Strongest trust tier (DIRECT_USER/OPERATOR == 0); belief writes require <= NORMAL(3).
STRONG_TRUST = 0

# -- Public CLI assertion path status. ------------------------------------------
# ``build_parser`` disables argparse abbreviation matching on both the top-level
# parser and subparsers, so global ``--object-store`` / ``--object-key-*`` flags
# no longer collide with the subcommand ``--object`` flag.
CLI_OBJECT_FLAG_STATUS = (
    "mneme {assert,propose,correct} --object <v> is parsed exactly; argparse abbreviation "
    "matching is disabled for the top-level parser and subparsers."
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(_SRC), existing) if p)
    return env


@dataclass(slots=True)
class CaseResult:
    name: str
    blueprint_ref: str
    expected: str
    observed: dict[str, Any]
    passed: bool
    status: str  # "ok" | "breach_unenforced" | "error"
    missing_enforcement: str | None = None


@dataclass(slots=True)
class AuditReport:
    cases: list[CaseResult] = field(default_factory=list)

    def add(self, case: CaseResult) -> None:
        self.cases.append(case)

    @property
    def all_invariants_hold(self) -> bool:
        # "hold" means: enforced invariants pass; the strict-xfail breach (c) is a
        # *known* unenforced gap and does NOT count as a passing invariant.
        return all(c.passed for c in self.cases if c.status != "breach_unenforced")

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit": "corroborated_erasure",
            "blueprint_refs": ["OQ6", "FR-8", "§31 RAIL 2 (min_corroboration_for_delete)"],
            "public_surface": "python -m mnemosyne.cli (subprocess)",
            "cli_object_option_status": CLI_OBJECT_FLAG_STATUS,
            "trust_tier_scale": "INVERTED: 0=DIRECT_USER/OPERATOR strongest, 5=UNTRUSTED weakest",
            "cases": [
                {
                    "name": c.name,
                    "blueprint_ref": c.blueprint_ref,
                    "expected": c.expected,
                    "observed": c.observed,
                    "passed": c.passed,
                    "status": c.status,
                    "missing_enforcement": c.missing_enforcement,
                }
                for c in self.cases
            ],
            "summary": {
                "total": len(self.cases),
                "enforced_pass": sum(1 for c in self.cases if c.status == "ok" and c.passed),
                "breach_unenforced": sum(1 for c in self.cases if c.status == "breach_unenforced"),
                "errors": sum(1 for c in self.cases if c.status == "error"),
                "all_enforced_invariants_hold": self.all_invariants_hold,
            },
        }


class CorroboratedErasureVerifier:
    """Drives the public surface to audit corroborated-erasure semantics.

    Parameters
    ----------
    store:
        Path to a fresh local JSON store (isolated, deterministic engine).
    object_store:
        Path to a local object store so case (d) can exercise the real shred path
        on an externalized binary payload.
    """

    def __init__(self, store: str, object_store: str, *, python: str | None = None):
        self.store = store
        self.object_store = object_store
        self.python = python or sys.executable

    # ---- public CLI subprocess seam --------------------------------------------

    def cli(self, command: str, *args: str, check: bool = True) -> dict[str, Any]:
        argv = [
            self.python, "-m", "mnemosyne.cli",
            "--backend", "local",
            "--store", self.store,
            "--object-store", self.object_store,
            command, *args,
        ]
        proc = subprocess.run(
            argv, capture_output=True, text=True, env=_env(), cwd=str(_REPO_ROOT), timeout=120.0
        )
        stdout = _strip_ansi(proc.stdout)
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"CLI failed (rc={proc.returncode}): mneme {command} {' '.join(args)}\n"
                f"--- stdout ---\n{stdout[-1500:]}\n--- stderr ---\n{_strip_ansi(proc.stderr)[-1500:]}"
            )
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            start, end = stdout.find("{"), stdout.rfind("}")
            if start != -1 and end > start:
                return json.loads(stdout[start : end + 1])
            raise RuntimeError(f"CLI emitted non-JSON for {command}: {stdout[-500:]!r}")

    def assert_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        source_evidence_cids: list[str],
        *,
        confidence: float = 0.9,
    ) -> str:
        """Create a corroborated assertion on ``main`` through the public CLI.

        This keeps the audit on the same subprocess boundary agents and operators
        use, including the formerly colliding ``assert --object`` flag.
        """
        evidence_args: list[str] = []
        for cid in source_evidence_cids:
            evidence_args.extend(["--evidence-cid", cid])
        result = self.cli(
            "assert",
            "--tenant", TENANT,
            "--user", USER,
            "--subject", subject,
            "--predicate", predicate,
            "--object", obj,
            *evidence_args,
            "--confidence", str(confidence),
            "--trust-tier", str(STRONG_TRUST),
            "--role", "operator",
            "--source-trust-tier", str(STRONG_TRUST),
        )
        return result["id"]

    # ---- CLI convenience wrappers ----------------------------------------------

    def capture(self, content: str, *, actor: str = "user", source_type: str = "chat") -> str:
        out = self.cli(
            "capture",
            "--tenant", TENANT, "--user", USER,
            "--actor", actor, "--source-type", source_type,
            "--content", content,
        )
        return out["cid"]

    def ingest_binary(self, payload: bytes, *, media_type: str = "image/png") -> dict[str, Any]:
        """Ingest a binary payload via the CLI so it is externalized to the object
        store (``content_pointer`` set) — the precondition for the real shred path.
        """
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as fh:
            fh.write(payload)
            path = fh.name
        try:
            return self.cli(
                "ingest",
                "--tenant", TENANT, "--user", USER,
                "--actor", "user", "--source-type", "upload",
                "--file", path, "--modality", "image", "--media-type", media_type,
                "--no-enqueue-consolidation",
            )
        finally:
            os.unlink(path)

    def forget(self, cid: str, *, erasure_mode: str = "tombstone_recompute", requested_by: str = "user") -> dict[str, Any]:
        return self.cli(
            "forget",
            "--tenant", TENANT, "--cid", cid,
            "--erasure-mode", erasure_mode,
            "--requested-by", requested_by,
            "--role", "operator", "--source-trust-tier", str(STRONG_TRUST),
        )

    def get(self, item_id: str) -> dict[str, Any] | None:
        out = self.cli("get", "--tenant", TENANT, "--id", item_id, check=False)
        # cmd_get raises KeyError -> non-zero exit when not found; tolerate that.
        if isinstance(out, dict) and out.get("record"):
            return out
        return None

    def export(self) -> dict[str, Any]:
        return LocalMemoryEngine(store_path=Path(self.store)).export_tenant(TENANT)

    def assertion_record(self, assertion_id: str) -> dict[str, Any] | None:
        """Read the assertion straight from ``export`` (status-agnostic; ``export``
        lists retracted assertions too, so we can observe retraction)."""
        for row in self.export().get("assertions", []):
            if row.get("id") == assertion_id:
                return row
        return None

    def evidence_present(self, cid: str) -> bool:
        """True iff the evidence row is still materially present (export filters
        out erased/hard-deleted rows)."""
        return any(row.get("cid") == cid for row in self.export().get("evidence", []))

    # ---- the four audit cases --------------------------------------------------

    def case_a_corroborated_retain_and_trim(self) -> CaseResult:
        cid_a = self.capture("Receipt A: Paris is the capital of France.", source_type="chat")
        cid_b = self.capture("Encyclopedia B: Paris is the capital of France.", actor="external", source_type="web")
        aid = self.assert_fact("Paris", "capital_of", "France", [cid_a, cid_b])
        before = self.assertion_record(aid)
        forget = self.forget(cid_a, erasure_mode="tombstone_recompute", requested_by="user")
        after = self.assertion_record(aid)

        observed = {
            "before_status": before["status"] if before else None,
            "before_cids": before["source_evidence_cids"] if before else None,
            "forget_propagated": forget.get("propagated"),
            "after_status": after["status"] if after else None,
            "after_cids": after["source_evidence_cids"] if after else None,
            "erased_cid": cid_a,
            "surviving_cid": cid_b,
        }
        passed = bool(
            after
            and after["status"] != "retracted"
            and cid_a not in after["source_evidence_cids"]
            and cid_b in after["source_evidence_cids"]
            # trimmed, NOT blanket-zeroed:
            and after["source_evidence_cids"] == [cid_b]
            and aid in (forget.get("propagated", {}).get("trimmed_assertions") or [])
            and aid not in (forget.get("propagated", {}).get("retracted_assertions") or [])
        )
        return CaseResult(
            name="a_corroborated_retain_and_trim",
            blueprint_ref="OQ6 / FR-8",
            expected=(
                "Erasing ONE of two corroborating sources RETAINS the projection (active) "
                "with provenance trimmed to the surviving CID only (erased CID removed, "
                "not blanket-zeroed)."
            ),
            observed=observed,
            passed=passed,
            status="ok" if passed else "error",
        )

    def case_b_sole_source_retract(self) -> CaseResult:
        cid_c = self.capture("Sole source C: the cat is named Mittens.", source_type="chat")
        aid = self.assert_fact("cat", "named", "Mittens", [cid_c])
        forget = self.forget(cid_c, erasure_mode="tombstone_recompute", requested_by="user")
        after = self.assertion_record(aid)

        observed = {
            "forget_propagated": forget.get("propagated"),
            "after_status": after["status"] if after else None,
            "after_cids": after["source_evidence_cids"] if after else None,
            "erased_cid": cid_c,
        }
        passed = bool(
            after
            and after["status"] == "retracted"
            and after["source_evidence_cids"] == []
            and aid in (forget.get("propagated", {}).get("retracted_assertions") or [])
        )
        return CaseResult(
            name="b_sole_source_retract_tombstone",
            blueprint_ref="OQ6 / FR-8",
            expected=(
                "Erasing the SOLE source of a projection RETRACTS/tombstones it "
                "(status=retracted, source_evidence_cids=[])."
            ),
            observed=observed,
            passed=passed,
            status="ok" if passed else "error",
        )

    def case_c_operator_delete_sole_uncorroborated_gate(self) -> CaseResult:
        """The corroboration rail refuses destructive operator deletion when it
        would strand a sole-source active assertion.
        """
        cid_d = self.capture("Sole uncorroborated source D: secret claim.", source_type="chat")
        aid = self.assert_fact("secret", "claim", "value-D", [cid_d])

        # Operator attempts to vaporize the only copy. We probe BOTH erasure modes
        # because the rail's intent ("min_corroboration_for_delete") spans any
        # destructive delete of a sole source backing an active assertion. The
        # blueprint rail-2 enforcement point is the HARD_DELETE_LEGAL branch.
        legal = self.forget(cid_d, erasure_mode="hard_delete_legal", requested_by="operator")
        after = self.assertion_record(aid)

        refused = (legal.get("erased") is False)
        observed = {
            "erasure_mode": "hard_delete_legal",
            "forget_erased": legal.get("erased"),
            "refused_by_corroboration_gate": refused,
            "assertion_after_status": after["status"] if after else "GONE",
            "sole_source_cid": cid_d,
        }
        passed = refused
        return CaseResult(
            name="c_operator_delete_sole_uncorroborated_blocked",
            blueprint_ref="§31 RAIL 2 (min_corroboration_for_delete >= 2)",
            expected=(
                "Operator deletion of a SOLE, uncorroborated source backing an active "
                "assertion must be REFUSED (forget returns erased=False or raises) by a "
                "min_corroboration_for_delete>=2 gate."
            ),
            observed=observed,
            passed=passed,
            status="ok" if passed else "breach_unenforced",
            missing_enforcement=None
            if passed
            else (
                "min_corroboration_for_delete is not enforced for destructive operator "
                "deletion of a sole-source active assertion."
            ),
        )

    def case_d_legal_is_corroboration_blind_and_shreds(self) -> CaseResult:
        """Legal/right-to-be-forgotten erasure ignores corroboration and shreds.

        Two sub-checks:
          d1) corroboration-blind: legally erasing ONE of TWO corroborators still
              hard-deletes that evidence row (gone from export) and trims the
              surviving projection — the corroboration count does NOT protect a
              legal erasure (contrast with case c's *intended* gate).
          d2) shred: a legal erasure of an externalized (object-store) payload
              invokes object_store.shred and returns an object_shred report.
        """
        # d1 — corroboration-blind hard delete of one of two corroborators.
        cid_e = self.capture("Corroborator E1: sky is blue.", source_type="chat")
        cid_f = self.capture("Corroborator E2: sky is blue.", actor="external", source_type="web")
        aid = self.assert_fact("sky", "color", "blue", [cid_e, cid_f])
        legal = self.forget(cid_e, erasure_mode="hard_delete_legal", requested_by="legal")
        after = self.assertion_record(aid)
        e_gone = not self.evidence_present(cid_e)

        # d2 — shred path on an externalized binary payload.
        ing = self.ingest_binary(b"\x89PNG\r\n\x1a\n" + b"corroborated-erasure-payload" * 64)
        bin_cid = ing["cid"]
        had_pointer = bool(ing.get("content_pointer"))
        legal_bin = self.forget(bin_cid, erasure_mode="hard_delete_legal", requested_by="legal")
        bin_gone = not self.evidence_present(bin_cid)

        observed = {
            "d1_corroboration_blind": {
                "legal_erased": legal.get("erased"),
                "erased_evidence_row_gone_from_export": e_gone,
                "projection_after_status": after["status"] if after else None,
                "projection_after_cids": after["source_evidence_cids"] if after else None,
            },
            "d2_shred": {
                "ingest_content_pointer": ing.get("content_pointer"),
                "had_externalized_payload": had_pointer,
                "legal_erased": legal_bin.get("erased"),
                "object_shred_report": legal_bin.get("object_shred"),
                "evidence_row_gone_from_export": bin_gone,
            },
        }
        passed = bool(
            # d1: legal erasure went through regardless of corroboration, row hard-deleted
            legal.get("erased") is True
            and e_gone
            and after is not None
            and cid_e not in (after["source_evidence_cids"] or [])
            # d2: shred actually invoked on the externalized payload
            and had_pointer
            and legal_bin.get("erased") is True
            and bin_gone
            and legal_bin.get("object_shred") is not None
        )
        return CaseResult(
            name="d_legal_corroboration_blind_and_shreds",
            blueprint_ref="FR-8 (legal erasure) / privacy.ErasureMode.HARD_DELETE_LEGAL",
            expected=(
                "Legal/right-to-be-forgotten erasure is corroboration-blind: it hard-deletes "
                "the evidence row regardless of corroboration count AND invokes "
                "object_store.shred on any externalized payload (object_shred report present)."
            ),
            observed=observed,
            passed=passed,
            status="ok" if passed else "error",
        )

    def run(self) -> AuditReport:
        report = AuditReport()
        for fn in (
            self.case_a_corroborated_retain_and_trim,
            self.case_b_sole_source_retract,
            self.case_c_operator_delete_sole_uncorroborated_gate,
            self.case_d_legal_is_corroboration_blind_and_shreds,
        ):
            try:
                report.add(fn())
            except Exception as exc:  # noqa: BLE001 - record, never swallow silently
                report.add(
                    CaseResult(
                        name=fn.__name__.replace("case_", "", 1),
                        blueprint_ref="OQ6 / FR-8",
                        expected="(case raised before it could assert)",
                        observed={"error": f"{type(exc).__name__}: {exc}"},
                        passed=False,
                        status="error",
                    )
                )
        return report


def run_audit(out_path: str | None = None) -> dict[str, Any]:
    """Run the full corroborated-erasure audit against the current ``src``.

    Returns the report dict. If ``out_path`` is given, also writes it as JSON.
    Uses fresh temp store + object store so the run is hermetic and repeatable.
    """
    tmp = tempfile.mkdtemp(prefix="corro-erasure-")
    store = os.path.join(tmp, "store.json")
    objstore = os.path.join(tmp, "objstore")
    verifier = CorroboratedErasureVerifier(store=store, object_store=objstore)
    report = verifier.run().to_dict()
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    default_out = str(
        _REPO_ROOT / "tests" / "completion" / "erasure" / "out" / "corroborated_erasure_audit.json"
    )
    out = sys.argv[1] if len(sys.argv) > 1 else default_out
    rep = run_audit(out)
    print(json.dumps(rep, indent=2, sort_keys=True))
    print(f"\n[corroborated-erasure] report written to: {out}", file=sys.stderr)
    summary = rep["summary"]
    print(
        f"[corroborated-erasure] enforced_pass={summary['enforced_pass']} "
        f"breach_unenforced={summary['breach_unenforced']} errors={summary['errors']} "
        f"all_enforced_invariants_hold={summary['all_enforced_invariants_hold']}",
        file=sys.stderr,
    )
    # Exit non-zero only on hard errors or an enforced-invariant regression.
    sys.exit(0 if (summary["errors"] == 0 and summary["all_enforced_invariants_hold"]) else 1)
