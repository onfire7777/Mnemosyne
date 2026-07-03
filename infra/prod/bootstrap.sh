#!/usr/bin/env bash
# Mnemosyne — production bootstrap (self-hosted, no-GPU). Idempotent first-run setup.
# Run ONCE before `docker compose -f infra/docker-compose.prod.yml up -d`.
# This prepares real, non-self-signed, non-dev infrastructure. It writes NO secrets to the repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SECRETS_DIR="${MNEMO_SECRETS_DIR:-/secure/outside/repo}"   # external, outside the repo
HOST="${MNEMO_HOST:-mnemo.local}"

echo "==> 0. Preconditions"
command -v docker >/dev/null || { echo "docker required"; exit 1; }
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
docker compose -f "$REPO_ROOT/infra/docker-compose.prod.yml" up -d step-ca
sleep 5
docker compose -f "$REPO_ROOT/infra/docker-compose.prod.yml" exec -T step-ca \
  cat /home/step/certs/root_ca.crt > "$SECRETS_DIR/step-ca-root.crt"
echo "    Add an ACME provisioner:  step ca provisioner add acme --type ACME"
echo "    Trust the root on the host so backends validate the chain (security/no-skip-verify)."
echo "    Issue the Vault leaf (infra/vault/vault.hcl expects it under \$MNEMO_SECRETS_DIR/vault-tls/):"
echo "      mkdir -p $SECRETS_DIR/vault-tls"
echo "      step ca certificate vault.mnemo.local $SECRETS_DIR/vault-tls/vault.crt \\"
echo "        $SECRETS_DIR/vault-tls/vault.key --ca-url https://ca.mnemo.local --root $SECRETS_DIR/step-ca-root.crt"

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
