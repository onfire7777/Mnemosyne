from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUNBOOK_DIR = REPO / ".planning" / "runbooks"


def _markdown_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalized_row_name(value: str) -> str:
    return " ".join(value.lower().split())


def test_every_row_runbook_points_to_universal_preflight_capture_flow() -> None:
    row_runbooks = sorted(RUNBOOK_DIR.glob("row-*.md"))
    assert len(row_runbooks) == 10

    for path in row_runbooks:
        text = path.read_text(encoding="utf-8")
        assert "## Production Capture" in text, path
        assert "infra/PRODUCTION-EVIDENCE.md" in text, path
        assert (
            'infra/scripts/capture-production-evidence.sh --preflight-only "$SOAK_MANIFEST" '
            '"$PREFLIGHT_OUT_ROOT"'
            in text
        ), path
        assert "setup proof only" in text, path
        assert "does not flip this row to Done" in text, path
        assert (
            'infra/scripts/capture-production-evidence.sh "$SOAK_MANIFEST" "$OUT_ROOT"'
            in text
        ), path
        assert (
            "Use absolute external paths outside the repo for `SOAK_MANIFEST`, "
            "`PREFLIGHT_OUT_ROOT`, `OUT_ROOT`, and the "
            "`MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory."
            in text
        ), path
        assert "reviewers must run" in text, path
        assert "retained `source-soak-manifest.json` custody" in text, path
        assert "source/operator command-profile agreement" in text, path
        assert "offline custody verification must pass before this row can flip Done" in text, path
        assert "`release_audit_ok=true`" in text, path
        assert "`redaction_scan_ok=true`" in text, path
        assert "`bundle-manifest.json`/fingerprint" in text, path
        assert "passing `production-evidence-verify`" in text, path
        assert (
            'release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" '
            "--require-production-validated --require-provider-forbid-local"
            in text
        ), path


def test_runbook_index_and_ops_handoff_document_preflight_scope() -> None:
    docs = [
        RUNBOOK_DIR / "README.md",
        REPO / ".planning" / "OPS-HANDOFF-AND-OWNERSHIP.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        assert "--preflight-only" in text, path
        assert "setup proof only" in text, path
        assert "capture-production-evidence.sh" in text, path
        assert "absolute external" in text, path
        assert "outside the repository" in text, path
        assert (
            "release-audit --evidence-manifest"
            in normalized
        ), path


def test_production_evidence_docs_require_manifest_bound_release_audit() -> None:
    production_evidence = (REPO / "infra" / "PRODUCTION-EVIDENCE.md").read_text(
        encoding="utf-8",
    )
    infra_readme = (REPO / "infra" / "README.md").read_text(encoding="utf-8")
    runbook_index = (RUNBOOK_DIR / "README.md").read_text(encoding="utf-8")
    ops_handoff = (REPO / ".planning" / "OPS-HANDOFF-AND-OWNERSHIP.md").read_text(
        encoding="utf-8",
    )

    assert "release-audit --evidence-manifest" in production_evidence
    assert "source-soak-manifest.json" in production_evidence
    assert "source/operator command-profile agreement" in production_evidence
    assert "source-soak-manifest.json" in infra_readme
    assert "source/operator command-profile agreement" in infra_readme
    assert "source-soak-manifest.json" in runbook_index
    assert "source/operator command-profile" in runbook_index
    assert "release-audit --evidence-manifest" in ops_handoff


def test_operator_docs_do_not_use_unbound_production_release_audit() -> None:
    phase_dir = REPO / ".planning" / "phases" / "06-exact-blueprint-runtime-parity"
    docs = [
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / "docs" / "ROADMAP-TO-100.md",
        REPO / "docs" / "STATE-OF-COMPLETION.md",
        REPO / ".planning" / "OPS-HANDOFF-AND-OWNERSHIP.md",
        REPO / ".planning" / "PARTIAL-ITEMS-KEY-SCHEMA.md",
        REPO / ".planning" / "ROADMAP.md",
        REPO / ".planning" / "ROLLBACK.md",
        REPO / ".planning" / "STATE.md",
        RUNBOOK_DIR / "README.md",
        RUNBOOK_DIR / "LOCAL-STAGING-DRY-RUN.md",
        *sorted(RUNBOOK_DIR.glob("row-*.md")),
        *sorted(phase_dir.glob("06-*.md")),
    ]
    unbound_pattern = re.compile(
        r"release-audit\s+(?![^`\\n]*--evidence-manifest)"
        r"(?=[^`\\n]*--require-production-validated)"
        r"(?=[^`\\n]*--require-provider-forbid-local)",
    )

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert not unbound_pattern.search(text), path
        assert '--evidence-manifest "/evidence/manifest.json"' not in text, path


def test_production_evidence_input_dir_is_not_capture_output() -> None:
    env_doc = (REPO / ".planning" / "ENV-AND-SECRETS.md").read_text(encoding="utf-8")
    rollback_doc = (REPO / ".planning" / "ROLLBACK.md").read_text(encoding="utf-8")
    infra_readme = (REPO / "infra" / "README.md").read_text(encoding="utf-8")

    assert "Prepared absolute external production input-artifact directory" in env_doc
    assert "capture output is passed separately as `OUT_ROOT`" in env_doc
    assert "absolute external directory" in rollback_doc
    assert "must not point inside the" in rollback_doc
    assert "new or empty absolute external custody path outside the" in rollback_doc
    assert "validates local real-service mechanics" in infra_readme
    assert "not production validation" in infra_readme


def test_roadmap_tier_b_table_routes_rows_through_full_production_manifest() -> None:
    roadmap = (REPO / "docs" / "ROADMAP-TO-100.md").read_text(encoding="utf-8")
    strict_audit = (REPO / ".planning" / "STRICT-BLUEPRINT-PARITY-AUDIT.md").read_text(
        encoding="utf-8",
    )
    assert "| # | Parity row | Real infra to stand up | Canonical capture |" in roadmap
    assert "Capture command" not in roadmap
    assert roadmap.count("Full 28-command production manifest via `infra/PRODUCTION-EVIDENCE.md`") == 10

    strict_rows = [
        _markdown_table_cells(line)[0]
        for line in strict_audit.splitlines()
        if line.startswith("| ")
        and " | Partial | " in line
        and len(_markdown_table_cells(line)) >= 3
    ]
    roadmap_rows = [
        _markdown_table_cells(line)[1]
        for line in roadmap.splitlines()
        if line.startswith("| B")
        and len(_markdown_table_cells(line)) >= 4
        and _markdown_table_cells(line)[0][1:].isdigit()
    ]
    runbook_rows = [
        path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ").split(" - ", 1)[1]
        for path in sorted(RUNBOOK_DIR.glob("row-*.md"))
    ]

    assert len(strict_rows) == 10
    assert [_normalized_row_name(row) for row in roadmap_rows] == [
        _normalized_row_name(row) for row in strict_rows
    ]
    assert [_normalized_row_name(row) for row in runbook_rows] == [
        _normalized_row_name(row) for row in strict_rows
    ]
    assert "B6 / row 06" in roadmap
    assert "B9 / row 09" in roadmap
