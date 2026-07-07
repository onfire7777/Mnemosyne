#!/usr/bin/env python3
"""External WORM copy adapter for the audit hash chain.

Reads the verified audit-chain JSON document on stdin, writes it to an S3
Object-Lock bucket under COMPLIANCE retention, then reads the retention back and
prints ops-report ``worm_copy`` evidence JSON on stdout:

    {"enabled": true, "external": true, "retained": true, "bucket": ..., "key": ...,
     "mode": "COMPLIANCE", "retain_until": ..., "object_sha256": ...}

The object cannot be overwritten or deleted before ``retain_until`` even by the
writing identity, so it is a genuine out-of-band immutable copy the app role
cannot tamper with. Wire in via
``MNEMOSYNE_AUDIT_WORM_COMMAND="python3 infra/seaweedfs/audit-worm-adapter.py"``.

SigV4 is hand-rolled on the stdlib so no boto3 is required. Environment:
  MNEMOSYNE_AUDIT_WORM_ENDPOINT     S3 endpoint (default http://seaweedfs:8333)
  MNEMOSYNE_AUDIT_WORM_BUCKET       object-lock bucket (default mnemosyne-audit-worm)
  MNEMOSYNE_AUDIT_WORM_ACCESS_KEY   S3 access key (required)
  MNEMOSYNE_AUDIT_WORM_SECRET_KEY   S3 secret key (required)
  MNEMOSYNE_AUDIT_WORM_REGION       region (default us-east-1)
  MNEMOSYNE_AUDIT_WORM_MODE         COMPLIANCE|GOVERNANCE (default COMPLIANCE)
  MNEMOSYNE_AUDIT_WORM_RETAIN_DAYS  retention window in days (default 3650)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ALGO = "AWS4-HMAC-SHA256"


def _fail(message: str) -> "None":
    sys.stderr.write(f"audit-worm-adapter: {message}\n")
    raise SystemExit(1)


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k = _sign(("AWS4" + secret).encode("utf-8"), datestamp)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")


def _request(
    method: str,
    endpoint: str,
    bucket: str,
    key: str,
    query: str,
    body: bytes,
    ak: str,
    sk: str,
    region: str,
    extra_headers: "dict[str, str] | None" = None,
) -> tuple[int, bytes, dict[str, str]]:
    # endpoint like http://host:port
    scheme, _, host = endpoint.partition("://")
    host = host.rstrip("/")
    path = "/" + bucket + ("/" + key if key else "")
    now = _dt.datetime.now(_dt.timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()

    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amzdate,
    }
    for k2, v2 in (extra_headers or {}).items():
        headers[k2.lower()] = v2

    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{h}:{headers[h]}\n" for h in sorted(headers))
    canonical_request = (
        f"{method}\n{path}\n{query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )
    scope = f"{datestamp}/{region}/s3/aws4_request"
    sts = f"{ALGO}\n{amzdate}\n{scope}\n" + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    signature = hmac.new(_signing_key(sk, datestamp, region, "s3"), sts.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = f"{ALGO} Credential={ak}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"

    url = f"{scheme}://{host}{path}" + (f"?{query}" if query else "")
    req_headers = {k3: headers[k3] for k3 in headers if k3 != "host"}
    req_headers["Authorization"] = authorization
    request = urllib.request.Request(url, data=body if method in ("PUT", "POST") else None, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})


def main() -> None:
    endpoint = os.environ.get("MNEMOSYNE_AUDIT_WORM_ENDPOINT", "http://seaweedfs:8333")
    bucket = os.environ.get("MNEMOSYNE_AUDIT_WORM_BUCKET", "mnemosyne-audit-worm")
    ak = os.environ.get("MNEMOSYNE_AUDIT_WORM_ACCESS_KEY")
    sk = os.environ.get("MNEMOSYNE_AUDIT_WORM_SECRET_KEY")
    region = os.environ.get("MNEMOSYNE_AUDIT_WORM_REGION", "us-east-1")
    mode = os.environ.get("MNEMOSYNE_AUDIT_WORM_MODE", "COMPLIANCE")
    retain_days = int(os.environ.get("MNEMOSYNE_AUDIT_WORM_RETAIN_DAYS", "3650"))
    if not ak or not sk:
        _fail("MNEMOSYNE_AUDIT_WORM_ACCESS_KEY/SECRET_KEY are required")

    body = sys.stdin.buffer.read()
    if not body:
        _fail("no chain document on stdin")
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        _fail(f"chain document is not JSON: {exc}")
    head = str(document.get("head_link_sha256") or "")[:16]
    tenant = str(document.get("tenant_id") or "unknown")
    object_sha256 = hashlib.sha256(body).hexdigest()
    key = f"chain/{tenant}/{head or object_sha256[:16]}.json"

    # Ensure the bucket exists WITH object lock enabled (idempotent).
    status, resp_body, _ = _request(
        "PUT", endpoint, bucket, "", "", b"", ak, sk, region,
        extra_headers={"x-amz-bucket-object-lock-enabled": "true"},
    )
    if status not in (200, 409) and b"BucketAlreadyOwnedByYou" not in resp_body and b"BucketAlreadyExists" not in resp_body:
        _fail(f"create object-lock bucket failed: HTTP {status}: {resp_body.decode('utf-8', 'replace')[:200]}")

    retain_until = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=retain_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    status, resp_body, _ = _request(
        "PUT", endpoint, bucket, key, "", body, ak, sk, region,
        extra_headers={
            "x-amz-object-lock-mode": mode,
            "x-amz-object-lock-retain-until-date": retain_until,
            "content-type": "application/json",
        },
    )
    if status not in (200, 201):
        _fail(f"object-lock PUT failed: HTTP {status}: {resp_body.decode('utf-8', 'replace')[:200]}")

    # Read the retention back to PROVE the object is under a lock (not inferred).
    # The subresource must be signed as an empty-valued query param ("retention=").
    status, resp_body, _ = _request("GET", endpoint, bucket, key, "retention=", b"", ak, sk, region)
    proven_mode = None
    proven_until = None
    if status == 200 and resp_body:
        try:
            root = ET.fromstring(resp_body)
            for el in root.iter():
                tag = el.tag.rsplit("}", 1)[-1]
                if tag == "Mode":
                    proven_mode = (el.text or "").strip()
                elif tag == "RetainUntilDate":
                    proven_until = (el.text or "").strip()
        except ET.ParseError:
            pass

    retained = bool(proven_mode) and bool(proven_until)
    print(json.dumps({
        "enabled": True,
        "external": True,
        "retained": retained,
        "bucket": bucket,
        "key": key,
        "mode": proven_mode or mode,
        "retain_until": proven_until or retain_until,
        "object_sha256": "sha256:" + object_sha256,
        "endpoint": endpoint,
    }))


if __name__ == "__main__":
    main()
