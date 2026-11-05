from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.canary_overlay import THIN_CANARIES_ENV
from mnemosyne.engine import LocalMemoryEngine, _merge_relation_overlap_component
from mnemosyne.models import Relation


@pytest.mark.parametrize("duration", [0, -5])
@pytest.mark.parametrize("thin", ["0", "1"])
def test_canary_replay_does_not_clone_same_closed_relation(duration, thin, monkeypatch):
    monkeypatch.setenv(THIN_CANARIES_ENV, thin)
    engine = LocalMemoryEngine()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    relation = Relation("t", "source", "relates to", "target", valid_from=start,
                        valid_to=start + timedelta(seconds=duration))
    engine.add_relation(relation)
    for index in range(8):
        branch = f"canary-{index}"
        engine.branch(branch, frm="main", kind="canary", tenant_id="t")
        engine.merge(branch, into="main", tenant_id="t")
        rows = list(engine.relations.in_branch("t", "main").values())
        assert len(rows) == 1
        assert rows[0].id == relation.id
        assert rows[0].valid_from == start
        assert rows[0].valid_to == start + timedelta(seconds=duration)


def test_closed_distinct_relation_identity_is_not_deduplicated():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    retained = Relation("t", "source", "relates to", "target", valid_from=start, valid_to=start)
    incoming = deepcopy(retained)
    incoming.id = "distinct-historical-row"
    assert _merge_relation_overlap_component(incoming, [retained]) == (None, [])
