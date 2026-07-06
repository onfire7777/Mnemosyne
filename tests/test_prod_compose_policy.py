"""Policy-as-code gate for the self-hosted production compose stack.

The header of ``infra/docker-compose.prod.yml`` requires CI to enforce the
hardening contract (no docker.sock, non-root, read_only, cap_drop ALL, limits)
and the architecture doc (`docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md` §7)
lists this gate as a required additive component. These checks are
text-structural (stdlib only — the project takes no new dependencies) and are
deliberately conservative: they pin the invariants of the committed file rather
than fully parsing YAML.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra"
COMPOSE = INFRA / "docker-compose.prod.yml"
SUPPLY_CHAIN_SCRIPT = INFRA / "scripts" / "verify-supply-chain.sh"

# cap_add is allowed only where the service cannot function without it.
CAP_ADD_ALLOWLIST = {
    "caddy": {"NET_BIND_SERVICE"},  # binds :443 as non-root
    "vault": {"IPC_LOCK"},  # mlock for sealed-memory pages
    "step-ca": {"NET_BIND_SERVICE"},  # binary ships file caps; bounded gain, see compose comment
    "host-llm-proxy": {"NET_BIND_SERVICE"},  # caddy binary ships file caps; needed to exec under no-new-privileges (relay listens on :11434)
}

# The sole ingress: the only service allowed to publish host ports.
SOLE_INGRESS = "caddy"

# Data-plane services must be isolated from the edge network.
DATASEC_ONLY = {"postgres", "vault"}

EXPECTED_SERVICES = {
    "caddy",
    "step-ca",
    "postgres",
    "embedder",
    "keycloak",
    "vault",
    "seaweedfs",
    "victoriametrics",
    "vmalert",
    "grafana",
    "mnemo-api",
    "mnemo-consolidator",
    "ollama",
    "operator",
}


def _compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def _service_blocks(text: str) -> dict[str, str]:
    """Split the ``services:`` mapping into named per-service text blocks."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "services:")
    except StopIteration:  # pragma: no cover - structural precondition
        raise AssertionError("docker-compose.prod.yml must declare a services: block")
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break  # next top-level key (volumes:, secrets:, ...)
        name_match = re.match(r"^  ([A-Za-z0-9_-]+):", line)
        if name_match:
            current = name_match.group(1)
            blocks[current] = [line]
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(body) for name, body in blocks.items()}


def _top_level_section(text: str, key: str) -> str:
    match = re.search(rf"^{key}:\n((?:[ \t].*\n|\n)*)", text, flags=re.MULTILINE)
    assert match, f"docker-compose.prod.yml must declare a {key}: block"
    return match.group(1)


def test_hardened_anchor_pins_the_baseline() -> None:
    text = _compose_text()
    anchor = re.search(r"^x-hardened: &hardened\n((?:[ \t].*\n)*)", text, flags=re.MULTILINE)
    assert anchor, "the shared x-hardened anchor must exist"
    body = anchor.group(1)
    assert "read_only: true" in body
    assert "no-new-privileges:true" in body
    assert 'cap_drop: ["ALL"]' in body
    assert "pids_limit:" in body
    assert "init: true" in body


def test_every_service_inherits_the_hardened_anchor() -> None:
    services = _service_blocks(_compose_text())
    assert services, "no services parsed from docker-compose.prod.yml"
    missing = [name for name, block in services.items() if "<<: *hardened" not in block]
    assert not missing, f"services missing the hardened anchor: {missing}"


def test_service_blocks_do_not_repeat_singleton_keys() -> None:
    singleton_keys = {
        "build",
        "cap_add",
        "command",
        "depends_on",
        "entrypoint",
        "environment",
        "healthcheck",
        "image",
        "networks",
        "ports",
        "secrets",
        "user",
        "volumes",
    }
    for name, block in _service_blocks(_compose_text()).items():
        keys = re.findall(r"^    ([A-Za-z0-9_-]+):", block, flags=re.MULTILINE)
        repeated = sorted({key for key in keys if key in singleton_keys and keys.count(key) > 1})
        assert not repeated, f"service {name} repeats singleton compose keys: {repeated}"


def test_expected_phase8_services_are_present() -> None:
    services = set(_service_blocks(_compose_text()))
    missing = EXPECTED_SERVICES - services
    assert not missing, f"production compose is missing Phase 8 services: {sorted(missing)}"


def test_profiles_retain_forbid_local_guidance() -> None:
    for profile in ("self-hosted.env", "cloud.env"):
        text = (INFRA / "profiles" / profile).read_text(encoding="utf-8").lower()
        assert "forbid_local:true" in text or "forbid_local: true" in text


def test_docker_socket_is_never_mounted() -> None:
    effective = "\n".join(
        line.split("#", 1)[0] for line in _compose_text().splitlines()
    )
    assert "docker.sock" not in effective


def test_only_the_sole_ingress_publishes_ports() -> None:
    services = _service_blocks(_compose_text())
    publishers = [name for name, block in services.items() if re.search(r"^\s+ports:", block, re.MULTILINE)]
    assert publishers == [SOLE_INGRESS], f"only {SOLE_INGRESS} may publish ports, found: {publishers}"


def test_cap_add_is_allowlisted() -> None:
    services = _service_blocks(_compose_text())
    for name, block in services.items():
        match = re.search(r"cap_add:\s*\[([^\]]*)\]", block)
        caps = {cap.strip().strip('"') for cap in match.group(1).split(",")} if match else set()
        allowed = CAP_ADD_ALLOWLIST.get(name, set())
        assert caps <= allowed, f"service {name} adds capabilities beyond its allowlist: {caps - allowed}"


def test_every_registry_image_is_digest_pinned() -> None:
    for line in _compose_text().splitlines():
        match = re.match(r"^\s+image:\s*(\S+)", line)
        if not match:
            continue
        image = match.group(1)
        assert re.match(r"^[^@\s]+:[^@\s]+@sha256:[0-9a-f]{64}$", image), (
            f"registry image must be tag+digest pinned: {image}"
        )


def test_internal_networks_are_internal() -> None:
    networks = _top_level_section(_compose_text(), "networks")
    for name in ("internal", "datasec", "hostllm"):
        line = re.search(rf"^\s+{name}:\s*(.*)$", networks, flags=re.MULTILINE)
        assert line and "internal: true" in line.group(1), f"network {name} must declare internal: true"


def _service_networks(services: dict[str, str], name: str) -> set[str]:
    block = services[name]
    inline = re.search(r"networks:\s*\[([^\]]*)\]", block)
    if inline:
        return {net.strip() for net in inline.group(1).split(",") if net.strip()}
    mapping = re.search(r"^    networks:[^\n]*\n((?:      .*\n)*)", block + "\n", re.MULTILINE)
    if not mapping:
        return set()
    return set(re.findall(r"^      (edge|internal|datasec|hostllm|hostbridge):", mapping.group(1), re.MULTILINE))


def test_network_segmentation_holds() -> None:
    services = _service_blocks(_compose_text())

    def nets(name: str) -> set[str]:
        networks = _service_networks(services, name)
        assert networks, f"service {name} must declare its networks"
        return networks

    for name in DATASEC_ONLY:
        assert "edge" not in nets(name), f"{name} must never be edge-reachable"
        assert "datasec" in nets(name), f"{name} belongs on the datasec network"
    assert nets("vault") == {"datasec"}, "vault is reachable only from the datasec network"
    assert "edge" not in nets("mnemo-consolidator"), "the consolidator must never be edge-reachable"
    assert "datasec" not in nets(SOLE_INGRESS), "the ingress must never reach the data-security network"


def test_host_llm_relay_network_is_least_privilege() -> None:
    """The default host-llm relay bridges to the host's unauthenticated Ollama.

    It must sit on its OWN dedicated host-egress network (hostbridge, relay-only)
    plus the client network (hostllm) — never edge or the general internal
    network — so caddy/api/stream can never reach the unauthenticated VM→host
    bridge, and only the sanctioned LLM clients (consolidator, role-http, and the
    profile-gated operator/test-runner bastions) may join hostllm.
    """
    services = _service_blocks(_compose_text())
    assert _service_networks(services, "host-llm-proxy") == {"hostbridge", "hostllm"}, (
        "the relay is hostbridge (relay-only host-gateway route) + hostllm only — NOT edge/internal"
    )
    on_hostllm = {name for name in services if "hostllm" in _service_networks(services, name)}
    assert on_hostllm == {"host-llm-proxy", "mnemo-consolidator", "role-http", "operator", "test-runner"}, (
        "only the sanctioned LLM clients may reach the host-llm relay"
    )


def test_repo_relative_mounts_exist() -> None:
    for line in _compose_text().splitlines():
        match = re.match(r"^\s+-\s+(\./[^:]+):", line)
        if not match:
            continue
        mounted = INFRA / match.group(1)[2:]
        assert mounted.exists(), f"compose mounts a repo path that does not exist: {match.group(1)}"


def test_secret_files_live_outside_the_repo() -> None:
    secrets = _top_level_section(_compose_text(), "secrets")
    paths = [p.strip('"') for p in re.findall(r"file:\s*([^\s}]+)", secrets)]
    assert paths, "the secrets block must reference external files"
    for path in paths:
        # absolute external path, or an env-parameterized path whose default is external
        assert (path.startswith("/") or path.startswith("${")) and not path.startswith(str(REPO_ROOT)), (
            f"secret files must be absolute and external to the repo: {path}"
        )
        assert "./" not in path, f"secret files must never be repo-relative: {path}"


def test_build_services_reference_existing_docker_assets() -> None:
    text = _compose_text()
    # dockerfile may be followed by more inline-map keys (e.g. `target: runtime`),
    # so the capture must stop at a comma as well as whitespace/`}`.
    for context, dockerfile in set(re.findall(r"context:\s*([^\s,}]+),\s*dockerfile:\s*([^\s,}]+)", text)):
        resolved = (INFRA / context / dockerfile).resolve()
        assert resolved.is_file(), f"missing build dockerfile: {context}/{dockerfile}"
    assert (INFRA / "entrypoint.sh").is_file(), "infra/entrypoint.sh (image entrypoint) must exist"
    for env_file in set(re.findall(r"env_file:\s*\[([^\]]*)\]", text)):
        for ref in env_file.split(","):
            ref_path = INFRA / ref.strip()[2:] if ref.strip().startswith("./") else Path(ref.strip())
            assert ref_path.is_file(), f"missing env_file referenced by compose: {ref.strip()}"


def test_supply_chain_gate_is_wired_for_required_tools() -> None:
    body = SUPPLY_CHAIN_SCRIPT.read_text(encoding="utf-8")
    assert SUPPLY_CHAIN_SCRIPT.stat().st_mode & 0o111, "supply-chain gate must be executable"
    for tool in ("docker", "gitleaks", "trivy", "syft", "grype", "cosign"):
        assert f"require_tool {tool}" in body
    for command in (
        "gitleaks git",
        "gitleaks dir",
        "trivy fs",
        "trivy image",
        "syft \"$REPO_ROOT\"",
        "syft \"registry:$image\"",
        "grype \"dir:$REPO_ROOT\"",
        "cosign verify",
        "config --images",
        "supply-chain-placeholder",
    ):
        assert command in body
    assert "MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY" in body
    assert "MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER" in body
    assert "MNEMOSYNE_COSIGN_KEY" in body
    assert ".artifacts" not in body


def test_supply_chain_gate_shell_syntax_is_valid() -> None:
    result = subprocess.run(
        ["/bin/bash", "-n", str(SUPPLY_CHAIN_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_prod_docs_call_the_supply_chain_gate() -> None:
    docs = [
        INFRA / "prod" / "README.md",
        REPO_ROOT / "docs" / "SELF-HOSTED-PRODUCTION-ARCHITECTURE.md",
        REPO_ROOT / ".planning" / "phases" / "08-self-hosted-first-production" / "08-01-PLAN.md",
    ]
    for path in docs:
        assert "infra/scripts/verify-supply-chain.sh" in path.read_text(encoding="utf-8")
