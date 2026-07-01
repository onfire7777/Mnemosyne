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
RUN chmod 0755 /usr/local/bin/mnemo-entrypoint

# Non-root; matches the compose hardening (read_only, cap_drop ALL, no-new-privileges).
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin mnemosyne
USER 10001:10001

ENTRYPOINT ["/usr/local/bin/mnemo-entrypoint"]
