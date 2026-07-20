"""Signed-session helpers and the retired PM/Trigger simulator marker.

The public harness mints its own Mnemosyne session tokens exactly as an agent
host would — a client responsibility — and presents them through the public
``--session-token`` seam.  Minting is pure standard-library HMAC-SHA256 over the
canonical claim payload; it never imports a memory engine and reproduces
``mnemosyne.security.SessionTokenVerifier.sign`` byte-for-byte so the production
CLI verifies the token without any private coupling.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


# Deterministic HMAC secret the harness uses on both sides of the public seam:
# it signs the session token with this secret and hands the same secret to the
# CLI subprocess (via ``MNEMOSYNE_SESSION_SECRET``) so verification succeeds.
# It is not a production credential and never enters any bundle or trace.
SESSION_SECRET = "mnemosyne-public-eval-session-secret"

# TrustTier.DIRECT_USER (0) — the strongest first-party trust tier, accepted by
# every authenticated working-memory and prospective-memory write.
_DIRECT_USER_TRUST_TIER = 0


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def mint_session_token(
    *,
    tenant_id: str,
    user_id: str,
    role: str,
    source_trust_tier: int = _DIRECT_USER_TRUST_TIER,
    agent_id: str | None = None,
    session_id: str | None = None,
    capabilities: Sequence[str] = (),
    secret: str = SESSION_SECRET,
) -> str:
    """Return a signed ``payload.signature`` Mnemosyne session token.

    The claim canonicalization (sorted keys, compact separators, optional agent,
    session, and capability fields) mirrors ``SessionIdentity.to_payload`` and
    ``SessionTokenVerifier.sign`` so a single shared secret verifies the token.
    """
    payload_data: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "source_trust_tier": source_trust_tier,
    }
    if agent_id:
        payload_data["agent_id"] = agent_id
    if session_id:
        payload_data["session_id"] = session_id
    if capabilities:
        payload_data["capabilities"] = list(capabilities)
    payload = _b64url(
        json.dumps(payload_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64url(
        hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{payload}.{signature}"


PM_TRIGGER_UNAVAILABLE_REASON = (
    "PM-Bench/TriggerBench are non-runnable: authenticated intention schedule, "
    "cancel, evaluate, and list commands exist, but the production CLI does not "
    "yet expose atomic update/reschedule/override/recurring semantics; stable "
    "fixture identity and session scope or query-without-firing where required; "
    "and explicit action selection or an approved deterministic-selection contract"
)


@dataclass
class ActionCLI:
    """Reject the retired fixture-aware simulator at its former public seam."""

    state: Path

    def run(self, command: str, *args: Mapping[str, Any]) -> dict[str, Any]:
        del command, args
        raise RuntimeError(PM_TRIGGER_UNAVAILABLE_REASON)
