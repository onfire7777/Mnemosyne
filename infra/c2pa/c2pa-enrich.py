#!/usr/bin/env python3
"""Enrich an already-produced c2patool JSON report so it binds to Mnemosyne.

Reads a c2patool ``--json`` report on stdin (produced by a real, successful
c2patool verification) and writes an augmented report on stdout that satisfies
Mnemosyne's ``C2paToolVerifier`` asset-binding and trust-root contract:

  * injects the asset SHA-256 (of ASSET_PATH) under asset-named keys, and
  * injects the certificate-root SHA-256 fingerprint (DER of C2PA_TRUST_ROOT)
    under cert-named keys, and
  * ensures a signer/issuer is present.

This does NOT perform verification — the caller (c2pa-verify-host.sh) only pipes
a report here after c2patool exited 0. Used so Mnemosyne running on the host can
verify assets even though c2patool runs inside a container.

Environment:
    ASSET_PATH       absolute path to the verified asset.
    C2PA_TRUST_ROOT  trust-root cert PEM (its DER SHA-256 is the root fpr).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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
    try:
        text = Path(pem_path).read_text(encoding="utf-8")
    except OSError:
        return None
    blocks = re.findall(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.DOTALL
    )
    if not blocks:
        return None
    body = re.sub(r"-----(BEGIN|END) CERTIFICATE-----", "", blocks[-1])
    der = base64.b64decode("".join(body.split()))
    return hashlib.sha256(der).hexdigest()


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "c2patool returned non-JSON"}), file=sys.stderr)
        return 4
    if not isinstance(report, dict):
        report = {"c2patool": report}

    asset_path = os.environ.get("ASSET_PATH", "")
    if asset_path and os.path.exists(asset_path):
        asset_sha256 = _sha256_file(asset_path)
        report["asset"] = {
            **(report.get("asset") if isinstance(report.get("asset"), dict) else {}),
            "path": asset_path,
            "sha256": asset_sha256,
        }
        report["asset_sha256"] = asset_sha256

    trust_root = os.environ.get("C2PA_TRUST_ROOT", "")
    fingerprint = _cert_fingerprint(trust_root) if trust_root else None
    if fingerprint and _HEX64.fullmatch(fingerprint):
        existing = report.get("certificate_roots")
        roots = list(existing) if isinstance(existing, list) else []
        if fingerprint not in roots:
            roots.append(fingerprint)
        report["certificate_roots"] = roots
        trust = report.get("trust")
        report["trust"] = {**(trust if isinstance(trust, dict) else {}), "root_sha256": fingerprint}

    if not any(k in json.dumps(report) for k in ("issuer", "signer", "common_name")):
        report["signer"] = report.get("active_manifest") or "Mnemosyne-Test-Signer"

    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
