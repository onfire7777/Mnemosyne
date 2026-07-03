#!/usr/bin/env bash
#
# Fail-closed supply-chain gate for the self-hosted production stack.
# Produces scanner/SBOM/signature artifacts under an operator-chosen external path.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: infra/scripts/verify-supply-chain.sh [--out-dir DIR] [--compose-file FILE]

Required tools: docker, gitleaks, trivy, syft, grype, cosign.

Cosign policy must be configured with one of:
  MNEMOSYNE_COSIGN_KEY=/path/to/cosign.pub
  MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY=... and MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER=...
  MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY_REGEXP=... and MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER=...

Environment knobs:
  MNEMOSYNE_TRIVY_SEVERITY=HIGH,CRITICAL
  MNEMOSYNE_GRYPE_FAIL_ON=high
  MNEMOSYNE_SUPPLY_CHAIN_OUT=/external/evidence/supply-chain
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${MNEMOSYNE_PROD_COMPOSE_FILE:-${REPO_ROOT}/infra/docker-compose.prod.yml}"
OUT_DIR="${MNEMOSYNE_SUPPLY_CHAIN_OUT:-}"
TRIVY_SEVERITY="${MNEMOSYNE_TRIVY_SEVERITY:-HIGH,CRITICAL}"
GRYPE_FAIL_ON="${MNEMOSYNE_GRYPE_FAIL_ON:-high}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir)
      OUT_DIR="${2:?--out-dir requires a directory}"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="${2:?--compose-file requires a file}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "required supply-chain tool is missing: $1" >&2
    exit 127
  }
}

slug() {
  printf '%s' "$1" | tr -cs 'A-Za-z0-9_.-' '_' | sed 's/_$//'
}

require_tool docker
require_tool gitleaks
require_tool trivy
require_tool syft
require_tool grype
require_tool cosign

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "compose file not found: $COMPOSE_FILE" >&2
  exit 2
fi
if [[ -z "$OUT_DIR" ]]; then
  echo "set MNEMOSYNE_SUPPLY_CHAIN_OUT or pass --out-dir; scanner artifacts must be retained outside the repo" >&2
  exit 2
fi

cosign_args=()
if [[ -n "${MNEMOSYNE_COSIGN_KEY:-}" ]]; then
  cosign_args=(--key "$MNEMOSYNE_COSIGN_KEY")
elif [[ -n "${MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY:-}" && -n "${MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER:-}" ]]; then
  cosign_args=(
    --certificate-identity "$MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY"
    --certificate-oidc-issuer "$MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER"
  )
elif [[ -n "${MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY_REGEXP:-}" && -n "${MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER:-}" ]]; then
  cosign_args=(
    --certificate-identity-regexp "$MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY_REGEXP"
    --certificate-oidc-issuer "$MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER"
  )
else
  echo "cosign verification policy is unset; configure a key or keyless identity+issuer" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
{
  echo "repo_root=$REPO_ROOT"
  echo "compose_file=$COMPOSE_FILE"
  echo "trivy_severity=$TRIVY_SEVERITY"
  echo "grype_fail_on=$GRYPE_FAIL_ON"
  echo "generated_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT_DIR/supply-chain.manifest"

echo "==> gitleaks git history"
gitleaks git --redact --report-format json --report-path "$OUT_DIR/gitleaks-git.json" "$REPO_ROOT"

echo "==> gitleaks current tree"
gitleaks dir --redact --report-format json --report-path "$OUT_DIR/gitleaks-dir.json" "$REPO_ROOT"

echo "==> trivy filesystem"
trivy fs \
  --scanners vuln,secret,config \
  --severity "$TRIVY_SEVERITY" \
  --exit-code 1 \
  --format json \
  --output "$OUT_DIR/trivy-fs.json" \
  "$REPO_ROOT"

echo "==> syft filesystem SBOM"
syft "$REPO_ROOT" \
  -o "spdx-json=$OUT_DIR/syft-repo.spdx.json" \
  -o "cyclonedx-json=$OUT_DIR/syft-repo.cdx.json"

echo "==> grype filesystem"
grype "dir:$REPO_ROOT" --fail-on "$GRYPE_FAIL_ON" -o json > "$OUT_DIR/grype-repo.json"

echo "==> production registry images"
mapfile -t images < <(
  env \
    MNEMO_SECRETS_DIR="${MNEMO_SECRETS_DIR:-/secure/outside/repo}" \
    KC_DB_PASSWORD="${KC_DB_PASSWORD:-supply-chain-placeholder}" \
    KC_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:-supply-chain-placeholder}" \
    docker compose -f "$COMPOSE_FILE" config --images | sort -u
)
if [[ ${#images[@]} -eq 0 ]]; then
  echo "no registry images resolved from $COMPOSE_FILE" >&2
  exit 2
fi

registry_images=()
local_build_images=()
for image in "${images[@]}"; do
  if [[ "$image" != *@sha256:* ]]; then
    if [[ "$image" == *"/"* || "$image" == *":"* ]]; then
      echo "registry image is not digest-pinned: $image" >&2
      exit 1
    fi
    local_build_images+=("$image")
    continue
  fi
  registry_images+=("$image")
done

if [[ ${#registry_images[@]} -eq 0 ]]; then
  echo "no digest-pinned registry images resolved from $COMPOSE_FILE" >&2
  exit 2
fi
if [[ ${#local_build_images[@]} -gt 0 ]]; then
  printf 'local_build_images=%s\n' "${local_build_images[*]}" >> "$OUT_DIR/supply-chain.manifest"
fi

for image in "${registry_images[@]}"; do
  image_slug="$(slug "$image")"
  echo "==> $image"
  cosign verify "${cosign_args[@]}" "$image" > "$OUT_DIR/cosign-${image_slug}.json"
  trivy image \
    --image-src remote \
    --severity "$TRIVY_SEVERITY" \
    --exit-code 1 \
    --format json \
    --output "$OUT_DIR/trivy-image-${image_slug}.json" \
    "$image"
  syft "registry:$image" \
    -o "spdx-json=$OUT_DIR/syft-image-${image_slug}.spdx.json" \
    -o "cyclonedx-json=$OUT_DIR/syft-image-${image_slug}.cdx.json"
  grype "registry:$image" --fail-on "$GRYPE_FAIL_ON" -o json > "$OUT_DIR/grype-image-${image_slug}.json"
done

echo "supply-chain gate passed; artifacts: $OUT_DIR"
