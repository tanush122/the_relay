"""Find the pieces that answer a question, entirely on this laptop.

Everything here is local, so retrieval spends zero Groq tokens. Two rankers are merged:
BM25 catches exact symbols and words (d_ff, "ratio loss"); a small embedding model catches
paraphrase. Reciprocal rank fusion (RRF) merges their rank lists without having to tune
how their very different score scales compare. Setting C then re-ranks the merged
candidates with a local cross-encoder, which reads question and piece together; only C
pays for that because it costs local time per query.
The heavy model library is imported inside load_models, so importing this module is cheap.
"""

import re
import time

from rank_bm25 import BM25Okapi

import config
from library.pieces import make_pieces

_MODELS = {}  # loaded once per process: "embed" and, for setting C, "rerank"
_LOAD_SECONDS = {}  # how long each model took to load the one time it was loaded


def load_models(need_rerank):
    """Load the embedding (and re-rank) model once; return load seconds per model."""
    from sentence_transformers import CrossEncoder, SentenceTransformer

    if "embed" not in _MODELS:
        start = time.perf_counter()
        _MODELS["embed"] = SentenceTransformer(config.EMBED_MODEL)
        _LOAD_SECONDS["embed_load_s"] = round(time.perf_counter() - start, 3)
    if need_rerank and "rerank" not in _MODELS:
        start = time.perf_counter()
        _MODELS["rerank"] = CrossEncoder(config.RERANK_MODEL)
        _LOAD_SECONDS["rerank_load_s"] = round(time.perf_counter() - start, 3)
    return dict(_LOAD_SECONDS)


def tokenize(text):
    """Lowercase word tokens; \\w keeps underscores, so d_ff stays one token."""
    return re.findall(r"\w+", text.lower())


def _embed(texts):
    return _MODELS["embed"].encode(texts, normalize_embeddings=True, convert_to_numpy=True)


def build_index(blocks_by_paper, setting_name):
    """Pieces for one setting plus their BM25 index and normalised embeddings."""
    setting = config.SETTINGS[setting_name]
    timings = {"models": load_models(setting["rerank"])}
    start = time.perf_counter()
    pieces = make_pieces(blocks_by_paper, setting_name)
    bm25 = BM25Okapi([tokenize(p["text"]) for p in pieces])
    emb = _embed([p["text"] for p in pieces])
    timings["build_s"] = round(time.perf_counter() - start, 3)
    return {"setting": setting_name, "pieces": pieces, "bm25": bm25, "emb": emb,
            "timings": timings}


def detect_papers(question):
    """Paper keys named in the question; an empty set means search all three."""
    q = question.lower()
    return {key for key, aliases in config.PAPER_ALIASES.items() if any(a in q for a in aliases)}


def _ranks(scores, pool):
    """Rank (1 = best) of each pool index by score."""
    order = sorted(pool, key=lambda i: scores[i], reverse=True)
    return {i: rank for rank, i in enumerate(order, start=1)}


def retrieve(index, question):
    """Return [(piece, score), ...] best first, SETTINGS[s]["pieces"] long."""
    start = time.perf_counter()
    setting = config.SETTINGS[index["setting"]]
    pieces = index["pieces"]
    papers = detect_papers(question)
    pool = [i for i, p in enumerate(pieces) if not papers or p["paper"] in papers]

    bm25_ranks = _ranks(index["bm25"].get_scores(tokenize(question)), pool)
    embed_ranks = _ranks(index["emb"] @ _embed([question])[0], pool)
    fused = {i: 1 / (config.RRF_K + bm25_ranks[i]) + 1 / (config.RRF_K + embed_ranks[i])
             for i in pool}
    best = sorted(pool, key=lambda i: fused[i], reverse=True)[:setting["candidates"]]
    scored = [(pieces[i], fused[i]) for i in best]

    if setting["rerank"]:
        pairs = [(question, piece["text"]) for piece, _ in scored]
        rerank_scores = [float(x) for x in _MODELS["rerank"].predict(pairs)]
        scored = sorted(zip([p for p, _ in scored], rerank_scores),
                        key=lambda pair: pair[1], reverse=True)
    index["timings"]["last_retrieve_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return [(piece, float(score)) for piece, score in scored[:setting["pieces"]]]
