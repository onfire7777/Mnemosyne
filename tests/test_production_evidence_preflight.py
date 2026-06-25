from __future__ import annotations

import json
import subprocess
from pathlib import Path

from mnemosyne.cli import PRODUCTION_RELEASE_REQUIRED_COMMANDS


REPO = Path(__file__).resolve().parents[1]


def _minimal_production_manifest(path: Path) -> None:
    manifest = {
        "kind": "mnemosyne-production-soak-manifest",
        "validation_scope": {
            "production_validated": True,
            "target_environment": "production",
            "operator_asserted": True,
        },
        "operator": {
            "name": "test operator",
            "user": "operator@example.invalid",
        },
        "checks": [
            {
                "name": command,
                "command": command,
                "args": [],
            }
            for command in PRODUCTION_RELEASE_REQUIRED_COMMANDS
        ],
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_capture_production_evidence_preflight_only_stops_before_soak(tmp_path: Path) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    stdout = json.loads(proc.stdout)
    preflight = json.loads((out_root / "preflight.json").read_text(encoding="utf-8"))
    copied_manifest = json.loads((out_root / "operator-soak-manifest.json").read_text(encoding="utf-8"))

    assert stdout["ok"] is True
    assert stdout["preflight_only"] is True
    assert preflight == stdout
    assert copied_manifest["validation_scope"]["target_environment"] == "production"
    assert sorted(preflight["provided_commands"]) == sorted(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    assert not (out_root / "evidence").exists()
    assert not (out_root / "deployment-soak.stdout.json").exists()
    assert not (out_root / "release-audit.json").exists()


def test_capture_production_evidence_preflight_rejects_unrendered_template(tmp_path: Path) -> None:
    out_root = tmp_path / "capture"
    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(REPO / "infra" / "templates" / "production-soak-manifest.template.json"),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "unresolved production placeholders" in proc.stderr
    assert not out_root.exists()
