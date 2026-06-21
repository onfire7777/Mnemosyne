"""Synthetic case generator for suite ignition (blueprint §33 cold-start fix).

The blueprint requires the seed suite to be augmented with **synthetic cases
auto-generated from the earliest episodes** so the private regression suite can
reach ignition size N before any candidate is promoted out of shadow mode.

This generator is intentionally *deterministic* (seeded) so the suite is
reproducible: the same episodes always yield the same synthetic cases, which is
mandatory for a regression suite that must distinguish a true regression from
generator noise.

Design: from a list of "episode" sentences (the earliest captured evidence), we
derive retrieval queries by:
  * key-phrase extraction (capitalised tokens / quoted spans / trailing nouns),
  * paraphrase templating ("what is X", "tell me about X", X-as-keyword),
each labelled with the originating doc as the single relevant id. These mirror
the kind of self-generated probes a cold-start system would mine from its own
history, and they exercise dense+lexical fusion (FR-3) without any human labels.
"""

from __future__ import annotations

import random
import re
from typing import Sequence

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "and", "or", "in",
    "on", "at", "for", "with", "by", "from", "as", "that", "this", "it", "its",
    "their", "they", "be", "has", "have", "had", "will", "would", "can", "could",
}


def _keyphrase(sentence: str) -> str:
    """Pick a salient phrase: longest run of non-stopword tokens (lowercased)."""
    tokens = re.findall(r"[A-Za-z0-9']+", sentence)
    best_run: list[str] = []
    current: list[str] = []
    for tok in tokens:
        if tok.lower() in _STOPWORDS or len(tok) <= 2:
            if len(current) > len(best_run):
                best_run = current
            current = []
        else:
            current.append(tok)
    if len(current) > len(best_run):
        best_run = current
    return " ".join(best_run[:6]) if best_run else sentence[:40]


def generate_retrieval_cases(
    episodes: Sequence[dict],
    *,
    seed: int = 7,
    paraphrases_per_episode: int = 2,
) -> dict:
    """Build a retrieval dataset (same schema as retrieval_curated.json) from episodes.

    Each episode is ``{"doc_id": str, "content": str}``. We emit one corpus entry
    per episode and ``paraphrases_per_episode`` queries whose single relevant id
    is the source episode — a self-supervised retrieval probe set.
    """
    rng = random.Random(seed)
    corpus = []
    queries = []
    templates = [
        "{kp}",
        "what is {kp}",
        "tell me about {kp}",
        "details on {kp}",
        "information regarding {kp}",
    ]
    for ep in episodes:
        doc_id = ep["doc_id"]
        content = ep["content"]
        corpus.append({"doc_id": doc_id, "content": content, "trust_tier": int(ep.get("trust_tier", 0))})
        kp = _keyphrase(content)
        chosen = rng.sample(templates, k=min(paraphrases_per_episode, len(templates)))
        for j, tmpl in enumerate(chosen):
            queries.append(
                {
                    "qid": f"syn_{doc_id}_{j}",
                    "query": tmpl.format(kp=kp),
                    "relevant_doc_ids": [doc_id],
                    "gold_answer": kp,
                    "answerable": True,
                    "synthetic": True,
                }
            )
    return {
        "dataset_id": "retrieval_synthetic_v1",
        "description": "Auto-generated retrieval cases mined from earliest episodes (suite ignition, §33). Deterministic given seed.",
        "tenant": "eval-retrieval-synthetic",
        "user": "eval-user",
        "k": 5,
        "seed": seed,
        "corpus": corpus,
        "queries": queries,
    }


# A small fixed pool of "earliest episodes" so the harness can run with zero
# external input. In production these would be the system's own first captures.
DEFAULT_EPISODES: list[dict] = [
    {"doc_id": "ep_vault", "content": "Project Mnemosyne stores evidence in an append-only content-addressed ledger."},
    {"doc_id": "ep_bitemporal", "content": "Assertions carry both valid time and transaction time for bitemporal queries."},
    {"doc_id": "ep_rrf", "content": "Hybrid retrieval fuses dense lexical and graph channels with reciprocal rank fusion."},
    {"doc_id": "ep_calib", "content": "Confidence scores are conformally calibrated per memory type before abstention."},
    {"doc_id": "ep_belief", "content": "Belief revision uses a truth maintenance system with cascade invalidation."},
    {"doc_id": "ep_branch", "content": "Scratch branches hold speculative writes that are discarded on rollback."},
    {"doc_id": "ep_trust", "content": "Retrieved content is treated as data and never as an executable instruction."},
    {"doc_id": "ep_forget", "content": "Fidelity tiered forgetting demotes memories by declining utility over time."},
]
