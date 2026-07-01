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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra"
COMPOSE = INFRA / "docker-compose.prod.yml"

# cap_add is allowed only where the service cannot function without it.
CAP_ADD_ALLOWLIST = {
    "caddy": {"NET_BIND_SERVICE"},  # binds :443 as non-root
    "vault": {"IPC_LOCK"},  # mlock for sealed-memory pages
}

# The sole ingress: the only service allowed to publish host ports.
SOLE_INGRESS = "caddy"

# Data-plane services must be isolated from the edge network.
DATASEC_ONLY = {"postgres", "vault"}


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


def test_every_image_is_tag_pinned() -> None:
    for line in _compose_text().splitlines():
        match = re.match(r"^\s+image:\s*(\S+)", line)
        if not match:
            continue
        image = match.group(1)
        assert ":" in image and not image.endswith(":latest"), f"image must be tag-pinned (not :latest): {image}"


def test_internal_networks_are_internal() -> None:
    networks = _top_level_section(_compose_text(), "networks")
    for name in ("internal", "datasec"):
        line = re.search(rf"^\s+{name}:\s*(.*)$", networks, flags=re.MULTILINE)
        assert line and "internal: true" in line.group(1), f"network {name} must declare internal: true"


def test_network_segmentation_holds() -> None:
    services = _service_blocks(_compose_text())

    def nets(name: str) -> set[str]:
        match = re.search(r"networks:\s*\[([^\]]*)\]", services[name])
        assert match, f"service {name} must declare its networks inline"
        return {net.strip() for net in match.group(1).split(",")}

    for name in DATASEC_ONLY:
        assert nets(name) == {"datasec"}, f"{name} must live only on the datasec network"
    assert "datasec" not in nets("mnemo-api"), "the edge API must never reach the data-security network"
    assert "edge" not in nets("mnemo-consolidator"), "the consolidator must never be edge-reachable"
    assert nets(SOLE_INGRESS) == {"edge"}, "the ingress terminates on the edge network only"


def test_repo_relative_mounts_exist() -> None:
    for line in _compose_text().splitlines():
        match = re.match(r"^\s+-\s+(\./[^:]+):", line)
        if not match:
            continue
        mounted = INFRA / match.group(1)[2:]
        assert mounted.exists(), f"compose mounts a repo path that does not exist: {match.group(1)}"


def test_secret_files_live_outside_the_repo() -> None:
    secrets = _top_level_section(_compose_text(), "secrets")
    paths = re.findall(r"file:\s*(\S+)", secrets)
    assert paths, "the secrets block must reference external files"
    for path in paths:
        assert path.startswith("/") and not path.startswith(str(REPO_ROOT)), (
            f"secret files must be absolute and external to the repo: {path}"
        )


def test_build_services_reference_existing_docker_assets() -> None:
    text = _compose_text()
    for dockerfile in set(re.findall(r"dockerfile:\s*([^\s}]+)", text)):
        assert (REPO_ROOT / dockerfile).is_file(), f"missing build dockerfile: {dockerfile}"
    assert (INFRA / "entrypoint.sh").is_file(), "infra/entrypoint.sh (image entrypoint) must exist"
    for env_file in set(re.findall(r"env_file:\s*\[([^\]]*)\]", text)):
        for ref in env_file.split(","):
            ref_path = INFRA / ref.strip()[2:] if ref.strip().startswith("./") else Path(ref.strip())
            assert ref_path.is_file(), f"missing env_file referenced by compose: {ref.strip()}"
