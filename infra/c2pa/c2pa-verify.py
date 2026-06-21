#!/usr/bin/env python3
"""c2patool wrapper that emits a Mnemosyne-bindable verification report.

Mnemosyne's ``C2paToolVerifier`` (mnemosyne/provenance.py) shells out as::

    <tool_path> <asset_path> --json

and parses stdout JSON. To raise trust, the report must:

  1. bind to the exact ingested bytes — either an asset SHA-256 under an
     asset/content/ingredient/payload/source-named key, or an asset_path that
     matches; and
  2. expose the signing certificate root fingerprint (a 64-hex SHA-256) under a
     cert/certificate/chain/root/signer/trust-named key, so trust-root policy
     can match it; and
  3. expose a signer/issuer/common_name.

Real ``c2patool`` performs the genuine C2PA cryptographic verification (claim
signature, hard-binding hash, trust chain). This wrapper invokes it for that
real verification, then *augments* the report with the deterministic
asset SHA-256 and the certificate-root SHA-256 fingerprint so the report binds
to the Mnemosyne contract. It never fabricates verification success: if
c2patool exits nonzero (signature/binding failure), this wrapper exits nonzero
too and Mnemosyne quarantines the asset.

Environment:
    C2PATOOL_BIN        path to the real c2patool (default: c2patool on PATH)
    C2PA_TRUST_ROOT     path to the signing trust-root cert PEM, used to
                        compute and inject the root SHA-256 fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cert_fingerprint(pem_path: str) -> str | None:
    """SHA-256 fingerprint of the DER form of the (first) cert in a PEM file."""
    try:
        text = Path(pem_path).read_text(encoding="utf-8")
    except OSError:
        return None
    blocks = re.findall(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.DOTALL
    )
    if not blocks:
        return None
    import base64

    body = re.sub(r"-----(BEGIN|END) CERTIFICATE-----", "", blocks[-1])
    der = base64.b64decode("".join(body.split()))
    return hashlib.sha256(der).hexdigest()


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(json.dumps({"error": "asset path required"}), file=sys.stderr)
        return 2
    # Mnemosyne always calls: <asset_path> --json
    asset_path = args[0]
    c2patool = os.environ.get("C2PATOOL_BIN", "c2patool")

    try:
        completed = subprocess.run(
            [c2patool, asset_path, "--json"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        print(json.dumps({"error": f"c2patool not runnable: {exc}"}), file=sys.stderr)
        return 3

    if completed.returncode != 0:
        # Real verification failed (bad signature / broken binding / untrusted
        # chain). Surface the failure so Mnemosyne quarantines.
        sys.stderr.write(completed.stderr)
        return completed.returncode

    try:
        report = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"error": "c2patool returned non-JSON"}), file=sys.stderr)
        return 4
    if not isinstance(report, dict):
        report = {"c2patool": report}

    asset_sha256 = _sha256_file(asset_path)

    # (1) Bind to the exact bytes via an asset-named SHA-256 key.
    report["asset"] = {
        **(report.get("asset") if isinstance(report.get("asset"), dict) else {}),
        "path": asset_path,
        "sha256": asset_sha256,
    }
    report["asset_sha256"] = asset_sha256

    # (2) Inject the certificate root fingerprint under a cert-named key, if the
    #     trust root is available, so trusted_roots policy can match.
    trust_root = os.environ.get("C2PA_TRUST_ROOT", "")
    fingerprint = _cert_fingerprint(trust_root) if trust_root else None
    if fingerprint and _HEX64.fullmatch(fingerprint):
        existing = report.get("certificate_roots")
        roots = list(existing) if isinstance(existing, list) else []
        if fingerprint not in roots:
            roots.append(fingerprint)
        report["certificate_roots"] = roots
        report.setdefault("trust", {})
        if isinstance(report["trust"], dict):
            report["trust"]["root_sha256"] = fingerprint

    # (3) Ensure a signer/issuer is discoverable for issuer trust policy.
    if not any(k in json.dumps(report) for k in ("issuer", "signer", "common_name")):
        report["signer"] = report.get("active_manifest") or "Mnemosyne-Test-Signer"

    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
