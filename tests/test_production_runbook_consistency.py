from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUNBOOK_DIR = REPO / ".planning" / "runbooks"


def test_every_row_runbook_points_to_universal_preflight_capture_flow() -> None:
    row_runbooks = sorted(RUNBOOK_DIR.glob("row-*.md"))
    assert len(row_runbooks) == 10

    for path in row_runbooks:
        text = path.read_text(encoding="utf-8")
        assert "## Production Capture" in text, path
        assert "infra/PRODUCTION-EVIDENCE.md" in text, path
        assert "infra/scripts/capture-production-evidence.sh --preflight-only" in text, path
        assert "setup proof only" in text, path
        assert "does not flip this row to Done" in text, path
        assert "infra/scripts/capture-production-evidence.sh" in text, path
        assert "release-audit --require-production-validated --require-provider-forbid-local" in text, path


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
        assert (
            "release-audit --require-production-validated --require-provider-forbid-local"
            in normalized
        ), path
