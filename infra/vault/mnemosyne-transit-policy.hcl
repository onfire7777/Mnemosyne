# Least-privilege Vault policy for Mnemosyne's command-backed object-key
# provider. It can encrypt (wrap a DEK), decrypt (unwrap a DEK), read key
# metadata, rotate the KEK, and delete (crypto-shred) per-object keys. It
# deliberately cannot read raw key material or manage unrelated mounts.
#
# Applied by setup-vault.sh as policy "mnemosyne-transit".

# Wrap a freshly generated data-encryption key under the named transit KEK.
path "transit/encrypt/mnemosyne-objects" {
  capabilities = ["update"]
}

# Unwrap a previously wrapped data-encryption key.
path "transit/decrypt/mnemosyne-objects" {
  capabilities = ["update"]
}

# Generate a high-entropy data key (plaintext + wrapped) in one call.
path "transit/datakey/plaintext/mnemosyne-objects" {
  capabilities = ["update"]
}

# Rotate the backing KEK (advances the key version; old ciphertext stays
# decryptable until min_decryption_version is raised).
path "transit/keys/mnemosyne-objects/rotate" {
  capabilities = ["update"]
}

# Read non-sensitive key metadata (latest version, type, deletion_allowed).
path "transit/keys/mnemosyne-objects" {
  capabilities = ["read"]
}

# Update key config (enable deletion / trim) to support crypto-shred.
path "transit/keys/mnemosyne-objects/config" {
  capabilities = ["update"]
}

# Per-object transit keys used for true crypto-shred (delete the key ->
# the wrapped DEK can never be unwrapped again).
path "transit/encrypt/mnemosyne-object-*" {
  capabilities = ["update"]
}

path "transit/decrypt/mnemosyne-object-*" {
  capabilities = ["update"]
}

path "transit/keys/mnemosyne-object-*" {
  capabilities = ["create", "read", "update", "delete"]
}

path "transit/keys/mnemosyne-object-*/config" {
  capabilities = ["update"]
}
