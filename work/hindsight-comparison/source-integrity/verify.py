"""Run targeted, provider-free regressions against a disposable live database.

Run with the project virtualenv Python from the repository. Supply the four
MNEMOSYNE_POSTGRES_* DSNs documented in REPORT.md; this script neither
creates nor destroys a database. No benchmark runner or model service is called.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
TESTS = [
    'test_ingestion_acknowledgement.py',
    'test_local_evidence_write_rollback.py',
    'test_policy_trust_tier_roundtrip.py',
    'test_time_window.py',
    'test_postgres_metadata_live.py',
    'test_postgres_entity_erasure_live.py',
    'test_shared_engine_contract.py',
    'test_runtime_parity_extensions.py',
    'test_engine_contract.py',
    'test_sqlite_ledger.py',
    'test_sqlite_erasure.py',
    'test_journal.py',
    'test_store_shared_values.py',
    'test_retrieval_integrity.py',
    'test_parity_retrieval.py',
    'test_access_policy_enforcement.py',
    'test_evidence_redaction.py',
    'test_mcp_validation_regressions.py',
    'test_g1_reliability_core.py',
    'test_surprise_gated_writes.py',
    'test_parity_learning.py',
    'test_mental_model_storage.py',
    'test_mental_model_change_refresh.py',
    'test_postgres_engine_live.py',
    'test_postgres_mental_model_refresh_live.py',
    'test_postgres_mental_model_guard.py',
    'test_postgres_working_memory.py',
    'test_postgres_prospective_memory.py',
    'test_postgres_security.py',
    'test_postgres_perf_lanes.py',
    'test_postgres_role_check.py',
    'test_session_aware_reads.py',
    'test_prospective_idempotency.py',
    'test_document_segment_identity.py',
    'test_local_source_transaction.py',
    'test_sqlite_source_transaction.py',
    'test_postgres_source_transaction_live.py',
    'test_projection_source_custody.py',
    'test_summary_source_custody.py',
    'test_summary_retrieval_custody.py',
    'test_retrieval_as_of.py',
    'test_relation_security_facts.py',
    'test_engine_perf_lanes.py',
    'test_canary_overlay.py',
    'test_sqlite_assertions.py',
    'test_sqlite_branch_merge.py',
    'test_sqlite_cache_projections.py',
    'test_sqlite_engine_core.py',
    'test_sqlite_observability.py',
    'test_sqlite_prospective_memory.py',
    'test_sqlite_retrieve.py',
    'test_sqlite_scans.py',
    'test_sqlite_working_memory.py',
]


def source_hashes():
    paths = set((ROOT / "src" / "mnemosyne").rglob("*.py"))
    paths.update((ROOT / "tests").rglob("*.py"))
    paths.update(ROOT / "tests" / name for name in TESTS)
    paths.update((ROOT / "config").glob("*.toml"))
    paths.update(ROOT / name for name in (
        "pyproject.toml", "uv.lock", "sql/schema.sql", "infra/postgres/roles.sql",
        ".github/workflows/ci.yml",
    ))
    paths.add(Path(__file__).resolve())
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main():
    for key in ("MNEMOSYNE_POSTGRES_DSN", "MNEMOSYNE_POSTGRES_APP_DSN",
                "MNEMOSYNE_POSTGRES_READONLY_DSN", "MNEMOSYNE_POSTGRES_ADMIN_DSN"):
        if not os.environ.get(key):
            raise SystemExit(f"Provide disposable database setting {key}")
    before = source_hashes()
    (OUT / "source-manifest.json").write_text(json.dumps(before, indent=2) + "\n")
    command = [sys.executable, "-m", "pytest", "-q",
               *(f"tests/{name}" for name in TESTS),
               f"--junitxml={OUT / 'regression.xml'}"]
    environment = dict(os.environ)
    environment.setdefault("MNEMOSYNE_POSTGRES_RLS_TEST_ROLE", "mnemosyne_consolidator")
    with (OUT / "regression.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, env=environment,
                                stdout=log, stderr=subprocess.STDOUT)
    with (OUT / "lint.log").open("w") as log:
        lint = subprocess.run([sys.executable, "-m", "ruff", "check", "."], cwd=ROOT,
                              stdout=log, stderr=subprocess.STDOUT)
    after = source_hashes()
    root = ET.parse(OUT / "regression.xml").getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = counts["tests"] - sum(counts[k] for k in ("failures", "errors", "skipped"))
    report = {
        "scope": "targeted regression tests; no benchmark or model inference",
        "modules": TESTS,
        "result": counts,
        "seconds": sum(float(s.attrib.get("time", 0)) for s in suites),
        "pytest_exit": result.returncode,
        "ruff_exit": lint.returncode,
        "source_files": len(before),
        "source_unchanged": before == after,
        "rls_test_role": environment["MNEMOSYNE_POSTGRES_RLS_TEST_ROLE"],
    }
    (OUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(bool(result.returncode or lint.returncode or before != after))


if __name__ == "__main__":
    raise SystemExit(main())
