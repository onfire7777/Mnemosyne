#!/usr/bin/env bash
# Mnemosyne — production bootstrap (self-hosted, no-GPU). Idempotent first-run setup.
# Run ONCE before `docker compose -f infra/docker-compose.prod.yml up -d`.
# This prepares real, non-self-signed, non-dev infrastructure. It writes NO secrets to the repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SECRETS_DIR="${MNEMO_SECRETS_DIR:-/secure/outside/repo}"   # external, outside the repo

echo "==> 0. Preconditions"
command -v docker >/dev/null || { echo "docker required"; exit 1; }
command -v openssl >/dev/null || { echo "openssl required"; exit 1; }
command -v step >/dev/null || { echo "step CLI required"; exit 1; }
command -v cmp >/dev/null || { echo "cmp required"; exit 1; }
mkdir -p "$SECRETS_DIR"
umask 077

echo "==> 1. Secret material (generated locally, stored OUTSIDE the repo, mode 0600)"
[ -f "$SECRETS_DIR/pg_superuser_pw" ]  || openssl rand -base64 32 > "$SECRETS_DIR/pg_superuser_pw"
[ -f "$SECRETS_DIR/grafana_admin_pw" ] || openssl rand -base64 24 > "$SECRETS_DIR/grafana_admin_pw"
[ -f "$SECRETS_DIR/kc_db_pw" ]         || openssl rand -hex 24 > "$SECRETS_DIR/kc_db_pw"
[ -f "$SECRETS_DIR/kc_admin_pw" ]      || openssl rand -hex 24 > "$SECRETS_DIR/kc_admin_pw"
for role in app consolidator eval; do
  [ -f "$SECRETS_DIR/${role}_db_pw" ] || openssl rand -hex 24 > "$SECRETS_DIR/${role}_db_pw"
done
# pgpass files: password custody for the least-privilege DSNs (PGPASSFILE in compose)
printf 'postgres.mnemo.local:5432:mnemosyne:app_user:%s\n' "$(cat "$SECRETS_DIR/app_db_pw")" > "$SECRETS_DIR/pgpass_app"
printf 'postgres.mnemo.local:5432:mnemosyne:consolidator_user:%s\n' "$(cat "$SECRETS_DIR/consolidator_db_pw")" > "$SECRETS_DIR/pgpass_consolidator"
chmod 0600 "$SECRETS_DIR"/pgpass_* 2>/dev/null || true
if [ ! -f "$SECRETS_DIR/seaweed-s3.json" ]; then   # S3 identity for SeaweedFS (mounted read-only by compose)
  SEAWEED_ACCESS_KEY="$(openssl rand -hex 16)"
  SEAWEED_SECRET_KEY="$(openssl rand -base64 32 | tr -d '\n')"
  cat > "$SECRETS_DIR/seaweed-s3.json" <<SEAWEED
{
  "identities": [
    {
      "name": "mnemosyne",
      "credentials": [{"accessKey": "$SEAWEED_ACCESS_KEY", "secretKey": "$SEAWEED_SECRET_KEY"}],
      "actions": ["Read", "Write", "List", "Tagging"]
    }
  ]
}
SEAWEED
fi

echo "==> 2. step-ca: bring up, export the ROOT cert so Caddy chains to a real (non-self-signed) CA"
STEP_CA_ROOT="$SECRETS_DIR/step-ca-root.crt"
STEP_CA_ROOT_NEXT="${STEP_CA_ROOT}.next"
[ ! -L "$STEP_CA_ROOT" ] || { echo "active step-ca trust bundle must not be a symlink" >&2; exit 65; }
[ ! -L "$STEP_CA_ROOT_NEXT" ] || { echo "staged step-ca root must not be a symlink" >&2; exit 65; }
if [ -e "$STEP_CA_ROOT" ] && [ ! -f "$STEP_CA_ROOT" ]; then
  echo "active step-ca trust bundle must be a regular file" >&2
  exit 65
fi
if [ -e "$STEP_CA_ROOT_NEXT" ] && [ ! -f "$STEP_CA_ROOT_NEXT" ]; then
  echo "staged step-ca root must be a regular file" >&2
  exit 65
fi
rm -f "$STEP_CA_ROOT_NEXT"
docker compose -f "$REPO_ROOT/infra/docker-compose.prod.yml" up -d step-ca
sleep 5
STEP_CA_ROOT_TMP=$(mktemp "$SECRETS_DIR/.step-ca-root.crt.XXXXXX")
trap 'rm -f "$STEP_CA_ROOT_TMP"' EXIT
docker compose -f "$REPO_ROOT/infra/docker-compose.prod.yml" exec -T step-ca \
  cat /home/step/certs/root_ca.crt > "$STEP_CA_ROOT_TMP"
chmod 0600 "$STEP_CA_ROOT_TMP"
if [ ! -s "$STEP_CA_ROOT_TMP" ] || \
  ! openssl x509 -in "$STEP_CA_ROOT_TMP" -noout >/dev/null 2>&1; then
  echo "step-ca did not export a valid root certificate" >&2
  exit 65
fi
mv "$STEP_CA_ROOT_TMP" "$STEP_CA_ROOT_NEXT"
trap - EXIT
if [ ! -f "$STEP_CA_ROOT" ]; then
  mv "$STEP_CA_ROOT_NEXT" "$STEP_CA_ROOT"
elif cmp -s "$STEP_CA_ROOT" "$STEP_CA_ROOT_NEXT"; then
  rm -f "$STEP_CA_ROOT_NEXT"
else
  echo "    Current step-ca root differs from the active trust bundle." >&2
  echo "    The active trust bundle was not replaced; the new root remains staged at:" >&2
  echo "      $STEP_CA_ROOT_NEXT" >&2
  echo "    Rotate and validate every dependent certificate in a maintenance window before publishing it." >&2
  exit 78
fi
echo "    ACME provisioner + 90-day (2160h) TLS leaf duration are applied AUTOMATICALLY"
echo "    by the step-ca CMD wrapper (infra/step-ca/mnemo-entrypoint.sh) at container start —"
echo "    no manual 'step ca provisioner add acme' needed; it is idempotent on every boot."
echo "    Trust the root on the host so backends validate the chain (security/no-skip-verify)."
VAULT_TLS_DIR="$SECRETS_DIR/vault-tls"
VAULT_CERT="$VAULT_TLS_DIR/vault.crt"
VAULT_KEY="$VAULT_TLS_DIR/vault.key"
if [ ! -f "$VAULT_CERT" ] || [ ! -f "$VAULT_KEY" ]; then
  echo "    Vault TLS material is missing. Issue it from the current step-ca generation, then rerun bootstrap:"
  echo "      mkdir -p $VAULT_TLS_DIR"
  echo "      step ca certificate vault.mnemo.local $VAULT_CERT.next \\"
  echo "        $VAULT_KEY.next --ca-url https://ca.mnemo.local --root $STEP_CA_ROOT"
  echo "      chmod 0600 $VAULT_KEY.next"
  echo "      infra/validate/validate-production-vault-tls.sh \\"
  echo "        $STEP_CA_ROOT $VAULT_CERT.next $VAULT_KEY.next"
  echo "      mv $VAULT_CERT.next $VAULT_CERT && mv $VAULT_KEY.next $VAULT_KEY"
  exit 78
fi
"$REPO_ROOT/infra/validate/validate-production-vault-tls.sh" \
  "$STEP_CA_ROOT" "$VAULT_CERT" "$VAULT_KEY"

echo "==> 3. Vault: init + unseal (PRODUCTION = sealed, NO dev mode, NO committed root token)"
echo "    Run the real flow against the vault service, store unseal/root material in your"
echo "    seal backend (auto-unseal) — NOT in env/files:"
echo "      vault operator init -key-shares=5 -key-threshold=3"
echo "      vault secrets enable transit"
echo "      vault write -f transit/keys/mnemosyne-session"
echo "      # per-tenant object keys are created on demand: transit/keys/mnemosyne-object-<tenant>"
echo "      vault auth enable approle && configure AppRole for the consolidator (decrypt-only / no wildcard delete)"

echo "==> 4. Keycloak: import the production realm (MFA-gated operator/tier-0 rules)"
echo "    Place realm export at infra/keycloak/mnemosyne-realm.json then:"
echo "      docker compose ... exec keycloak /opt/keycloak/bin/kc.sh import --file /opt/keycloak/data/import/mnemosyne-realm.json"

echo "==> 5. Postgres roles are applied automatically via /docker-entrypoint-initdb.d (roles.sql)."
echo "    After tables exist, apply the GRANTs + ENABLE/FORCE RLS + tenant policies from roles.sql."

echo "==> 6. Models: pull arctic-embed + reranker into the TEI volume on first up (auto)."
echo "    Role-LLM: install Qwen3-4B GGUF for /opt/mnemosyne/bin/role-llm; frontier role adapters plug into /opt/mnemosyne/bin/role-ladder."

echo "==> Bootstrap prepared. Next:"
echo "    cp infra/profiles/self-hosted.env $SECRETS_DIR/production-render.env   # fill non-secret values"
echo "    export MNEMO_SECRETS_DIR=$SECRETS_DIR"
echo "    export KC_DB_PASSWORD=\$(cat $SECRETS_DIR/kc_db_pw) KC_ADMIN_PASSWORD=\$(cat $SECRETS_DIR/kc_admin_pw)"
echo "    docker compose -f infra/docker-compose.prod.yml up -d"
echo "    infra/scripts/render-production-soak-manifest.sh --check-environment"
echo "    # then the per-row capture (infra/PRODUCTION-EVIDENCE.md) for B1-B8, B10."
