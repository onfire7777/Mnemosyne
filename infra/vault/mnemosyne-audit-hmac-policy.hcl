# Least-privilege Vault policy for the append-only audit hash-chain anchor.
#
# The audit hash chain is anchored with an HMAC produced by the `mnemosyne-audit`
# transit key so the key never leaves Vault. This policy authorises ONLY the HMAC
# (and verify) operation on that single key — it cannot read raw key material,
# rotate/delete keys, or reach unrelated transit keys (object-key KEKs, session).
#
# Apply with an admin token (matches the setup-vault.sh bootstrap pattern):
#   vault policy write mnemosyne-audit-hmac infra/vault/mnemosyne-audit-hmac-policy.hcl
#   vault token create -policy=mnemosyne-audit-hmac -period=720h -no-default-policy=false
# then hand the scoped token to the ops-report audit-hmac adapter out-of-band.

# Compute the head-anchor HMAC over the chain head digest.
path "transit/hmac/mnemosyne-audit/sha2-256" {
  capabilities = ["create", "update"]
}

path "transit/hmac/mnemosyne-audit" {
  capabilities = ["create", "update"]
}

# Verify a retained anchor without exposing the key.
path "transit/verify/mnemosyne-audit/sha2-256" {
  capabilities = ["create", "update"]
}
