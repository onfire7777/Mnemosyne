---
type: analysis
title: Jake's AI VA T9 Planning Catalog
updated: '2026-08-01T00:00:00.000Z'
visibility: private
ingested_via: 'mcp:put_page'
ingested_at: '2026-08-02T01:16:56.940Z'
source_kind: 'mcp:put_page'
tags:
  - archive
  - jakes-ai-va
  - planning
  - research
  - t9
---

# Jake's AI VA T9 Planning Catalog

This catalog records the read-only Samsung T9 discovery for Jake's AI VA and Jake's Professionals without ingesting stale code, private transcripts, credentials, databases, or packaged applications.

## Inventory receipt

- Volume: `/Volumes/T9-4TB`
- Mount state: NTFS, read-only
- In-scope documents: 53
- Unique SHA-256 hashes: 44
- Exact duplicates: 9
- Loose/archive documents: 28 files, 19 unique
- Safe loose planning/research candidates: 17
- Curated primary copy: 10 files
- Local curated archive: `/Users/admin/Jakes AI VA T9 Planning Archive`

## Repository findings

- T9 desktop clone: `master` at `409549459463`; older than canonical and no unique repository documentation.
- T9 release-manager clone: `main` at `09ab19b56bd4`; older than canonical and no unique repository documentation.
- Repository docs are byte-identical or CRLF-only variants of the canonical checkouts.
- Neither T9 clone was copied, indexed, mounted differently, or modified.

## Primary curated planning set

| File | SHA-256 | Purpose |
|---|---|---|
| `jake-va-agentic-blueprint-FINAL.md` | `1913d2c64d68ae8e593544aff4c509536f7faa76d27b1997e6fded9150c9e461` | Definitive historical implementation blueprint |
| `jake-va-agentic-blueprint-v2.md` | `5094c10395b823c5a8c2f263916bfff650dae9692c67e3bfcbad0d9c4b1ceb78` | Detail-rich predecessor with non-duplicated material |
| `Critical Analysis of the Agentic Architecture Blueprint v1.md` | `4f7e0a917ffa5940359e083474bffbe437dcb9d23e7d5e0aa9eb2487c4b364ca` | Design rationale and gap analysis |
| `Jakes AI UI design RnD creative.pdf` | `bf22ac826ed4616917e4ef05889088d873a24ff7e3ee1ef93c1c56c1397166f4` | UI and interaction research |
| `Jakes AI VA explained.pdf` | `e1452b2cc5e0af5031dad342c517ae8914f3b201e5021ff5c3d08040970b3211` | Product and architecture overview |
| `Framework_Software_Complete_Improvement_Spec.docx` | `701bc89496a9b6beb821d1d93ab8b18f3a9406e27d4a4b389397fcd9dfd05108` | Framework implementation priorities |
| `Definitive_System_Feedback_v2.docx` | `91625f5f93dfd189a57acd40cc6a16f7da25dce2943edb84eb9f44702f939443` | System feedback and corrections |
| `Definitive_Framework_Template_Final.docx` | `fde8a36051fd30728033f10b0a2e36af3fff3e0cf2efbea9fd6a62c88c97aaf1` | Framework template |
| `Deep_Dive_Research_Updated.docx` | `36abc7758b6326396537a5a0c682425d9badca37a4a84776a53b3001390966af` | Jake's Professionals primary research |
| `Revised_Critical_Review_Deep_Dive_Research.docx` | `da6510e4f0575581032760c1d19bd8a31693b15b5854a06aedd292450a7dabe0` | Corrected critical review |

The local `MANIFEST.sha256` verifies all ten copies, and byte comparison confirmed `10/10` are identical to their T9 sources.

## Canonical loose sources

- `/Volumes/T9-4TB/90_Inbox_Unsorted/Desktop_Organized/Jake's AI VA Project`
- `/Volumes/T9-4TB/90_Inbox_Unsorted/Local-Desktop/Jakes Professionals/VA documents`

The sibling `Local AI Research/Jake's AI VA Project` contributes nine exact duplicates and no unique documents.

## Exclusions

- `conversation_transcript.txt` and `main_export.txt`: potentially sensitive, metadata-only cataloging.
- `.env`, recovery codes, browser stores, credentials, private keys, books and Chroma databases.
- Executables, `_internal`, installers, release binaries, archives, `node_modules`, and `WindowsImageBackup`.
- Duplicate rendered/intermediate blueprint variants unless provenance is later needed.
- The Proper Thinking packaged application: no first-party planning documents remained after exclusions.

## Interpretation

These planning files predate the current canonical architecture and audit documents. Use them for historical rationale, requirements mining, and research provenance; verify every implementation claim against [[projects/jakes-ai-va-desktop]], [[projects/jakes-ai-va-release-manager]], and their live CBM indexes.
