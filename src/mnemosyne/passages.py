"""Corpus-aware passage ranking over already authorized, redacted evidence."""

from collections import Counter, defaultdict
from dataclasses import replace
from math import log
from typing import Sequence

from mnemosyne.models import Hit
from mnemosyne.text import tokenize


def is_passage(hit: Hit) -> bool:
    return (
        hit.kind == "evidence"
        and hit.metadata.get("source_type") not in {
            "consolidation-summary", "statistical-trace", "provider-proposal",
        }
        and not hit.metadata.get("summary")
        and hit.metadata.get("reality_class") not in {"self_generated", "simulated"}
    )


class PassageIndex:
    """BM25 with positive IDF, scoped to the caller's readable corpus.

    No global text cache: the owning engine retains at most its latest scope.
    Candidates are reauthorized before every lookup, including cache hits.
    """

    def __init__(self, texts: tuple[str, ...]):
        self.texts = texts
        self.lengths = []
        self.postings = defaultdict(list)
        for index, text in enumerate(texts):
            counts = Counter(tokenize(text))
            self.lengths.append(sum(counts.values()))
            for term, count in counts.items():
                self.postings[term].append((index, count))
        self.average_length = sum(self.lengths) / max(len(texts), 1) or 1.0

    def scores(self, query: str) -> dict[int, float]:
        scores = defaultdict(float)
        for term, query_count in Counter(tokenize(query)).items():
            postings = self.postings.get(term, ())
            idf = log(1.0 + (len(self.texts) - len(postings) + 0.5) / (len(postings) + 0.5))
            for index, count in postings:
                norm = 1.2 * (0.25 + 0.75 * self.lengths[index] / self.average_length)
                scores[index] += query_count * idf * count * 2.2 / (count + norm)
        return dict(scores)


def rank_passages(owner: object, query: str, candidates: Sequence[Hit], k: int) -> list[Hit]:
    passages = [hit for hit in candidates if is_passage(hit)]
    texts = tuple(hit.text for hit in passages)
    index = getattr(owner, "_passage_bm25_index", None)
    if index is None or index.texts != texts:
        index = PassageIndex(texts)
        owner._passage_bm25_index = index
    scores = index.scores(query)
    ranked = sorted(scores, key=lambda i: (-scores[i], passages[i].id))[:max(k, 0)]
    return [replace(passages[i], score=scores[i], channel="lexical_bm25") for i in ranked]
