# E-dependency-alert-6 — package-name collision

Date: 2026-10-22. Reviewed source: `f21ef47b06a13d53e8e7922ddcd51684df7f1c8f`.

GitHub reported [Dependabot alert #6](https://github.com/onfire7777/Mnemosyne/security/dependabot/6)
during the push to `main`. The [upstream advisory GHSA-xcw4-53cc-hv32](https://github.com/advisories/GHSA-xcw4-53cc-hv32)
describes an unverified JWT in `mnemosyne/core/sync_server.py` in the separate
`mnemosyne-oss/mnemosyne` project. Its affected distribution is named
`mnemosyne-memory`, through version 3.10.0; its fix is version 3.10.1.

This repository uses the same distribution name, but `uv.lock` identifies its sole
`mnemosyne-memory` entry as version 1.7.0 with `source = { editable = "." }`.
It resolves to this checkout, not the upstream distribution. This repository has
neither that sync server module nor the `/sync/status`, `/sync/push`, or `/sync/pull`
handlers described by the advisory. Independent source review confirmed the mismatch.

Our `SessionSigner.verify` checks HMAC signatures with `hmac.compare_digest`.
`OidcJwtVerifier.verify` enforces allowed algorithms and verifies signatures before
accepting registered claims. Existing tests exercise algorithm rejection, tampering,
expiry, key handling and claims validation. The focused verification command was:

```sh
uv run --locked python -m pytest -q tests/test_security_sessions.py \
  --junitxml=work/hindsight-comparison/dependency-alert-auth-verification.xml
```

Result: **41 passed, 1 optional live-provider skip, zero failures/errors**, 4.328 seconds.
The XML and log are retained beside the other case receipts. This confirms the tested
authentication behavior; it is not a comprehensive security audit.

Assessment: this alert is a package-name collision. Upgrading the local project to the
unrelated distribution's 3.10.1 would be an incorrect remedy. A unique distribution
name is a separate packaging decision; no package rename or runtime dependency change
was made in this follow-up.

Alert #6 was dismissed as **inaccurate or incorrect**, with the package-source mismatch
and test result recorded in its dismissal comment. The GitHub page was then verified
to show **Dismissed** and the saved comment. This is an applicability decision for this
specific advisory, not acceptance of a known vulnerability or a disabled security check.
