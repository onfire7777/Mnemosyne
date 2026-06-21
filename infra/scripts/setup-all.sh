#!/usr/bin/env bash
#
# setup-all.sh — seed all three providers in order: Keycloak realm, Vault
# transit, and the C2PA test cert + signed asset.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "############################################################"
echo "# 1/3  Keycloak realm + client + users + JWKS"
echo "############################################################"
"${HERE}/setup-keycloak.sh"

echo
echo "############################################################"
echo "# 2/3  Vault transit engine + KEK + policy + scoped token"
echo "############################################################"
"${HERE}/setup-vault.sh"

echo
echo "############################################################"
echo "# 3/3  C2PA test trust root + signed asset + trust policy"
echo "############################################################"
"${HERE}/setup-c2pa.sh"

echo
echo "==> All providers seeded. Next: ./infra/validate/validate-all.sh"
