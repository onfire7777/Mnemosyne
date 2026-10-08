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
    RERANK_PROMPT,
    SECOND_HOP_PROMPT,
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


# -- ordinary search, live indexing and model failure (memory upgrade phase 2) ---------------


def _default_ranked(engine, query: str) -> tuple[list[str], dict]:
    result = engine.retrieve(query, tenant_id=TENANT, filt={"role": "reader"}, record_access=False)
    titles = [hit.text.split("\n")[0] for hit in result.hits if hit.kind == "evidence"]
    return titles, result.explain


def test_default_search_ranks_passages_with_the_graph(tmp_path) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)
    titles, explain = _default_ranked(engine, "When did Lothair II's mother pass away?")
    # Without the graph the answer passage, which never names Lothair II, ranks below two.
    assert "Ermengarde of Tours" in titles[:2]
    assert explain["passage_graph"]["route"] == "ppr"
    assert explain["activation"]["reason"] == "passage_relevance_order"


def test_default_search_caps_extracted_fact_slots(tmp_path) -> None:
    from mnemosyne.models import Assertion

    engine, graph, _chat, cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)
    for n in range(6):
        engine.upsert_assertion(Assertion(
            tenant_id=TENANT, subject=f"Lothair II fact {n}", predicate="mother", object="Ermengarde of Tours",
            source_evidence_cids=[cids["Lothair II"]], status="active", access_policy={"tenant": TENANT},
        ))
    result = engine.retrieve("Lothair II mother", tenant_id=TENANT, filt={"role": "reader"}, record_access=False)
    facts = [hit for hit in result.hits if hit.kind in {"assertion", "relation"}]
    assert len(facts) <= max(1, engine.policy.top_k // 4)


def test_a_model_that_is_down_falls_back_to_bm25(tmp_path) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)

    class Down(BagEmbedder):
        def embed(self, text: str) -> list[float]:
            raise OSError("connection refused")

    graph.embedder = Down()
    graph._query_vectors.clear()
    for filt in ({"role": "reader"}, {"role": "reader", "query_mode": "passages"}):
        result = engine.retrieve("Ermengarde of Tours", tenant_id=TENANT, filt=filt, record_access=False)
        assert result.explain["passage_graph"]["fallback"] == "bm25"
        assert result.hits[0].text.startswith("Ermengarde of Tours")


def test_a_new_memory_is_indexed_in_the_background(tmp_path) -> None:
    engine, graph, chat, _cids = _setup(tmp_path)
    tools = MemoryTools(engine)
    tools.index_passages(TENANT)
    graph.live_index, graph.live_debounce_seconds = True, 0.01
    calls = chat.openie_calls
    made = tools.capture(TENANT, "u", "user", "document", "Rotrude\nRotrude was a daughter of Ermengarde of Tours.")
    assert made["created"] is True
    assert graph.wait_idle(10)
    assert chat.openie_calls == calls + 1
    assert graph.store.openie(TENANT, graph.openie_model, [made["cid"]])
    assert graph.store.vectors(TENANT, "passage", "bag|64", [made["cid"]])
    assert graph.health()["last_report"]["openie_new"] == 1
    titles, _explain = _default_ranked(engine, "Rotrude daughter")
    assert titles[0] == "Rotrude"


def test_live_indexing_failure_never_fails_a_capture(tmp_path) -> None:
    engine, graph, chat, _cids = _setup(tmp_path)
    graph.live_index, graph.live_debounce_seconds = True, 0.01

    class Broken(ScriptedChat):
        def json(self, prompt: str) -> dict:
            raise OSError("model is not running")

    graph.chat = Broken()  # type: ignore[assignment]
    made = MemoryTools(engine).capture(TENANT, "u", "user", "document", "Pippin\nPippin was a son of Lothair II.")
    assert made["created"] is True
    assert graph.wait_idle(10)
    health = graph.health()
    assert health["live_index"] is True and health["running"] is False
    # One extraction failed; the passage is still found, by BM25.
    assert health["last_report"]["openie_failures"] >= 1
    result = engine.retrieve("Pippin", tenant_id=TENANT, filt={"role": "reader"}, record_access=False)
    assert any(hit.text.startswith("Pippin") for hit in result.hits)


def test_a_passage_forgotten_mid_index_is_not_written_back(tmp_path) -> None:
    engine, graph, _chat, cids = _setup(tmp_path)
    target = cids["Turin"]
    graph.purge(TENANT, [target])
    MemoryTools(engine).index_passages(TENANT)
    assert graph.store.openie(TENANT, graph.openie_model, [target]) == {}
    assert graph.store.vectors(TENANT, "passage", "bag|64", [target]) == {}


def test_default_search_keeps_unreadable_passages_out(tmp_path) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id="u", actor="user", source_type="document",
        content="Secret ledger\nErmengarde of Tours kept a secret ledger.", sensitivity=3,
        access_policy={"tenant": TENANT},
    ))
    MemoryTools(engine).index_passages(TENANT)
    titles, _explain = _default_ranked(engine, "Ermengarde of Tours secret ledger")
    assert "Secret ledger" not in titles


def test_passage_graph_from_env(tmp_path) -> None:
    from mnemosyne.passages import passage_graph_from_env

    assert passage_graph_from_env({}) is None
    with pytest.raises(ValueError, match="CHAT_MODEL"):
        passage_graph_from_env({"MNEMOSYNE_PASSAGE_INDEX": str(tmp_path / "i.sqlite")})
    graph = passage_graph_from_env({
        "MNEMOSYNE_PASSAGE_INDEX": str(tmp_path / "i.sqlite"),
        "MNEMOSYNE_PASSAGE_CHAT_MODEL": "qwen3:4b-instruct",
        "MNEMOSYNE_PASSAGE_CHAT_URL": "http://127.0.0.1:11434/v1/chat/completions",
        "MNEMOSYNE_PASSAGE_EMBEDDING_URL": "http://127.0.0.1:11434/v1/embeddings",
        "MNEMOSYNE_PASSAGE_EMBEDDING_MODEL": "qwen3-embedding:8b",
        "MNEMOSYNE_PASSAGE_RERANK_TOP": "10",
    })
    assert graph is not None and graph.chat is not None and graph.embedder.dims == 1024
    assert graph.rerank_top == 10 and graph.openie_model == "qwen3:4b-instruct|openie.v1"
    graph.store.close()


def test_mcp_server_wires_the_graph_and_reports_it(tmp_path, monkeypatch) -> None:
    from mnemosyne.mcp_server import MnemosyneMcpServer, _passage_graph_health

    monkeypatch.setenv("MNEMOSYNE_PASSAGE_INDEX", str(tmp_path / "index.sqlite"))
    monkeypatch.setenv("MNEMOSYNE_PASSAGE_CHAT_MODEL", "scripted")
    # Nothing listens on port 9: every model call is refused at once.
    monkeypatch.setenv("MNEMOSYNE_PASSAGE_CHAT_URL", "http://127.0.0.1:9/v1/chat/completions")
    monkeypatch.setenv("MNEMOSYNE_PASSAGE_EMBEDDING_URL", "http://127.0.0.1:9/v1/embeddings")
    with MnemosyneMcpServer(store_path=tmp_path / "store.json") as server:
        assert server.engine.adapters.passage_graph is server.passage_graph
        assert server.passage_graph.live_index is True
        server.passage_graph.live_debounce_seconds = 0.01
        made = server.tools.capture(TENANT, "u", "user", "document", "Charles\nCharles was a king.")
        assert made["created"] is True
        assert server.passage_graph.wait_idle(30)
        found = server.tools.search(TENANT, "Charles king")
        assert found["hits"] and found["explain"]["passage_graph"]["fallback"] == "bm25"
        assert _passage_graph_health(server)["configured"] is True
    assert _passage_graph_health(object()) == {"configured": False}


# -- second hop and a wider rerank (memory upgrade phase 3) ---------------------------------


class HopChat(ScriptedChat):
    """OpenIE from the table; a second-hop prompt gets a fixed follow-up search."""

    def __init__(self, follow_up: object = "When did Ermengarde of Tours pass away") -> None:
        super().__init__()
        self.follow_up = follow_up
        self.prompts: list[str] = []

    def json(self, prompt: str) -> dict:
        if prompt.startswith(SECOND_HOP_PROMPT[:40]):
            self.prompts.append(prompt)
            if isinstance(self.follow_up, Exception):
                raise self.follow_up
            return {"query": self.follow_up}
        if prompt.startswith(RERANK_PROMPT[:40]):
            self.prompts.append(prompt)
            return {"passages": []}
        return super().json(prompt)


def _passage_search(engine, query: str):
    result = engine.retrieve(
        query, tenant_id=TENANT, filt={"query_mode": "passages", "role": "reader"}, record_access=False
    )
    return [hit.text.split("\n")[0] for hit in result.hits], result.explain["passage_graph"]


def test_second_hop_fuses_a_walk_from_the_follow_up_search(tmp_path) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)
    # A dense first hop: the bridge passage shares no word with the question.
    graph.link_top_k = 0
    question = "Lothair II marriage"
    first_hop = _ranked(engine, question)
    hop = HopChat()
    graph.chat, graph.second_hop = hop, True  # type: ignore[assignment]
    titles, explain = _passage_search(engine, question)
    assert explain["second_hop"]["applied"] is True
    assert explain["second_hop"]["query"] == hop.follow_up
    assert "Lothair II" in hop.prompts[0]
    # The follow-up lifts the bridge passage; the first hop's best answer stays on top.
    assert titles.index("Ermengarde of Tours") < first_hop.index("Ermengarde of Tours")
    assert titles[0] == first_hop[0]
    graph.second_hop_weight = 0.0
    assert _passage_search(engine, question)[0] == first_hop


@pytest.mark.parametrize("follow_up", ["", None, OSError("model is not running")])
def test_second_hop_without_a_follow_up_keeps_the_first_ranking(tmp_path, follow_up) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)
    question = "When did Lothair II's mother pass away?"
    expected = _ranked(engine, question)
    graph.chat, graph.second_hop = HopChat(follow_up), True  # type: ignore[assignment]
    titles, explain = _passage_search(engine, question)
    assert titles == expected
    assert explain["second_hop"]["applied"] is False


def test_second_hop_whose_search_cannot_be_embedded_keeps_the_first_ranking(tmp_path) -> None:
    engine, graph, _chat, _cids = _setup(tmp_path)
    MemoryTools(engine).index_passages(TENANT)
    question = "When did Lothair II's mother pass away?"
    expected = _ranked(engine, question)

    class FollowUpDown(BagEmbedder):
        def embed(self, text: str) -> list[float]:
            if "Ermengarde of Tours pass away" in text:
                raise OSError("timed out")
            return super().embed(text)

    graph.chat, graph.second_hop, graph.embedder = HopChat(), True, FollowUpDown()  # type: ignore[assignment]
    titles, explain = _passage_search(engine, question)
    assert titles == expected
    assert explain["second_hop"]["applied"] is False and "timed out" in explain["second_hop"]["error"]


def test_a_wide_rerank_shares_its_text_budget_and_uses_the_rerank_model(tmp_path) -> None:
    from types import SimpleNamespace

    _engine, graph, chat, _cids = _setup(tmp_path)
    rerank = HopChat()
    graph.rerank_chat = rerank  # type: ignore[assignment]
    head = [SimpleNamespace(text="memory " * 300) for _ in range(30)]

    def longest(prompt: str) -> tuple[int, int]:
        lines = [line.split("] ", 1)[1] for line in prompt.splitlines() if re.match(r"\[\d+\] ", line)]
        return len(lines), max(len(line) for line in lines)

    graph._rerank("question", head)  # type: ignore[arg-type]
    assert longest(rerank.prompts[-1]) == (30, 300)
    graph._rerank("question", head[:5])  # type: ignore[arg-type]
    assert longest(rerank.prompts[-1]) == (5, 600)
    assert chat.openie_calls == 0


def test_passage_graph_from_env_reads_the_rerank_model_and_second_hop(tmp_path) -> None:
    from mnemosyne.passages import passage_graph_from_env

    graph = passage_graph_from_env({
        "MNEMOSYNE_PASSAGE_INDEX": str(tmp_path / "i.sqlite"),
        "MNEMOSYNE_PASSAGE_CHAT_MODEL": "qwen3:4b-instruct",
        "MNEMOSYNE_PASSAGE_CHAT_URL": "http://127.0.0.1:11434/v1/chat/completions",
        "MNEMOSYNE_PASSAGE_RERANK_MODEL": "qwen3:8b",
        "MNEMOSYNE_PASSAGE_RERANK_REASONING_EFFORT": "none",
        "MNEMOSYNE_PASSAGE_SECOND_HOP": "1",
    })
    assert graph is not None and graph.second_hop is True
    assert graph.rerank_chat is not None and graph.rerank_chat.model == "qwen3:8b"
    assert graph.rerank_chat.reasoning_effort == "none"
    # The index stays named after the extractor, so a new rerank model keeps every triple.
    assert graph.openie_model == "qwen3:4b-instruct|openie.v1"
    health = graph.health()
    assert health["rerank_model"] == "qwen3:8b" and health["second_hop"] is True
    graph.store.close()


# -- one text, many tenants: derivatives are keyed by the text ---------------------------------


def test_a_text_two_tenants_hold_is_extracted_once_and_purged_last(tmp_path) -> None:
    engine, graph, chat, cids = _setup(tmp_path)
    other = "other-tenant"
    other_cids = {}
    for text in PASSAGES:
        other_cids[text.split("\n")[0]] = engine.append_evidence(Evidence(
            tenant_id=other, user_id="u", actor="user", source_type="document",
            content=text, access_policy={"tenant": other},
        ))
    tools = MemoryTools(engine)
    tools.index_passages(TENANT)
    assert chat.openie_calls == len(PASSAGES)
    report = tools.index_passages(other)
    assert chat.openie_calls == len(PASSAGES), "the same text was extracted again for the second tenant"
    assert report["openie_new"] == 0 and report["embedded"]["passage"] == 0
    assert report["passages"] == len(PASSAGES)
    target = cids["Ermengarde of Tours"]
    other_target = other_cids["Ermengarde of Tours"]
    assert target != other_target
    assert graph.store.openie(other, graph.openie_model, [other_target])
    # Each tenant still only sees its own passages.
    assert graph.store.openie(other, graph.openie_model, [target]) == {}
    date_vector = hashlib.sha256(phrase_key("20 March 851").encode()).hexdigest()
    tools.forget(TENANT, target)
    assert graph.store.openie(TENANT, graph.openie_model, [target]) == {}
    # The other tenant still holds the text, so nothing derived from it is dropped.
    assert graph.store.openie(other, graph.openie_model, [other_target])
    assert graph.store.vectors(other, "passage", "bag|64", [other_target])
    assert graph.store.vectors(other, "entity", "bag|64", [date_vector])
    tools.forget(other, other_target)
    assert graph.store.openie(other, graph.openie_model, [other_target]) == {}
    assert graph.store.vectors(other, "entity", "bag|64", [date_vector]) == {}


def test_a_first_layout_index_is_migrated_without_extracting_again(tmp_path) -> None:
    import sqlite3
    from array import array

    from mnemosyne.passages import OPENIE_VERSION

    text = "Turin\nTurin is a city in Piedmont where many people died of plague."
    cid = LocalMemoryEngine().append_evidence(Evidence(
        tenant_id=TENANT, user_id="u", actor="user", source_type="document",
        content=text, access_policy={"tenant": TENANT},
    ))
    path = tmp_path / "index.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE openie (scope TEXT NOT NULL, sha TEXT NOT NULL, model TEXT NOT NULL, triples TEXT NOT NULL,
          PRIMARY KEY (scope, sha, model));
        CREATE TABLE vectors (scope TEXT NOT NULL, sha TEXT NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL,
          vec BLOB NOT NULL, PRIMARY KEY (scope, sha, kind, model));
    """)
    conn.execute("INSERT INTO openie VALUES (?, ?, ?, ?)",
                 (TENANT, cid, f"scripted|{OPENIE_VERSION}", json.dumps(PASSAGES[text])))
    conn.execute("INSERT INTO vectors VALUES (?, ?, 'passage', 'bag|64', ?)",
                 (TENANT, cid, array("f", BagEmbedder().embed(text)).tobytes()))
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="migrate"):
        PassageIndexStore(path, read_only=True)

    engine, graph, chat, cids = _setup(tmp_path)
    assert cids["Turin"] == cid
    assert graph.store.openie(TENANT, graph.openie_model, [cid]) == {cid: PASSAGES[text]}
    report = MemoryTools(engine).index_passages(TENANT)
    assert chat.openie_calls == len(PASSAGES) - 1
    assert report["openie_new"] == len(PASSAGES) - 1 and report["embedded"]["passage"] == len(PASSAGES) - 1
    assert graph.store.openie(TENANT, graph.openie_model, [cid]) == {cid: PASSAGES[text]}
    assert graph.store.vectors(TENANT, "passage", "bag|64", [cid])
    # Re-keyed to the text: a second tenant with the same passage is served from it too.
    other_cid = engine.append_evidence(Evidence(
        tenant_id="other-tenant", user_id="u", actor="user", source_type="document",
        content=text, access_policy={"tenant": "other-tenant"},
    ))
    calls = chat.openie_calls
    MemoryTools(engine).index_passages("other-tenant")
    assert chat.openie_calls == calls
    assert graph.store.openie("other-tenant", graph.openie_model, [other_cid]) == {other_cid: PASSAGES[text]}
    result = engine.retrieve(
        "Turin plague", tenant_id=TENANT, filt={"query_mode": "passages", "role": "reader"}, record_access=False
    )
    assert result.explain["passage_graph"]["route"] == "ppr"
