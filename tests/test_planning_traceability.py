from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / ".planning"
REQUIREMENTS = PLANNING / "milestones" / "v1.0-REQUIREMENTS.md"
V2_REQUIREMENTS = PLANNING / "REQUIREMENTS.md"
V2_ROADMAP = PLANNING / "ROADMAP.md"
PHASE_15_S4_PLAN = (
    PLANNING
    / "phases"
    / "15-security-calibration-performance-and-scale-columns"
    / "15-03-PLAN.md"
)
ARCHITECTURE_OVERVIEW = ROOT / "docs" / "ARCHITECTURE-OVERVIEW.md"
ENGINE_CONTRACT = ROOT / "docs" / "ENGINE-CONTRACT.md"
DEPENDENCY_LEASE_MAP = (
    ROOT
    / "docs"
    / "coordination"
    / "2026-07-28-remaining-dependency-write-lease-map.md"
)
GOAL = ROOT / "GOAL.md"
STATE = PLANNING / "STATE.md"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TOPOLOGY_VERIFIER = ROOT / "infra" / "scripts" / "verify-topology-refresh.py"
LEASE_BASELINE = re.compile(r"^Baseline: `main@([0-9a-f]{40})`$", re.MULTILINE)
LEASE_CURRENT_BASELINE_CLAIMS = (
    re.compile(r"recomputed from the new baseline `main@([0-9a-f]{8})`"),
    re.compile(r"at main@([0-9a-f]{8}) \(current baseline\)"),
    re.compile(
        r"This map has now been recomputed from the resulting "
        r"`?main@([0-9a-f]{8})`?"
    ),
    re.compile(
        r"## Concurrency and integration rules .*?This revision "
        r"(?:\*\*)?is(?:\*\*)? the recomputation from "
        r"(?:the resulting )?`?main@([0-9a-f]{8})`?"
    ),
)
ID_PATTERN = re.compile(r"(?:REQ|NFR)-\d{3}")
TRACE_ROW = re.compile(
    r"^\| ((?:REQ|NFR)-\d{3}) \| ([^|]+) \| `([^`]+)` \| `([^`]+)` "
    r"\| ([^|]+) \| \[x\] Verified \|$"
)
V2_CAP_ROW = re.compile(r"^\| \[[ x]\] (CAP-\d{3}) \|")
CANONICAL_CLAIM_PHRASE = "current canonical baseline"
# The two phrasings the lifecycle prose uses for a canonical-baseline claim:
# "...at `main@X` (...), which is the current canonical baseline" and
# "The current canonical baseline is `main@X`".
CANONICAL_CLAIMS = (
    # Bind to the nearest preceding SHA: these sentences also cite historical
    # merges, so the match must not cross another `main@` reference.
    re.compile(
        r"`main@([0-9a-f]{8})`(?:(?!main@)[^.])*?"
        r"which is the current canonical baseline"
    ),
    re.compile(r"current canonical baseline is `main@([0-9a-f]{8})`"),
)
STATE_STOPPED_AT = re.compile(r'^stopped_at: "(.*)"$', re.MULTILINE)
STATE_STOPPED_AT_CLAIM = re.compile(r"at `?main@([0-9a-f]{8})`?;")


def _frontmatter_list(text: str, key: str) -> set[str]:
    lines = text.splitlines()
    marker = f"{key}:"
    inline_prefix = f"{key}: ["
    for line in lines:
        if line.startswith(inline_prefix) and line.endswith("]"):
            return {
                value.strip()
                for value in line[len(inline_prefix) : -1].split(",")
                if value.strip()
            }
    try:
        start = lines.index(marker) + 1
    except ValueError:
        return set()
    values: set[str] = set()
    for line in lines[start:]:
        if not line.startswith("  - "):
            break
        values.add(line.removeprefix("  - ").strip())
    return values


def _resolve_planning_path(value: str) -> Path:
    path = PLANNING / value
    assert path.is_file(), f"traceability source does not exist: {path}"
    return path


def test_all_canonical_requirements_have_one_truthful_three_source_join() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    expected = {f"REQ-{index:03d}" for index in range(1, 19)} | {
        f"NFR-{index:03d}" for index in range(1, 6)
    }
    checked = set(re.findall(r"\[x\] ((?:REQ|NFR)-\d{3})", text))
    assert checked == expected

    rows: dict[str, tuple[str, str, str, str]] = {}
    for line in text.splitlines():
        match = TRACE_ROW.match(line)
        if not match:
            continue
        requirement, phase, verification, summary, closure = match.groups()
        assert requirement not in rows, f"duplicate primary owner: {requirement}"
        rows[requirement] = (phase.strip(), verification, summary, closure.strip())
    assert set(rows) == expected

    for requirement, (phase, verification_name, summary_name, closure) in rows.items():
        assert phase, f"missing primary phase for {requirement}"
        verification = _resolve_planning_path(verification_name)
        summary = _resolve_planning_path(summary_name)
        verification_text = verification.read_text(encoding="utf-8")
        summary_text = summary.read_text(encoding="utf-8")
        assert "status: passed" in verification_text
        assert requirement in verification_text
        assert requirement in _frontmatter_list(summary_text, "requirements-completed")
        assert closure


def test_traceability_uses_only_canonical_requirement_ids() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    ids = set(ID_PATTERN.findall(text))
    assert {f"REQ-{index:03d}" for index in range(1, 19)} <= ids
    assert {f"NFR-{index:03d}" for index in range(1, 6)} <= ids


def test_unit_drift_checkout_fetches_canonical_main_history() -> None:
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    job_start = lines.index("  test:")
    job_end = next(
        index
        for index in range(job_start + 1, len(lines))
        if lines[index].startswith("  ") and not lines[index].startswith("    ")
    )
    job = lines[job_start:job_end]
    checkout = job.index(
        "      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    )
    assert job[checkout + 1 : checkout + 3] == [
        "        with:",
        "          fetch-depth: 0",
    ]


def test_canonical_baseline_is_identical_across_the_three_lifecycle_files() -> None:
    """The lease map, GOAL.md, and STATE.md must name one canonical baseline.

    Each reconciliation round restates the same merge SHA by hand in three
    places, so a partial update silently leaves one authority pointing at a
    superseded baseline. This pins them together.

    Presence of the new SHA is not enough: a partial update leaves the *stale*
    claim behind, and a stale claim is still a claim. So each file must make
    exactly one canonical-baseline claim, and it must name the lease map's
    baseline. Prose here is hand-wrapped and rewritten every round, so match
    against whitespace-normalized text rather than raw lines.
    """
    lease_text = DEPENDENCY_LEASE_MAP.read_text(encoding="utf-8")
    baselines = LEASE_BASELINE.findall(lease_text)
    assert len(baselines) == 1, f"expected exactly one Baseline line, got {baselines}"
    sha = baselines[0]
    short = sha[:8]

    goal_text = GOAL.read_text(encoding="utf-8")
    # The GOAL.md verification block's lapse detector must assert this exact SHA,
    # and the ancestry list must include it. These are shell lines, so they are
    # matched unnormalized.
    assert f'test "$(git rev-parse main)" = "{sha}"' in goal_text
    assert f"git merge-base --is-ancestor {sha} main" in goal_text

    goal_normalized = " ".join(goal_text.split())
    state_text = STATE.read_text(encoding="utf-8")
    state_normalized = " ".join(state_text.split())

    stopped_at = STATE_STOPPED_AT.findall(state_text)
    assert len(stopped_at) == 1, f"expected one stopped_at line, got {stopped_at}"

    for label, normalized in (
        ("GOAL.md", goal_normalized),
        (".planning/STATE.md", state_normalized),
    ):
        claimed = [
            claim
            for pattern in CANONICAL_CLAIMS
            for claim in pattern.findall(normalized)
        ]
        assert len(claimed) == 1, (
            f"{label} must make exactly one canonical-baseline claim, got {claimed}"
        )
        assert claimed[0] == short, (
            f"the canonical-baseline claim in {label} must name `main@{short}`, "
            f"got {claimed[0]}"
        )
        # Guard the regexes against a reworded claim slipping past them: every
        # occurrence of the phrase must be one of the matched claims.
        recognized_claim_count = len(claimed)
        assert normalized.count(CANONICAL_CLAIM_PHRASE) == recognized_claim_count, (
            f"{label} has a '{CANONICAL_CLAIM_PHRASE}' claim that names no SHA "
            f"in a recognized form"
        )

    claimed = STATE_STOPPED_AT_CLAIM.findall(stopped_at[0])
    assert claimed == [short], (
        f".planning/STATE.md stopped_at must name `main@{short}` exactly once, "
        f"got {claimed}"
    )
    subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            sha,
            "refs/remotes/origin/main",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    # Ancestry alone passes for *any* superseded baseline, so it can never
    # detect the lapse GOAL.md's canonical-baseline gate exists to catch: a PR
    # landing on `main` while the lifecycle files still name an older baseline.
    #
    # Tip equality (`recorded == origin/main`) cannot express that invariant
    # either — the commit that records a baseline necessarily lands *after* it,
    # so the claim is stale the instant it merges and `main` would never be
    # green. The enforceable form is: every PR merged into `main` since the
    # recorded baseline must be accounted for in the lease map.
    unrecorded = _unrecorded_merged_prs(sha)
    assert not unrecorded, (
        "these PRs merged into origin/main after the recorded baseline "
        f"`main@{short}` but appear nowhere in {DEPENDENCY_LEASE_MAP.name}: "
        + ", ".join(f"PR #{pr}" for pr in unrecorded)
        + " — recompute the canonical baseline and record their receipts "
        "before admitting further work"
    )


# GitHub's default merge subject plus the shorter hand-written variants.
# A trailing "(#N)" (squash-merge style) is deliberately NOT treated as a PR
# merge: this repository merges every PR with a merge commit and uses that
# suffix for *issue* references instead (e.g. "... Lease G wire ... (#17)"),
# so accepting it would report issues as unrecorded PRs.
MERGED_PR = re.compile(r"^Merge (?:pull request |PR )?#(\d+)\b", re.MULTILINE)
# Only a structured lease-map entry counts as a record. Bare prose such as
# "PR #91 was the deferred GoalEx-owner delivery" must not satisfy the gate:
# an incidental mention would otherwise authorise an unrecorded merge without
# a lifecycle entry or receipts.
LEASE_PR_RECORD = re.compile(r"^\s*[-*] PR #(\d+)[:,]", re.MULTILINE)


def _unrecorded_merged_prs(baseline_sha: str) -> list[str]:
    """PR numbers merged into origin/main since `baseline_sha` and not recorded.

    Returns the sorted PR numbers whose merge commits are reachable from
    `origin/main` but not from the recorded baseline, and for which the
    dependency lease map holds no structured record. An empty list means the
    lease map accounts for everything that has landed since the baseline.
    """
    subjects = subprocess.run(
        [
            "git",
            "log",
            "--merges",
            "--format=%s",
            f"{baseline_sha}..refs/remotes/origin/main",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lease_text = DEPENDENCY_LEASE_MAP.read_text(encoding="utf-8")
    recorded = set(LEASE_PR_RECORD.findall(lease_text))
    landed = set(MERGED_PR.findall(subjects))
    return sorted(landed - recorded, key=int)


def test_t6_terminal_receipts_are_consistent_across_lifecycle_files() -> None:
    """T6 must remain closed with one shared PR #95 receipt tuple."""
    lifecycle_texts = {
        "GOAL.md": GOAL.read_text(encoding="utf-8"),
        ".planning/STATE.md": STATE.read_text(encoding="utf-8"),
        "lease map": DEPENDENCY_LEASE_MAP.read_text(encoding="utf-8"),
    }
    normalized = {
        label: " ".join(text.split()) for label, text in lifecycle_texts.items()
    }
    receipt_pattern = re.compile(
        r"PR #95 at `main@([0-9a-f]{8})`(?: \(|, )exact head `([0-9a-f]{8})`, "
        r"exact-head CI `([0-9]+)`, (?:and )?post-merge CI `([0-9]+)`\)?"
    )
    expected = {("42abaab7", "d7c0938f", "30737466988", "30738303497")}
    for label, text in normalized.items():
        assert set(receipt_pattern.findall(text)) == expected, (
            f"{label} has inconsistent T6 receipts"
        )

    assert "| T6 | MERGED |" in lifecycle_texts["lease map"]
    assert "No GoalEx lifecycle or source node is admitted" in normalized["lease map"]
    assert (
        "no GoalEx lifecycle or source node is currently admitted"
        in normalized["GOAL.md"]
    )
    assert "no lifecycle writer is now admitted" in normalized[".planning/STATE.md"]


def test_unrecorded_post_baseline_merge_is_detected(
    tmp_path: Path, monkeypatch
) -> None:
    """A PR landing on main after the baseline must not pass unrecorded.

    Ancestry-only checking accepted any superseded baseline; this pins the
    replacement so the detector cannot silently regress to that behaviour.
    """
    last_pr_merge = subprocess.run(
        [
            "git",
            "log",
            "--merges",
            "--grep=^Merge pull request #",
            "-1",
            "--format=%H %s",
            "refs/remotes/origin/main",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert last_pr_merge, "expected at least one PR merge on origin/main"

    merge_sha, subject = last_pr_merge.split(" ", 1)
    matched = MERGED_PR.match(subject)
    assert matched, f"unparsable merge subject: {subject}"
    pr_number = matched.group(1)

    # The commit main sat on immediately before that PR landed: a baseline
    # recorded there is stale by exactly one merge.
    stale_baseline = subprocess.run(
        ["git", "rev-parse", f"{merge_sha}^1"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    lease_without_receipt = tmp_path / "lease-map-missing-receipt.md"
    lease_without_receipt.write_text(
        "This lease map records no receipts.\n", encoding="utf-8"
    )
    monkeypatch.setitem(globals(), "DEPENDENCY_LEASE_MAP", lease_without_receipt)
    assert pr_number in _unrecorded_merged_prs(stale_baseline), (
        f"PR #{pr_number} landed after {stale_baseline} and is absent from the "
        "lease map, so it must be reported as unrecorded"
    )


def test_unstructured_pr_mention_does_not_count_as_a_record(
    tmp_path: Path, monkeypatch
) -> None:
    """Prose naming a PR must not satisfy the gate — only a structured entry.

    The lease map cites PR numbers constantly in narrative text. If any mention
    counted, a merge could be authorised by an unrelated sentence rather than by
    a lifecycle entry carrying receipts.
    """
    merged = subprocess.run(
        [
            "git",
            "log",
            "--merges",
            "--grep=^Merge pull request #",
            "-1",
            "--format=%H %s",
            "refs/remotes/origin/main",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    merge_sha, subject = merged.split(" ", 1)
    pr_number = MERGED_PR.match(subject).group(1)
    stale_baseline = subprocess.run(
        ["git", "rev-parse", f"{merge_sha}^1"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    prose_only = tmp_path / "lease-map-prose-only.md"
    prose_only.write_text(
        f"PR #{pr_number} was discussed here, and PR #{pr_number} is pending.\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "DEPENDENCY_LEASE_MAP", prose_only)
    assert pr_number in _unrecorded_merged_prs(stale_baseline), (
        "a prose mention must not be accepted as a lease-map record"
    )

    structured = tmp_path / "lease-map-structured.md"
    structured.write_text(
        f"- PR #{pr_number}: delivered, receipts recorded.\n", encoding="utf-8"
    )
    monkeypatch.setitem(globals(), "DEPENDENCY_LEASE_MAP", structured)
    assert pr_number not in _unrecorded_merged_prs(stale_baseline), (
        "a structured entry must be accepted as a lease-map record"
    )


def test_merge_subject_variants_are_all_recognised() -> None:
    """Receipt detection must not depend on GitHub's default subject alone."""
    for subject, expected in (
        ("Merge pull request #96 from onfire7777/codex/x", "96"),
        ("Merge PR #96: land the thing", "96"),
        ("Merge #96: land the thing", "96"),
    ):
        matched = MERGED_PR.match(subject)
        assert matched and matched.group(1) == expected, subject
    # Issue references in this repo use the trailing "(#N)" form, so that shape
    # must not be read as a PR merge.
    assert not MERGED_PR.match("feat(phase12): Lease G wire — corroboration (#17)")


def test_stale_alternate_canonical_baseline_claim_fails(
    tmp_path: Path, monkeypatch
) -> None:
    goal_text = GOAL.read_text(encoding="utf-8")
    duplicate_goal = tmp_path / "GOAL.md"
    duplicate_goal.write_text(
        goal_text + "\nThe current canonical baseline is `main@deadbeef`.\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "GOAL", duplicate_goal)

    try:
        test_canonical_baseline_is_identical_across_the_three_lifecycle_files()
    except AssertionError:
        return
    raise AssertionError("stale alternate canonical-baseline claim was accepted")


def test_non_ancestral_baseline_commit_fails(tmp_path: Path, monkeypatch) -> None:
    commit_env = os.environ | {
        "GIT_AUTHOR_NAME": "planning-traceability-test",
        "GIT_AUTHOR_EMAIL": "planning-traceability-test@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_NAME": "planning-traceability-test",
        "GIT_COMMITTER_EMAIL": "planning-traceability-test@example.invalid",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    }
    non_ancestor = subprocess.run(
        ["git", "commit-tree", "HEAD^{tree}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        input="object-only non-ancestral baseline\n",
        text=True,
        env=commit_env,
    ).stdout.strip()
    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            non_ancestor,
            "refs/remotes/origin/main",
        ],
        cwd=ROOT,
        capture_output=True,
    )
    assert ancestry.returncode == 1

    lease_text = DEPENDENCY_LEASE_MAP.read_text(encoding="utf-8")
    baseline = LEASE_BASELINE.findall(lease_text)[0]
    for global_name, source in (
        ("GOAL", GOAL),
        ("STATE", STATE),
        ("DEPENDENCY_LEASE_MAP", DEPENDENCY_LEASE_MAP),
    ):
        substituted = tmp_path / global_name
        substituted.write_text(
            source.read_text(encoding="utf-8")
            .replace(baseline, non_ancestor)
            .replace(baseline[:8], non_ancestor[:8]),
            encoding="utf-8",
        )
        monkeypatch.setitem(globals(), global_name, substituted)

    try:
        test_canonical_baseline_is_identical_across_the_three_lifecycle_files()
    except (AssertionError, subprocess.CalledProcessError):
        return
    raise AssertionError("non-ancestral baseline commit was accepted")


def test_lease_map_body_names_only_the_header_baseline() -> None:
    lease_text = DEPENDENCY_LEASE_MAP.read_text(encoding="utf-8")
    baselines = LEASE_BASELINE.findall(lease_text)
    assert len(baselines) == 1, f"expected exactly one Baseline line, got {baselines}"
    short = baselines[0][:8]
    normalized = " ".join(lease_text.split())

    claimed = [
        claim
        for pattern in LEASE_CURRENT_BASELINE_CLAIMS
        for claim in pattern.findall(normalized)
    ]
    assert len(claimed) == 1, (
        "lease map must make exactly one recognized in-body current-baseline claim, "
        f"got {claimed}"
    )
    assert claimed[0] == short, (
        f"the lease map's current-baseline claim must name `main@{short}`, "
        f"got {claimed[0]}"
    )


def test_phase_13_truth_lease_names_existing_authoritative_files() -> None:
    text = DEPENDENCY_LEASE_MAP.read_text(encoding="utf-8")
    t0_row = next(line for line in text.splitlines() if line.startswith("| T0 |"))
    for relative_path in (
        ".planning/phases/13-external-benchmark-adapters-and-scheduled-ci/"
        "13-01-PLAN.md",
        ".planning/phases/13-external-benchmark-adapters-and-scheduled-ci/"
        "13-01-SUMMARY.md",
    ):
        assert f"`{relative_path}`" in t0_row
        assert (ROOT / relative_path).is_file()
    assert "13-source-adapter-parity" not in t0_row


def test_v2_memory_plane_requirements_are_complete_and_traceable() -> None:
    text = V2_REQUIREMENTS.read_text(encoding="utf-8")
    expected_rows = {
        "CAP-012": (
            "Prospective memory persists subject-scoped intentions and evaluates "
            "supported triggers deterministically and idempotently with provenance "
            "and audit records across Local, Postgres, and Sqlite engines.",
            "W3 P1/P4",
        ),
        "CAP-013": (
            "Working memory provides tenant/session-scoped short-TTL storage, "
            "explicit promotion, deterministic expiry, and a distinct retrieval "
            "route across Local, Postgres, and Sqlite engines.",
            "W3 P3/P4",
        ),
    }

    rows_by_requirement: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = V2_CAP_ROW.match(line)
        if match:
            rows_by_requirement.setdefault(match.group(1), []).append(line)

    for requirement, (description, authority) in expected_rows.items():
        assert rows_by_requirement.get(requirement) == [
            f"| [x] {requirement} | {description} | {authority} | Complete |"
        ]

    phase_15 = next(line for line in text.splitlines() if line.startswith("| 15 |"))
    assert phase_15 == "| 15 | CAP-004..011, CAP-012, CAP-013, RAIL-001..004 |"
    assert _frontmatter_list(
        PHASE_15_S4_PLAN.read_text(encoding="utf-8"), "requirements"
    ) == {"CAP-006", "CAP-011", "RAIL-001", "RAIL-002", "RAIL-003", "RAIL-004"}
    roadmap = V2_ROADMAP.read_text(encoding="utf-8")
    phase_15_roadmap = roadmap.split("### Phase 15:", 1)[1].split("\n### Phase 16:", 1)[
        0
    ]
    assert (
        "**Requirements:** CAP-004..011, CAP-012, CAP-013, RAIL-001..004"
        in phase_15_roadmap
    )
    assert "remaining Phase 15 items (CAP-004..011) stay planned" in phase_15_roadmap


def test_memory_plane_architecture_documents_routes_and_ownership() -> None:
    text = ARCHITECTURE_OVERVIEW.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for expected in (
        "prospective_memory",
        "working_memory",
        "without firing or mutating them",
        "never promotes them implicitly",
        "Local, Postgres, and Sqlite engines",
        "kind ∈ {evidence, assertion, relation, preference, intention, working}",
        "remain data-only",
        "docs/ENGINE-CONTRACT.md",
    ):
        assert expected in normalized

    for engine_contract_detail in (
        "schedule_intention",
        "evaluate_due_intentions",
        "put_working",
        "expire_working",
    ):
        assert engine_contract_detail not in normalized


def test_engine_contract_documents_three_engine_memory_plane_parity() -> None:
    text = ENGINE_CONTRACT.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for expected in (
        '@pytest.fixture(params=["local", "postgres", "sqlite"])',
        "schedule_intention",
        "cancel_intention",
        "list_intentions",
        "evaluate_due_intentions",
        "put_working",
        "get_working",
        "list_working",
        "expire_working",
        "created_at <= as_of < expires_at",
        "session_id`, `user_id`, `agent_id`, `task_id`, and `branch",
        "legacy tombstone",
        "limited to erased-replay detection",
        "restricted to the owning user or agent",
        "working_promote",
        "working-promote",
        "PromotionGate",
        "Memory-plane implementation mapping",
        "SqliteEngine (`src/mnemosyne/sqlite_engine.py`)",
    ):
        assert expected in normalized


def test_goalex_round_cleanup_contract_is_behaviorally_reproducible() -> None:
    goal = " ".join((ROOT / "GOAL.md").read_text(encoding="utf-8").split()).replace(
        "`", ""
    )
    for primitive in (
        "relative path bytes",
        "lstat object type and permission bits",
        "SHA-256 over raw bytes",
        "raw readlink target bytes",
        "keyed digest of the local bytes",
        "secret-bearing regular-file row",
        "operator-approved encrypted custody location",
        "owner's lock/quiescence",
        "temporary access-controlled snapshot",
        "Delete it after the final successful manifest comparison",
        "subject to the secret/privacy/custody export restrictions above",
        "any round-owned artifact whose classification forbids export",
        "round-start HEAD",
        "current HEAD",
        "git diff --cached --quiet",
        "git diff --quiet",
    ):
        assert primitive in goal

    with tempfile.TemporaryDirectory(prefix="mnemo-goalex-clean-") as tmp:
        repo = Path(tmp)

        def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                ["git", *args], cwd=repo, check=check, capture_output=True
            )

        def ignored_manifest(root: Path) -> tuple[tuple[bytes, int, int, bytes], ...]:
            rows: list[tuple[bytes, int, int, bytes]] = []
            pending = [root]
            while pending:
                path = pending.pop()
                metadata = path.lstat()
                relative = os.fsencode(str(path.relative_to(repo)))
                object_type = stat.S_IFMT(metadata.st_mode)
                permissions = stat.S_IMODE(metadata.st_mode)
                if stat.S_ISREG(metadata.st_mode):
                    identity = hashlib.sha256(path.read_bytes()).digest()
                elif stat.S_ISLNK(metadata.st_mode):
                    identity = os.readlink(os.fsencode(path))
                else:
                    identity = b""
                rows.append((relative, object_type, permissions, identity))
                if stat.S_ISDIR(metadata.st_mode):
                    pending.extend(path.iterdir())
            return tuple(sorted(rows))

        git("init", "-q")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "Test")
        (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        tracked = repo / "tracked.txt"
        tracked.write_bytes(b"A\n")
        git("add", ".gitignore", "tracked.txt")
        git("commit", "-qm", "fixture")

        ignored = repo / "ignored"
        nested = ignored / "nested"
        nested.mkdir(parents=True)
        binary = ignored / "binary.dat"
        binary.write_bytes(b"alpha\x00omega")
        binary.chmod(0o640)
        child = nested / "child.dat"
        child.write_bytes(b"child")
        regular = ignored / "object"
        regular.write_bytes(b"regular")
        baseline = ignored_manifest(ignored)

        binary.write_bytes(b"changed\x00omega")
        assert ignored_manifest(ignored) != baseline
        binary.write_bytes(b"alpha\x00omega")

        binary.chmod(0o600)
        assert ignored_manifest(ignored) != baseline
        binary.chmod(0o640)

        nested_mode = stat.S_IMODE(nested.stat().st_mode)
        nested.chmod(nested_mode ^ stat.S_IXOTH)
        assert ignored_manifest(ignored) != baseline
        nested.chmod(nested_mode)
        assert ignored_manifest(ignored) == baseline

        regular.unlink()
        regular.symlink_to("target-a")
        assert ignored_manifest(ignored) != baseline
        symlink_manifest = ignored_manifest(ignored)
        regular.unlink()
        regular.symlink_to("target-b")
        assert ignored_manifest(ignored) != symlink_manifest
        regular.unlink()
        regular.write_bytes(b"regular")

        child.write_bytes(b"nested-change")
        assert ignored_manifest(ignored) != baseline
        child.write_bytes(b"child")
        assert ignored_manifest(ignored) == baseline

        tracked.write_bytes(b"B\n")
        git("add", "tracked.txt")
        tracked.write_bytes(b"C\n")
        git("restore", "--source=HEAD", "--staged", "--worktree", "--", "tracked.txt")

        assert git("show", ":tracked.txt").stdout == b"A\n"
        assert tracked.read_bytes() == b"A\n"

        tracked.write_bytes(b"D\n")
        git("add", "tracked.txt")
        git("commit", "-qm", "valid round commit")
        tracked.write_bytes(b"E\n")
        git("add", "tracked.txt")
        tracked.write_bytes(b"F\n")
        git("restore", "--source=HEAD", "--staged", "--worktree", "--", "tracked.txt")

        assert git("show", ":tracked.txt").stdout == b"D\n"
        assert tracked.read_bytes() == b"D\n"
        assert git("diff", "--cached", "--quiet").returncode == 0
        assert git("diff", "--quiet").returncode == 0
        assert ignored_manifest(ignored) == baseline
        assert git("status", "--porcelain", "--untracked-files=all").stdout == b""
        assert git(
            "status", "--porcelain", "--untracked-files=all", "--ignored"
        ).stdout == (
            b"!! ignored/binary.dat\n!! ignored/nested/child.dat\n!! ignored/object\n"
        )


def _topology_fixture(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "topology"
    repo.mkdir(parents=True)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    for path, text in (
        (".planning/STATE.md", "anchor state\n"),
        ("GOAL.md", "anchor goal\n"),
        (
            "docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md",
            "anchor lease\n",
        ),
        ("immutable.txt", "anchor content\n"),
    ):
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "anchor")
    anchor = git("rev-parse", "HEAD")

    (repo / ".planning/STATE.md").write_text("parent state\n", encoding="utf-8")
    git("add", ".planning/STATE.md")
    git("commit", "-qm", "permitted parent")
    parent = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "candidate")
    return repo, git("rev-parse", "HEAD"), parent, anchor


def _verify_topology(repo: Path, *refs: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOPOLOGY_VERIFIER), *refs],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def _topology_module() -> object:
    spec = importlib.util.spec_from_file_location("topology_verifier", TOPOLOGY_VERIFIER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_topology_refresh_verifier_accepts_permitted_lifecycle_only_change(
    tmp_path: Path,
) -> None:
    repo, candidate, parent, anchor = _topology_fixture(tmp_path)
    result = _verify_topology(repo, candidate, parent, anchor)
    assert result.returncode == 0, result.stdout
    assert not result.stdout


def test_topology_refresh_verifier_rejects_non_lifecycle_drift(
    tmp_path: Path,
) -> None:
    for change, path, content in (
        ("content", "immutable.txt", "changed\n"),
        ("addition", "added.txt", "added\n"),
        ("deletion", "immutable.txt", None),
        ("rename", "renamed.txt", "anchor content\n"),
        ("mode", "immutable.txt", None),
    ):
        repo, _, parent, anchor = _topology_fixture(tmp_path / change)
        if change == "deletion":
            (repo / path).unlink()
        elif change == "rename":
            (repo / "immutable.txt").rename(repo / path)
        elif change != "mode":
            (repo / path).write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        if change == "mode":
            subprocess.run(
                ["git", "update-index", "--chmod=+x", path],
                cwd=repo,
                check=True,
            )
        subprocess.run(["git", "commit", "-qm", change], cwd=repo, check=True)
        candidate = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = _verify_topology(repo, candidate, parent, anchor)
        assert result.returncode == 1, (change, result.stdout)
        assert f"immutable path differs from anchor: {path}" in result.stdout


def test_topology_refresh_verifier_rejects_lifecycle_missing_or_different(
    tmp_path: Path,
) -> None:
    repo, _, parent, anchor = _topology_fixture(tmp_path)
    (repo / "GOAL.md").unlink()
    (repo / ".planning/STATE.md").write_text("different\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bad lifecycle"], cwd=repo, check=True)
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    result = _verify_topology(repo, candidate, parent, anchor)
    assert result.returncode == 1, result.stdout
    assert "lifecycle path missing from candidate: GOAL.md" in result.stdout
    assert "lifecycle path differs from permitted parent: .planning/STATE.md" in result.stdout


def test_topology_refresh_verifier_rejects_missing_parent_lifecycle_path(
    tmp_path: Path,
) -> None:
    repo, _, _, anchor = _topology_fixture(tmp_path)
    (repo / "GOAL.md").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "parent missing lifecycle"], cwd=repo, check=True)
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(
        ["git", "commit", "--allow-empty", "-qm", "candidate"], cwd=repo, check=True
    )
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    result = _verify_topology(repo, candidate, parent, anchor)
    assert result.returncode == 1, result.stdout
    assert "lifecycle path missing from permitted parent: GOAL.md" in result.stdout


def test_topology_refresh_verifier_rejects_unresolvable_full_sha(tmp_path: Path) -> None:
    repo, _, parent, anchor = _topology_fixture(tmp_path)
    result = _verify_topology(repo, "f" * 40, parent, anchor)
    assert result.returncode == 2
    assert result.stdout == "error: cannot read tree for " + "f" * 40 + "\n"


def test_topology_refresh_verifier_rejects_malformed_tree_output(
    monkeypatch, capsys
) -> None:
    module = _topology_module()
    valid = b"100644 blob " + b"0" * 40 + b"\tvalid"
    for output in (
        valid,
        valid + b"\0\0",
        b"100644 blob\tvalid\0",
        b"100600 blob " + b"0" * 40 + b"\tvalid\0",
        b"100644 commit " + b"0" * 40 + b"\tvalid\0",
        b"100644 blob " + b"F" * 40 + b"\tvalid\0",
        b"100644 blob " + b"0" * 40 + b"\t\0",
        valid + b"\0" + valid + b"\0",
    ):
        monkeypatch.setattr(
            module.subprocess,
            "run",
            lambda *args, output=output, **kwargs: subprocess.CompletedProcess(
                args, 0, stdout=output
            ),
        )
        assert module.main(["script", "a" * 40, "b" * 40, "c" * 40]) == 2
        assert capsys.readouterr().out == "error: cannot parse tree for " + "a" * 40 + "\n"


def test_topology_refresh_verifier_escapes_unusual_path_bytes() -> None:
    assert _topology_module()._path(b"line\n\xff\tname") == r"line\n\xff\tname"


def test_topology_refresh_verifier_normalizes_git_launch_error(monkeypatch, capsys) -> None:
    module = _topology_module()

    def cannot_run_git(*args: object, **kwargs: object) -> None:
        raise OSError("locale-dependent launch detail")

    monkeypatch.setattr(module.subprocess, "run", cannot_run_git)
    assert module.main(["script", "a" * 40, "b" * 40, "c" * 40]) == 2
    assert capsys.readouterr().out == "error: cannot run git\n"


def test_goal_documents_topology_refresh_verifier_invocation() -> None:
    goal = GOAL.read_text(encoding="utf-8")
    assert (
        'python3 infra/scripts/verify-topology-refresh.py \\\n'
        '  "$CANDIDATE_SHA" \\\n'
        '  "$PERMITTED_PARENT_SHA" \\\n'
        '  "$IMMUTABLE_ANCHOR_SHA"'
    ) in goal
