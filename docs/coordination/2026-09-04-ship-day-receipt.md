# 2026-09-04 ship-day receipt

CoS-owned. Documentation only. Authorizes no artifact, no CODE-READY
upgrade, and no Stage A implement.

## Tip

- `main` SHA `d98bf6467a2915b5a596830ec40add1f90a3bc38` (short `d98bf646`) via #143
- Tip Unit+drift CI `33987300294` **SUCCESS**.
- Prior tip `8badc4ef` via #140 is historical (Unit+drift `33984430535` FAILURE; cured by #143).
- Prior tip `47f44ef3` via #142 is historical (Unit+drift `33971409778` SUCCESS).
- Prior tip `73bea352` via #139 is historical (was red; cured by #142).
- Prior tip `9eefd482` via #141 remains historical (was live tip before N12 landed).
- Prior tip `eb51a065` via #138 remains historical (was red; cured by #141).
- Prior tip `89a74a01` via #135 remains historical.

## Merged this day (PT)

| PR | title | merge tip | notes |
|---|---|---|---|
| #129 | docs: record merged PR #121 in write-lease map | `9b451b192ea71dd5619deb073d3456d4ae7c9e49` | Lease-map receipt for prior-window #121 (M04-B). Merged 11:21 PT. |
| #128 | WMBS M05-B: register wmbs-m05-development (provenance adapter) | `eb3320d4eab18326e8013169c8b94bddf70ebb67` | M05-B harness registration. Remains `PROPOSED`; publication flags false. Merged 12:46 PT. |
| #131 | docs: record merged PR #128 in write-lease map | `94825265b0276cef1fc73d430d0d89f1a514b1b1` | Lease-map receipt for #128. Merged 13:46 PT. |
| #130 | docs: M05 README hierarchy residual + M12/M13 peer cells | `0bb4f559eb716a5c5958acf44859c774646d4c28` | README/disclosure residual only. Merged 14:20 PT. |
| #133 | docs: record merged PR #130 in write-lease map | `6e41fb161a3dfd4cf88ea301895a3488fec0fa71` | Lease-map receipt for #130. Merged 14:54 PT. |
| #132 | docs: inventory — record ACCEPT plan PRs for M06–M09/M11/M17–M19 | `9288c12c88a7a408b3d1ed047e142f96ea13aa63` | Inventory ACCEPT receipts. Docs-only. Merged 15:26 PT. |
| #134 | docs(coordination): record #132 inventory ACCEPT in lease-map | `e29ea51bf1b76d6fa50958eaf0bdde4054373642` | Lease-map receipt for #132. Prior tip before #116. Merged 15:59 PT. |
| #116 | docs: PROPOSED M06 consolidation plan (not code-ready) | `51bdf0c51a043b2bf1780da685787b05315b3b2e` | M06 consolidation plan PROPOSED / NOT CODE-READY; docs only. Historical tip; VOID as live tip. |
| #135 | docs: discharge P13-C and retire obsolete publication lease | `89a74a019d0daff163e4319a7b59b0f8eb617dce` | P13-C discharge; lease-map / N12 admission (**READY FOR ADMISSION**); obsolete Mac publication lease retired; not N12 implement. Merged 18:51 PT. |
| #138 | eval: pin M02 canonical-replay seed | `eb51a0654545f31e123932dfd5598a67fb6de734` | M02 canonical-replay seed pin. Merged ~19:50 PT 2026-09-04. Tip was red until #141. |

#121 is **not** in this window (merged `2026-08-31T19:05:19Z`; merge
`08d39639c43e590688f66c196e5bea4835dd9a35`). Recorded on this day only via #129.

## Merged next calendar day (PT) — 2026-09-05

#141 cured red tip #138 overnight. #139 then landed N12. Prior tip `73bea35`
(#139) was red (Unit+drift `33968198517` FAILURE); #142 (lease-map for #139)
cured it (`33971409778` SUCCESS). #140 then landed Frontend smoke (prior
tip; Unit+drift `33984430535` FAILURE). #143 (lease-map for #140) cured it
and is the live tip (`33987300294` SUCCESS). Recorded here so this receipt
tracks current `main`; none is a 2026-09-04 PT merge.

| PR | title | merge tip | notes |
|---|---|---|---|
| #141 | docs: record merged PR #138 in write-lease map | `9eefd48274462ecc8961dd5f53f053b496eb7d25` | Lease-map receipt curing post-#138 Unit+drift. Prior live tip. Merged ~04:55 PT 2026-09-05. |
| #139 | feat(leaderboard): additive result-v2 integration (N12) | `73bea352a86e7eb868c9928219a4f9421fdea93b` | N12 landed. Prior live tip. Merged ~06:11 PT 2026-09-05. Tip CI `33968198517` FAILURE; cured by #142. |
| #142 | docs: record merged PR #139 in write-lease map | `47f44ef364ff726ab9bb4d409a1b49ac23ea1fa5` | Lease-map receipt for #139. Cured post-#139 Unit+drift. Prior live tip. Merged ~07:18 PT 2026-09-05. Tip CI `33971409778` Unit+drift SUCCESS. |
| #140 | test(leaderboard): Frontend render-output smoke (CLEAR of N12) | `8badc4efe97f38119adc8ac24cdbdb06977aa8d4` | Frontend smoke landed. Prior tip. Merged ~11:33 PT 2026-09-05. Tip CI `33984430535` Unit+drift FAILURE; cured by #143. |
| #143 | docs: record merged PR #140 in write-lease map | `d98bf6467a2915b5a596830ec40add1f90a3bc38` | Lease-map receipt for #140. Cured post-#140 Unit+drift. Live tip. Merged ~12:30 PT 2026-09-05. Tip CI `33987300294` Unit+drift SUCCESS. |

## Open / holds

- ACCEPT plan land wave `#118→#119→#122→#123→#124→#125→#127` (#126 DEFERRED, #120 OFF)
- Code lanes after N12:
  - #143 lease-map for #140 **MERGED** at `d98bf6467a2915b5a596830ec40add1f90a3bc38`. Live tip. Tip CI `33987300294` Unit+drift SUCCESS.
  - #140 Frontend smoke **MERGED** at `8badc4efe97f38119adc8ac24cdbdb06977aa8d4`. Prior tip was red (Unit+drift `33984430535` FAILURE); cured by #143.
  - #142 lease-map for #139 **MERGED** at `47f44ef364ff726ab9bb4d409a1b49ac23ea1fa5`. Prior tip. Tip CI `33971409778` Unit+drift SUCCESS.
  - #139 N12 **MERGED** at `73bea352a86e7eb868c9928219a4f9421fdea93b`. Prior tip was red; cured by #142. #135 lease-map admission is historical; N12 implement landed in #139.
- Stage A implement **HOLD** (gates)
- Memory/GBrain Mac offline — receipts drafted **HOLD**

## Canonical pointers

- inventory: `docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`
- lease-map: `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` (do not edit)
