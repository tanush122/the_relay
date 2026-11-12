"""Find the pieces that answer a question, entirely on this laptop.

Everything here is local, so retrieval spends zero Groq tokens. Two rankers are merged:
BM25 catches exact symbols and words (d_ff, "ratio loss"); a small embedding model catches
paraphrase. Reciprocal rank fusion (RRF) merges their rank lists without having to tune
how their very different score scales compare. Setting C then re-ranks the merged
candidates with a local cross-encoder, which reads question and piece together; only C
pays for that because it costs local time per query.
Long pieces (review ME-01): the embedding model reads at most 256 word-pieces and the
cross-encoder 512, so a B or C piece (up to ~450 words) would be judged on its first part
only. Each piece is therefore cut into short windows (config.EMBED_WINDOW_WORDS) and
scored by its best window, so a fact in the second half of a piece still counts.
Strength: the best window's cosine similarity to the question, an absolute number the
decide step can compare with config.MIN_STRENGTH (RRF scores are ranks, not evidence).
The heavy model library is imported inside load_models, so importing this module is cheap.
"""

import re
import time

import numpy as np

from rank_bm25 import BM25Okapi

import config
from library.pieces import make_pieces, window_starts

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


def split_windows(text):
    """Short overlapping word windows covering a piece, each short enough to be read whole."""
    words = text.split()
    size = config.EMBED_WINDOW_WORDS
    stride = size - config.EMBED_WINDOW_OVERLAP_WORDS
    starts = window_starts(words, size, stride)
    return [" ".join(words[start:start + size]) for start in starts]


def build_index(blocks_by_paper, setting_name):
    """Pieces for one setting, their BM25 index, and embeddings of every piece window."""
    setting = config.SETTINGS[setting_name]
    timings = {"models": load_models(setting["rerank"]),
               "embed_max_seq_length": _MODELS["embed"].max_seq_length}
    start = time.perf_counter()
    pieces = make_pieces(blocks_by_paper, setting_name)
    bm25 = BM25Okapi([tokenize(p["text"]) for p in pieces])
    windows, owner = [], []  # owner[w] = index of the piece window w belongs to
    for i, piece in enumerate(pieces):
        for text in split_windows(piece["text"]):
            windows.append(text)
            owner.append(i)
    emb = _embed(windows)
    centroids = {}  # each paper's average meaning, for routing a question by meaning
    for paper in {p["paper"] for p in pieces}:
        rows = [w for w, i in enumerate(owner) if pieces[i]["paper"] == paper]
        mean = emb[rows].mean(axis=0)
        centroids[paper] = mean / np.linalg.norm(mean)
    timings["build_s"] = round(time.perf_counter() - start, 3)
    return {"setting": setting_name, "pieces": pieces, "bm25": bm25, "windows": windows,
            "owner": np.array(owner), "emb": emb, "centroids": centroids, "timings": timings}


def route(index, question):
    """The papers a question is about, judged by meaning (config.ROUTING == "meaning"):
    the question's similarity to each paper's average meaning; every paper within
    config.ROUTE_MARGIN of the closest one is searched. With "names", the old alias list."""
    if config.ROUTING != "meaning":
        return detect_papers(question)
    q = _embed([question])[0]
    scores = {paper: float(c @ q) for paper, c in index["centroids"].items()}
    best = max(scores.values())
    return {paper for paper, score in scores.items() if score >= best - config.ROUTE_MARGIN}


def _best_per_piece(window_scores, owner, n_pieces):
    """Each piece's best window score (pieces are scored by their best part)."""
    best = np.full(n_pieces, -np.inf)
    np.maximum.at(best, owner, window_scores)
    return best


def detect_papers(question):
    """Paper keys named in the question; an empty set means search all three."""
    q = question.lower()
    return {key for key, aliases in config.PAPER_ALIASES.items() if any(a in q for a in aliases)}


def _ranks(scores, pool):
    """Rank (1 = best) of each pool index by score."""
    order = sorted(pool, key=lambda i: scores[i], reverse=True)
    return {i: rank for rank, i in enumerate(order, start=1)}


def _rerank(index, question, candidates):
    """Setting C: cross-encoder score of each candidate's best window, best first."""
    pairs, owner = [], []
    for i in candidates:
        for w in np.flatnonzero(index["owner"] == i):
            pairs.append((question, index["windows"][w]))
            owner.append(i)
    scores = _MODELS["rerank"].predict(pairs)
    best = {}
    for i, score in zip(owner, scores):
        best[i] = max(best.get(i, -np.inf), float(score))
    return sorted(candidates, key=lambda i: best[i], reverse=True), best


def retrieve(index, question, papers=None):
    """Return ([(piece, score), ...] best first, strength).

    papers: the paper keys to search (an empty set searches all three); by default the
    papers the question names. The list is SETTINGS[s]["pieces"] long; score is the RRF
    score, or the cross-encoder score for setting C. strength is the best cosine
    similarity between the question and any window of the returned pieces.
    """
    start = time.perf_counter()
    setting = config.SETTINGS[index["setting"]]
    pieces = index["pieces"]
    papers = route(index, question) if papers is None else papers
    pool = [i for i, p in enumerate(pieces) if not papers or p["paper"] in papers]

    cosine = _best_per_piece(index["emb"] @ _embed([question])[0], index["owner"], len(pieces))
    bm25_ranks = _ranks(index["bm25"].get_scores(tokenize(question)), pool)
    embed_ranks = _ranks(cosine, pool)
    score = {i: 1 / (config.RRF_K + bm25_ranks[i]) + 1 / (config.RRF_K + embed_ranks[i])
             for i in pool}
    best = sorted(pool, key=lambda i: score[i], reverse=True)[:setting["candidates"]]
    if setting["rerank"]:
        best, score = _rerank(index, question, best)
    best = best[:setting["pieces"]]
    index["timings"]["last_retrieve_ms"] = round((time.perf_counter() - start) * 1000, 2)
    strength = max((float(cosine[i]) for i in best), default=0.0)
    return [(pieces[i], float(score[i])) for i in best], strength
