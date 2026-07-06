# Mnemosyne application image for the self-hosted production stack.
# Built by infra/docker-compose.prod.yml with build context at the repo root:
#   build: { context: .., dockerfile: infra/Dockerfile, target: runtime }
# Hardened-runtime friendly: non-root, no writes outside /tmp (tmpfs), single
# role-dispatching entrypoint (MNEMOSYNE_ROLE=api|consolidator).
#
# Stages:
#   runtime     — the production image every deployed service runs (default target
#                 for all prod services; compose pins `target: runtime` explicitly).
#   test-runner — runtime + the repo's dev test extras (pytest/hypothesis/
#                 pytest-benchmark). Used ONLY by the profile-gated `test-runner`
#                 compose service for the row-10 live-parity suite. Never deployed
#                 as a long-running production service.

# Optional native kernels (mnemosyne_native, pyo3 abi3-py312). Pure Python
# stays canonical: the wheel only accelerates byte-parity-proven kernels and
# MNEMOSYNE_PURE=1 disables it at runtime (src/mnemosyne/text.py dispatch).
FROM rust:1.95-slim AS native-builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir --break-system-packages 'maturin>=1.14,<2'
COPY rust/mnemosyne-native /native/mnemosyne-native
WORKDIR /native/mnemosyne-native
# --compatibility linux: installed into our own matching image below, so no
# manylinux audit is needed (and none of its toolchain enters the image).
RUN maturin build --release --out /wheels --compatibility linux

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/mnemosyne

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir '.[postgres,mcp]'
COPY --from=native-builder /wheels /tmp/native-wheels
RUN pip install --no-cache-dir /tmp/native-wheels/*.whl \
    && rm -rf /tmp/native-wheels \
    && python -c "import mnemosyne_native as n; print('native kernels baked:', n.parity_marker())"

COPY infra/entrypoint.sh /usr/local/bin/mnemo-entrypoint
# Command-backed providers at the paths the self-hosted profile references.
COPY infra/vault/vault-object-key-provider.py /opt/mnemosyne/bin/vault-object-key
COPY infra/vault/vault-session-secret-provider.py /opt/mnemosyne/bin/vault-session-secret
COPY infra/providers/role-llm.py /opt/mnemosyne/bin/role-llm
COPY infra/providers/role-ladder.py /opt/mnemosyne/bin/role-ladder
# Hosted HTTPS role provider service (B4/B9): wraps role-llm's dispatch over
# HTTP; fronted by Caddy at roles.mnemo.local. Keeps role-llm's .py-less sibling
# name resolvable (role-http loads role-llm by explicit source loader).
COPY infra/providers/role-http.py /opt/mnemosyne/bin/role-http
# B6 multimodal: command-backed media text extractor + bge-backed media embedder.
COPY infra/providers/media-text-extractor.py /opt/mnemosyne/bin/media-text-extractor
COPY infra/providers/media-embedding.py /opt/mnemosyne/bin/media-embedding
# Minimal self-hosted alert receiver (B8 core): vmalert notifier delivery target.
COPY infra/observability/alert-sink.py /opt/mnemosyne/bin/alert-sink
RUN chmod 0755 /usr/local/bin/mnemo-entrypoint /opt/mnemosyne/bin/*

# Non-root; matches the compose hardening (read_only, cap_drop ALL, no-new-privileges).
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin mnemosyne
# Pre-create the runtime data mountpoint owned by the non-root user. A fresh
# named volume inherits this ownership on first mount, so the AES-GCM object
# store and Vault-wrapped DEK sidecars (MNEMOSYNE_VAULT_WRAP_DIR=/data/...) are
# writable without a runtime root chown (the rootfs is read_only).
RUN mkdir -p /data/wrapped-keys /pub && chown -R 10001:10001 /data /pub
USER 10001:10001

ENTRYPOINT ["/usr/local/bin/mnemo-entrypoint"]

# ---------------------------------------------------------------------------
# Row-10 live-parity test runner: the exact production runtime plus the repo's
# pinned dev test extras (pyproject [dependency-groups].dev, minus lint-only
# ruff). Kept as a separate stage so the deployed images stay byte-identical
# to `runtime`; compose services all pin `target: runtime`.
# ---------------------------------------------------------------------------
FROM runtime AS test-runner
USER 0
# git: the g0 harness / evidence-capture tests resolve repo provenance by
# shelling out to git against the bind-mounted repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    # the bind-mounted repo is owned by the host user, not uid 10001
    && git config --system safe.directory /Users/admin/Mnemosyne
RUN pip install --no-cache-dir 'pytest==9.1.1' 'hypothesis>=6.100' 'pytest-benchmark>=5.1'
USER 10001:10001
