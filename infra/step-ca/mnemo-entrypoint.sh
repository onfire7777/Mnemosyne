#!/bin/bash
# Mnemosyne step-ca CMD wrapper — reproducible 90-day TLS leaf duration.
#
# WHY: the stock smallstep/step-ca image only runs `step ca init` (via the image
# ENTRYPOINT + DOCKER_STEPCA_INIT_* env) on a fresh volume, producing an ACME
# provisioner whose x509 leaf duration defaults to 24h. The Mnemosyne TLS gate
# (tls-cert / tls-rotation-plan / tls-lifecycle checks) requires 90-day (2160h)
# leaves. Previously that was patched by hand INSIDE the running container's
# volume-local ca.json, so a fresh `docker compose up` on a clean volume would
# silently revert to 24h. This wrapper makes the 90-day posture reproducible from
# the repo: it runs AFTER the stock entrypoint's init and BEFORE the CA server
# starts, idempotently ensuring an ACME provisioner exists and issues 90-day
# leaves, then execs the real step-ca server.
#
# Wired in infra/docker-compose.prod.yml as the step-ca service `command:` (the
# stock ENTRYPOINT `/bin/bash /entrypoint.sh` still performs `step ca init`, then
# exec's this script as its CMD argument).
#
# IDEMPOTENT: safe to run on every boot. On an already-configured volume it just
# re-asserts the durations (no duplicate provisioner, JWK admin provisioner
# untouched). Only writes to the stepca volume (/home/step), so it is compatible
# with the hardened read_only rootfs.
set -eo pipefail

# Image ENV already provides these; default them defensively so the script is
# also runnable standalone (e.g. isolated verification).
: "${STEPPATH:=/home/step}"
: "${CONFIGPATH:=${STEPPATH}/config/ca.json}"
: "${PWDPATH:=${STEPPATH}/secrets/password}"

# 90 days = 2160h. Overridable, but the defaults ARE the production posture.
TLS_DEFAULT_DUR="${MNEMO_STEPCA_TLS_DEFAULT_DUR:-2160h}"
TLS_MAX_DUR="${MNEMO_STEPCA_TLS_MAX_DUR:-2160h}"
TLS_MIN_DUR="${MNEMO_STEPCA_TLS_MIN_DUR:-5m}"
ACME_NAME="${MNEMO_STEPCA_ACME_PROVISIONER:-acme}"

set_acme_tls_duration() {
    step ca provisioner update "${ACME_NAME}" \
        --x509-default-dur "${TLS_DEFAULT_DUR}" \
        --x509-max-dur "${TLS_MAX_DUR}" \
        --x509-min-dur "${TLS_MIN_DUR}" \
        --ca-config "${CONFIGPATH}"
}

if [ -f "${CONFIGPATH}" ]; then
    # update-first is the existence probe: it fails iff the ACME provisioner is
    # absent (fresh init creates only the JWK admin provisioner). In that case
    # create it, then set the durations. No jq/grep parsing of ca.json needed.
    if ! set_acme_tls_duration 2>/dev/null; then
        step ca provisioner add "${ACME_NAME}" --type ACME --ca-config "${CONFIGPATH}"
        set_acme_tls_duration
    fi
    echo "[mnemo-step-ca] ACME provisioner '${ACME_NAME}' TLS leaf duration set:" \
         "default=${TLS_DEFAULT_DUR} max=${TLS_MAX_DUR} min=${TLS_MIN_DUR}"
else
    echo "[mnemo-step-ca] WARNING: ${CONFIGPATH} not found; the stock init did not run." \
         "Skipping TLS-duration setup." >&2
fi

# Hand off to the real CA server (mirrors the stock image CMD).
exec /usr/local/bin/step-ca --password-file "${PWDPATH}" "${CONFIGPATH}"
