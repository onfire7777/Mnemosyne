# Case Scope

## meta
- case_id: hindsight-comparison
- created: 2026-10-22T15:59:36-07:00
- operator: local
- project_root: /Users/admin/Desktop/Mnemosyne
- primary_skill: code-audit/SKILL.md
- primary_id: R26
- lead_role: lead
- specialist_roles: [source_research, ranking_audit, code_review]
- hint:
- preset: offline-sample

## auth
- status: granted
- basis: own_system
- evidence_of_auth: User requested local Mnemosyne analysis and fixes, approved local router setup, and on 2026-10-22 explicitly requested live PostgreSQL validation, a fair Hindsight comparison through the existing Codex account, and commit/push of fixes to main
- MUST NOT proceed if status != granted

## in_scope
- assets:
  - /Users/admin/Desktop/Mnemosyne/src/mnemosyne/engine.py
  - /Users/admin/Desktop/Mnemosyne
- surfaces: [local_source, local_tests, local_generated_reports, disposable_local_postgresql, isolated_local_hindsight]
- activities: [read_source, fix_local_bugs, offline_regression_tests, live_local_postgresql_tests, generate_evidence, evaluate_public_dataset_via_existing_codex_login, install_isolated_official_runtime_dependencies, commit_and_push_main]

## out_of_scope
- assets: []
- activities: [dos, phishing_real_users, unrestricted_exfil]

## network_profile
- mode: authorized_target_only
- notes: |
    Source audit and regression tests operate locally. Public documentation/datasets may be read.
    Model inference is limited to the existing authenticated Codex CLI for public evaluation data.
    Official source/dependencies and model weights may be downloaded for isolated local evaluation.
    Disposable PostgreSQL and Hindsight services bind only to loopback; no production data is used.
    No external runtime probing, target scanning, separate provider purchase or credential extraction.

## deliverables
- report: true
- field_journal: true
- diagrams: true
- timeline: true

## constraints
- timebox: {}
- stealth: low
- data_handling: anonymize

## signoff
- ready_for_act: true
- checklist:
  - [x] auth.status = granted
  - [x] in_scope.assets non-empty OR offline sample path set
  - [x] network_profile.mode chosen
  - [x] out_of_scope reviewed
  - [x] roles assigned (see skills/ops/role-map.md)

## ops_refs
- skills/ops/scope-contract.md
- skills/ops/evidence-finding-path.md
- skills/ops/role-map.md
- skills/ops/timeline-workitem.md
- skills/ops/IDENTITY.md

## Public-source research boundary
Hindsight and Mnemetric public/authorized repository material was read as documentation. No external runtime was scanned or attacked. External source review does not grant testing permission. No separate paid-provider API was configured. Codex inference consumes the existing account quota; monetary cost is not measured. Mnemosyne and Mnemetric retain independent code and data; comparison references are permitted.
