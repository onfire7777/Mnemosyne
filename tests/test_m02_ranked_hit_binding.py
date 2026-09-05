"""M02 metrics must follow returned hit order, never diagnostic text."""

from eval.public.adapters.whole_memory_reference import _m02_ranked_ids


CORPUS = {"first": "The first document.", "second": "The second document."}


def test_content_bound_hits_preserve_returned_order():
    result = {
        "hits": [
            {"id": "cid-second", "text": CORPUS["second"]},
            {"id": "cid-first", "text": CORPUS["first"]},
        ]
    }
    assert _m02_ranked_ids(result, set(CORPUS), CORPUS) == ["second", "first"]


def test_diagnostics_cannot_invent_retrieval_hits():
    result = {"hits": [], "explain": {"query": CORPUS["first"]}}
    assert _m02_ranked_ids(result, set(CORPUS), CORPUS) == []


def test_stable_source_identity_wins_over_backend_specific_id():
    result = {"hits": [{"id": "cid-second", "source_identity": "second"}]}
    assert _m02_ranked_ids(result, set(CORPUS), CORPUS) == ["second"]


def test_ambiguous_content_cannot_invent_multiple_hits():
    corpus = {"a": "same", "b": "same"}
    result = {"hits": [{"id": "unknown", "text": "same"}]}
    assert _m02_ranked_ids(result, set(corpus), corpus) == []


def test_repeated_ids_keep_first_occurrence_and_ignore_outside_corpus():
    result = {"hits": ["second", "outside", "first", "second"]}
    assert _m02_ranked_ids(result, set(CORPUS), CORPUS) == ["second", "first"]
