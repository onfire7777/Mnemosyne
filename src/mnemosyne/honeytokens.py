"""Leak-canary honeytokens (privacy policy §10; spec §4.0).

Deterministic per (sensitivity class, tenant) marker strings seeded into
memories; their appearance beyond their boundary (another tenant's journal,
a non-embeddable cache, provider/front-end logs, benchmark artifacts) is a
leak alarm. Stdlib only.
"""
from __future__ import annotations

import hashlib
import re

HONEYTOKEN_PREFIX = "HTKN"
_TOKEN_RE = re.compile(r"HTKN-(S[0-4])-([0-9a-f]{16})")


def _tenant_hash(cls: str, tenant_id: str) -> str:
    return hashlib.sha256(f"{cls}:{tenant_id}".encode()).hexdigest()[:16]


def honeytoken(cls: str, tenant_id: str) -> str:
    if not re.fullmatch(r"S[0-4]", cls):
        raise ValueError(f"unknown sensitivity class: {cls}")
    return f"{HONEYTOKEN_PREFIX}-{cls}-{_tenant_hash(cls, tenant_id)}"


def scan_for_foreign_honeytokens(text: str, *, own_tenant_id: str) -> list[str]:
    """Return honeytoken markers in ``text`` foreign to ``own_tenant_id``.

    A marker counts as *own* only when its hash matches ``own_tenant_id``
    under the class carried in the marker's own prefix. Because
    ``_tenant_hash`` mixes the class into the hash, this flags both other
    tenants' tokens (any class) and same-tenant tokens whose class label was
    rewritten after generation — the class-binding property that makes
    cross-class leakage detectable.
    """
    return [
        m.group(0)
        for m in _TOKEN_RE.finditer(text)
        if m.group(2) != _tenant_hash(m.group(1), own_tenant_id)
    ]
