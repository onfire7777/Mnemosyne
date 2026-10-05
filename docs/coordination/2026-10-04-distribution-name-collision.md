# Distribution identity and advisory triage — 2026-10-04

The current source checkout declares `mnemosyne-memory` version `1.0.1` in
`pyproject.toml`. Its `uv.lock` entry is `source = { editable = "." }`;
it does not download that package from PyPI.

PyPI's [current package metadata](https://pypi.org/pypi/mnemosyne-memory/json)
instead identifies version `3.15.1` and links its repository to
`https://github.com/AxDSan/mnemosyne`. That is a different project from this
repository, `onfire7777/Mnemosyne`. Installing the bare package name from PyPI
must not be presented as installing this checkout.

GitHub Dependabot alert #6 associates this editable root package with
[GHSA-xcw4-53cc-hv32 / CVE-2026-59163](https://github.com/advisories/GHSA-xcw4-53cc-hv32).
The advisory concerns the other project's `mnemosyne/core/sync_server.py`
and `/sync/status`, `/sync/push`, `/sync/pull` endpoints, through version
3.10.0. None of those source paths or endpoint strings exists in this
checkout. Our `src/mnemosyne/security.py` verifies session HMAC signatures
with `hmac.compare_digest`; its OIDC verifier restricts algorithms and verifies
the signature before accepting claims. Existing session/OIDC tamper tests pass.

Disposition: the advisory's described code is not present in this source tree;
the package-name collision explains the alert. This is a scoped applicability
assessment, not a declaration that all authentication paths are vulnerability-free.
The alert has not been dismissed and security scanning has not been disabled.

The CLI's missing-MCP-extra guidance now points to a repository-local install.
Continue using the cloned repository and `uv sync` (or local-path pip installs).
Before any PyPI release, resolve ownership or select and verify a distinct
distribution name, update installation references and release metadata, and
recheck the resulting dependency identity. Do not raise the version merely to
escape the advisory's affected range, or replace this project with the other
package's code. This publication prerequisite remains open.
