# Board Status and Activation Register

Version: 0.2.0
Status: inactive board; source-owned gates in progress; External activation required only for the optional board upgrade

Two registers. Register A gates publication and is entirely within the
operator's control. Register B is an optional upgrade that would permit the
stronger *neutral* label; nothing in the roadmap waits on it.

## Register A — publication gates (source-owned, blocking)

Per [CHARTER](CHARTER.md) and [CREDIBILITY-MODEL](CREDIBILITY-MODEL.md).

| Gate | Current evidence | State |
|---|---|---|
| Pre-registration in force | Not implemented | Open |
| Append-only signed run ledger | Ed25519 signing and audit hash chain exist from v1.0 Tier-B; not yet applied to eval runs | Open |
| Reproducible by construction | Reproduction bundles specified in METHODOLOGY; one-command path not published | Open |
| Open stack published | Harness and adapters exist under Apache-2.0 in `eval/public/`; memory-native generators and graders not written | Partial |
| Adversarial self-report populated | None | Open |
| Public dispute channel | Repository issues available; no logged resolution protocol wired | Open |
| Public methods write-up | Outline only; preprint and open review channel not published | Open |

No gate above requires another organisation, funding, or a legal entity. Each is
a software and disclosure task.

## Register B — optional independent-board upgrade (non-blocking)

Recorded so the option stays open and its cost stays honest.
The board is not yet seated and governance is not yet active.
None of these gates blocks building, measuring, or publishing under Register A.

| Gate | Current evidence | State |
|---|---|---|
| Five eligible members and written acceptances | None | Not pursued |
| Signed public conflict disclosures | Template only | Not pursued |
| Independent chair and role assignments | None | Not pursued |
| Legal steward and jurisdiction | None | Not pursued |
| Durable funding, hosting, and license decisions | None | Not pursued |
| Charter and methodology external ratification | Source drafts only | Not pursued |
| DOI plus multi-owner immutable archive | None | Not pursued |
| Methods paper publication | Outline only | Not pursued |

If Register B is ever satisfied, the *neutral* label becomes available. Until
then the honest label is **open, operator-run, fully auditable**.

## Failure mode this register exists to prevent

v0.1.0 placed Register B on the critical path. Because a solo maintainer cannot
seat academics or retain a legal steward by writing software, Phase 16 could
never open regardless of engineering effort. Separating the registers keeps the
disclosure standard intact while making the path completable.
