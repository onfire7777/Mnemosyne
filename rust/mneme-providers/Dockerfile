# syntax=docker/dockerfile:1.7

ARG RUST_IMAGE=rust:1.88-trixie
ARG DEBIAN_IMAGE=debian:trixie-slim

FROM ${RUST_IMAGE} AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
ARG MNEME_PROVIDERS_FEATURES=models
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/src/target \
    cargo build --release --features "${MNEME_PROVIDERS_FEATURES}" \
      --bin mneme-providers --bin mneme-providers-prefetch && \
    mkdir -p /out && \
    cp target/release/mneme-providers target/release/mneme-providers-prefetch /out/

FROM ${DEBIAN_IMAGE} AS models
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libgomp1 libssl3t64 libstdc++6 && \
    rm -rf /var/lib/apt/lists/*
ENV FASTEMBED_CACHE_DIR=/models \
    HF_HOME=/models \
    HF_HUB_OFFLINE=0 \
    MNEME_PROVIDERS_BACKEND=fastembed \
    MNEMOSYNE_EMBEDDING_DIMS=1024 \
    MNEMOSYNE_EMBEDDING_MODEL=EmbeddingGemma300MQ \
    MNEMOSYNE_RERANKER_MODEL=JinaRerankerV1TurboEN
COPY --from=build /out/mneme-providers-prefetch /usr/local/bin/mneme-providers-prefetch
RUN /usr/local/bin/mneme-providers-prefetch && chmod -R a+rX /models

FROM ${DEBIAN_IMAGE} AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libgomp1 libssl3t64 libstdc++6 && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin mneme
ENV FASTEMBED_CACHE_DIR=/models \
    HF_HOME=/models \
    HF_HUB_OFFLINE=1 \
    MNEME_PROVIDERS_BACKEND=fastembed \
    MNEMOSYNE_EMBEDDING_DIMS=1024 \
    MNEMOSYNE_EMBEDDING_MODEL=EmbeddingGemma300MQ \
    MNEMOSYNE_RERANKER_MODEL=JinaRerankerV1TurboEN \
    MNEME_PROVIDERS_BIND=0.0.0.0:8000
COPY --from=models /models /models
COPY --from=build /out/mneme-providers /usr/local/bin/mneme-providers
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["mneme-providers"]
