# Live Self-Hosted Production Deployment — Validation Log (2026-07-04)

**Historical status:** superseded on 2026-07-07 by the retained `capture-bc10`
Tier-B production evidence bundle. This file remains the live bring-up log that
explains what the self-hosted stack proved before the final signed/redacted
production capture.

**What this is:** a real, first bring-up of `infra/docker-compose.prod.yml` on the
target-class host (macOS, 16 GB, Docker Desktop 12.5 GB, **no GPU**), driven end to
end. It records what was proven against live infrastructure before the final
capture. It was not itself the Tier-B evidence bundle; `capture-bc10` later
provided the full operator-captured, signed, redacted `deployment-soak` ->
`release-audit` -> `production-evidence-verify` proof.

## Stack brought up (14 containers, all healthy)

step-ca · Caddy (sole ingress, :443) · Postgres (pgvector) · Vault (sealed→unsealed) ·
Keycloak · embedder (baked bge + cross-encoder) · SeaweedFS · VictoriaMetrics · vmalert ·
Grafana · Ollama (Qwen3-4B pulled) · mnemo-api · mnemo-consolidator · operator.

## Real infrastructure proofs (executed on the live stack)

| Area | Blueprint row | Proof |
|---|---|---|
| **TLS / real CA** | B2, §4 | step-ca issued a real intermediate-chained leaf for Vault; Caddy terminates TLS with a step-ca ACME cert; the app container reached `https://kc.mnemo.local` validating against the step-ca root (no skip-verify anywhere). |
| **Postgres role separation** | B2, B5, §4 | `roles.sql` applied at initdb: 6 roles present. `postgres-role-check` (the command added 2026-07-04) ran against the **live** app + consolidator DSNs and passed **9/9** checks, 0 findings: app_user NOSUPERUSER/NOBYPASSRLS, no DELETE/TRUNCATE, consolidator sole-write, `audit_log` append-only. |
| **Vault KMS crypto-shred** | B7 | Full lifecycle via the app's `vault-object-key` provider against sealed→unsealed Vault transit: `get_or_create_key` → `get_key` (identical 32-byte DEK) → `has_key:true` → `shred_key` → `get_key` fails closed → `has_key:false`. |
| **Session-secret custody** | B2 | The app read the signed-session keyring from Vault KV over TLS using its AppRole-scoped token file. |
| **Live IdP / JWKS + kid pin** | B2 | Live Keycloak `mnemosyne` realm imported; JWKS served with signing kid `PIoKoLlxeK…` (sha256 `be9206ff…`); `idp-jwks-live-check` loaded the JWKS from the internal host and engaged kid-sha256 pinning. |
| **Production MCP profile (fail-closed)** | B3, §4 | `mnemo-api` started with `MNEMOSYNE_MCP_PRODUCTION_PROFILE=1` and served `/health` 200 `http-json-rpc` — startup itself proves signed sessions, session-secret custody, AES-GCM object encryption, and command-backed object-key custody are all wired (it refuses to start otherwise). |
| **Retrieval (real embedder → pgvector)** | B1 | Live embedder serves real 1024-dim `bge-small-en-v1.5` vectors through Caddy TLS. A capture into live Postgres followed by a **cross-vocabulary** query ("bird photographed near wetland") retrieved the stored evidence ("heron at dawn over the marsh") via the `http-embedding`/`http-reranker` adapters over native `postgres-fts` + `postgres-recursive-ppr`. |
| **Sealed Vault + audit device** | §4 | Vault initialized 5-share/threshold-3, unsealed, transit + KV + AppRole enabled, file audit device on; no dev root token in any service. |

## Defects fixed while bringing the stack up (6)

These were found **only** by actually deploying — each would block a real self-hosted
bring-up. All landed with tests on `phase3/providers-consolidation`:

1. **embedder self-test import** — `services/embedding/selftest.py` imported `mnemosyne`
   unconditionally, breaking the hermetic service-image build; loopback-only fallback added.
2. **vmalert crash-loop** — alerting rules loaded with no notifier; added `-notifier.blackhole`
   (self-hosted has no external Alertmanager; tripwires are scraped to Grafana).
3. **`/data` volume ownership** — initialized root-owned, so the non-root runtime could not
   write Vault-wrapped DEK sidecars under a read-only rootfs; the image now pre-creates and
   chowns `/data` so a fresh named volume inherits uid 10001.
4. **object-key provider token custody** — only read `VAULT_TOKEN`; the hardened compose
   supplies `VAULT_TOKEN_FILE` (mounted secret). Added file-form support like the session provider.
5. **retrieval internal-host allowlist** — the HTTP embedder/reranker at `tei.mnemo.local`
   (private address) was blocked by the network-safety guard; added
   `MNEMOSYNE_RETRIEVAL_ALLOWED_INTERNAL_HOSTS`.
6. **OIDC JWKS internal-host allowlist** — the IdP behind Caddy on a LAN/VPN (private) address
   was blocked for JWKS fetch; added `MNEMOSYNE_IDP_ALLOWED_INTERNAL_HOSTS`.

## Historical Remaining Items Before `capture-bc10`

At the time of this validation log, the full signed Tier-B capture per row had
not been produced here. The later `capture-bc10` bundle is the authoritative
production-evidence surface.

- **Operator-authored input artifacts** (calibration datasets, authz policies,
  provenance trust suites, per-row ops bundles) — later captured and retained
  in `capture-bc10`.
- **Specialist adapters** the self-hosted profile deliberately substitutes with native
  equivalents: ParadeDB BM25 and Apache AGE for the strict B1 lexical/graph
  rows. Native recursive-PPR remains the accepted self-hosted evidence path
  unless the audit contract is changed again.
- **A production realm fixture** — later supplied through the production
  operator bundle.
- **B9 (FR-21) trainer** — superseded by ADR-002's amended CPU-parametric
  self-hosted path; B9 is Done only because the retained `capture-bc10` evidence
  passed the same release-audit and offline custody gates.

Everything above remains useful deployment provenance, not a separate current
completion checklist.
