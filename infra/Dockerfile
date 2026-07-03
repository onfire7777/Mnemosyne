# Mnemosyne application image for the self-hosted production stack.
# Built by infra/docker-compose.prod.yml with build context at the repo root:
#   build: { context: .., dockerfile: infra/Dockerfile }
# Hardened-runtime friendly: non-root, no writes outside /tmp (tmpfs), single
# role-dispatching entrypoint (MNEMOSYNE_ROLE=api|consolidator).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/mnemosyne

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir '.[postgres,mcp]'

COPY infra/entrypoint.sh /usr/local/bin/mnemo-entrypoint
# Command-backed providers at the paths the self-hosted profile references.
COPY infra/vault/vault-object-key-provider.py /opt/mnemosyne/bin/vault-object-key
COPY infra/vault/vault-session-secret-provider.py /opt/mnemosyne/bin/vault-session-secret
COPY infra/providers/role-llm.py /opt/mnemosyne/bin/role-llm
COPY infra/providers/role-ladder.py /opt/mnemosyne/bin/role-ladder
RUN chmod 0755 /usr/local/bin/mnemo-entrypoint /opt/mnemosyne/bin/*

# Non-root; matches the compose hardening (read_only, cap_drop ALL, no-new-privileges).
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin mnemosyne
USER 10001:10001

ENTRYPOINT ["/usr/local/bin/mnemo-entrypoint"]
