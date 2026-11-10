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
# Spend estimates are deliberately high: the larger of words x TOKENS_PER_WORD and
# characters / CHARS_PER_TOKEN (math-heavy text has long "words"), plus a fixed overhead
# per request for the chat template Groq wraps around the messages. The overhead is
# unverified until the probe: compare it with usage.prompt_tokens and update it here.
CHARS_PER_TOKEN = 3.0
REQUEST_OVERHEAD_TOKENS = 60

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

# Chat models Groq's free models list returned on 10 Nov 2026 (probe run_20261110T060353Z).
# The Llama chat models the plan assumed are NOT on the account.
CANDIDATE_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
DRAFT_MODEL = "openai/gpt-oss-20b"  # provisional until the probe; Tanush chooses the drafting model (PLAN 2.6)
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
# Values are assistant defaults pending Tanush. Two profiles (Tanush approved "lean" as
# the default): lean answers the questions Table 1 needs; "full" adds the token-limit
# burst, its recovery and the max_tokens 50 vs 1000 pair, and runs only with --profile full.
PROBE = {
    "profiles": {
        "lean": ["models", "header_sample", "spaced", "rpm_burst", "recovery_rpm",
                 "concurrency"],
        "full": ["models", "header_sample", "spaced", "rpm_burst", "recovery_rpm",
                 "tpm_burst", "recovery_tpm", "concurrency", "max_tokens_pair"],
    },
    "default_profile": "lean",
    "models": CANDIDATE_MODELS,
    "main_model": DRAFT_MODEL,
    "small_prompt": "Reply with the single word: ok",
    "small_max_tokens": 16,
    "header_sample_max_tokens": 200,
    "spaced_requests": 50,
    "spaced_interval_s": 4.0,
    "rpm_burst_requests": 40,  # an upper bound: the burst stops at its first 429
    "rpm_burst_wave": 5,  # sent 5 at a time, so 40 tiny requests fit well inside a minute
    "tpm_burst_requests": 4,
    "tpm_burst_prompt_tokens": 2500,
    "tpm_burst_max_tokens": 16,
    "recovery_poll_interval_s": 5.0,
    "recovery_max_polls": 30,  # an upper bound: recovery stops at its first 200
    "concurrency_levels": [1, 2, 4, 8],  # stops after the first level that gets a 429
    "max_tokens_pair": [50, 1000],
    # Seconds to wait before a stage so the previous burst's per-minute window has passed.
    "pause_before_s": {"tpm_burst": 60, "concurrency": 60},
    # Abort if a header limit is under this fraction of DOCUMENTED_LIMITS: report, do not retry.
    "low_limit_fraction": 0.5,
    "default_cap": 30000,
}

# What Groq's limits page is believed to say per model, used ONLY to spot a header that is
# far lower than expected (then the probe aborts and reports). Not measurements, never in
# Table 1. The headers report requests per day and tokens per minute (docs/RESEARCH.md).
# All values: docs/RESEARCH.md table (Groq rate-limits page as read on 9 Nov 2026).
DOCUMENTED_LIMITS = {
    "openai/gpt-oss-20b": {"requests_per_day": 1000, "tokens_per_minute": 8000},
    "openai/gpt-oss-120b": {"requests_per_day": 1000, "tokens_per_minute": 8000},
    "qwen/qwen3.8-27b": {"requests_per_day": 1000, "tokens_per_minute": 8000},
}
