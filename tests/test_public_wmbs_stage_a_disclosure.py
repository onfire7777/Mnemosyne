"""Pin the M02/M04/M05 Stage-A development gap disclosure in the public README.

The README section ``M02/M04/M05 Stage-A development oracles (unregistered)`` is
the only place a reader of the public harness learns that those three modules run
no system, are unregistered, and carry no publication or headline claim.  It
therefore must neither be deleted nor drift away from the modules and fixtures it
describes.  This mirrors the M12 and M13 pinning tests in
``tests/test_public_pm_bench_triggerbench.py`` and
``tests/test_public_working_memory_action_probe.py``.

Nothing here changes module behavior, fixture bytes, the registry, the adapter,
runner routing, or a scoring profile; it only refuses to let the honest labels
rot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.public import wmbs_m02 as m02
from eval.public import wmbs_m04 as m04
from eval.public import wmbs_m05 as m05
from eval.public.runner import load_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "eval" / "public" / "README.md"
FIXTURES_DIR = REPO_ROOT / "eval" / "public" / "fixtures"

SECTION_HEADING = "### M02/M04/M05 Stage-A development oracles (unregistered)"

#: Registry keys the disclosure asserts do not exist.  If Stage B ever lands one
#: of these, the disclosure text has become false and must be rewritten in the
#: same change.
UNREGISTERED_SUITE_KEYS = (
    "wmbs-m02-retrieval-development",
    "wmbs-m04-development",
    "wmbs-m05-provenance-development",
)


def _readme() -> str:
    """Return the README with line wrapping collapsed to single spaces."""
    return " ".join(README_PATH.read_text(encoding="utf-8").split())


def _disclosure_section() -> str:
    text = README_PATH.read_text(encoding="utf-8")
    assert SECTION_HEADING in text, "the Stage-A gap disclosure section was removed"
    body = text.split(SECTION_HEADING, 1)[1]
    # The section runs to the next heading of any level, or to end of file.
    for line in body.splitlines():
        if line.startswith("#"):
            body = body.split("\n" + line, 1)[0]
            break
    return " ".join(body.split())


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_disclosure_section_exists_and_names_all_three_modules() -> None:
    section = _disclosure_section()
    for module_file in ("`wmbs_m02.py`", "`wmbs_m04.py`", "`wmbs_m05.py`"):
        assert module_file in section, f"{module_file} dropped from the disclosure"
    assert "Stage-A development oracles" in section
    assert "runs no system and observes no SUT" in section
    assert "nothing whatsoever about any memory system" in section, (
        "the no-evidence statement is the point of the disclosure"
    )


def test_disclosure_states_the_unregistered_status_and_the_registry_agrees() -> None:
    """The 'unregistered' claim must stay true of the live registry.

    Asserting both halves is what makes this a pin rather than a spell check: a
    future ``wmbs-m02``/``m04``/``m05`` registry entry fails here and forces the
    disclosure to be rewritten alongside it.
    """
    section = _disclosure_section()
    assert "All three are **unregistered**." in section
    assert (
        "None has a `registry.json` entry, an adapter, a runner route, or a" in section
    )
    assert "scoring-profile registration" in section
    assert "none produces a bundle, and none produces a benchmark result" in section

    registry = load_registry()
    for key in UNREGISTERED_SUITE_KEYS:
        assert key not in registry, (
            f"{key} is now registered; the README Stage-A disclosure claims it is "
            "unregistered and must be rewritten in the same change"
        )
    # Also catch a differently-named entry for the same modules.
    registry_blob = json.dumps(registry)
    for module_id in ("wmbs-m02", "wmbs-m04", "wmbs-m05"):
        assert module_id not in registry_blob, (
            f"a registry entry now mentions {module_id}; update the Stage-A "
            "disclosure before registering these modules"
        )


def test_disclosure_admission_labels_match_the_modules() -> None:
    section = _disclosure_section()
    assert "Every one of them is admission state `PROPOSED`" in section
    assert 'M02 and M04 declare `ADMISSION_STATE = "PROPOSED"` directly' in section
    assert (
        '`admission_state: "PROPOSED"` in both its labels and its committed' in section
    )
    assert "`publishable: false` and `pbpp_headline_eligible: false`" in section
    assert "M02 emits no publication or headline field at all" in section

    assert m02.ADMISSION_STATE == "PROPOSED"
    assert m04.ADMISSION_STATE == "PROPOSED"

    m05_fixture = _fixture("wmbs-m05-provenance-development.json")
    assert m05_fixture["admission_state"] == "PROPOSED"
    assert m05_fixture["publishable"] is False
    assert m05_fixture["pbpp_headline_eligible"] is False
    assert m05._LABELS["publishable"] is False
    assert m05._LABELS["pbpp_headline_eligible"] is False

    # M02 makes no publication claim anywhere in its module or fixture: pin the
    # absence, not just the prose asserting it.
    m02_fixture = _fixture("wmbs-m02-retrieval-development.json")
    assert not [key for key in m02_fixture if "publish" in key or "headline" in key]
    m02_source = (REPO_ROOT / "eval" / "public" / "wmbs_m02.py").read_text(
        encoding="utf-8"
    )
    assert "pbpp_headline_eligible" not in m02_source
    assert "publishable" not in m02_source


def test_disclosure_license_claim_matches_the_modules() -> None:
    section = _disclosure_section()
    assert 'M02 and M05 declare `license: "CC0-1.0"`' in section
    assert "M04 declares no license field at all" in section

    assert m02.LICENSE == "CC0-1.0"
    assert m05.LICENSE == "CC0-1.0"
    assert _fixture("wmbs-m02-retrieval-development.json")["license"] == "CC0-1.0"
    assert _fixture("wmbs-m05-provenance-development.json")["license"] == "CC0-1.0"
    assert "license" not in _fixture("wmbs-m04-development.json")
    assert not hasattr(m04, "LICENSE")


def test_disclosure_cost_and_resource_gaps_match_the_scorers() -> None:
    section = _disclosure_section()
    assert "None of the three measures cost or resources." in section
    assert (
        "M02's scorer reports `latency`, `tokens`, `calls`, and `storage` "
        "literally as `unsupported`" in section
    )
    assert "M04 and M05 emit no latency, token, call, or storage metric" in section

    m04_source = (REPO_ROOT / "eval" / "public" / "wmbs_m04.py").read_text(
        encoding="utf-8"
    )
    m05_source = (REPO_ROOT / "eval" / "public" / "wmbs_m05.py").read_text(
        encoding="utf-8"
    )
    for source, name in ((m04_source, "M04"), (m05_source, "M05")):
        for metric in ('"latency"', '"tokens"', '"calls"', '"storage"'):
            assert metric not in source, (
                f"{name} now emits {metric}; the Stage-A disclosure says it emits "
                "no cost or resource metric"
            )


def test_disclosure_m02_fixture_shape_matches_the_committed_bytes() -> None:
    section = _disclosure_section()
    assert (
        "generated from seed `20260801` and holds 240 documents and 60 questions"
        in (section)
    )
    assert "ten per query family" in section
    assert (
        "The specification names a 2,000-event local corpus; Stage A commits 240 "
        "documents and defers the 2,000-event variant" in section
    )

    fixture = _fixture("wmbs-m02-retrieval-development.json")
    assert fixture["seed"] == 20260801 == m02.DEFAULT_SEED
    assert len(fixture["corpus"]) == 240
    assert len(fixture["questions"]) == 60
    families = sorted({question["family"] for question in fixture["questions"]})
    assert families == [
        "entity",
        "exact",
        "multi-hop",
        "paraphrase",
        "relation",
        "unanswerable",
    ]
    for family in families:
        assert (
            sum(question["family"] == family for question in fixture["questions"]) == 10
        )
        assert f"`{family}`" in section


def test_disclosure_m04_fixture_shape_and_declared_gaps_match() -> None:
    section = _disclosure_section()
    assert "generated from seed `20260801` and holds 140 cases over five per-case" in (
        section
    )
    assert "Numeric confidence calibration is `unsupported`" in section
    assert "`branch_merge` as `UNSUPPORTED-BY-SYSTEM`" in section
    assert "`transaction_time` as `unsupported`" in section
    assert "`update_hook` as `emulated`" in section
    assert "the `sqlite` and `postgresql` backends as `DEFERRED`" in section
    assert (
        "an additional load-bearing `source_id` that keys the ablation gold" in section
    )
    assert "never an ABI conformance claim" in section

    fixture = _fixture("wmbs-m04-development.json")
    assert fixture["seed"] == 20260801 == m04.DEFAULT_SEED
    assert len(fixture["cases"]) == 140
    assert tuple(fixture["seeds"]) == m04.SEEDS == (11, 23, 37, 53, 71)
    assert tuple(fixture["permutations"]) == m04.PERMUTATIONS
    assert tuple(fixture["source_classes"]) == m04.SOURCE_CLASSES
    for seed in fixture["seeds"]:
        assert f"`{seed}`" in section
    for name in list(fixture["permutations"]) + list(fixture["source_classes"]):
        assert f"`{name}`" in section

    disclosures = fixture["disclosures"]
    assert disclosures["branch_merge"] == "UNSUPPORTED-BY-SYSTEM"
    assert disclosures["transaction_time"] == "unsupported"
    assert disclosures["update_hook"] == "emulated"
    assert disclosures["backends"]["sqlite"] == "DEFERRED"
    assert disclosures["backends"]["postgresql"] == "DEFERRED"

    # The `source_id` departure is the disclosure's most load-bearing admission:
    # pin that the key is really there rather than trusting the prose.
    events = [
        event
        for case in fixture["cases"]
        for bundle in case["events_by_permutation"].values()
        for event in bundle
    ]
    assert events, "the M04 fixture must carry events for this pin to mean anything"
    assert all("source_id" in event for event in events)


def test_disclosure_m05_fixture_shape_and_deferrals_match() -> None:
    section = _disclosure_section()
    assert "generated from seed `13`, declares the five seeds" in section
    assert "five slices of twenty cases each" in section
    assert (
        "The module declares three retrieval stage IDs (`dense_hash`, `lexical`, "
        "`graph_ppr`), but every committed case freezes `lexical` alone" in section
    )
    assert "It scores **one-hop** claim-to-source grounding only" in section
    assert "explicitly **unsigned** (`signed: false`" in section
    assert (
        "eight unresolved integration dependencies in `INTEGRATION_DEPENDENCIES`"
        in (section)
    )

    fixture = _fixture("wmbs-m05-provenance-development.json")
    assert fixture["generator_seed"] == 13
    assert tuple(fixture["seeds"]) == m05.SEEDS == (13, 29, 41, 59, 73)
    for seed in fixture["seeds"]:
        assert f"`{seed}`" in section

    slices = fixture["slices"]
    assert len(slices) == 5
    for slice_ in slices:
        assert len(slice_["cases"]) == 20
        assert f"`{slice_['slice_id']}`" in section

    assert m05.RETRIEVAL_STAGE_IDS == ("dense_hash", "lexical", "graph_ppr")
    exercised = sorted(
        {
            stage
            for slice_ in slices
            for case in slice_["cases"]
            for stage in case["retrieval_stages"]
        }
    )
    assert exercised == ["lexical"], (
        "the committed M05 cases now exercise more than the lexical stage; the "
        "README disclosure says they freeze `lexical` alone"
    )

    assert fixture["source_manifest"]["signed"] is False
    dependencies = fixture["integration_dependencies"]
    assert len(dependencies) == 8 == len(m05.INTEGRATION_DEPENDENCIES)
    for tag in ("Q1", "Q2", "Q3", "Q4", "Q7", "Q9", "Q10", "Q12"):
        assert any(dependency.startswith(tag) for dependency in dependencies)
        assert f"{tag} " in section


def test_disclosure_keeps_stage_b_undelivered_and_claims_nothing() -> None:
    section = _disclosure_section()
    assert (
        "Stage B — harness integration for all three modules — is **not delivered**."
        in (section)
    )
    assert "gated on the public-harness integration owner's lease" in section
    assert (
        "Nothing here is a publication, comparability, ranking, superiority, or "
        "upstream-equivalence claim." in section
    )

    for plan in (
        "docs/plans/wmb-m02-retrieval-organization-implementation-plan.md",
        "docs/plans/wmb-m04-conflict-correction-implementation-plan.md",
        "docs/plans/wmb-m05-provenance-explanation-implementation-plan.md",
    ):
        assert plan in section, f"the disclosure no longer links {plan}"
        assert (REPO_ROOT / plan).is_file(), f"{plan} is linked but missing"


@pytest.mark.parametrize("module_id", ["wmbs-m02", "wmbs-m04", "wmbs-m05"])
def test_disclosure_section_precedes_no_registration_elsewhere(module_id: str) -> None:
    """No other public-harness doc may register what the disclosure calls absent."""
    readme = _readme()
    assert f"--suite {module_id}" not in readme, (
        f"the README now documents selecting {module_id} with `--suite`, which "
        "contradicts the Stage-A unregistered disclosure"
    )
