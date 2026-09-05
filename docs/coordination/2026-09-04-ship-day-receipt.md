# Ship-day receipt — 2026-09-04

Human-readable record of what merged today on `onfire7777/Mnemosyne`. Not a status pin (Memory owns `mnemosyne-current-main-status`). Not CODE-READY admission. Not a GOAL/STATE/lease-map edit.

## Live tip

| Field | Value |
|-------|-------|
| Tip SHA | `3281e61ed6b3d077628e3fd03ce0ec8de22cde18` |
| Tip via | #134 MERGED |
| CI | Unit+drift / tip overall **success** — run [`33927734374`](https://github.com/onfire7777/Mnemosyne/actions/runs/33927734374) on `3281e61e` |

## Merged today (exact merge SHAs)

| PR | Merge SHA | What |
|----|-----------|------|
| [#128](https://github.com/onfire7777/Mnemosyne/pull/128) | `ad9d5f809bb2a26df506c3958aef6a149a173f4a` | M05-B register `wmbs-m05-development` (provenance adapter). Suite **PROPOSED**; not landed / not end-to-end. |
| [#129](https://github.com/onfire7777/Mnemosyne/pull/129) | `b7f351cdeeb989d7b84e7e2a0ad736efd5a6f5a1` | Lease-map record for #121 |
| [#130](https://github.com/onfire7777/Mnemosyne/pull/130) | `0679cdc762d6ac7be610b6be11f62a474fa74240` | M05 README hierarchy residual + M12/M13 peer cells |
| [#131](https://github.com/onfire7777/Mnemosyne/pull/131) | `ec8aa1f28822ac7e992cf110cd9be18643c12e46` | Lease-map record for #128 |
| [#132](https://github.com/onfire7777/Mnemosyne/pull/132) | `83804715d19c90c77161924f6acc79e62e567998` | Inventory ACCEPT for plan PRs M06–M09/M11/M17–M19. Inventory only — not module landed. |
| [#133](https://github.com/onfire7777/Mnemosyne/pull/133) | `661e3f3f3b8fc8714094e6e84c186871c842f756` | Lease-map record for #130 |
| [#134](https://github.com/onfire7777/Mnemosyne/pull/134) | `3281e61ed6b3d077628e3fd03ce0ec8de22cde18` | Lease-map record for #132 (current tip) |

## Open (do not claim merged)

| PR | Head (live) | Note |
|----|-------------|------|
| [#116](https://github.com/onfire7777/Mnemosyne/pull/116) | `e463f61f00fef1913bd7a0df9db739616a906b54` | M06 plan — first in ACCEPT land wave; Unit+drift pending |
| [#118](https://github.com/onfire7777/Mnemosyne/pull/118) | `be3bcbe725f7ed149fc6b1a2df272675883c542f` | M07 plan — rebased |
| [#135](https://github.com/onfire7777/Mnemosyne/pull/135) | `392549f77452b8435ca946e84c239e5cfeb10ff7` | Jake P13-C discharge — **exclusive** GOAL/STATE/lease-map |
| [#120](https://github.com/onfire7777/Mnemosyne/pull/120) | `74a7a1bcc80cadaeb2c0d66562852dcf84dd3c68` | **OFF** |
| [#126](https://github.com/onfire7777/Mnemosyne/pull/126) | `98e121e89724e03c91819a204009e8b56818f1dc` | M19 **DEFERRED** — skip land wave |

## Open holds

- **N12 Mac residual** — lease-blocked pending external Mac worktree disposition/release; remote merge does not clear it.
- **Stage A HOLD** — still held (no CODE-READY invent).
- **ACCEPT land wave** (CoS order): `#116 → #118 → #119 → #122 → #123 → #124 → #125 → #127`. Skip `#126`. `#120` OFF.
- **#135 P13-C** — open; Jake exclusive on GOAL/STATE/lease-map.
- **GBrain Mac host** — #128 + #132 human receipts drafted; **HOLD PUT** until Mac/Memory host (one retry then park).

## Honesty

- Tip green ≠ publication claim ≠ N12 admitted.
- Inventory ACCEPT ≠ module landed ≠ code-ready implement.
- Lease-map / GOAL / STATE writers for #135: Jake only.
