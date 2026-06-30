# Production Profiles

Two profiles drive the **same** `provider-manifest.production.template.json` and the **same** gates.
They differ **only** in the *values* bound to env references — never code, never gate logic.
`forbid_local: true` is retained in **both**.

| Profile | File | Role |
|---|---|---|
| `self-hosted` | `self-hosted.env` | **Preferred baseline.** Closes B1–B8 + B10 on real, self-hosted, no-GPU infra. |
| `cloud` | `cloud.env` | **B9-capable extension.** Required for B9/FR-21 (GPU LoRA/test-time-training) and any capability a no-GPU host cannot evidence. |

**Strict-100% note:** the no-GPU `self-hosted` profile does **not** by itself satisfy the strict v1.0
parity bar — B9 needs real GPU evidence via `cloud.env` (or an explicit ADR changing the strict audit).
Do not mark B9 / strict 100% complete on a no-GPU host by declaration.

## Use
```bash
cp infra/profiles/self-hosted.env /secure/outside/repo/production-render.env   # fill secrets-by-reference
set -a; . /secure/outside/repo/production-render.env; set +a
infra/scripts/render-production-soak-manifest.sh --check-environment
```
Secrets never live in these files: bind them to Vault paths / command providers / `*_FILE` Docker
secrets. These files carry **non-secret endpoints, hostnames, model ids, and `*_COMMAND` absolute
paths** only.
