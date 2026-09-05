# 2026-09-04 ship-day receipt

CoS-owned. Documentation only. Authorizes no artifact, no CODE-READY
upgrade, and no Stage A implement.

## Tip

- `main` SHA `4af5b20ca871c9768965f808a7482839bc92d26a` (short `4af5b20c`) via #139
- Tip Unit+drift CI `33968198517` **IN_PROGRESS** at receipt time (rebase allowed).
- Prior tip `1df2416a` via #141 is historical (was live tip before N12 landed).
- Prior tip `ec26c40d` via #138 remains historical (was red; cured by #141).
- Prior tip `c67e9174` via #135 remains historical.

## Merged this day (PT)

| PR | title | merge tip | notes |
|---|---|---|---|
| #129 | docs: record merged PR #121 in write-lease map | `b7f351cdeeb989d7b84e7e2a0ad736efd5a6f5a1` | Lease-map receipt for prior-window #121 (M04-B). Merged 11:21 PT. |
| #128 | WMBS M05-B: register wmbs-m05-development (provenance adapter) | `ad9d5f809bb2a26df506c3958aef6a149a173f4a` | M05-B harness registration. Remains `PROPOSED`; publication flags false. Merged 12:46 PT. |
| #131 | docs: record merged PR #128 in write-lease map | `ec8aa1f28822ac7e992cf110cd9be18643c12e46` | Lease-map receipt for #128. Merged 13:46 PT. |
| #130 | docs: M05 README hierarchy residual + M12/M13 peer cells | `0679cdc762d6ac7be610b6be11f62a474fa74240` | README/disclosure residual only. Merged 14:20 PT. |
| #133 | docs: record merged PR #130 in write-lease map | `661e3f3f3b8fc8714094e6e84c186871c842f756` | Lease-map receipt for #130. Merged 14:54 PT. |
| #132 | docs: inventory — record ACCEPT plan PRs for M06–M09/M11/M17–M19 | `83804715d19c90c77161924f6acc79e62e567998` | Inventory ACCEPT receipts. Docs-only. Merged 15:26 PT. |
| #134 | docs(coordination): record #132 inventory ACCEPT in lease-map | `3281e61ed6b3d077628e3fd03ce0ec8de22cde18` | Lease-map receipt for #132. Prior tip before #116. Merged 15:59 PT. |
| #116 | docs: PROPOSED M06 consolidation plan (not code-ready) | `1f6b3b1c236c837aee77ba504f9eb06eab2a9c98` | M06 consolidation plan PROPOSED / NOT CODE-READY; docs only. Historical tip; VOID as live tip. |
| #135 | docs: discharge P13-C and retire obsolete publication lease | `c67e917410d7b468a337fda19ba654d57367d843` | P13-C discharge; lease-map / N12 admission (**READY FOR ADMISSION**); obsolete Mac publication lease retired; not N12 implement. Merged 18:51 PT. |
| #138 | eval: pin M02 canonical-replay seed | `ec26c40d359fc1f6904a97eac51aab461f9fd0f6` | M02 canonical-replay seed pin. Merged ~19:50 PT 2026-09-04. Tip was red until #141. |

#121 is **not** in this window (merged `2026-08-31T19:05:19Z`; merge
`eea12f798c22e281100a62552589225321b6c424`). Recorded on this day only via #129.

## Merged next calendar day (PT) — 2026-09-05

#141 cured red tip #138 overnight. #139 then landed N12 and is the live tip.
Both are recorded here so this receipt tracks current `main`; neither is a
2026-09-04 PT merge.

| PR | title | merge tip | notes |
|---|---|---|---|
| #141 | docs: record merged PR #138 in write-lease map | `1df2416ad89afbc11b12943a6984bbcbc17ee5a2` | Lease-map receipt curing post-#138 Unit+drift. Prior live tip. Merged ~04:55 PT 2026-09-05. |
| #139 | feat(leaderboard): additive result-v2 integration (N12) | `4af5b20ca871c9768965f808a7482839bc92d26a` | N12 landed. Live tip. Merged ~06:11 PT 2026-09-05. Tip CI `33968198517` IN_PROGRESS at receipt time. |

## Open / holds

- ACCEPT plan land wave `#118→#119→#122→#123→#124→#125→#127` (#126 DEFERRED, #120 OFF)
- Code lanes after N12:
  - #139 N12 **MERGED** at `4af5b20ca871c9768965f808a7482839bc92d26a`. #135 lease-map admission is historical; N12 implement landed in #139.
  - #140 Frontend smoke **CLOSED** (not merged) at `2026-09-05T13:11:56Z`.
- Stage A implement **HOLD** (gates)
- Memory/GBrain Mac offline — receipts drafted **HOLD**

## Canonical pointers

- inventory: `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`
- lease-map: `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` (do not edit)
