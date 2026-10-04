# Board Status and Activation Register

Version: 0.2.1
Status: inactive board; source-owned gates in progress; External activation required only for the optional board upgrade

Two registers. Register A gates publication and is entirely within the
operator's control. Register B is an optional upgrade that would permit the
stronger *neutral* label; nothing in the roadmap waits on it.

## Register A — publication gates (source-owned, blocking)

Per [CHARTER](CHARTER.md) and [CREDIBILITY-MODEL](CREDIBILITY-MODEL.md).

| Gate | Current evidence | State |
|---|---|---|
| Pre-registration in force | `eval/public/runner.py` checks candidate protocol, budgets, model and prompt custody against registration. A complete public launch registration and admitted run evidence remain unverified. | Open |
| Append-only signed run ledger | `leaderboard/ledger.py` implements signed eval entries, hash-chain verification and signed roster heads. A real launch ledger with its complete run evidence remains missing. | Open |
| Reproducible by construction | `eval/public/bundle.py` implements bundle verification and replay; development lifecycle checks exist. Public headline-eligible results and their reproduced bundles remain unverified. | Open |
| Open stack published | Harness, adapters, memory-native generators and graders exist in `eval/public/`; `leaderboard/` contains rendering, publication and readiness tools. A deployed site, versioned public run data and mirrored evidence are not established by source availability. | Partial |
| Adversarial self-report populated | None | Open |
| Public dispute channel | Repository issues and `APPEALS-AND-DISPUTES.md` exist. An operational public log and a Register A process consistent with optional board activation remain unverified. | Open |
| Public methods write-up | Outline only; preprint and open review channel not published | Open |
| Roster-to-ledger completeness | `leaderboard/ledger.py` rejects changed rosters, unknown entrants and omitted outcomes during complete verification. No complete real launch roster/ledger is supplied. | Open |

Evidence reconciled on 2026-10-04. These are status corrections, not changes to
the original gates. Implemented validators and passing fixture tests do not
prove that real launch evidence exists or satisfies those validators.

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
