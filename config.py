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
RESULTS_PATH = DATA_DIR / "results.csv"  # the brief's raw file: one row per request
TRACE_PATH = TRACES_DIR / "traces.jsonl"  # richer per-request detail (steps, pieces, usage)
QUESTIONS_PATH = DATA_DIR / "questions.csv"  # Tanush's questions and answer key
GRADING_DIR = DATA_DIR / "grading"  # one sheet per evaluation run, graded by hand
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
# Diversity (maximal marginal relevance, library/search.py diverse): 1.0 = off. Measured
# offline on Tanush's 18 questions (key-answer figures found in the retrieved pieces, of
# 291, A / B / C): off 194 / 223 / 201; 0.7 199 / 224 / 201; 0.5 204 / 218 / 217 (Q1's base
# dimensions: 5 of 9 found -> 9 of 9 under C).
MMR_LAMBDA = 0.5
MMR_POOL = 3  # rank MMR_POOL x pieces candidates to choose from
RRF_K = 60  # reciprocal rank fusion constant for merging BM25 and embedding ranks
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
# The embedding model reads at most 256 word-pieces, the re-ranker 512 (question + text).
# Pieces are scored by their best window of this many words, so long B/C pieces are read whole.
EMBED_WINDOW_WORDS = 150
EMBED_WINDOW_OVERLAP_WORDS = 30

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

# --- Routing and re-query (robust-by-default audit, 12 Nov) ---
# "meaning": a question goes to the papers whose average meaning is within ROUTE_MARGIN
# of the closest (library/search.py route); "names": the old alias list below.
# Measured offline on Tanush's 18 questions (key-answer figures found in the retrieved
# pieces, of 291): name list A 195 / B 223 / C 199; paper-centroid routing (margin 0.05)
# 191 / 214 / 191; searching all papers and letting meaning-based ranking decide
# 194 / 223 / 201. So no routing filter: margin 1.0 keeps every paper.
ROUTING = "meaning"
ROUTE_MARGIN = 1.0
# "context": a weak search is rewritten with the section titles the first search found;
# "keywords": the old rule (stop words removed).
REQUERY = "context"  # none of the 18 questions needed a re-query (all strengths >= 0.38)

# --- Pipeline: understand, retrieve, decide, draft, check (relay/pipeline.py) ---
# Decide: below this retrieval strength (best cosine, 0..1) the question is re-queried once,
# then refused with no model call. PROVISIONAL: set from Tanush's question runs (EVAL-05).
# Checked 10 Nov on test probes only: the three known facts scored 0.47-0.76, off-topic
# questions (capital of France, football, sourdough) 0.12-0.20, and an in-domain question
# the papers may not answer (H-Net training GPU) 0.44-0.46, which only the model and the
# check step can catch. 0.30 sits between off-topic and in-domain.
MIN_STRENGTH = 0.30
MAX_REQUERIES = 1  # the loop cap: at most one re-query per question
MAX_QUESTION_CHARS = 1000  # understand: longer questions are refused before any work
REFUSAL_TEXT = "The papers do not say."  # the model's own refusal, from the prompt below
WITHHELD_NOTE = ("[Part of this answer was withheld because it could not be checked against "
                 "the papers.]")
CHECK_FAILED_TEXT = ("I could not check an answer against the papers, so I will not guess. "
                     "The papers may not say this.")
# Draft: gpt-oss reasons before its visible text (probe, 10 Nov: ~6 reasoning tokens on a
# tiny prompt, 37 on the first real answer; at max_tokens 16, 33 of 50 replies ended before
# any visible text). max_tokens counts reasoning too, so headroom is added on top.
# Visible answer budget. 250 cut off 11 of 36 real setting-C replies (12 Nov) mid-formula or
# mid-list; whether a reply runs long was not predictable from its pieces (tables or formula
# density marked 5 of 11 cut-offs and 13 of 25 complete replies), so the cap is raised for
# all. It is a cap: real spend grows only for replies that would have been cut off.
ANSWER_MAX_TOKENS = 450
REASONING_HEADROOM_TOKENS = 150
# Per-request ceiling (estimated prompt + max_tokens): the lowest pieces are dropped to fit.
# 6,000 keeps one request well inside the 8,000 tokens a minute and leaves every setting
# whole (B's 4 x 600-token pieces estimate ~4,500); at 4,000 it silently cut B to 3 pieces.
REQUEST_TOKEN_CEILING = 6000

# Cost per 1,000 answers (Table 2b) at Groq's published list price, in dollars per million
# tokens: console.groq.com/docs/model/openai/gpt-oss-20b, read 13 Nov 2026 (input $0.075,
# output $0.30; cached input $0.037 not used: no prompt caching was relied on).
PRICE_PER_MILLION_TOKENS = {"in": 0.075, "out": 0.30}

# --- Answer drafting ---
ANSWER_SYSTEM_PROMPT = (
    "Answer the question using only the numbered pieces of the papers given below. "
    "Answer every part of the question that the pieces support, and end each paragraph with "
    "the ids of the pieces that support it in square brackets, for example [moshi-C-012]. "
    "Say plainly which parts of the question the pieces do not cover. Only if the pieces "
    "support nothing relevant to the question, reply exactly: The papers do not say."
)
# The check's meaning test (relay/check.py): a local NLI cross-encoder, and the entailment
# score a paragraph needs. The threshold is calibrated from data (docs/DECISIONS.md).
NLI_MODEL = "cross-encoder/nli-MiniLM2-L6-H768"
# Calibrated 12 Nov on paragraphs of the 54 real replies whose citations and numbers check
# out (23, presumed supported; weak labels) vs the same paragraphs judged against pieces of
# another paper (test fixtures). Chosen to favour few wrong passes: at 0.4 (best sentence)
# the whole gate keeps 48% of the first and lets 4% (1 of 23) of the second through; at
# 0.25 it would keep 65% but let 13% through. Mean, median and share-of-sentences rules
# did worse on the same data.
ENTAIL_THRESHOLD = 0.4
# A paragraph that says what the papers do not cover needs no citation (it claims nothing).
# Chosen 12 Nov from five phrasings on varied test wordings (fixtures): with this one, six
# "not covered" wordings scored at least 0.49 and five factual claims at most 0.27.
NOT_COVERED_HYPOTHESIS = "The answer is not given."
NOT_COVERED_THRESHOLD = 0.4
# One piece id, e.g. moshi-C-012. A bracket may hold several, separated by commas.
CITATION_ID = r"[a-z]+-[ABC]-\d+"

# --- Rate-limit probe ---
# The lean probe Tanush approved and ran on 10 Nov (run_20261110T133218Z). The token-limit
# burst and the max_tokens pair ("full" profile) were never run and were removed in phase 2.
PROBE = {
    "stages": ["models", "header_sample", "spaced", "rpm_burst", "recovery_rpm", "concurrency"],
    "models": CANDIDATE_MODELS,
    "main_model": DRAFT_MODEL,
    "small_prompt": "Reply with the single word: ok",
    "small_max_tokens": 16,
    "header_sample_max_tokens": 200,
    "spaced_requests": 50,
    "spaced_interval_s": 4.0,
    "rpm_burst_requests": 40,  # an upper bound: the burst stops at its first 429
    "rpm_burst_wave": 5,  # sent 5 at a time, so 40 tiny requests fit well inside a minute
    "recovery_poll_interval_s": 5.0,
    "recovery_max_polls": 30,  # an upper bound: recovery stops at its first 200
    "concurrency_levels": [1, 2, 4, 8],  # stops after the first level that gets a 429
    # Seconds to wait before a stage so the previous burst's per-minute window has passed.
    "pause_before_s": {"concurrency": 60},
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

# --- Time (relay/clock.py) ---
TIME_SCALE = 1.0  # wall seconds per model second; load runs compress time (0.02 = 50x)

# --- Gateway (relay/gateway.py): the only door to the model ---
# Limits the gateway plans with, per model. Measured on 10 Nov (run_20261110T133218Z): 30
# requests/min (429 body), 8,000 tokens/min and 1,000 requests/day (headers). Tokens/day is
# NOT measured: 200,000 is Groq's documented value. Headers give only requests/day and
# tokens/minute, so requests/minute and tokens/day are counted locally.
LIMITS = {"rpm": 30, "tpm": 8000, "rpd": 1000, "tpd": 200000}
LIMIT_SAFETY = 0.9  # plan with 90% of each limit, so small estimate errors never cause a 429
# Deadlines (PLAN 3.2, pending Tanush): first token target 2,000 ms median / 5,000 ms p95;
# a person gives up after GIVE_UP_MS without an answer.
FIRST_TOKEN_TARGET_MS = 2000
GIVE_UP_MS = 15000
QUEUE_MAX = 50
# "fifo", or "small_first": when less than one answer is affordable this minute, the queued
# request with the smallest token estimate goes first (Tanush's idea, 12 Nov).
QUEUE_ORDER = "fifo"
# Ladder, in answers still affordable this minute (one answer ~2,400-4,100 of 8,000 tokens):
# Normal at LEAN_BELOW_ANSWERS or more, Lean below it, Day-gone when the daily budget cannot
# pay for one more answer. Citations, the check and the refusal rule never change.
LEAN_BELOW_ANSWERS = 1.5
LEVELS = {"normal": {"max_pieces": None, "answer_max_tokens": ANSWER_MAX_TOKENS, "requery": True},
          "lean": {"max_pieces": 2, "answer_max_tokens": 120, "requery": False}}
DAY_GONE_PASSAGES = 2  # pieces shown verbatim when the daily budget is gone
CACHE_ON = True  # exact-match cache of finished, checked answers
# Retries (PLAN 3.5): only these statuses and a first-token timeout; full-jitter backoff;
# never past the deadline; a retry budget of 10% of recent calls (switch off for the
# retry-storm run); never after text was shown.
RETRY_STATUSES = {429, 500, 502, 503}
RETRY_MAX = 2
RETRY_BASE_S = 0.5
RETRY_BUDGET = 0.10  # None = no budget (retry-storm comparison)
RETRY_WINDOW = 100  # the budget counts the last this-many model calls
# Timeouts from the probe: the first streamed event came by 2,001 ms at the most (p99, n=50,
# tiny prompts; a 2,365-token prompt took 1,063 ms) and chunks after it arrived within 34 ms.
FIRST_TOKEN_TIMEOUT_S = 4.0
STALL_TIMEOUT_S = 1.0
# The retrieve tool gets its own timeout; on timeout it is retried once, then the person is
# told honestly that the library search failed (never an answer without passages).
RETRIEVE_TIMEOUT_S = 1.0
INJECT_RETRIEVE_DELAY_S = 0.0  # INJECTED fault for the tool-timeout scenario (0 = off)

# --- Stand-in model service (relay/standin.py) ---
# Timings are resampled from the real probe (STANDIN_PROBE_RUN). Everything marked
# INJECTED or ASSUMED is not measured and is labelled as such in the write-up.
STANDIN_PROBE_RUN = PROBE_DIR / "run_20261110T133218Z"
STANDIN = {
    "limits": dict(LIMITS),  # what the stand-in enforces (scenarios halve or shrink these)
    # First-event time by prompt size, from real data only: prompts under
    # large_prompt_tokens resample the probe's 50 spaced tiny requests (median 502 ms);
    # larger ones resample the 54 real evaluation replies of 12 Nov (1,601-3,103 prompt
    # tokens, median 933 ms). Within that range a straight-line fit explains almost nothing
    # (first event = 820 ms + 0.117 ms x prompt tokens, r = 0.10, residual sd 569 ms), so
    # the stand-in draws from the measured spread instead of a fitted slope.
    "large_prompt_tokens": 1000,
    "eval_traces": TRACE_PATH,
    "prompt_token_ratio": 0.713,  # Groq's prompt count / our estimate (median of 54; 0.60-0.89)
    "reasoning_tokens": 43, "answer_tokens": 170,  # medians of the 54 real replies
    "slowdown_above_inflight": 8,  # ASSUMED: no slowdown was measured up to 8 at once
    "slowdown_per_extra": 0.05,  # ASSUMED: +5% latency per request in flight above that
    "straggler_rate": 0.0, "straggler_factor": 3.0,  # INJECTED slow successes (0 = off)
    "fail_rate": 0.0,  # INJECTED 503s (0 = off)
    "stall_rate": 0.0, "stall_s": 2.0,  # INJECTED mid-stream stalls (0 = off)
    "seed": 7,
}

# Table 3 reads only the full evaluation runs of the final system, one per setting (not the
# 2-question eval-final-interrupted run of 12 Nov, kept in results.csv as raw data).
TABLE3_RUNS = ("eval-final-A", "eval-final-B", "eval-final-C")

# --- Load runs (relay/loadgen.py) against the stand-in ---
# Arrivals are a STATED process, not a replayed public trace (no trace's licence could be
# confirmed for this use): Poisson arrivals at rate_per_min, plus an optional burst of
# `count` extra arrivals spread evenly over `over_s` seconds starting at `at_s`. Seeded.
# Capacity for reference: 8,000 tokens a minute / ~3,000 per answer = ~2.7 answers a minute.
LOAD_TIME_SCALE = 0.02  # 50x compression (see relay/clock.py for what that distorts)
LOAD_SETTING = "C"
# At Groq's documented 200,000 tokens a day, two answers a minute use up the day in about
# 35 minutes: the daily limit binds long before the per-minute one. So the per-minute
# scenarios lift the daily limits (stated in the write-up) and only day_exhausted keeps them.
NO_DAY_LIMIT = {**LIMITS, "rpd": 10**9, "tpd": 10**12}
# The exact-match cache is switched off in the load scenarios: with a pool of 18 questions
# almost every request would be a cache hit and the limits would never be exercised. Its
# effect is shown once, in burst_cached (incident bursts repeat the same few questions).
NO_CACHE = {"cache_on": False}
SCENARIOS = {
    "steady": {"rate_per_min": 2.0, "requests": 1000, "limits": NO_DAY_LIMIT,
               "gateway": NO_CACHE},
    "burst": {"rate_per_min": 1.5, "requests": 1000, "limits": NO_DAY_LIMIT, "gateway": NO_CACHE,
              "burst": {"at_s": 1800, "count": 60, "over_s": 30}},
    "burst_cached": {"rate_per_min": 1.5, "requests": 1000, "limits": NO_DAY_LIMIT,
                     "burst": {"at_s": 1800, "count": 60, "over_s": 30}},
    "overload": {"rate_per_min": 8.0, "requests": 1000, "limits": NO_DAY_LIMIT,
                 "gateway": NO_CACHE},
    # Retry storm (heading 6). At 8 a minute nobody can be retried: people already wait
    # ~8 s in the queue, so after a 4 s first-token timeout a retry would end past the 15 s
    # give-up, and the deadline rule forbids it (seen 12 Nov: 0 retries). So the storm pair
    # runs just above capacity (3 a minute vs ~2.7 affordable) with INJECTED slow successes
    # (30% of calls take 5x longer and pass the first-token timeout after the provider has
    # charged the prompt). Retry budget on (10%) vs off: does retrying make things worse?
    "retry_budget_on": {"rate_per_min": 3.0, "requests": 1000, "limits": NO_DAY_LIMIT,
                        "gateway": NO_CACHE,
                        "standin": {"straggler_rate": 0.3, "straggler_factor": 5.0}},
    "retry_budget_off": {"rate_per_min": 3.0, "requests": 1000, "limits": NO_DAY_LIMIT,
                         "gateway": {**NO_CACHE, "retry_budget": None},
                         "standin": {"straggler_rate": 0.3, "straggler_factor": 5.0}},
    "overload_small_first": {"rate_per_min": 8.0, "requests": 1000, "limits": NO_DAY_LIMIT,
                             "gateway": {**NO_CACHE, "queue_order": "small_first"}},
    # The stand-in's per-minute limits halve mid-run; the gateway is not told.
    "limit_halved": {"rate_per_min": 2.0, "requests": 1000, "limits": NO_DAY_LIMIT,
                     "gateway": NO_CACHE, "halve_at_s": 15000},
    "day_exhausted": {"rate_per_min": 2.0, "requests": 300, "limits": LIMITS,
                      "gateway": NO_CACHE},
}
