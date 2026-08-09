---
type: concept
title: Mnemosyne Phase 8 network egress hardening 2026-07-03
tags:
  - mnemosyne
  - network-egress
  - phase8
  - security
  - tier-b
---

# Mnemosyne Phase 8 network egress hardening 2026-07-03

Commit `e745909` on `/Users/admin/Mnemosyne` branch `phase3/providers-consolidation` routes Vault transit, Vault session-secret, internal Ollama role-LLM, and embedding self-test HTTP calls through `mnemosyne.network_safety.safe_urlopen` / `validate_fetch_url`.

The source-owned decision is default-deny internal resolution: private/internal addresses are rejected unless the host is explicitly allowlisted through `MNEMOSYNE_VAULT_ALLOWED_INTERNAL_HOSTS` or `MNEMOSYNE_OLLAMA_ALLOWED_INTERNAL_HOSTS`. `safe_urlopen` now accepts a custom TLS context so the Vault step-ca CA bundle can be used without bypassing redirect denial or DNS pinning.

`tests/test_network_egress_policy.py` gates future raw outbound HTTP drift. Remaining documented exceptions are the official MCP SDK `httpx.AsyncClient` transport after upstream URL validation and the container-local Docker healthcheck. This is source hardening only; Tier-B parity still requires runtime default-deny egress/proxy/firewall evidence plus operator-captured production bundles.
