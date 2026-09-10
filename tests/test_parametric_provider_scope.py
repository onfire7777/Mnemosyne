"""Exercise source eligibility at the real subprocess provider boundary."""

import sys

import pytest

from mnemosyne.learning import Lesson, Procedure
from mnemosyne.parametric import CommandParametricTrainer, ParametricTier


@pytest.mark.parametrize("kind", ["lessons", "procedures"])
def test_provider_never_receives_ineligible_records_sharing_a_source_id(kind):
    command = [sys.executable, "-c", (
        "import json,sys; p=json.load(sys.stdin); "
        "rows=p['lessons']+p['procedures']; "
        "print(json.dumps({'metrics':{'received':len(rows),"
        "'foreign':sum(r['tenant_id']!='tenant-a' for r in rows),"
        "'ineligible':sum(r['status']=='candidate' for r in rows)}}))"
    )]
    if kind == "lessons":
        rows = [Lesson(tenant, "corrective", "synthetic", "synthetic", status=status, id="shared")
                for tenant, status in [("tenant-a", "active"), ("tenant-b", "active"), ("tenant-a", "candidate")]]
    else:
        rows = [Procedure(tenant, "checklist", "synthetic", "synthetic", {}, status=status, id="shared")
                for tenant, status in [("tenant-a", "validated"), ("tenant-b", "validated"), ("tenant-a", "candidate")]]
    tier = ParametricTier(trainer=CommandParametricTrainer(command))
    artifact = tier.propose_from_lessons(
        "tenant-a", rows if kind == "lessons" else [], rows if kind == "procedures" else []
    )
    assert artifact.source_ids == ["shared"]
    assert artifact.metrics["received"] == 1
    assert artifact.metrics["foreign"] == 0
    assert artifact.metrics["ineligible"] == 0
