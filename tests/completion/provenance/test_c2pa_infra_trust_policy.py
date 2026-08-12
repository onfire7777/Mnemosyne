"""P0 regression: the infra C2PA trust path must trust the positive asset.

Wave 1 reproduced an infra defect where the *emitted* trust policy
(``infra/scripts/setup-c2pa.sh`` → ``infra/c2pa/out/trust-policy.json``) caused a
correctly signed, correctly bound asset to be QUARANTINED instead of trusted.

Two compounding causes, both in the EMITTED policy (the production
``mnemosyne.provenance`` code is correct and unchanged):

1. ``ProvenanceTrustRule.from_dict`` defaults a missing ``require_trusted_issuer``
   to ``True`` (provenance.py ~line 113), and ``ProvenanceTrustPolicy.for_context``
   OR-merges rule flags into the scoped policy (~lines 218-219). The
   ``camera-binary-tenant-a`` rule omitted ``require_trusted_issuer``, so issuer
   trust was silently forced ON for that scope even though the top-level policy
   set it ``false``.
2. ``C2paToolVerifier`` selects the signer via ``provenance._find_first`` over
   ``{issuer, signer, claim_generator, claimGenerator, common_name, commonName}``
   in *insertion order* (~line 334). In a real c2patool ``--json`` report the
   active manifest's ``claim_generator`` is encountered first, so the signer
   string actually evaluated is the claim_generator
   (``"Mnemosyne-Test-Signer/1.0 c2patool/<ver>"``) — NOT the leaf CN
   ``"mnemosyne-test-signer"`` the old policy listed in ``trusted_issuers``.

The fix (in ``setup-c2pa.sh``) sets the rule's ``require_trusted_issuer`` to
``false`` explicitly (root-only trust for that scope, defeating the default +
OR-merge) AND populates ``trusted_issuers`` with the real surfaced signer string.

This test drives the *real* ``mnemosyne.provenance.C2paToolVerifier`` and
``ProvenanceTrustPolicy`` (no mocks of the production decision code) through a
stub ``c2patool`` that emits a realistic enriched c2patool report — the exact
shape ``infra/c2pa/c2pa-enrich.py`` produces. It needs neither Docker nor the
real c2patool binary, so it is a permanent, hermetic regression for the fix.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from mnemosyne import provenance as prov

_HERE = Path(__file__).resolve().parent
_REPORT_TEMPLATE = _HERE / "c2patool_report_camera_tenant_a.json"

# The signer string a real c2patool report surfaces (the active manifest's
# claim_generator), encountered by _find_first before signature_info issuer/CN.
SURFACED_SIGNER = "Mnemosyne-Test-Signer/1.0 c2patool/0.9.12"
ROOT_FPR = "a" * 64  # stand-in DER SHA-256 of the test trust root
PAYLOAD = b"mnemosyne-c2pa-test-asset-bytes"


def _emitted_policy_dict(*, fixed: bool) -> dict:
    """Reproduce the trust-policy.json that setup-c2pa.sh emits.

    ``fixed=False`` is the pre-fix policy that Wave 1 reproduced as broken.
    ``fixed=True`` is the policy the patched setup-c2pa.sh now emits.
    """
    if fixed:
        return {
            "trusted_issuers": [SURFACED_SIGNER, "mnemosyne-test-signer", "Mnemosyne-Test-Signer"],
            "trusted_roots": [ROOT_FPR],
            "require_trusted_issuer": False,
            "require_trusted_root": False,
            "rules": [
                {
                    "name": "camera-binary-tenant-a",
                    "scope": {"tenant_id": "tenant-a", "source_type": "camera", "modality": "binary"},
                    "trusted_issuers": [SURFACED_SIGNER],
                    "trusted_roots": [ROOT_FPR],
                    "require_trusted_issuer": False,
                    "require_trusted_root": True,
                }
            ],
        }
    return {
        "trusted_issuers": ["mnemosyne-test-signer", "Mnemosyne-Test-Signer"],
        "trusted_roots": [ROOT_FPR],
        "require_trusted_issuer": False,
        "require_trusted_root": False,
        "rules": [
            {
                "name": "camera-binary-tenant-a",
                "scope": {"tenant_id": "tenant-a", "source_type": "camera", "modality": "binary"},
                "trusted_roots": [ROOT_FPR],
                "require_trusted_root": True,
            }
        ],
    }


def _write_stub_tool(tmp_path: Path, report: dict) -> str:
    """A stub c2patool: prints the enriched report JSON to stdout, exits 0."""
    payload = tmp_path / "report.py"
    payload.write_text(
        "import json, sys\nprint(json.dumps(%r))\n" % report,
        encoding="utf-8",
    )
    if os.name == "nt":
        tool = tmp_path / "c2patool-stub.cmd"
        tool.write_text(
            '@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, payload),
            encoding="utf-8",
        )
    else:
        tool = tmp_path / "c2patool-stub.sh"
        tool.write_text(
            "#!/usr/bin/env bash\nexec %s %s\n" % (sys.executable, payload),
            encoding="utf-8",
        )
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(tool)


def _build_report(asset_path: str, sha: str, *, root_fpr: str = ROOT_FPR) -> dict:
    raw = _REPORT_TEMPLATE.read_text(encoding="utf-8")
    raw = (
        raw.replace(
            "__ASSET_PATH__",
            json.dumps(asset_path, ensure_ascii=False)[1:-1],
        )
        .replace("__ASSET_SHA256__", sha)
        .replace("__ROOT_FPR__", root_fpr)
    )
    return json.loads(raw)


def _run(tmp_path: Path, *, fixed: bool, root_fpr: str = ROOT_FPR, payload: bytes = PAYLOAD):
    asset = tmp_path / "asset.signed.jpg"
    asset.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    report = _build_report(str(asset), sha, root_fpr=root_fpr)
    tool = _write_stub_tool(tmp_path, report)
    policy = prov.ProvenanceTrustPolicy.from_dict(_emitted_policy_dict(fixed=fixed))
    verifier = prov.C2paToolVerifier(tool_path=tool, trust_policy=policy)
    manifest = {
        "asset_path": str(asset),
        "sha256": sha,
        "_ingest_context": {
            "tenant_id": "tenant-a",
            "source_type": "camera",
            "modality": "binary",
        },
    }
    return verifier.verify(payload, manifest)


def test_surfaced_signer_is_claim_generator():
    """_find_first surfaces the claim_generator, not the leaf CN."""
    report = _build_report("/tmp/x.jpg", "0" * 64)
    signer = prov._find_first(
        report,
        {"issuer", "signer", "claim_generator", "claimGenerator", "common_name", "commonName"},
    )
    assert signer == SURFACED_SIGNER


def test_old_policy_quarantines_positive_path(tmp_path):
    """Regression witness: the PRE-FIX emitted policy quarantines the good asset."""
    decision = _run(tmp_path, fixed=False)
    # Valid manifest, bound to the bytes, yet rejected by the (buggy) trust policy.
    assert decision.valid is True
    assert decision.trusted is False
    assert decision.quarantine is True
    assert "trust policy" in decision.reason


def test_fixed_policy_trusts_positive_path(tmp_path):
    """The FIXED emitted policy returns valid=True, trusted=True, quarantine=False."""
    decision = _run(tmp_path, fixed=True)
    assert decision.valid is True
    assert decision.trusted is True
    assert decision.quarantine is False
    assert decision.reason == "c2pa manifest verified"


def test_fixed_policy_quarantines_tampered_payload(tmp_path):
    """A byte-tampered payload no longer matches the report binding → quarantine.

    Models the validate-c2pa.sh negative test: the c2patool report binds to the
    ORIGINAL signed asset's SHA-256, but Mnemosyne is handed tampered bytes. The
    asset-binding check (provenance._verify_report_asset_binding) then fails and
    quarantines — exactly as the real flow does (the real c2patool would also
    exit nonzero on the broken hard binding).
    """
    asset = tmp_path / "asset.signed.jpg"
    asset.write_bytes(PAYLOAD)
    original_sha = hashlib.sha256(PAYLOAD).hexdigest()
    # Report binds to the original asset hash (what setup-c2pa.sh produced).
    report = _build_report(str(asset), original_sha)
    tool = _write_stub_tool(tmp_path, report)
    policy = prov.ProvenanceTrustPolicy.from_dict(_emitted_policy_dict(fixed=True))
    verifier = prov.C2paToolVerifier(tool_path=tool, trust_policy=policy)
    manifest = {
        "asset_path": str(asset),
        "sha256": original_sha,
        "_ingest_context": {"tenant_id": "tenant-a", "source_type": "camera", "modality": "binary"},
    }
    tampered = bytearray(PAYLOAD)
    tampered[-1] ^= 0xFF
    decision = verifier.verify(bytes(tampered), manifest)
    assert decision.valid is False
    assert decision.quarantine is True
    assert decision.trusted is False
    assert "asset" in decision.reason  # "c2pa report asset hash mismatch"


def test_fixed_policy_quarantines_untrusted_root(tmp_path):
    """Root trust is still enforced: an unknown cert root quarantines."""
    decision = _run(tmp_path, fixed=True, root_fpr="c" * 64)
    assert decision.valid is True
    assert decision.trusted is False
    assert decision.quarantine is True
    assert "certificate root" in decision.reason


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    sys.exit(pytest.main([__file__, "-v"]))
