# Real c2patool image for Mnemosyne provenance (FR-19).
#
# Installs the official c2patool from crates.io (real C2PA signing and
# verification) plus openssl for the test certificate root. The image is used
# both to mint a test cert + signed asset (setup-c2pa.sh) and as the runtime
# c2patool that Mnemosyne's C2paToolVerifier shells out to.
#
# Pinned c2patool version for reproducibility; bump deliberately.
FROM rust:1.81-slim-bookworm AS build
ARG C2PATOOL_VERSION=0.9.12
RUN apt-get update \
 && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN cargo install c2patool --version "${C2PATOOL_VERSION}" --locked --root /usr/local

FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates jq python3 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin/c2patool /usr/local/bin/c2patool
RUN mkdir -p /work/out
WORKDIR /work
# Sanity: fail the build if the binary is not runnable.
RUN c2patool --version
