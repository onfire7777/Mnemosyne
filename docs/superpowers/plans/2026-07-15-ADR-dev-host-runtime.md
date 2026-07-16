# ADR / Ops Plan — Development-Host Runtime (Colima → OrbStack), and the Native-Linux Server Option

**Date:** 2026-07-15
**Status:** Proposed (ops decision; operator-owned). Separate from the product.
**Parent context:** the memory-pressure investigation in this program's session
(16 GiB Mac; the 12 GiB Colima VM is the structural constraint) and the
world-best master spec (which governs the *product*, not the dev host).

## Why this is a separate document

This is a **development-environment and multi-tenant-server operations** decision,
NOT a product workstream (W1–W5). It does not touch the 8 GiB product profile, the
quality-parity claim, or any benchmark number. It exists so the runtime research
this session produced is not lost, and so the recurring hardware-admission stalls
on the dev Mac have a durable fix. It changes no §31/§33 rail, custody rule, or
`HARDWARE-WORKLOAD-PREFLIGHT.md` threshold.

## Problem

The dev Mac is 16 GiB. The production stack runs under **Colima (VZ, 6 CPU /
12 GiB fixed)**. Colima never returns freed guest memory to macOS — it ratchets
toward its 12 GiB allocation and holds it — so the host sits near / below the
admission-gate thresholds (55% free for model/protected work; 35% for targeted
tests), repeatedly stalling the loop. Stopping the VM frees ~12 GiB but re-seals
Vault and takes the stack offline (the current interim workaround, operator-approved).

## Findings (researched this session; sources in the session record)

- **OrbStack (v2.2.x, 2026)** is the one macOS runtime that returns freed guest
  memory to the host **while containers keep running** (custom dynamic-memory
  implementation, community-reported reclaim in seconds; ~200–300 MB idle vs
  Colima's ratchet-to-12 GiB). It runs the real Docker engine + compose — a
  **drop-in** for the docker CLI/compose: existing two bridge networks, aliases,
  healthchecks, digest pins, and named volumes carry over via `docker context`.
  Caveats: free for personal/non-commercial use only ($96/user/yr if commercial);
  closed source (vendor-trust); a few 2026 heavy-load bug reports (VM-manager kill
  under load #2502; postgres:18-on-Tahoe #2222) — so soak-test before
  decommissioning Colima.
- **Apple `container` (1.x, 2026)** is NOT viable for a 20-service stack: no native
  compose, macOS-26 requirement for multi-container networking, and — per Apple's
  own docs — freed guest pages are **not** returned while running (worse for a
  constrained host). Re-evaluate in 2027.
- **Colima/Lima/Podman/Docker Desktop**: all fixed-allocation ratchets on VZ; no
  dynamic reclaim. Colima can be shrunk (`colima start --memory 8`) with per-service
  `mem_limit`s and periodic `colima restart` as the only tuning surface.
- **Native Linux (optional, bigger):** the macOS VM tax disappears entirely on a
  dedicated Linux host — the same digest-pinned images/compose run natively and the
  stack idles ~3–5 GiB. Requires: re-pinning to multi-arch **index** digests (not
  arm64 manifest digests), rebuilding the locally-built Python images for the host
  arch, standard volume migration (`pg_dump` + stopped-stack volume tar), Vault
  storage move (same seal; unseal on the new host), and `*.mnemo.local` → LAN IP
  via `/etc/hosts` or a self-hosted WireGuard/Headscale tunnel. This is **required
  by no claim** and is the operator's call; it is recorded as an option, not a
  recommendation to act now.

## Decision (proposed; operator-owned)

1. **Adopt OrbStack for the dev Mac**, keeping the Colima profile intact as
   rollback (both coexist; switch via `docker context`). Expected effect: idle host
   cost drops from "ratcheted-to-12 GiB" to roughly container RSS + a few hundred
   MB, with post-burst memory handed back in seconds — ending the admission-gate
   stalls without stopping the stack or re-sealing Vault on every dev cycle.
2. **Keep native-Linux migration as a documented option**, not an action.

## Migration checklist (if OrbStack is adopted)

- [ ] Install OrbStack; import existing Docker data; `docker context use orbstack`.
- [ ] Bring up the prod compose stack; confirm the 20 services, two networks,
  aliases, healthchecks, digest pins, and named volumes resolve unchanged.
- [ ] Run the existing 29-check deployment-soak against OrbStack **before**
  decommissioning Colima; keep Colima as rollback.
- [ ] Re-run the Vault unseal drill (a runtime migration restarts the stack and
  re-seals Vault; operator-held key).
- [ ] Update `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md` ONLY if the memory
  behavior materially changes the admission math — with an ADR note; do not weaken
  a threshold.
- [ ] Confirm the licensing posture (personal vs commercial) for this project.

## Rails

No §31/§33/custody/preflight-threshold change. No product-profile or parity impact.
Vault is never re-initialized. This is an operator decision; agents prepare and
document, the operator adopts. Rollback is retained (Colima profile intact).
