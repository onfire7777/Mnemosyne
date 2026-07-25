# Leaderboard Charter

Version: 0.2.0
Status: source-owned gates active; External activation required only for the optional independent-board upgrade

## Purpose and authority

This charter governs an open, operator-run, fully auditable comparison of memory
systems. Authority rests on **mechanical verifiability**, not on an institution:
every published number is reproducible from a signed, pre-registered bundle by
any third party. The reasoning is in [CREDIBILITY-MODEL](CREDIBILITY-MODEL.md).

Outputs are labelled **open, operator-run, fully auditable**. They may not be
described as *neutral* or *independent* unless the optional board upgrade below
is actually seated.

## Roles and composition

In the base model there is one role: the **operator**, who builds the harness,
runs every system under it, and publishes results and traces. The operator holds
a permanent, non-curable conflict with respect to Mnemosyne, governed by
[CONFLICT-OF-INTEREST](CONFLICT-OF-INTEREST.md).

Because a solo operator cannot be separated from the product team as a person,
separation is enforced in time and code instead — deterministic pipeline, frozen
pre-registered configuration, programmatic grading, automated publication from
an append-only ledger. See [OPERATOR-FIREWALL](OPERATOR-FIREWALL.md).

## Powers and constraints

The operator may publish methodology versions, resolve appeals in public, and
issue versioned corrections. The operator may **not** waive the equal-treatment
firewall, conceal run history, silently alter or retract scores, grant private
access to any system including Mnemosyne, or tune Mnemosyne against an
operator-authored benchmark without disclosure.

Methodology changes require a versioned entry in
[CHANGE-CONTROL](CHANGE-CONTROL.md) and a pre-registration digest that precedes
any affected score.

## Activation gate

Publication is gated on **verifiable source-owned evidence**, all of which the
operator can produce:

| Gate | Evidence required |
|---|---|
| Pre-registration in force | Signed `preregistration.json` committed before any scored run |
| Append-only run ledger | Hash-chained, signed, containing every run including failures and discards |
| Reproducible by construction | A stranger can reproduce any published number from its pinned bundle with one documented command |
| Open stack | Specification, generators, graders, adapters, and harness published under the repository licence |
| Adversarial self-report | A populated record of where Mnemosyne underperforms |
| Public dispute channel | Open, logged, with resolutions published |
| Roster-to-ledger completeness | Every pre-registered entrant resolves to a result or a reasoned `no_run` record |

Two publication classes, so "publishable" is unambiguous:

- **Track publication** — a measured track with its traces, bundle, and
  pre-registration may be published as soon as *that track* satisfies the gates
  above. This is what permits the site to render incrementally.
- **Headline publication** — any comparative ranking, leaderboard standing, or
  external claim requires **every** gate above to hold across all rendered
  tracks.

Until a class's gates hold, its outputs are labelled **source-ready**, not
published. No gate depends on another organisation.

## Optional upgrade: independent board

Seating an independent board remains desirable.
It is a strict upgrade and is optional, not a prerequisite. It would permit the stronger *neutral* label. Its composition
requirements and the external evidence it would need are recorded in
[BOARD-STATUS](BOARD-STATUS.md). No build, measurement, or publication step in
this project waits on it.
