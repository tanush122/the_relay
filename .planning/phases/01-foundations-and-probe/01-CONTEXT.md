# Phase 1 context: Foundations and probe

Written in place of /gsd-discuss-phase from Tanush's instructions (relayed 2026-11-10), docs/PLAN.md (plan of record, sections 2.1–2.3, 3.9, 4.1) and docs/DECISIONS.md. Answers not explicitly from Tanush are marked **assistant default, pending Tanush** and are logged in docs/DECISIONS.md.

## Locked decisions (Tanush)

- Python. Real measured data only — nothing invented is ever written to results.csv or reported as a measurement. Test fixtures are fine, clearly as fixtures.
- Work locally in ~/Desktop/the-relay. Install uv (official installer, user-level) and Python 3.12 for this project only. No global changes beyond the uv binary.
- Code must be explainable and changeable live by Tanush: small files, plain functions, standard library plus a few well-known packages (httpx, rank-bm25, sentence-transformers, pytest, beautifulsoup4/lxml for HTML parsing, pypdf only if the PDF fallback is needed). NO LangChain or agent frameworks. Docstrings say *why*. **Target ~400–500 lines of non-test code for phase 1.**
- The Groq key lives ONLY in a git-ignored `.env`. Create `.env.example` containing `GROQ_API_KEY=` and a git-ignored `.env` containing only `GROQ_API_KEY=` (empty) so Tanush pastes his key after the equals sign. Never write, echo, log or commit the key.
- One `config.py` holds every tunable (model names, base URL, limits defaults, retrieval settings, timeouts, probe sizes, token caps).

## Scope (from plan owner)

a. **Environment**: uv + Python 3.12 project; `pyproject.toml` with pinned versions; `.gitignore` covers `.env`, `.venv`, `data/raw`, caches (model caches, `__pycache__`, `.pytest_cache`); a test that fails if any git-tracked file contains a string matching `gsk_[A-Za-z0-9]{10,}` (allow the bare rule text "gsk_" in docs). Optional git pre-commit hook running the same check.
b. **Library** (`library/`): fetch arXiv HTML at exactly `1706.03762v7`, `2410.00037v1`, `2507.07955v2` (`https://arxiv.org/html/<id>v<n>`), PDF (`https://arxiv.org/pdf/<id>v<n>`) as fallback and also fetched for its stable checksum. Fetch once each, a few seconds apart, cached under `data/raw/`, never refetched if present. Commit a manifest (`data/manifest.json`) with url, version, bytes, sha256, fetched_at for every file. Verify each file states the right version (the HTML/PDF content or arXiv page indicates v7/v1/v2) — the Moshi v1 vs v2 trap matters. Parse into a section tree; every piece carries paper, version, section number, section title, piece id. Tables with captions kept whole (imperfect tables acceptable, documented).
c. **Three splitting settings as configuration** (PLAN 2.2): A small fixed ~180 tokens / 30 overlap / 8 pieces / no re-rank; B large fixed ~600 / 80 overlap / 4 pieces / no re-rank; C section-aware (split on headings, tables whole, prefix "Paper > §section") / 4 chosen from top 20 / local cross-encoder re-rank. One code path parameterised by a settings dict where possible. Retrieval = BM25 + small local embedding model (e.g. `sentence-transformers/all-MiniLM-L6-v2` or `BAAI/bge-small-en-v1.5`) merged by reciprocal rank fusion; local cross-encoder (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) for C. Filter to a paper when the question names one. Zero Groq tokens. Load models once; record cold/warm timing.
d. **Groq client** (`relay/llm.py` or similar): async (httpx), streaming SSE, OpenAI-compatible `/openai/v1/chat/completions`, one `BASE_URL` setting so the stand-in can replace it in phase 3. Per call it records: time to first *content* token, total time, token usage (from the final chunk's `usage` / `x_groq.usage` if present), **all** response headers verbatim (especially `x-ratelimit-*`, `retry-after`), HTTP status and error body. Writes one JSON trace line per request (`data/traces/*.jsonl`). Key read from environment or `.env` only.
e. **Probe** (`probe.py` or `bench/probe.py`): `--dry-run` prints every planned request and the estimated token spend; real mode refuses unless `--confirm` AND `--max-tokens-total N` are given, and stops before exceeding the cap. Saves raw responses (status, headers, timings, usage, error bodies, final chunk) under `data/probe/`. A small script drafts Table 1 (rows: requests per minute, tokens per minute, requests per day, tokens per day, requests in flight at once, what it returns when a limit is hit, time until it recovers; columns: Limit, Value found, How found, Confidence) from those raw files, writing "not measured" / "unconfirmed" honestly.
f. **One thin end-to-end path** (`ask.py` or similar): question → retrieve (chosen setting) → one streamed Groq draft that answers only from numbered pieces and cites piece ids → ids mapped in code to "paper vX, §section title". The full five steps come in phase 2.

## Probe design (assistant default, pending Tanush — derived from checker findings; changes only *what the probe measures*, not the plan)

- A free `GET /openai/v1/models` call first to confirm which candidate models exist (llama-3.1-8b-instant, llama-3.3-70b-versatile, openai/gpt-oss-20b, openai/gpt-oss-120b may or may not exist).
- ~50 spaced small streamed requests (configurable) for the latency spread; record per-model header values from the first response of each candidate model.
- Detect reasoning output: record delta types and whether content arrives after reasoning; support a `reasoning_effort`/`reasoning_format` setting in config for gpt-oss models.
- Two bursts instead of one: (1) many tiny requests to trip requests-per-minute, (2) a few large-prompt requests to trip tokens-per-minute; save both 429 bodies and `retry-after`; measure recovery by polling until the first 200.
- A small concurrency ramp (1, 2, 4, 8 concurrent) to give "requests in flight at once" a method.
- Optional: a max_tokens 50 vs 1,000 pair to see whether requested max_tokens is charged at admission.
- Every stage's token estimate is included in the dry-run total; the default per-run cap should keep the whole probe around 25–30k tokens (PLAN 5.3 budgets ~30k for Tuesday).

## Hard stops

1. No real Groq call until the key is in `.env` AND Tanush says yes after seeing the dry run's estimated spend. If the key is not present, build and test everything, run the dry run, and stop.
2. Never write, echo or commit the key.
3. Do not start phase 2 work (full five steps, refusal gates, grading sheet, results.csv writer).

## Tests required (pytest)

- The fetched papers are the exact versions (manifest + content check).
- Parsing produces sensible sections for all three papers (non-empty, expected top-level section numbers present).
- A known fact is retrievable under each setting A, B, C: Attention feed-forward dimension (d_ff = 2048), Moshi's Mimi frame rate (12.5 Hz), H-Net's ratio loss.
- The client parses a streamed response and the rate-limit headers correctly against a tiny local fake server (fixture, not a measurement).
- The `gsk_` guard.
Tests that need downloaded papers/models may be marked so they skip cleanly when data is absent, but they must run in this phase's verification.

## Deferred / not in phase 1

Five-step pipeline, refusal threshold, grading sheet, results.csv writer and validator (phase 2). Gateway, stand-in, load generator (phase 3). All other checker findings stay in .planning/CHECKER-FINDINGS.md for Tanush.

## Note added 2026-11-10: .env already exists

`.env` (git-ignored, containing the line `GROQ_API_KEY=`) was created before execution so Tanush can paste his key. Executors must NEVER overwrite, recreate, read aloud, print or modify `.env`; only create it if it is missing.
