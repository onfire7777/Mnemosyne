"""Pin the M01-M20 completeness inventory to the tree it was recomputed from.

The inventory at ``docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md``
is Round 0 of the operator's benchmark directive: a module-by-module table of
which artifacts exist for each Whole-Memory Benchmark Standard module. It is a
backlog, so it is only useful while it is true. These tests re-derive every
claim from the tree: each claimed path, scoring profile, scorer symbol,
registry key, and each explicit "no" cell.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = (
    ROOT / "docs" / "coordination" / "2026-08-03-wmbs-module-completeness-inventory.md"
)
REGISTRY = ROOT / "eval" / "public" / "registry.json"
SCORING = ROOT / "eval" / "public" / "scoring.py"
FIXTURE_DIR = ROOT / "eval" / "public" / "fixtures"
# The inventory's own definition of "scorer": a dedicated ``wmbs_mNN.py``, an
# inline dispatch in ``scoring.py``, or module logic in either of these two.
SCORER_SURFACES = (
    ROOT / "eval" / "public" / "adapters" / "whole_memory_reference.py",
    ROOT / "eval" / "public" / "bundle.py",
)

MODULES = tuple(f"M{index:02d}" for index in range(1, 21))

COLUMNS = (
    "module",
    "capability",
    "plan",
    "fixture",
    "scorer",
    "tests",
    "registry",
    "admission",
    "next_step",
)

# A backticked repository path, optionally suffixed with `:<line>`.
PATH_REF = re.compile(
    r"`((?:docs|eval|tests|leaderboard|adapters|\.planning)/[A-Za-z0-9_./-]+?)"
    r"(?::(\d+))?`"
)
# A bare `:<line>` continuation ref (`…py:94`, `:158`) reusing the previous path.
LINE_REF = re.compile(r"`:(\d+)`")
PROFILE_REF = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)*-v\d+)`")
SYMBOL_REF = re.compile(r"`((?:_score|run)_[a-z0-9_]+)`")
COUNT_CLAIM = re.compile(r"(\d+) of 20\.?\*\*")
# `wmbs_mNN.py`, `docs/plans/wmb-mNN-…` and friends are placeholders, not paths.
PLACEHOLDER = ("NN", "…", "*")


def _rows() -> dict[str, dict[str, str]]:
    """Parse the ``## M01-M20`` table into ``{module: {column: cell}}``."""
    rows: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\| M\d\d \|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == len(COLUMNS), (
            f"row {cells[0]!r} has {len(cells)} cells, expected {len(COLUMNS)}"
        )
        row = dict(zip(COLUMNS, cells))
        order.append(row["module"])
        rows[row["module"]] = row
    assert order == list(MODULES), (
        f"inventory rows are {order}, expected exactly {list(MODULES)} in order"
    )
    return rows


ROWS = _rows()


def _registry_keys() -> set[str]:
    return set(json.loads(REGISTRY.read_text(encoding="utf-8")))


def _claims_absent(cell: str) -> bool:
    """True when the cell opens with a bolded ``no`` verdict."""
    return cell.startswith("**no")


def _claims_satisfied(cell: str) -> bool:
    """Present, or absent with an explicit by-design exemption (M15)."""
    return not _claims_absent(cell) or "by design" in cell


def _resolve(ref: str) -> Path | None:
    """Resolve a cited path, which may be relative to ``eval/public/``."""
    if any(token in ref for token in PLACEHOLDER):
        return None
    direct = ROOT / ref
    if direct.exists():
        return direct
    nested = ROOT / "eval" / "public" / ref
    return nested if nested.exists() else direct


def _paths_in(cell: str) -> list[Path]:
    resolved = (_resolve(match.group(1)) for match in PATH_REF.finditer(cell))
    return [path for path in resolved if path is not None]


def test_table_covers_exactly_m01_through_m20() -> None:
    assert list(ROWS) == list(MODULES)
    assert len(ROWS) == len(set(ROWS)) == 20


def test_every_referenced_path_exists_with_the_claimed_line() -> None:
    """Every backticked repo path in the document resolves, line refs included."""
    text = INVENTORY.read_text(encoding="utf-8")
    seen_any = False
    for line in text.splitlines():
        # A bare `:N` ref continues the path that *precedes* it, so record
        # where each path was cited rather than keeping only the last one.
        anchors: list[tuple[int, Path]] = []
        for match in PATH_REF.finditer(line):
            path = _resolve(match.group(1))
            if path is None:
                continue
            seen_any = True
            assert path.exists(), f"inventory cites missing path {match.group(1)}"
            anchors.append((match.start(), path))
            if match.group(2) is not None:
                _assert_has_line(path, int(match.group(2)))
        for match in LINE_REF.finditer(line):
            preceding = [path for start, path in anchors if start < match.start()]
            if preceding and preceding[-1].is_file():
                _assert_has_line(preceding[-1], int(match.group(1)))
    assert seen_any, "inventory cites no repository paths at all"


def _assert_has_line(path: Path, lineno: int) -> None:
    assert path.is_file(), f"line ref {path}:{lineno} points at a non-file"
    total = len(path.read_text(encoding="utf-8").splitlines())
    assert lineno <= total, (
        f"inventory cites {path.relative_to(ROOT)}:{lineno} but the file has "
        f"{total} lines"
    )


def test_fixture_cells_match_the_fixture_directory() -> None:
    for module, row in ROWS.items():
        cell = row["fixture"]
        for path in _paths_in(cell):
            if path.parent == FIXTURE_DIR:
                assert path.is_file(), f"{module}: missing fixture {path.name}"
        if _claims_absent(cell):
            stray = sorted(FIXTURE_DIR.glob(f"*{module.lower()}*"))
            assert not stray, (
                f"{module}: fixture cell says no, but {stray} exist in the tree"
            )
        else:
            assert any(path.parent == FIXTURE_DIR for path in _paths_in(cell)), (
                f"{module}: fixture cell claims yes but cites no fixture file"
            )


def _dispatched_profiles() -> set[str]:
    """Every string literal inside ``scoring.py``'s ``score_profile`` body.

    Membership in the module's text is not enough: a removed routing branch
    leaves the profile name behind in scorer output and helper code, so the
    positive check below reads the dispatcher itself.
    """
    tree = ast.parse(SCORING.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "score_profile":
            return {
                literal.value
                for literal in ast.walk(node)
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str)
            }
    raise AssertionError("eval/public/scoring.py defines no score_profile function")


DISPATCHED_PROFILES = _dispatched_profiles()


def test_scorer_cells_match_the_scoring_surface() -> None:
    scoring_text = SCORING.read_text(encoding="utf-8")
    for module, row in ROWS.items():
        cell = row["scorer"]
        dedicated = ROOT / "eval" / "public" / f"wmbs_{module.lower()}.py"
        cited = _paths_in(cell)
        if _claims_absent(cell):
            assert not dedicated.exists(), (
                f"{module}: scorer cell says no, but {dedicated.name} exists"
            )
            assert f"wmbs-{module.lower()}-" not in scoring_text, (
                f"{module}: scorer cell says no, but scoring.py dispatches a "
                f"wmbs-{module.lower()} profile"
            )
            # The inventory counts the adapter and the bundle as scorer surfaces
            # too, so a "no" cell must hold across all three, not just the file
            # glob and the profile dispatch.
            #
            # Known limit: this is a module-ID scan, so a scorer that names
            # neither `mNN` nor `wmbs-mNN-` anywhere (say an M06 scorer routed
            # as `wmbs-consolidation-v1`) would slip past it. Closing that gap
            # needs a structured module-ID declaration inside the scorer
            # surfaces themselves, which is the public-harness integration
            # owner's lease and outside this documentation-and-tests node.
            marker = re.compile(rf"\b{module.lower()}\b", re.IGNORECASE)
            for surface in (SCORING, *SCORER_SURFACES):
                hit = marker.search(surface.read_text(encoding="utf-8"))
                assert hit is None, (
                    f"{module}: scorer cell says no, but "
                    f"{surface.relative_to(ROOT)} mentions {hit.group(0)!r}"
                )
            continue
        for profile in PROFILE_REF.findall(cell):
            assert profile in DISPATCHED_PROFILES, (
                f"{module}: cited profile {profile!r} is not dispatched inside "
                "score_profile in eval/public/scoring.py"
            )
        for symbol in SYMBOL_REF.findall(cell):
            sources = [path for path in cited if path.suffix == ".py"]
            assert sources, f"{module}: cites symbol {symbol!r} with no source file"
            assert any(
                f"def {symbol}(" in path.read_text(encoding="utf-8") for path in sources
            ), f"{module}: symbol {symbol!r} is defined in none of {sources}"


def test_plan_cells_separate_plan_existence_from_plan_approval() -> None:
    """A `PROPOSED` plan may never be recorded as an approved one.

    The ladder's step 2 is freeze/approval; recording a `PROPOSED` planning
    artifact as approved would let the inventory authorize implementation
    before that gate.
    """
    for module, row in ROWS.items():
        cell = row["plan"]
        if _claims_absent(cell):
            continue
        if "pilot plan" in cell:
            # The owner-landed pilot plan is the one approved exact plan.
            assert "not approved" not in cell, (
                f"{module}: cites the owner-landed pilot plan yet says 'not approved'"
            )
            continue
        plans = [path for path in _paths_in(cell) if path.parts[-2] == "plans"]
        assert plans, f"{module}: plan cell claims a plan but cites no plan file"
        proposed = [
            path
            for path in plans
            if any(
                marker in "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
                for marker in ("PROPOSED", "PLANNING ARTIFACT", "NOT CODE-READY")
            )
        ]
        if proposed:
            assert "not approved" in cell, (
                f"{module}: cites {[p.name for p in proposed]}, whose status header "
                "is PROPOSED, but the cell does not say 'not approved'"
            )
        else:
            assert "not approved" not in cell, (
                f"{module}: cell says 'not approved' but no cited plan is PROPOSED"
            )


def test_test_suite_cells_match_the_tests_directory() -> None:
    for module, row in ROWS.items():
        cell = row["tests"]
        cited = [path for path in _paths_in(cell) if path.parts[-2] == "tests"]
        if _claims_absent(cell):
            # Glob, not one exact filename: `test_public_wmbs_m06_extra.py`
            # contradicts a "no" cell just as squarely as the bare name does.
            stray = sorted(
                path.name
                for path in (ROOT / "tests").glob(f"test_*wmbs_{module.lower()}*.py")
            )
            assert not stray, (
                f"{module}: test cell says no, but {stray} exist in tests/"
            )
            continue
        assert cited, f"{module}: test cell claims yes but cites no test file"
        for path in cited:
            assert path.is_file(), f"{module}: missing test file {path}"


def test_registry_cells_match_registry_json() -> None:
    keys = _registry_keys()
    for module, row in ROWS.items():
        cell = row["registry"]
        cited = {name for name in re.findall(r"`([a-z0-9-]+-development)`", cell)}
        if _claims_absent(cell):
            assert not cited, f"{module}: registry cell says no yet names suites"
            stray = {key for key in keys if key.startswith(f"wmbs-{module.lower()}")}
            assert not stray, (
                f"{module}: registry cell says no, but registry.json has {stray}"
            )
            continue
        assert cited, f"{module}: registry cell claims yes but names no suite"
        for name in cited:
            assert name in keys, f"{module}: registry.json has no suite {name!r}"


def test_every_wmbs_artifact_in_the_tree_appears_in_the_table() -> None:
    """A new module artifact cannot land without the inventory noticing."""
    text = INVENTORY.read_text(encoding="utf-8")
    for path in sorted((ROOT / "eval" / "public").glob("wmbs_m*.py")):
        assert path.name in text, f"{path.name} exists but is absent from the inventory"
    for key in sorted(key for key in _registry_keys() if key.startswith("wmbs-")):
        assert key in text, f"registry suite {key!r} is absent from the inventory"
    for path in sorted(FIXTURE_DIR.glob("wmbs-*.json")):
        assert path.name in text, f"fixture {path.name} is absent from the inventory"


def test_correction_counts_match_the_table() -> None:
    """The bolded ``N of 20`` corrections are re-derived, not asserted."""
    text = INVENTORY.read_text(encoding="utf-8")
    claimed = [int(value) for value in COUNT_CLAIM.findall(text)]
    assert len(claimed) == 5, f"expected 5 bolded counts, found {claimed}"

    scorer_bearing = [m for m, row in ROWS.items() if not _claims_absent(row["scorer"])]
    registry_admitted = [
        m for m, row in ROWS.items() if not _claims_absent(row["registry"])
    ]
    planned = [m for m, row in ROWS.items() if not _claims_absent(row["plan"])]
    greenfield = [
        m
        for m, row in ROWS.items()
        if all(
            _claims_absent(row[column])
            for column in ("plan", "fixture", "scorer", "tests", "registry")
        )
    ]
    landed = [
        m
        for m, row in ROWS.items()
        if all(
            _claims_satisfied(row[column])
            for column in ("plan", "fixture", "scorer", "tests", "registry")
        )
    ]

    assert claimed == [
        len(scorer_bearing),
        len(registry_admitted),
        len(planned),
        len(greenfield),
        len(landed),
    ], (
        "corrections section disagrees with the table: "
        f"scorers={scorer_bearing}, registry={registry_admitted}, "
        f"plans={planned}, greenfield={greenfield}, landed={landed}"
    )
