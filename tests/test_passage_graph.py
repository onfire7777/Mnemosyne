"""The HippoRAG passage graph: fact-seeded PPR reaches the second-hop passage, the index only
ever sees passages a reader may read, and erasure purges what was derived from a passage."""

from __future__ import annotations

import hashlib
import json
import math
import re

import pytest

pytest.importorskip("numpy")

from mnemosyne.engine import LocalMemoryEngine  # noqa: E402
from mnemosyne.mcp_tools import MemoryTools  # noqa: E402
from mnemosyne.models import Evidence  # noqa: E402
from mnemosyne.passages import (  # noqa: E402
    OPENIE_PROMPT,
    PassageGraphIndex,
    PassageIndexStore,
    _embed,
    clean_triples,
    phrase_key,
)
from mnemosyne.retrieval import RetrievalAdapters  # noqa: E402

TENANT = "graph-tenant"


@pytest.mark.parametrize("vector", [[1.0], [float("nan"), 0.0], [float("inf"), 0.0], [True, 0.0]])
@pytest.mark.parametrize("batched", [False, True])
def test_passage_embedding_rejects_invalid_vectors(vector, batched):
    class InvalidEmbedder:
        dims = 2

        def embed(self, text):
            return vector

    provider = InvalidEmbedder()
    if batched:
        provider.embed_many = lambda texts: [vector for _ in texts]
    with pytest.raises(ValueError):
        _embed(provider, ["synthetic passage"])


def test_passage_embedding_preserves_valid_batch():
    class Provider:
        dims = 2

        def embed_many(self, texts):
            return [[1, 0] for _ in texts]

    assert _embed(Provider(), ["one", "two"]) == [[1.0, 0.0], [1.0, 0.0]]


PASSAGES = {
    "Lothair II\nLothair II's mother was Ermengarde of Tours.": [
        ["Lothair II", "mother", "Ermengarde of Tours"],
    ],
    "Ermengarde of Tours\nErmengarde of Tours passed away on 20 March 851.": [
        ["Ermengarde of Tours", "passed away on", "20 March 851"],
    ],
    "Teutberga\nTeutberga was a queen of Lotharingia by marriage to Lothair II.": [
        ["Teutberga", "queen of", "Lotharingia"],
    ],
    "Victor Amadeus II\nThe mother of Victor Amadeus II died in Turin.": [
        ["Victor Amadeus II", "mother died in", "Turin"],
    ],
    "Turin\nTurin is a city in Piedmont where many people died of plague.": [
        ["Turin", "city in", "Piedmont"],
    ],
}


class BagEmbedder:
    """Deterministic bag-of-words vectors - semantic enough to test ranking, no network."""

    name = "test-bag"
    model = "bag"
    dims = 64

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        query = text.split("Query:")[-1]
        for word in re.findall(r"\w+", query.lower()):
            vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dims] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class ScriptedChat:
    """OpenIE answers from the table above; the recognition filter keeps every fact."""

    model = "scripted"

    def __init__(self) -> None:
        self.openie_calls = 0

    def json(self, prompt: str) -> dict:
        if prompt.startswith(OPENIE_PROMPT.split("{passage}")[0][:40]):
            self.openie_calls += 1
            passage = prompt.split("Passage:\n", 1)[1].strip()
            return {"named_entities": [], "triples": PASSAGES.get(passage, [])}
        listed = [json.loads(line) for line in prompt.splitlines() if line.startswith("[")]
        return {"facts": listed}


def _setup(tmp_path, *, read_only: bool = False):
    chat = ScriptedChat()
    graph = PassageGraphIndex(
        store=PassageIndexStore(tmp_path / "index.sqlite"),
        extractor="scripted",
        chat=chat,  # type: ignore[arg-type]
        embedder=BagEmbedder(),
        # One linked fact, as five are out of a large corpus: five of this corpus's five facts
        # would seed every entity and test nothing.
        link_top_k=1,
    )
    engine = LocalMemoryEngine(adapters=RetrievalAdapters(passage_graph=graph))
    cids = {}
    for text in PASSAGES:
        cids[text.split("\n")[0]] = engine.append_evidence(
            Evidence(
                tenant_id=TENANT, user_id="u", actor="user", source_type="document",
                content=text, access_policy={"tenant": TENANT},
            )
        )
    return engine, graph, chat, cids


def _ranked(engine, query: str) -> list[str]:
    result = engine.retrieve(
        query, tenant_id=TENANT, filt={"query_mode": "passages", "role": "reader"}, record_access=False
    )
    return [hit.text.split("\n")[0] for hit in result.hits]


def test_clean_triples_rejects_malformed_model_output() -> None:
    raw = [["A", "is", "B"], ["A", "is", "B"], ["", "x", "C"], ["only", "two"], "text", ["C", "", "D"], [1, 2, 3]]
    assert clean_triples(raw) == [["A", "is", "B"]]
    assert phrase_key("  Lothair II, of  Lotharingia ") == "lothair ii of lotharingia"


def test_graph_reaches_the_second_hop_passage(tmp_path) -> None:
    engine, graph, chat, _cids = _setup(tmp_path)
    report = MemoryTools(engine).index_passages(TENANT)
    assert report["configured"] is True
    assert report["passages"] == len(PASSAGES)
    assert report["openie_failures"] == 0
    question = "When did Lothair II's mother pass away?"
    ranked = _ranked(engine, question)
    # The answer passage never names Lothair II - only the mother fact links the two.
    assert ranked[:2] == ["Lothair II", "Ermengarde of Tours"]
    lexical_only = LocalMemoryEngine()
    for text in PASSAGES:
        lexical_only.append_evidence(
            Evidence(tenant_id=TENANT, user_id="u", actor="user", source_type="document",
                     content=text, access_policy={"tenant": TENANT})
        )
    assert _ranked(lexical_only, question).index("Ermengarde of Tours") > 1
    result = engine.retrieve(
        "When did Lothair II's mother pass away?", tenant_id=TENANT,
        filt={"query_mode": "passages", "role": "reader"}, record_access=False,
    )
    assert result.explain["passage_graph"]["route"] == "ppr"
    assert all(hit.kind == "evidence" for hit in result.hits)
    # Indexing again is free: every passage is already extracted and embedded.
    calls = chat.openie_calls
    again = MemoryTools(engine).index_passages(TENANT)
    assert chat.openie_calls == calls and again["openie_new"] == 0
    assert again["embedded"] == {"passage": 0, "fact": 0, "entity": 0}


def test_unreadable_passages_are_never_indexed_or_returned(tmp_path) -> None:
    engine, graph, chat, _cids = _setup(tmp_path)
    secret = "Secret ledger\nErmengarde of Tours kept a secret ledger."
    engine.append_evidence(
        Evidence(
            tenant_id=TENANT, user_id="u", actor="user", source_type="document", content=secret,
            sensitivity=3, access_policy={"tenant": TENANT},
        )
    )
    other = "Other tenant\nErmengarde of Tours appears in another tenant."
    engine.append_evidence(
        Evidence(
            tenant_id="someone-else", user_id="u", actor="user", source_type="document", content=other,
            access_policy={"tenant": "someone-else"},
        )
    )
    MemoryTools(engine).index_passages(TENANT)
    assert chat.openie_calls == len(PASSAGES)
    ranked = _ranked(engine, "Ermengarde of Tours")
    assert "Secret ledger" not in ranked and "Other tenant" not in ranked


def test_a_passage_the_index_never_saw_is_still_found(tmp_path) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)
    engine.append_evidence(
        Evidence(
            tenant_id=TENANT, user_id="u", actor="user", source_type="document",
            content="Late note\nThe archive of Lotharingia reopened in spring.", access_policy={"tenant": TENANT},
        )
    )
    result = engine.retrieve(
        "archive of Lotharingia", tenant_id=TENANT, filt={"query_mode": "passages", "role": "reader"},
        record_access=False,
    )
    assert [hit.text.split("\n")[0] for hit in result.hits][:2].count("Late note") == 1
    assert result.explain["passage_graph"]["unindexed_passages"] == 1


def test_forget_purges_what_the_index_derived_from_the_passage(tmp_path) -> None:
    engine, graph, _chat, cids = _setup(tmp_path)
    tools = MemoryTools(engine)
    tools.index_passages(TENANT)
    store = graph.store
    target = cids["Ermengarde of Tours"]
    assert store.openie(TENANT, graph.openie_model, [target])
    date_vector = hashlib.sha256(phrase_key("20 March 851").encode()).hexdigest()
    shared_vector = hashlib.sha256(phrase_key("Ermengarde of Tours").encode()).hexdigest()
    model = "bag|64"
    assert store.vectors(TENANT, "entity", model, [date_vector, shared_vector]).keys() == {date_vector, shared_vector}
    outcome = tools.forget(TENANT, target)
    assert outcome.get("erased") or any(item.get("erased") for item in outcome.get("branches", {}).values())
    assert store.openie(TENANT, graph.openie_model, [target]) == {}
    assert store.vectors(TENANT, "passage", model, [target]) == {}
    # "20 March 851" came only from the erased passage; Ermengarde is still in Lothair II's.
    assert store.vectors(TENANT, "entity", model, [date_vector, shared_vector]).keys() == {shared_vector}
    assert "Ermengarde of Tours" not in _ranked(engine, "When did Lothair II's mother pass away?")


def test_prepared_query_vectors_are_used_instead_of_the_embedder(tmp_path) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)
    question = "When did Lothair II's mother pass away?"
    expected = _ranked(engine, question)
    graph.prepare([question], BagEmbedder())

    class Refusing(BagEmbedder):
        def embed(self, text: str) -> list[float]:
            raise AssertionError("query was embedded again")

    graph.embedder = Refusing()
    graph._cache = None
    assert graph.store.vectors(TENANT, "passage", "bag|64", [_cids["Lothair II"]])
    assert _ranked(engine, question) == expected


def test_read_only_index_refuses_to_write(tmp_path) -> None:
    PassageIndexStore(tmp_path / "index.sqlite").close()
    graph = PassageGraphIndex(
        store=PassageIndexStore(tmp_path / "index.sqlite", read_only=True), extractor="scripted",
        chat=ScriptedChat(), embedder=BagEmbedder(),  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="read-only"):
        graph.index(TENANT, [], BagEmbedder())
