# Phase 08 — Security Findings (full capture)

**Source:** adversarial security workflow (15 agents: design → red-team → synthesize) over the
self-hosted production architecture, grounded in blueprint §27/§31 + `network_safety.py` + the
`*-ops-check` gates. **Epistemic note:** AI-adversarial-review-derived. The *unsafe-default* items are
code-checkable facts (verify + fix). The *gate-integrity* item is the most consequential claim — verify
against the actual checker code before treating as fully confirmed, but harden toward it regardless.
**No control here weakens a gate, a §31 rail, or a §16 SLO.**

## Headline finding A — gate integrity (verify, then harden)
The `*-ops-check` / `release-audit` / `provider-check` family largely **validates an operator-supplied
JSON evidence bundle (booleans + key-NAMES); it does not re-execute the operation or probe live infra**
(some checks *do* live-probe — e.g. `idp-jwks-live-check`, `validate-keycloak.sh`). So RLS, secret
custody, JWKS rotation, erasure, residency, and provenance are attestation-only and forgeable by a
compromised CI step or careless operator. **Fix:** extend the high-value checks to MEASURE —
auth-ops forges `alg=none`/wrong-aud/replayed-kid tokens against the live verifier; privacy-ops does a
real `forget` then re-reads to confirm 404 + Vault transit key gone; provider-check round-trips the live
endpoint; **sign every evidence bundle with a collector-only key** the gate verifies + freshness.

## Headline finding B — unsafe shipped defaults (code-checkable; production profile must fail-closed)
- MCP dev mode can still run with `require_session=OFF`; the production profile now has a code-level
  `MNEMOSYNE_MCP_PRODUCTION_PROFILE=1` boot gate that refuses missing signed sessions, missing
  verifier custody, disabled AES-GCM object encryption, or non-command object-key custody. Remaining
  work: live ops evidence and MFA-gated privilege checks.
- Runtime Postgres connections now have a shared safe-role guard; the self-hosted profile enables it
  with `MNEMOSYNE_POSTGRES_REQUIRE_SAFE_ROLE=1`, and the MCP production profile enables it
  automatically for engine/state/queue surfaces. Remaining work: live role/grant evidence and an
  operator-captured `rolsuper`/`rolbypassrls` probe.
- Object-store encryption defaults to `none` → breaks right-to-be-forgotten in backups.
- Dev-mode Vault with a committed fixed root token is the only KMS wiring.
- OIDC policy now rejects operator/consolidator or trust-tier≤1 rules unless they have a
  non-tenant claim matcher plus `required_acr`, `required_amr`, and bounded `auth_time`.
  Remaining work: capture live Keycloak/MFA evidence against production credentials.
- `ProvenanceTrustPolicy` is **fail-OPEN**.

## The 16 must-do controls (ship before any production capture)
1. **Gate integrity → measure-not-attest** + collector-signed bundles (finding A).
2. **Auth fail-closed by default:** MCP `require_session=True` (refuse boot if unset); tenant/role/trust ONLY from the verified session claim, never a tool arg; startup + ops-check enforce it. **Code status:** production-profile startup enforcement is wired; live ops-check evidence and MFA-gated elevation evidence remain.
3. **Postgres role separation under RLS:** `mnemosyne_app` (NOSUPERUSER/NOBYPASSRLS/no DELETE/TRUNCATE), separate `mnemosyne_consolidator` (sole write/destructive), SELECT-only eval roles; ops-check live-probes `rolsuper`/`rolbypassrls`. (DDL: `infra/postgres/roles.sql`.) **Code status:** shared safe-role guard is wired into `PostgresEngine`, `PostgresRuntimeState`, and `PostgresQueue`; `MNEMOSYNE_POSTGRES_REQUIRE_SAFE_ROLE=1` enables it for CLI/self-hosted profile and the MCP production profile enables it automatically. Live role/grant evidence remains required.
4. **MFA-gate privilege elevation:** any rule granting operator/consolidator or trust_tier≤1 requires a non-empty claim matcher AND `required_acr/amr`; implement acr/amr/auth_time verification; reject tenant-only operator rules; bind superseding trust to the verified session (R4). **Code status:** source enforcement is wired in `OidcAuthorizationPolicy`; live Keycloak/MFA rollout evidence remains required.
5. **Production KMS (no dev mode):** sealed Vault/OpenBao (raft + transit auto-unseal via a separate hardened seal; AppRole/workload-identity, not root; audit device on; step-ca TLS); remove committed dev root token; single-use response-wrapped short-TTL CIDR-bound secret_ids; `kms-ops-check` asserts not-dev/no-root/key-version-advanced.
6. **Mandatory at-rest object encryption:** `MNEMOSYNE_OBJECT_STORE_ENCRYPTION=aesgcm` + Vault-transit key provider; boot-time refuse-to-start if it resolves to `none` while S2+ writable; gate crypto-shred on it. **Code status:** MCP production-profile startup enforcement is wired for `aesgcm` + command-backed object-key custody; live Vault/KMS crypto-shred evidence remains.
7. **Tenant-scope crypto-shred + split erase authority:** per-tenant-namespaced transit key paths + per-tenant policies (no wildcard `transit/keys/mnemosyne-object-*` delete); separate higher-auth credential for delete vs encrypt/decrypt; one-way `deletion_allowed`; alert on every transit DELETE; bound per-tenant KEKs wrapping per-object DEKs (rotation O(tenants)).
8. **Provenance fail-closed:** `require_trusted_issuer=True` (+ `require_trusted_root` when roots set); self-signed/untrusted/digest-mismatch → data-only, never raises trust; `provenance-trust-check` fails on empty/dev roots.
9. **Policy-as-code + socket-deny as required CI rails (do FIRST among infra):** trivy-config/conftest gate fails the build on any docker.sock mount or Docker-API-over-TCP, `privileged`, `seccomp/apparmor=unconfined`, missing `read_only`/`cap_drop:[ALL]`/`no-new-privileges`/non-root user/limits/healthcheck, unpinned image, or literal secret in `environment:`; fail-closed if the policy file is missing; scope-exempt only the dev compose by path.
10. **Secret scanning in CI:** `evidence_redaction.scan_evidence_paths` over the tree/rendered config + gitleaks (history) as required PR gates, fail-closed; high-entropy/UUID heuristics to catch opaque AppRole secret_ids/seal tokens; convert prod Postgres/Grafana creds to Docker secrets/`*_FILE`.
11. **Digest-pin every image + verify provenance:** `@sha256` on every `FROM`/`image:` across dev+prod compose, CI, Dockerfiles, and the scanner-action refs; hash-pin build inputs (`pip --require-hashes`, `cargo --locked`); cosign-verify curl'd binaries; Trivy/Grype over source+image (HIGH,CRITICAL, --ignore-unfixed); verify running digest == scanned/signed digest at deploy.
12. **Single SSRF egress chokepoint:** force ALL outbound HTTP (JWKS/TEI/Vault/object-store/C2PA/provider SDK clients) through `validate_fetch_url`+`safe_urlopen`; lint fails on a raw urllib/httpx/requests/SDK socket call outside `network_safety`; back it with a default-deny egress proxy/firewall allow-listing only enumerated origins by IP+SNI, dropping metadata/link-local (incl. IPv6 fe80::/10, fd00:ec2::254)/RFC1918/NAT64; validate-and-connect atomic (no re-resolution; re-validate after redirect). On rootless/Docker-Desktop without host firewalling, treat egress-deny as **NOT achieved** and gate production on a working DOCKER-USER/host firewall.
13. **Pin OIDC signing trust:** pin JWKS keys by expected kid-sha256 allowlist (enforce the hashes the gate already records, under change-control); verify the JWKS endpoint TLS cert against step-ca; rate-limit/coalesce forced unknown-kid refreshes.
14. **Privilege-separate the Mnemosyne service:** front API/MCP container (no secrets/data/KMS) + back consolidator/KMS-user (no edge reachability) over a narrow internal RPC; only the back holds the Vault role; short-lived response-wrapped decrypt-only transit tokens; destructive ops behind a separate offline/quorum path. (Encoded in `infra/docker-compose.prod.yml`.)
15. **Production compose & edge topology:** Caddy the only published port; all else `expose`-only on `internal:true` tiers; step-ca-issued mTLS between services (verify expected SAN, not just chain-to-CA; CI fails on `tls_insecure_skip_verify`); remove host ports from the providers compose; a topology-invariance CI test renders BOTH profiles and asserts exactly one published port, `internal:true` on data/secrets, no service gained edge+secrets, and an enumerated egress allowlist.
16. **Tamper-evident audit log:** hash-chained append-only `audit_log` (prev_hash/row_hash keyed by a Vault-held HMAC, BEFORE UPDATE/DELETE trigger raises, INSERT-only grant, break-glass-only mutate); `audit-verify` run in CI against the live DB; pgaudit + an off-box append-only (Loki/WORM) second copy the app role cannot rewrite; log every write AND every auth decision (actor/source/tier/diff/reason, hashed PII).

## Layered controls (defense-in-depth)
- **Perimeter/network:** Caddy sole ingress (LAN/VPN iface, never 0.0.0.0/WAN); tiered internal networks; topology-invariance CI test.
- **Host/container:** policy-as-code CI gate; digest pins; non-root/read_only/cap_drop ALL/no-new-privileges/limits; docker.sock never mounted.
- **Identity:** MCP as OAuth2.1 resource server; mandatory sessions; tenant/role/trust from verified claim only; RS/ES-only verifier; MFA-gated elevation.
- **Secrets:** sealed Vault; AppRole; no standing tokens; Docker-secret injection.
- **Data:** mandatory AES-GCM; per-tenant DEK/KEK; AAD binds tenant/cid/kind; transitive crypto-shred (R2); LUKS for PGDATA/Vault; encrypted PITR + verified restore.
- **Application-rails:** the seven §31 rails from a single root-owned :ro mount, enforcers reject MISSING keys; R6 single choke point `assemble_system_prompt` + credential-less quarantine worker.
- **Monitoring:** tamper-evident audit log + pgaudit + out-of-band WORM; tripwire dashboards.

## Residual risks (mitigated structurally, not eliminated)
1. **[high]** In-band abuse of *legitimate* tool authority (poisoned memory / compromised model endpoint drives the consolidator to legitimate-but-harmful writes) — mitigated by KMS off the edge surface, decrypt-only transit, R6 boundary; not eliminated.
2. **[high]** Single-tenant/local deployments get ZERO per-tenant-isolation benefit (the #1 anti-MINJA defense) — mitigated by R6 + per-source trust tiers + data-never-instruction.
3. **[high]** Evidence-bundle/attestation forgery residue even after live-probing — mitigated by collector-signed bundles + constrained collector identity.
4. **[medium]** Rootless/Docker-Desktop/WSL2 where host firewalling is absent → egress-deny silently not enforced — gate production on a working host firewall + the SNI-allowlisting egress proxy.
5. **[medium]** step-ca compromise = per-LAN cert-forgery oracle — provisioner-scoped SAN allowlists + account-key binding + CA key in Vault/HSM (offline root) + per-leaf SAN pinning.
6. **[medium]** Crypto-shred vs DR: a pre-shred KMS snapshot can resurrect "erased" data — shorten pre-shred snapshot retention below the erasure SLA + post-restore shred reconciliation.
7. **[medium]** Per-object KEK explosion (millions of keys) — bounded per-tenant/class KEKs wrapping per-object DEKs.
8. **[medium]** Cloud-profile swap widens egress where data is most exposed — topology-invariance test across both profiles + same SNI-allowlisted chokepoint.
9. **[medium]** Observability as reconnaissance (compromised tier reads /metrics + tripwires) — authenticated scrape + out-of-band WORM sink.
10. **[low]** Log-rotation as secret retention — no-secret-in-logs at source + CI test + redact-before-egress.
11. **[low]** Self-attesting seccomp/AppArmor/cap claims weaker than asserted on permissive daemons — runtime docker-inspect probe in CI/startup.

## Blueprint mapping
Binds to §27 (memory defended architecturally, not by detection) + the seven §31 rails; **preserves,
never weakens, the Tier-B gate set.** Per-tenant/source isolation realized simultaneously at RLS,
Postgres-role, per-tenant-KEK, object-prefix, and network-segmentation layers, proven by a LIVE
`rolsuper`/`rolbypassrls` probe. R6 = single choke point + credential-less quarantine worker. Capability
mediation enforced at the credential layer via privilege separation. C2PA provenance fail-closed.
