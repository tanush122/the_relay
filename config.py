"""Every tunable in The Relay lives here, so a live change is one edit in one file.

Paths, the three papers, model names, the Groq base URL, timeouts, the retrieval
settings A/B/C, probe sizes, token caps and the answer prompt. Other modules import
these names; nothing else should hard-code a limit or a setting.
"""

import os
from pathlib import Path

# --- Paths (all inside the project folder) ---
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # downloaded papers, git-ignored
MANIFEST_PATH = DATA_DIR / "manifest.json"  # committed evidence of what was fetched
TRACES_DIR = DATA_DIR / "traces"  # one JSON line per model request
PROBE_DIR = DATA_DIR / "probe"  # raw probe responses
ENV_PATH = ROOT / ".env"  # holds GROQ_API_KEY; git-ignored, never printed
MODEL_CACHE_DIR = ROOT / ".cache" / "huggingface"
# Keep Hugging Face model downloads inside the project, not in a global ~/.cache.
os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR))

# --- The three papers ---
# Always fetch the versioned URL. Moshi trap: the latest Moshi is v2, but we use v1.
PAPERS = [
    {"key": "attention", "arxiv_id": "1706.03762", "version": "v7",
     "title": "Attention Is All You Need", "short": "Attention"},
    {"key": "moshi", "arxiv_id": "2410.00037", "version": "v1",
     "title": "Moshi: a speech-text foundation model for real-time dialogue", "short": "Moshi"},
    {"key": "hnet", "arxiv_id": "2507.07955", "version": "v2",
     "title": "Dynamic Chunking for End-to-End Hierarchical Sequence Modeling", "short": "H-Net"},
]
# Lowercase phrases that name a paper in a question, used to filter retrieval to it.
# "transformer" is deliberately absent: it appears in all three papers.
PAPER_ALIASES = {
    "attention": ["attention is all you need", "vaswani"],
    "moshi": ["moshi", "mimi", "helium", "kyutai"],
    "hnet": ["h-net", "hnet", "dynamic chunking"],
}

# --- Fetching (polite: once per file, a few seconds apart) ---
FETCH_SPACING_S = 3.0
FETCH_TIMEOUT_S = 60.0
USER_AGENT = "the-relay/0.1 (take-home research script; fetches 3 papers once)"

# Approximation used for piece sizes and spend estimates; real counts come from Groq usage.
TOKENS_PER_WORD = 1.33

# --- Retrieval settings (PLAN 2.2) ---
# For C, piece_tokens is the cap above which a long section is split into windows
# that keep the same "Paper > §section" prefix.
SETTINGS = {
    "A": {"split": "fixed", "piece_tokens": 180, "overlap_tokens": 30,
          "candidates": 8, "pieces": 8, "rerank": False},
    "B": {"split": "fixed", "piece_tokens": 600, "overlap_tokens": 80,
          "candidates": 4, "pieces": 4, "rerank": False},
    "C": {"split": "section", "piece_tokens": 600, "overlap_tokens": 50,
          "candidates": 20, "pieces": 4, "rerank": True},
}
RETRIEVAL_SETTING = "C"  # default for ask.py; Tanush's call, swappable live
RRF_K = 60  # reciprocal rank fusion constant for merging BM25 and embedding ranks
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# --- Model service ---
# The one switch that points the client at Groq or, in phase 3, the stand-in.
BASE_URL = os.environ.get("RELAY_BASE_URL", "https://api.groq.com/openai/v1")
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 60.0

CANDIDATE_MODELS = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile",
                    "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
DRAFT_MODEL = "llama-3.1-8b-instant"  # provisional until the probe; Tanush chooses the drafting model (PLAN 2.6)
# Reasoning models may spend tokens before the first content token; the probe records
# whether this happens. Groq's `reasoning_format` applies to other reasoning models and is
# believed not to apply to gpt-oss (which uses reasoning_effort / include_reasoning).
# Unverified until the probe; add it per model here if needed.
MODEL_PARAMS = {
    "openai/gpt-oss-20b": {"reasoning_effort": "low"},
    "openai/gpt-oss-120b": {"reasoning_effort": "low"},
}

# --- Answer drafting ---
ANSWER_MAX_TOKENS = 250
ANSWER_SYSTEM_PROMPT = (
    "Answer the question using only the numbered pieces of the papers given below. "
    "After each claim, cite the id of the piece it comes from in square brackets, "
    "for example [moshi-C-012]. If the pieces do not contain the answer, reply "
    "exactly: The papers do not say."
)
# One piece id, e.g. moshi-C-012. A bracket may hold several, separated by commas.
CITATION_ID = r"[a-z]+-[ABC]-\d+"

# --- Rate-limit probe ---
# The whole probe must stay around 25-30k tokens (PLAN 5.3 Tuesday budget).
# Values are assistant defaults pending Tanush.
PROBE = {
    "models": CANDIDATE_MODELS,
    "main_model": DRAFT_MODEL,
    "small_prompt": "Reply with the single word: ok",
    "small_max_tokens": 16,
    "header_sample_max_tokens": 200,
    "spaced_requests": 50,
    "spaced_interval_s": 4.0,
    "rpm_burst_requests": 40,
    "tpm_burst_requests": 4,
    "tpm_burst_prompt_tokens": 2500,
    "tpm_burst_max_tokens": 16,
    "recovery_poll_interval_s": 5.0,
    "recovery_max_polls": 30,
    "concurrency_levels": [1, 2, 4, 8],
    "max_tokens_pair": [50, 1000],
    "default_cap": 30000,
}
