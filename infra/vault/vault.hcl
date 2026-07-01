# Vault server config for the self-hosted production stack (docker-compose.prod.yml).
# PRODUCTION: sealed by default, file storage, NO dev mode, NO committed root token.
# TLS chains to the internal step-ca (real, non-self-signed) — issue the leaf with:
#   step ca certificate vault.mnemo.local vault.crt vault.key --ca-url https://ca.mnemo.local
# and place vault.crt / vault.key under $MNEMO_SECRETS_DIR/vault-tls/ (mounted at /vault/tls).

ui            = false
disable_mlock = false   # IPC_LOCK is granted to the vault service in the compose file

storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/vault/tls/vault.crt"
  tls_key_file  = "/vault/tls/vault.key"
}

# Reachable only on the isolated `datasec` internal network; the consolidator is
# the sole client. api_addr matches the step-ca-issued SAN.
api_addr = "https://vault.mnemo.local:8200"
