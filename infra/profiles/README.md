# Production Profiles

Two profiles drive the **same** `provider-manifest.production.template.json` and the **same** gates.
They differ **only** in the *values* bound to env references — never code, never gate logic.
`forbid_local: true` is retained in **both**.

| Profile | File | Role |
|---|---|---|
| `self-hosted` | `self-hosted.env` | **Preferred baseline.** Closes B1-B10 on real, self-hosted, no-GPU infra through the attested CPU-parametric path. |
| `cloud` | `cloud.env` | **Scale/quality extension.** Optional for larger accelerator-backed providers and any capability the no-GPU host cannot evidence. |

**Strict-100% note:** B9 is not marked Done by declaration. It is Done only
because the 2026-07-07 Tier-B bundle retained real CPU-trained parametric
adapter evidence that passed the unchanged `parametric-trainer-check`,
release-audit, and offline verifier path.

## Use
```bash
cp infra/profiles/self-hosted.env /secure/outside/repo/production-render.env   # fill secrets-by-reference
set -a; . /secure/outside/repo/production-render.env; set +a
infra/scripts/render-production-soak-manifest.sh --check-environment
```
Secrets never live in these files: bind them to Vault paths / command providers / `*_FILE` Docker
secrets. These files carry **non-secret endpoints, hostnames, model ids, and `*_COMMAND` absolute
paths** only.
