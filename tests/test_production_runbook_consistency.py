from __future__ import annotations

import json
import re
from pathlib import Path

from mnemosyne.production_parity import PARITY_LANES_BY_COMMAND


REPO = Path(__file__).resolve().parents[1]
RUNBOOK_DIR = REPO / ".planning" / "runbooks"
PHASE_06_SUMMARY = (
    REPO
    / ".planning"
    / "phases"
    / "06-exact-blueprint-runtime-parity"
    / "06-09-SUMMARY.md"
)
INPUT_ARTIFACT_CHECKLIST = REPO / "infra" / "templates" / "production-input-artifacts.checklist.md"
OPERATOR_ENV_INVENTORY = REPO / "infra" / "templates" / "production-operator-env.inventory.md"
PROVIDER_MANIFEST_TEMPLATE = REPO / "infra" / "templates" / "provider-manifest.production.template.json"


def _markdown_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalized_row_name(value: str) -> str:
    return " ".join(value.lower().split())


def _checklist_row_artifacts() -> dict[str, tuple[Path, list[str]]]:
    rows: dict[str, tuple[Path, list[str]]] = {}
    for line in INPUT_ARTIFACT_CHECKLIST.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| B"):
            continue
        cells = _markdown_table_cells(line)
        if len(cells) < 3:
            continue
        lane = cells[0].split(maxsplit=1)[0]
        runbook_matches = re.findall(r"`([^`]+\.md)`", cells[1])
        assert len(runbook_matches) == 1, line
        artifact_names = [
            item
            for item in re.findall(r"`([^`]+)`", cells[2])
            if not item.startswith(".planning/")
        ]
        rows[lane] = (REPO / runbook_matches[0], artifact_names)
    return rows


def _provider_manifest_env_refs() -> set[str]:
    payload = json.loads(PROVIDER_MANIFEST_TEMPLATE.read_text(encoding="utf-8"))
    refs: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if set(value) == {"env"} and isinstance(value["env"], str):
                refs.add(value["env"])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return refs


def test_every_row_runbook_points_to_universal_preflight_capture_flow() -> None:
    row_runbooks = sorted(RUNBOOK_DIR.glob("row-*.md"))
    assert len(row_runbooks) == 10

    for path in row_runbooks:
        text = path.read_text(encoding="utf-8")
        assert "## Production Capture" in text, path
        assert "infra/PRODUCTION-EVIDENCE.md" in text, path
        assert (
            'infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" '
            '--preflight-only "$SOAK_MANIFEST" "$PRECHECK_OUTPUT_ROOT"' in text
        ), path
        assert "setup proof only" in text, path
        assert "does not flip this row to Done" in text, path
        assert (
            'infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" '
            '--fingerprint-record-output "$FINGERPRINT_RECORD" "$SOAK_MANIFEST" "$OUT_ROOT"'
            in text
        ), path
        assert "`FINGERPRINT_RECORD`" in text, path
        assert "`RUNTIME_ENV_FILE`" in text, path
        assert (
            "Use absolute external paths outside the repo for `SOAK_MANIFEST`, "
            "`PRECHECK_OUTPUT_ROOT`, `OUT_ROOT`, `FINGERPRINT_RECORD`, "
            "`RUNTIME_ENV_FILE`, and the "
            "`MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory." in text
        ), path
        assert "reviewers must run" in text, path
        assert "retained `preflight.json`" in text, path
        assert "`redaction-scan.json`" in text, path
        assert "`bundle-manifest.json`" in text, path
        assert "`source-soak-manifest.json`" in text, path
        assert "`operator-soak-manifest.json`" in text, path
        assert "`input-artifacts/`" in text, path
        assert "`tool-artifacts/`" in text, path
        assert "`summary.json.offline_verify`" in text, path
        assert "verifier `row_review.rows[]`" in text, path
        assert "source/operator command-profile agreement" in text, path
        assert (
            "offline custody verification with an external `--report-output` artifact must pass"
            in text
        ), path
        assert "`release_audit_ok=true`" in text, path
        assert "`redaction_scan_ok=true`" in text, path
        assert "`bundle-manifest.json`/fingerprint" in text, path
        assert "passing `production-evidence-verify`" in text, path
        assert (
            'release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" '
            "--require-production-validated --require-provider-forbid-local" in text
        ), path


def test_row_runbooks_list_checklist_input_artifacts() -> None:
    rows = _checklist_row_artifacts()

    assert set(rows) == {f"B{index}" for index in range(1, 11)}
    for lane, (runbook_path, artifact_names) in rows.items():
        text = runbook_path.read_text(encoding="utf-8")
        assert "## Required Production Input Artifacts" in text, runbook_path
        assert "MNEMOSYNE_PROD_EVIDENCE_DIR" in text, runbook_path
        for artifact_name in artifact_names:
            assert f"`{artifact_name}`" in text, (lane, runbook_path, artifact_name)


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
        assert "release-audit --evidence-manifest" in normalized, path

    ops_handoff = (REPO / ".planning" / "OPS-HANDOFF-AND-OWNERSHIP.md").read_text(
        encoding="utf-8",
    )
    assert (
        'capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" '
        '--preflight-only "$SOAK_MANIFEST" "$PRECHECK_OUTPUT_ROOT"' in ops_handoff
    )
    assert (
        'capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" '
        '--fingerprint-record-output "$FINGERPRINT_RECORD"' in ops_handoff
    )


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


def test_production_evidence_docs_point_to_generated_next_commands_script() -> None:
    for path in [
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "reports/next-commands.sh" in text, path
        assert "reports/row-action-plan" in text, path
        assert "reports/input-artifact-worklist" in text, path
        assert "reports/input-artifact-validation-commands.sh" in text, path
        assert "row-scoped" in text or "specific row" in text, path
        assert "placeholder" in text, path
        assert "expanded sequence" in text, path
        assert (
            "RUNTIME_ENV_FILE=/secure/path/to/mnemosyne-production-runtime.env"
            in text
        ), path


def test_operator_docs_use_runtime_env_variable_for_runtime_commands() -> None:
    docs = [
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / "infra" / "templates" / "production-input-artifacts.checklist.md",
        REPO / "infra" / "templates" / "production-render.env.example",
        REPO / ".planning" / "ENV-AND-SECRETS.md",
        REPO / ".planning" / "TIER-B-TO-100-AGENT-PROMPT.md",
        PHASE_06_SUMMARY,
        REPO / "docs" / "ROADMAP-TO-100.md",
    ]
    stale_command_patterns = [
        "--env-file /secure/path/to/mnemosyne-production-runtime.env",
        "--runtime-env-file /secure/path/to/mnemosyne-production-runtime.env",
        "capture-production-evidence.sh --env-file /secure/path/to/mnemosyne-production-runtime.env",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "RUNTIME_ENV_FILE" in text, path
        for pattern in stale_command_patterns:
            assert pattern not in text, (path, pattern)


def test_tier_b_master_prompt_uses_current_single_checkout_coordination() -> None:
    text = (REPO / ".planning" / "TIER-B-TO-100-AGENT-PROMPT.md").read_text(
        encoding="utf-8"
    )

    assert "current single-checkout continuation" in text
    assert "authorized clean commits and pushes to `main`" in text
    assert "Stage explicit paths only" in text
    assert "source-stability boundaries" in text
    assert "old multi-lane ownership table" in text
    assert "Only the CC-SYNC lane touches" not in text
    assert "Branch-per-lane" not in text
    assert "serialized integration order" not in text
    assert "CC-PG \u2192 CC-RT" not in text


def test_production_evidence_docs_require_independent_bundle_fingerprint() -> None:
    docs_with_command_snippets = [
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / ".planning" / "TIER-B-TO-100-AGENT-PROMPT.md",
        RUNBOOK_DIR / "README.md",
    ]
    docs_with_custody_language = [
        *docs_with_command_snippets,
        REPO / ".planning" / "ENV-AND-SECRETS.md",
        REPO / ".planning" / "runbooks" / "LOCAL-STAGING-DRY-RUN.md",
        REPO / ".planning" / "STRICT-BLUEPRINT-PARITY-AUDIT.md",
        REPO / ".planning" / "STATE.md",
        PHASE_06_SUMMARY,
        REPO / "docs" / "blueprint" / "cognitive-architecture" / "CODEX-HANDOFF.md",
        REPO / "docs" / "ROADMAP-TO-100.md",
        *sorted(RUNBOOK_DIR.glob("row-*.md")),
    ]
    self_referential_snippet = (
        'json.loads((pathlib.Path(sys.argv[1]) / "summary.json").read_text())'
        '["bundle_fingerprint"]'
    )

    for path in docs_with_command_snippets:
        text = path.read_text(encoding="utf-8")
        assert "FINGERPRINT_RECORD=" in text, path
        assert "mnemosyne-production-bundle-fingerprint.json" in text, path
        assert "VERIFY_REPORT=/secure/path/to/mnemosyne-production-evidence-verify.json" in text, path
        assert "EXPECTED_BUNDLE_FINGERPRINT=" not in text, path
        assert '["bundle_fingerprint"]' not in text, path
        assert '--fingerprint-record "$FINGERPRINT_RECORD"' in text, path
        assert '--report-output "$VERIFY_REPORT"' in text, path

    for path in docs_with_custody_language:
        text = path.read_text(encoding="utf-8")
        assert "out-of-band" in text, path
        if path in docs_with_command_snippets:
            assert "bundle under review" in text, path
        assert self_referential_snippet not in text, path
        assert "expected `summary.json` `bundle_fingerprint`" not in text, path
        assert "optional `--report-output`" not in text, path
        if path.parent == RUNBOOK_DIR and path.name.startswith("row-"):
            assert "`--fingerprint-record` pointing to" in text, path


def test_production_evidence_docs_explain_reviewer_handoff_record() -> None:
    for path in [
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / ".planning" / "STATE.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "reviewer_handoff" in text, path
        assert "suggested external verifier report path" in text, path
        assert "verifier report" in text, path


def test_phase_06_summary_uses_current_capture_and_offline_review_boundary() -> None:
    text = PHASE_06_SUMMARY.read_text(encoding="utf-8")

    assert (
        "infra/scripts/capture-production-evidence.sh /secure/path/to/production-soak-manifest.json"
        not in text
    )
    assert "infra/scripts/capture-production-evidence.sh \\" in text
    assert "/secure/path/to/mnemosyne-production-evidence" in text
    assert "--fingerprint-record" in text
    assert "--report-output" in text
    assert "bundle under review" in text
    assert "hosted LLM/calibration evidence" in text


def test_current_state_docs_do_not_reopen_closed_local_feature_gaps() -> None:
    matrix = (REPO / ".planning" / "BLUEPRINT-PARITY-MATRIX.md").read_text(
        encoding="utf-8"
    )
    handoff = (
        REPO / "docs" / "blueprint" / "cognitive-architecture" / "CODEX-HANDOFF.md"
    ).read_text(encoding="utf-8")

    assert "current parity blocker is the Tier-B operator-captured production evidence path" in matrix
    assert "The only two genuinely-missing **features** are" not in matrix
    assert "9621971" in handoff
    assert "CI run `28414377562` passed" in handoff
    assert "Latest source-bearing baseline before this handoff update, `03f2611`" not in handoff
    assert "Last recorded green source-bearing GitHub baseline before this handoff update" not in handoff


def test_operator_docs_stage_all_production_input_artifacts_before_readiness() -> None:
    docs = [
        REPO / "infra" / "README.md",
        REPO / "docs" / "ROADMAP-TO-100.md",
        REPO / "docs" / "blueprint" / "cognitive-architecture" / "CODEX-HANDOFF.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "production-input-artifacts.checklist.md" in text, path
        assert "provider-manifest.production.json" in text, path
        assert "manifest-referenced production input artifact" in text, path


def test_operator_docs_use_refreshable_tier_b_custody_packet() -> None:
    docs = [
        REPO / ".planning" / "ACTIVE-GOAL-OPERATING-CONTRACT.md",
        REPO / ".planning" / "TIER-B-TO-100-AGENT-PROMPT.md",
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / "infra" / "templates" / "production-input-artifacts.checklist.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "prepare-production-evidence-custody.py" in text, path
        assert "--refresh" in text, path
        assert "--refresh-report" not in text, path


def test_operator_docs_use_strict_render_env_file() -> None:
    docs = [
        REPO / ".planning" / "ENV-AND-SECRETS.md",
        REPO / ".planning" / "ROADMAP.md",
        REPO / ".planning" / "STATE.md",
        REPO / ".planning" / "STRICT-BLUEPRINT-PARITY-AUDIT.md",
        REPO / ".planning" / "TIER-B-TO-100-AGENT-PROMPT.md",
        REPO
        / ".planning"
        / "phases"
        / "06-exact-blueprint-runtime-parity"
        / "06-09-SUMMARY.md",
        REPO / "docs" / "blueprint" / "cognitive-architecture" / "CODEX-HANDOFF.md",
        REPO / "docs" / "ROADMAP-TO-100.md",
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / "infra" / "templates" / "production-input-artifacts.checklist.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "--env-file" in text, path
        assert "production-render.env" in text, path
        assert "set -a" not in text, path
        assert ". /secure/path" not in text, path
        assert "exported non-secret environment values" not in text, path
        assert "copy and fill outside the repo" not in text, path

    strict_loader_docs = [
        REPO / ".planning" / "ENV-AND-SECRETS.md",
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
    ]
    for path in strict_loader_docs:
        text = path.read_text(encoding="utf-8")
        assert "load-env.py" in text, path


def test_operator_docs_use_strict_capture_env_file() -> None:
    docs = [
        REPO / ".planning" / "TIER-B-TO-100-AGENT-PROMPT.md",
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / "infra" / "templates" / "production-input-artifacts.checklist.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        assert "capture-production-evidence.sh" in text, path
        assert "--env-file" in text, path
        assert '--env-file "$RUNTIME_ENV_FILE"' in normalized, path
        assert "RUNTIME_ENV_FILE" in text, path
        assert "Omit `--env-file`" not in text, path
        assert "trusted secret manager or supervisor" not in text, path
        assert "already-exported shell environment variables" not in text, path
        assert "shell-sourcing" in text or "shell-source" in text or path.name != "PRODUCTION-EVIDENCE.md"


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
        REPO / ".planning" / "TIER-B-TO-100-AGENT-PROMPT.md",
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
    assert "new absolute external custody path outside the" in rollback_doc
    assert "must not already exist" in rollback_doc
    assert "validates local real-service mechanics" in infra_readme
    assert "not production validation" in infra_readme


def test_provider_manifest_env_refs_are_documented_for_operators() -> None:
    env_doc = (REPO / ".planning" / "ENV-AND-SECRETS.md").read_text(encoding="utf-8")
    operator_inventory = OPERATOR_ENV_INVENTORY.read_text(encoding="utf-8")
    missing = sorted(
        ref
        for ref in _provider_manifest_env_refs()
        if ref not in env_doc or ref not in operator_inventory
    )

    assert missing == []


def test_provider_check_routes_are_documented_for_shared_manifest_rows() -> None:
    docs = {
        REPO / ".planning" / "OPS-HANDOFF-AND-OWNERSHIP.md": [
            "`provider-check` oidc/session_secret",
            "`provider-check` object_key_manager/residency_policy",
            "`policy-ops-check`",
        ],
        RUNBOOK_DIR / "row-01-production-postgres-retrieval.md": [
            "`provider-check` for `retrieval_backends`",
            "do not create a row-local provider manifest",
        ],
        RUNBOOK_DIR / "row-02-tenant-isolation-and-auth.md": [
            "`provider-check` for `oidc` and `session_secret`",
            "`policy-ops-check`",
            "do not create a row-local provider manifest",
        ],
        RUNBOOK_DIR / "row-04-consolidation-role-pipeline.md": [
            "`provider-check` for `candidate_extractor`, `summarizer`,",
            "`entity_resolver`, `lesson_distiller`, and `skill_inducer`",
            "do not create a row-local provider manifest",
        ],
        RUNBOOK_DIR / "row-06-multimodal-retrieval.md": [
            "`provider-check` for `media_extractor` and `media_embedding`",
            "do not create a row-local provider manifest",
        ],
        RUNBOOK_DIR / "row-07-privacy-and-erasure.md": [
            "`provider-check` for `object_key_manager` and `residency_policy`",
            "do not create a row-local provider manifest",
        ],
        RUNBOOK_DIR / "row-09-parametric-tier.md": [
            "`provider-check` for `parametric`",
            "do not create a row-local provider manifest",
        ],
        RUNBOOK_DIR / "row-10-live-parity-suite.md": [
            "`provider-check` for production adapter/provider coverage",
            "do not create a row-local provider manifest",
        ],
    }

    for path, snippets in docs.items():
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, (path, snippet)

    row7 = (RUNBOOK_DIR / "row-07-privacy-and-erasure.md").read_text(encoding="utf-8")
    assert "`policy-ops-check`" not in row7


def test_production_parity_command_routes_match_row_runbooks() -> None:
    expected_routes = {
        "calibration-tune": ["B9"],
        "consolidation-ops-check": ["B4"],
        "gate-suite-check": ["B4"],
        "hosted-llm-check": ["B9"],
        "ops-dashboard-check": ["B8"],
        "ops-report": ["B8"],
        "parametric-trainer-check": ["B9"],
        "projection-recompute-once": ["B4"],
        "worker-ops-check": ["B4"],
        "worker-run": ["B4"],
    }

    for command, lanes in expected_routes.items():
        assert PARITY_LANES_BY_COMMAND[command] == lanes, command


def test_operator_docs_bind_c2pa_executable_metadata_and_rollback_verify() -> None:
    docs = [
        REPO / "infra" / "PRODUCTION-EVIDENCE.md",
        REPO / "infra" / "README.md",
        REPO / ".planning" / "ENV-AND-SECRETS.md",
        RUNBOOK_DIR / "README.md",
    ]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "canonical" in text, path
        assert "symlink" in text, path
        assert "SHA-256" in text or "sha256" in text, path

    rollback = (REPO / ".planning" / "ROLLBACK.md").read_text(encoding="utf-8")
    assert "--preflight-only" in rollback
    assert "--fingerprint-record" in rollback
    assert "out-of-band rollback capture record" in rollback


def test_roadmap_tier_b_table_routes_rows_through_full_production_manifest() -> None:
    roadmap = (REPO / "docs" / "ROADMAP-TO-100.md").read_text(encoding="utf-8")
    strict_audit = (REPO / ".planning" / "STRICT-BLUEPRINT-PARITY-AUDIT.md").read_text(
        encoding="utf-8",
    )
    assert "| # | Parity row | Real infra to stand up | Canonical capture |" in roadmap
    assert "Capture command" not in roadmap
    assert (
        roadmap.count(
            "Full 28-command production manifest via `infra/PRODUCTION-EVIDENCE.md`"
        )
        == 10
    )

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
        path.read_text(encoding="utf-8")
        .splitlines()[0]
        .removeprefix("# ")
        .split(" - ", 1)[1]
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
