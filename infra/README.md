# Mnemosyne real-services local stack

Turnkey Docker Compose stack that brings up **real** production dependencies for
Mnemosyne so the deterministic local stand-ins can be replaced with the genuine
services they emulate:

| Service | Image | Satisfies | Mnemosyne contract it feeds |
| --- | --- | --- | --- |
| **Keycloak** | `quay.io/keycloak/keycloak:25.0` | FR-7 / FR-9 auth | `OidcJwtVerifier` / `session-exchange` / `idp-jwks-live-check` (real OIDC ID tokens + JWKS) |
| **HashiCorp Vault** | `hashicorp/vault:1.17` | KMS / crypto-erase | `CommandKeyManager` object-key provider (real transit wrap / unwrap / rotate / shred) |
| **c2patool** | built from `infra/c2pa/Dockerfile` | FR-19 provenance | `C2paToolVerifier` (real C2PA manifest signing + verification with a test cert root) |

Blueprint references: `docs/BLUEPRINT-COMPLETION-PLAN.md` rows **FR-7/FR-9** (auth),
**KMS**, and **FR-19** (signed provenance), plus the "P1 (real services)" line.
This stack validates local real-service mechanics for FR-7/FR-9/FR-19; it is
not production validation and does not flip Tier B rows without
operator-captured production evidence.

> These services are **not required** to run in the build environment. Everything
> here is turnkey and documented so an operator can stand it up on any Docker
> host. The provider scripts that Mnemosyne shells out to (the Vault key provider
> and the C2PA verify wrapper) have been unit-proven against the real Mnemosyne
> `CommandKeyManager`, `OidcJwtVerifier`, and `C2paToolVerifier` code paths.

## Layout

```
infra/
  docker-compose.providers.yml      # the three services (Keycloak, Vault, c2pa)
  README.md                         # this file
  keycloak/
    realm-mnemosyne.json            # realm + client + users + claim mappers
    out/                            # (generated) oidc.env, jwks.json, id_token.jwt
  vault/
    mnemosyne-transit-policy.hcl    # least-privilege transit policy
    vault-object-key-provider.py    # command-backed KMS provider (Mnemosyne contract)
    providers.json                  # provider-check manifest (Vault = required object key)
    out/                            # (generated) vault.env, wrapped-keys/
  c2pa/
    Dockerfile                      # builds real c2patool + openssl
    manifest.json                   # c2patool claim definition for the test signer
    c2pa-verify-host.sh             # what Mnemosyne --c2pa-tool points at (host)
    c2pa-verify.py                  # runs real c2patool + enriches (native path)
    c2pa-enrich.py                  # enriches an existing c2patool report (container path)
    out/                            # (generated) certs, signed asset, trust-policy.json
  scripts/
    up.sh  down.sh                  # stack lifecycle
    setup-all.sh                    # seed all three providers
    render-production-soak-manifest.sh
    capture-production-evidence.sh  # production Tier-B deployment-soak runner
    setup-keycloak.sh setup-vault.sh setup-c2pa.sh
    keycloak-token.sh               # mint a fresh ID token on demand
  templates/
    production-soak-manifest.template.json
    production-render.env.example   # blank non-secret render inputs template
  validate/
    validate-all.sh                 # run all three validations
    validate-keycloak.sh validate-vault.sh validate-c2pa.sh
  PRODUCTION-EVIDENCE.md            # production evidence capture runbook
```

Everything generated lands under `*/out/` and is git-ignored (it contains
secrets, private keys, and tokens).

## Prerequisites

- Docker with Compose v2 (`docker compose version`)
- `curl`, `jq`, `openssl`, `python3` on the host (used by setup/validation)
- A Mnemosyne checkout (this repo). Validation auto-detects `./.venv/bin/python`
  and falls back to `python3`. Override with `MNEMOSYNE_PYTHON=...`.

## Quick start

```bash
# 1. Bring up Keycloak + Vault and build the c2patool image.
./infra/scripts/up.sh

# 2. Seed all three providers (realm, transit key, test cert + signed asset).
./infra/scripts/setup-all.sh

# 3. Validate Mnemosyne against every real service.
./infra/validate/validate-all.sh

# 4. Capture scoped local deployment-soak/release-audit evidence.
./infra/scripts/capture-local-evidence.sh

# 5. For production Tier-B evidence, render the production template.
open ./infra/PRODUCTION-EVIDENCE.md

# 6. Tear down (add --volumes for a full reset).
./infra/scripts/down.sh
```

`capture-local-evidence.sh` writes to a new, non-symlinked, timestamped
`/tmp/mnemosyne-tierb-local-evidence-*` directory outside the repository, runs
`deployment-soak --evidence-dir`, and then runs scoped
`release-audit --allow-provider-local` for Keycloak, Vault/KMS provider,
retrieval-provider metadata reporting, and C2PA trust verification. It does not
prove live ParadeDB/AGE/pgvector retrieval and does not claim production
validation; production parity still requires operator-captured
`release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local` evidence against deployed
infrastructure.

For production Tier-B evidence, render the production soak manifest outside the
repository, then use the production runner:

```bash
cp infra/templates/production-render.env.example \
  /secure/path/to/production-render.env
# Fill /secure/path/to/production-render.env outside this repository.
set -a
. /secure/path/to/production-render.env
set +a
infra/scripts/render-production-soak-manifest.sh --check-environment
infra/scripts/render-production-soak-manifest.sh \
  --output /secure/path/to/production-soak-manifest.json
infra/scripts/capture-production-evidence.sh \
  --preflight-only \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-preflight
infra/scripts/capture-production-evidence.sh \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-evidence
PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else command -v python3; fi)}"
BUNDLE_DIR=/secure/path/to/mnemosyne-production-evidence
# Set this from the operator's out-of-band capture record, not from summary.json
# inside the bundle under review.
EXPECTED_BUNDLE_FINGERPRINT=sha256:...
"$PYTHON" -m mnemosyne.cli production-evidence-verify \
  "$BUNDLE_DIR" \
  --expected-bundle-fingerprint "$EXPECTED_BUNDLE_FINGERPRINT"
```

The completed production bundle must retain `summary.json`, `preflight.json`,
`redaction-scan.json`, `bundle-manifest.json`, `source-soak-manifest.json`,
`operator-soak-manifest.json`, and `input-artifacts/` custody. Those artifacts
are the offline handoff surface for `production-evidence-verify`; they do not
replace operator capture against deployed infrastructure.

`--check-environment` writes no files and prints no values. It always reports
the required `MNEMOSYNE_PROD_*` key names, operator readiness file paths, and
static template-derived input artifact inventory so operators can prepare the
external custody directory before sourcing environment values. Once the
environment is present, it verifies the external production input directory, the
manifest-referenced relative input artifacts in that directory, and the external
executable C2PA verifier before rendering. Its JSON includes
`required_input_artifacts_detail` and `missing_input_artifacts_detail` entries
with relative path, existence, check/command/option references, Tier-B lane,
strict-audit row, and row-runbook routing so operators can repair missing inputs
without exposing absolute custody paths. It also includes
`parity_row_readiness`, which groups the same required artifact and check
references by Tier-B lane/runbook and, when environment values are present,
reports row-local missing artifacts, row-local validation errors, and
`input_artifacts_complete`. This readiness grouping is assignment metadata only;
the production capture plus release-audit path still gates every Partial row.
Check-level `input_artifacts` metadata is included in the same custody inventory
for evidence that must be retained but is not passed as a command argument.

The renderer replaces non-secret `MNEMOSYNE_PROD_*` placeholders from the
operator environment and validates production scope plus the full command
profile before writing the manifest. The runner is intentionally fail-closed. It
refuses manifests unless `validation_scope.production_validated=true`,
`validation_scope.target_environment="production"`, and
`validation_scope.operator_asserted=true`; rejects unresolved production
placeholders, secret-bearing CLI options, high-confidence secret material,
unscannable retained artifacts, and pre-existing output roots; and requires the
exact production release command profile, with no missing,
duplicate, or unknown commands, before running `deployment-soak --evidence-dir`
followed by
`release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`.
The deployment evidence manifest binds its report and check artifacts with
SHA-256 digests; release-audit verifies those digests, rejects artifact paths
that resolve outside the evidence bundle, and confirms retained check JSON
matches the audited report before trusting the bundle. The offline
`production-evidence-verify` command rechecks an already captured bundle's
custody metadata, retained input-artifact bindings, and release-audit replay
without contacting production or rerunning deployment soak. Custody review
requires `--expected-bundle-fingerprint` from an independently retained
out-of-band capture record; `--internal-consistency-only` is diagnostic-only.
Use `--preflight-only` to validate and copy the rendered manifest without
running production checks; preflight output plus `redaction-scan.json` is setup
proof only, not production parity evidence. Successful full capture writes
`bundle-manifest.json` with SHA-256 hashes for retained artifacts, keeps
`source-soak-manifest.json` for source/operator command-profile agreement, and
surfaces its `bundle_fingerprint` in `summary.json` for operator handoff custody.
Put secrets in environment variables, files, or command-backed providers, not
in manifest `args`.

Ports are offset from defaults to avoid clashes:

| Service | Host port | URL |
| --- | --- | --- |
| Keycloak | `8089` | http://localhost:8089 (admin `admin` / `admin`) |
| Vault | `8211` | http://localhost:8211 (dev root `mnemosyne-dev-root`) |

---

## 1. Keycloak — real OIDC / JWKS (FR-7 / FR-9)

`setup-keycloak.sh` imports realm **`mnemosyne`** with:

- confidential client **`mnemosyne-cli`** (direct-access grant enabled so the
  scripts can mint ID tokens without a browser),
- users **`agent-a`** (`mnemosyne_role=agent`, trust tier `3`) and **`analyst-a`**
  (`mnemosyne_role=operator`, trust tier `0`),
- protocol mappers that emit exactly the claims Mnemosyne's verifier expects by
  default: `tenant_id`, `sub`, `mnemosyne_role`, `mnemosyne_source_trust_tier`,
  and `jti` (→ Mnemosyne `session_id`), plus an `aud=mnemosyne` audience mapper.

It writes `infra/keycloak/out/oidc.env`:

```bash
while IFS= read -r assignment; do
  [ -n "${assignment}" ] && export "${assignment?}"
done < <(
  python3 infra/scripts/load-env.py infra/keycloak/out/oidc.env \
    MNEMOSYNE_IDP_ISSUER MNEMOSYNE_IDP_AUDIENCE MNEMOSYNE_IDP_JWKS_URL
)
```

Local capture and validation scripts load this file through the strict
allowlisted parser above; do not shell-source generated provider env files.

### Use it with Mnemosyne

```bash
# Preflight (validates token + JWKS, mints NO session):
python -m mnemosyne.cli idp-jwks-live-check \
  --idp-token "$MNEMOSYNE_IDP_TOKEN" \
  --idp-jwks-url "$MNEMOSYNE_IDP_JWKS_URL" --idp-allow-insecure-jwks-url \
  --idp-issuer "$MNEMOSYNE_IDP_ISSUER" --idp-audience "$MNEMOSYNE_IDP_AUDIENCE" \
  --idp-algorithm RS256

# Exchange a real Keycloak ID token for a Mnemosyne signed session:
python -m mnemosyne.cli --session-secret "$MNEMOSYNE_SESSION_SECRET" session-exchange \
  --idp-token "$(./infra/scripts/keycloak-token.sh agent-a agent-a-password)" \
  --idp-jwks-url "$MNEMOSYNE_IDP_JWKS_URL" --idp-allow-insecure-jwks-url \
  --idp-issuer "$MNEMOSYNE_IDP_ISSUER" --idp-audience "$MNEMOSYNE_IDP_AUDIENCE" \
  --idp-algorithm RS256
```

`validate-keycloak.sh` runs both, asserts the identity maps to `tenant-a / agent /
trust 3`, and includes a negative test (wrong audience must be rejected,
fail-closed).

> Keycloak dev mode serves JWKS over **http**, so the env sets
> `MNEMOSYNE_IDP_ALLOW_INSECURE_JWKS_URL=1`. In production use the HTTPS issuer
> and drop that flag. The realm uses RS256; the verifier is configured to only
> accept RS256 here.

### What the real path needs in production

A production realm over HTTPS, a per-environment client secret in a vault, and
(optionally) `--idp-authz-policy-file` to map IdP clients/claims to Mnemosyne
roles instead of trusting raw `mnemosyne_role` claims. The realm JSON is a
starting template, not a hardened production realm.

---

## 2. Vault — real KMS via the transit engine (crypto-erase)

`setup-vault.sh` enables the **transit** secrets engine, creates the KEK
`mnemosyne-objects` (`deletion_allowed=true`), installs the least-privilege
policy `mnemosyne-transit`, and mints a scoped token. It writes
`infra/vault/out/vault.env`:

```bash
while IFS= read -r assignment; do
  [ -n "${assignment}" ] && export "${assignment?}"
done < <(
  python3 infra/scripts/load-env.py infra/vault/out/vault.env \
    VAULT_ADDR VAULT_TOKEN MNEMOSYNE_OBJECT_KEY_COMMAND
)
```

The parser rejects symlinks, group/world-accessible files, unexpected keys, and
shell-executable dotenv syntax before exporting values.

### The provider (`vault-object-key-provider.py`)

This is a real implementation of Mnemosyne's command-backed object-key contract
(`mnemosyne.storage.CommandKeyManager`). Mnemosyne invokes it without a shell,
appending the action name and sending a JSON request on stdin:

| Action | Vault operation | Response |
| --- | --- | --- |
| `get_or_create_key` | generate a 32-byte DEK, **wrap** it under a per-object transit key | `{"key":"<b64-32-bytes>"}` |
| `get_key` | **unwrap** the stored ciphertext via transit | `{"key":"<b64-32-bytes>"}` |
| `has_key` | check sidecar + transit key existence | `{"exists":true|false}` |
| `shred_key` | **delete** the per-object transit key (crypto-erase) | `{"shredded":true|false}` |
| `rotate` *(extra)* | advance the transit key version + rewrap | `{"rotated":true,...}` |

Each object gets its own transit key (named deterministically from Mnemosyne's
`key_id`). Only the Vault ciphertext rests on disk (`vault/out/wrapped-keys/`);
raw key bytes never persist. **Crypto-shred deletes the per-object KEK in Vault,
so the wrapped DEK becomes permanently unrecoverable.**

### Use it with Mnemosyne

```bash
python -m mnemosyne.cli \
  --object-store ./objects \
  --object-store-encryption aesgcm \
  --object-key-provider command \
  --object-key-command "$MNEMOSYNE_OBJECT_KEY_COMMAND" \
  provider-check
```

`validate-vault.sh` runs `provider-check` (the canonical wrap → has_key →
get_key consistency → shred → verify-gone round-trip) **and** an end-to-end
ingest → read-back → confirm-ciphertext flow.

### What the real path needs in production

A non-dev Vault (real seal/unseal, audit device, AppRole/Kubernetes auth instead
of the dev root token), TLS on the listener, and a token-renewal sidecar. The
`MNEMOSYNE_VAULT_WRAP_DIR` sidecar store (the wrapped-DEK envelopes) should live
on the same durable medium as the object store; losing it without Vault is the
same as crypto-shred.

---

## 3. c2patool — real C2PA provenance (FR-19)

`setup-c2pa.sh`:

1. builds the c2patool image (`infra/c2pa/Dockerfile`, real `c2patool` from
   crates.io),
2. generates a **test certificate ROOT** + a leaf signing certificate with
   openssl,
3. signs a deterministic test asset with the real c2patool, and
4. writes the trust policy + `infra/c2pa/out/provenance.env`:

```bash
while IFS= read -r assignment; do
  [ -n "${assignment}" ] && export "${assignment?}"
done < <(
  python3 infra/scripts/load-env.py infra/c2pa/out/provenance.env \
    MNEMOSYNE_C2PA_TOOL MNEMOSYNE_PROVENANCE_TRUST_POLICY C2PA_SIGNED_ASSET
)
```

### How the wrapper satisfies the contract

Mnemosyne's `C2paToolVerifier` runs `<tool_path> <asset> --json` and, to raise
trust, needs the report to (a) bind to the exact bytes (asset SHA-256) and
(b) expose the signing certificate root fingerprint (a 64-hex SHA-256) under a
cert-named key. `c2pa-verify-host.sh` (what `MNEMOSYNE_C2PA_TOOL` points at):

1. runs the **real c2patool** for genuine C2PA verification (claim signature +
   hard-binding hash + chain). If c2patool exits nonzero, the wrapper does too →
   Mnemosyne quarantines.
2. enriches the verified report (`c2pa-enrich.py`) with the asset SHA-256 and the
   trust-root DER SHA-256 fingerprint so it binds to the Mnemosyne contract.

Trust is decided by `mnemosyne.provenance.ProvenanceTrustPolicy`. Two subtleties
of that production code drive how the emitted `trust-policy.json` must be shaped,
and getting them wrong **quarantines a correctly signed asset**:

- **The signer string is the report's `claim_generator`, not the leaf CN.**
  `C2paToolVerifier` selects the signer via `provenance._find_first` over
  `{issuer, signer, claim_generator, claimGenerator, common_name, commonName}` in
  insertion order, and a real c2patool report exposes the active manifest's
  `claim_generator` first (e.g. `Mnemosyne-Test-Signer/1.0 c2patool/<ver>`). So
  `setup-c2pa.sh` extracts that exact surfaced string from the report it just
  produced and writes it into `trusted_issuers` — listing only the leaf CN
  `mnemosyne-test-signer` would never match.
- **`require_trusted_issuer` defaults to `true` per rule and is OR-merged.**
  `ProvenanceTrustRule.from_dict` defaults a missing `require_trusted_issuer` to
  `true`, and `for_context` OR-merges rule flags into the scoped policy. The
  `camera-binary-tenant-a` rule therefore sets `require_trusted_issuer: false`
  **explicitly** — it trusts by certificate **root**
  (`require_trusted_root: true`); an omitted flag would silently force issuer
  trust on for that scope and quarantine.

With those two corrections in the emitted policy, the signed asset returns
`valid + trusted` (root matched, and the surfaced signer is also in
`trusted_issuers`), and a single flipped byte quarantines on asset-binding
mismatch. This is proven hermetically against the real `ProvenanceTrustPolicy` /
`C2paToolVerifier` in `tests/completion/provenance/test_c2pa_infra_trust_policy.py`
(no Docker, no c2patool binary required). The end-to-end run through the live
c2patool **container** additionally requires building the c2patool image
(`infra/c2pa/Dockerfile`), which compiles c2patool from crates.io and needs
network plus a working Rust/OpenSSL toolchain on first build.

### Use it with Mnemosyne

```bash
python -m mnemosyne.cli \
  --c2pa-tool "$MNEMOSYNE_C2PA_TOOL" \
  --provenance-trust-policy "$MNEMOSYNE_PROVENANCE_TRUST_POLICY" \
  ingest --tenant tenant-a --user user-a --actor external \
    --source-type camera --file "$C2PA_SIGNED_ASSET" --modality binary --trust-tier 5
```

`validate-c2pa.sh` ingests the signed asset (asserts verified + not quarantined)
and runs a negative tamper test.

### What the real path needs in production

A real signing certificate chained to a CA your organization trusts (not the
self-signed test root), a real timestamp authority, and `trusted_roots` /
`trusted_issuers` in the policy populated with your production roots. If
c2patool is installed natively on the host, set `C2PATOOL_BIN=/path/to/c2patool`
and the wrapper skips the Docker round-trip.

---

## Cross-checks already performed

The provider glue was validated against the real Mnemosyne source in this repo
(no service required) so the contracts are known-correct before you ever start
Docker:

- **OIDC**: an RS256 token with the realm's claim shape verifies through
  `OidcJwtVerifier` + `issue_session_from_oidc` → `tenant-a / agent / trust 3`,
  `jti → session_id`.
- **KMS**: the Vault provider drives `CommandKeyManager` through a full
  wrap/unwrap/has_key/shred lifecycle; the unwrapped key is byte-identical
  across calls and unrecoverable after shred.
- **C2PA**: with the emitted `trust-policy.json` (surfaced-`claim_generator`
  issuer + explicit `require_trusted_issuer: false` on the root-trusted rule),
  the `c2pa-enrich.py` report shape makes `C2paToolVerifier` return
  `valid + trusted`; a tampered payload or an unknown certificate root
  quarantines. Proven hermetically in
  `tests/completion/provenance/test_c2pa_infra_trust_policy.py`. (The live
  c2patool container path is documented above and depends on a successful
  c2patool image build.)

## Troubleshooting

- **Keycloak slow to start**: dev mode + realm import can take ~40s. `up.sh`
  waits on the container healthcheck; re-run `setup-keycloak.sh` if you started
  it manually before health.
- **`session exchange denied: ... audience is not allowed`**: the token's `aud`
  must equal `--idp-audience`. The realm's audience mapper sets `aud=mnemosyne`.
- **Vault `permission denied`**: reload `vault/out/vault.env` through
  `infra/scripts/load-env.py`; the scoped token has a 24h TTL, so re-run
  `setup-vault.sh` to mint a fresh one.
- **c2patool image build fails offline**: the Dockerfile compiles c2patool from
  crates.io, which needs network on first build. Cached afterwards.
