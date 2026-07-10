---
phase: 08-self-hosted-first-production
validated: 2026-07-10
status: passed-current-coverage
nyquist_compliant: true
wave_0_complete: true
reconstructed: true
---

# Phase 08 Nyquist Validation

This present-day coverage map was reconstructed on 2026-07-10. It proves that
every critical Phase 8 seam has a focused executable or integrity check today;
it does not claim contemporaneous Wave-0 sampling during the historical plan.

| Seam | Focused evidence | Backstop |
|---|---|---|
| Compose/profile topology and hardening | `uv run --locked python -m pytest tests/test_prod_compose_policy.py tests/test_production_manifest_renderer.py -q` | Full suite + CI |
| Provider/retrieval contracts | `uv run --locked python -m pytest tests/test_provider_contract.py tests/test_provider_check_parametric_probe.py tests/test_parity_retrieval.py -q` | Release audit + CI |
| Identity/session/TLS boundaries | `uv run --locked python -m pytest tests/test_security_sessions.py tests/test_runtime_surfaces.py -q` | Full security suite |
| RLS/role parity | `uv run --locked python -m pytest tests/test_postgres_role_check.py tests/test_postgres_security.py -q` | DSN-gated live tests + CI |
| Supply chain/network/manifest | `uv run --locked python -m pytest tests/test_infra_script_hardening.py tests/test_infra_docker_context_hygiene.py tests/test_network_egress_policy.py -q` | Release audit |
| Audit/privacy/custody | `uv run --locked python -m pytest tests/test_audit_chain.py tests/test_evidence_signing.py tests/test_evidence_redaction.py -q` | External offline verifier |
| B1-B10 operator result | Validate `verify-bc10.json`, `release-audit.json`, and `summary.json` fingerprints/findings/row counts read-only | Independent milestone audit |

Any failed seam blocks the corresponding truth. A missing external packet is an
operator-evidence failure, not something a local unit test may replace.

