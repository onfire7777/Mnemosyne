# Phase 11 Research

## LongMemEval

- Official code: `xiaowu0162/LongMemEval@9e0b455f4ef0e2ab8f2e582289761153549043fc`.
- Official cleaned dataset: `xiaowu0162/longmemeval-cleaned@98d7416c24c778c2fee6e6f3006e7a073259d48f`.
- Upstream reports 500 questions across extraction, multi-session reasoning,
  knowledge update, temporal reasoning, and abstention. The cleaned September
  2025 release is authoritative for this milestone.
- Dataset file: `longmemeval_s_cleaned.json`, LFS SHA-256
  `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`
  (277,383,467 bytes). The companion `longmemeval_oracle.json` is SHA-256
  `821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c`
  (15,388,478 bytes).
- The pinned Hugging Face dataset card and code repository both declare MIT.
- Pinned asset base URL:
  `https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/`.
  Cite Wu et al., *LongMemEval* (ICLR 2025, arXiv:2410.10813).
- Retrieval scoring uses dataset-owned session/turn support labels only; no LLM
  scorer and no answer-key inference.

## HippoRAG 2

- Derivation repo: `OSU-NLP-Group/HippoRAG@ad30fc3e2062202d9e975e32cd28212424a56ccb`.
- Dataset repo: `osunlp/HippoRAG_2@5ec05b38deecc3318bb432c69865959c56058990`.
- Query/corpus SHA-256 pairs:
  - `musique.json`: `98ed4e21d3076532f6388d42320fb809599c63a0d8dffca8ece5e41922be6b46`.
  - `musique_corpus.json`: `73157a03ce3f0b1a5673dd5dc12bb970c24976dbffc688af9eecdd758c97ffcb`.
  - `2wikimultihopqa.json`: `895cba294064df0c3302c76847b1fc08d99b5619f7663dfaa3b65cd780f1cac4`.
  - `2wikimultihopqa_corpus.json`: `9d6e352952aafb18dab22bf8195039461321a44a949df902ae83bce134ad238a`.
  - `hotpotqa.json`: `3ad9c0bcbf93f41d7004ca6007049c904d2605046b314a2f7ecfb379c64cba6d`.
  - `hotpotqa_corpus.json`: `9333647b922382776cd2cb02893b390d77984df85a91bfa8be411284978aca7d`.
- Original provenance pins:
  - MuSiQue `922ac98f19a201998dbdae6d7f2887a5258dbdeb` (CC BY 4.0).
  - 2Wiki `13800e5be57df1b4040b9b1588c6c811779e69e9` (Apache-2.0).
  - HotpotQA `3635853403a8735609ee997664e1528f4480762a`
    (data CC BY-SA 4.0; code Apache-2.0).
- Published HippoRAG 2 Llama-3.3-70B context, not pass thresholds:
  MuSiQue 56.1/74.7, 2Wiki 76.2/90.4, HotpotQA 83.5/96.3 for Recall@2/@5.
- MuSiQue carries an upstream seed-question leakage warning; retain exclusion
  IDs and a contamination declaration.
- Pinned asset base URL:
  `https://huggingface.co/datasets/osunlp/HippoRAG_2/resolve/5ec05b38deecc3318bb432c69865959c56058990/`.
  Cite the original dataset papers plus HippoRAG 2 (arXiv:2502.14802). Mutable
  `main` is forbidden.

## Required Harness Changes

The Phase 10 verifier is deliberately smoke-specific. Phase 11 must generalize
it through explicit versioned scoring profiles, never by weakening checks.
Fractional passage Recall@k and token F1 use deterministic bootstrap intervals;
binary hit/all-recall and EM may use Wilson. Retrieval and QA remain separate
families. Publication flags remain false until PBPP plus independent
reproduction are satisfied.

## Exact Metric Definitions

- LongMemEval gold unit is an upstream `has_answer=true` turn identified by
  `(session_id, turn_index)`. Recall@5 is gold-turn recall in the top five,
  macro-averaged by question. nDCG@5 uses binary gain, `1/log2(rank+1)`
  discount, and ideal DCG truncated to five, then macro-averages by question.
- Hippo passage Recall@k is `|unique retrieved gold passage IDs in top k| /
  |unique gold passage IDs|`, with stable first-occurrence deduplication and
  macro aggregation by question.
- EM normalization is Unicode NFKC, lowercase, punctuation removal, English
  article removal, and whitespace collapse; aliases take the maximum.
- Token F1 uses the same normalization and multiset token overlap, maximized
  over aliases. It is not emitted in a retrieval-family bundle.
- Bootstrap resamples questions with replacement for 2,000 iterations at seed
  1234 and reports percentile 95% bounds. Wilson 95% is reserved for binary
  proportions such as EM, never fractional recall or token F1.
