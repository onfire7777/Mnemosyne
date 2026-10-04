from copy import deepcopy
import pytest
from eval.compact_answering.train_groups import group_rows, document_keys
from eval.compact_answering.train_intake import ASSETS


def row(identity, docs):
    repo, rev, path, _, digest = ASSETS[1]
    return {
        "upstream_id": identity,
        "raw_row_sha256": "a" * 64,
        "source": dict(repository=repo, revision=rev, path=path, sha256=digest),
        "split": "train",
        "training_admitted": False,
        "documents": [dict(title=t, context=c) for t, c in docs],
    }


def test_all_documents_connect_transitively_without_order_dependent_ids():
    rows = [
        row("a", [("First", "text one")]),
        row("b", [("First", "different paragraph"), ("Second", "text two")]),
        row("c", [("Alias", "text two")]),
        row("d", [("Separate", "unique")]),
    ]
    result, summary = group_rows(rows)
    assert result[0]["group_id"] == result[1]["group_id"] == result[2]["group_id"]
    assert result[3]["group_id"] != result[0]["group_id"]
    assert summary["groups"] == 2 and summary["largest_group_rows"] == 3
    reverse, _ = group_rows(reversed(rows))
    assert sorted(result, key=lambda x: x["row_identity_sha256"]) == sorted(
        reverse, key=lambda x: x["row_identity_sha256"]
    )


def test_title_aliases_and_normalized_context_are_explicit():
    a = document_keys(dict(title="Caf%C3%A9_au_lait", context="Ａ  B"))
    b = document_keys(dict(title="Cafe\u0301 au lait", context="a b"))
    assert a == b
    assert (
        document_keys(dict(title="Fish_&amp;_Chips", context="x"))[0]
        == document_keys(dict(title="fish & chips", context="y"))[0]
    )


def test_unapproved_or_ambiguous_rows_fail_closed():
    good = row("x", [("T", "C")])
    with pytest.raises(ValueError):
        group_rows([good, good])
    for field, value in [
        ("split", "validation"),
        ("training_admitted", True),
        ("documents", []),
    ]:
        bad = deepcopy(good)
        bad[field] = value
        with pytest.raises(ValueError):
            group_rows([bad])
    bad = deepcopy(good)
    bad["source"]["repository"] = "protected/eval"
    with pytest.raises(ValueError):
        group_rows([bad])
