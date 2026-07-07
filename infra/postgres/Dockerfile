# Mnemosyne production Postgres: the pinned pgvector/pgvector:pg16 retrieval
# engine + pgaudit for the tamper-evident audit rail (blueprint: hash-chained
# append-only audit_log + pgaudit + WORM copy). pgaudit is a PGDG package for
# PostgreSQL 16 and is loaded via shared_preload_libraries in the compose command.
#
# Built FROM the digest-pinned base so supply-chain provenance is preserved
# (verify-supply-chain.sh). apt runs as root at build time; the runtime user is
# pinned to 999:999 by the compose service, so no trailing USER is set here.
FROM pgvector/pgvector:pg16@sha256:ad2e18408bf447f62092a8a5259e7df10505c5a0360bd1a1853ac8b8b0763da2

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-16-pgaudit; \
    rm -rf /var/lib/apt/lists/*
