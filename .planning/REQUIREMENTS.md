# Requirements: The Relay

**Defined:** 2026-11-10
**Core Value:** Every number in the write-up is a real measurement that recomputes from results.csv, and the system never sends an uncited or wrong answer to stay fast.

Sources: docs/BRIEF.md (authority), docs/PLAN.md (plan of record, section numbers given as "PLAN x.y"). Brief references given as "BRIEF: ...".

## v1 Requirements

### Environment and hygiene (ENV)

- [x] **ENV-01**: Project runs on Python 3.12 via uv with pinned dependencies (BRIEF: Python; PLAN 6 phase 1)
- [x] **ENV-02**: Groq key is read only from a git-ignored .env; .env.example ships with an empty `GROQ_API_KEY=`; key never printed, logged or committed (BRIEF ground rule: do not include your key)
- [x] **ENV-03**: A test or pre-commit guard fails if a string starting with `gsk_` appears in any tracked file (BRIEF ground rule: key)
- [x] **ENV-04**: Every tunable (limits, deadlines, ladder thresholds, retry policy, retrieval setting, model names) lives in one config module, so a live change is a one-line edit (PLAN 5.7)
- [ ] **ENV-05**: Every real Groq run prints its estimated token spend first and refuses to run without an explicit confirmation flag and a per-run hard token cap (BRIEF: plan your requests; PLAN 5.3)

### Library and retrieval (LIB)

- [x] **LIB-01**: The three papers are fetched once at exactly 1706.03762v7, 2410.00037v1, 2507.07955v2 (arXiv HTML, PDF fallback), cached locally, with a committed manifest of URL, version, bytes, sha256 and fetch time (BRIEF: the library, exact versions)
- [x] **LIB-02**: Papers are parsed into a section tree; every piece carries paper, version, section number, section title and a piece id; tables are kept whole with captions (BRIEF: cite where in the papers; PLAN 2.1)
- [x] **LIB-03**: Three retrieval settings exist as configuration: A small fixed (~180 tokens, 30 overlap, 8 pieces, no re-rank), B large fixed (~600 tokens, 80 overlap, 4 pieces, no re-rank), C section-aware (4 of top 20, local cross-encoder re-rank) (BRIEF: at least three settings — piece size, pieces fetched, re-ranking; PLAN 2.2)
- [x] **LIB-04**: Retrieval combines BM25 and a small local embedding model by reciprocal rank fusion, spends zero Groq tokens, and filters to a paper when the question names one (PLAN 2.3)
- [x] **LIB-05**: A known fact from each paper is retrievable under every setting (e.g. Attention feed-forward dimension, Moshi Mimi frame rate, H-Net ratio loss) (BRIEF: one step must retrieve passages)

### Real service and client (REAL)

- [ ] **REAL-01**: An async streaming model client with a single base-URL setting talks to Groq or the stand-in unchanged (BRIEF: real hosted model on Groq free tier; stand-in replaces it)
- [ ] **REAL-02**: The client records per call: time to first token, total time, token usage and all rate-limit headers, and writes a per-request trace line (BRIEF: TTFT and total time; PLAN 3.9)
- [ ] **REAL-03**: A probe sends a modest number of real requests (~50 spaced, then one deliberate burst) and saves raw status, headers, timings, usage and error bodies (BRIEF: what to run — first, modest number of real requests; latency spread, limits, behaviour at a limit)
- [ ] **REAL-04**: A script drafts Table 1 from the raw probe files with every row: requests per minute, tokens per minute, requests per day, tokens per day, requests in flight at once, what it returns when a limit is hit, time until it recovers — columns Limit, Value found, How found, Confidence (BRIEF: Table 1)
- [ ] **REAL-05**: The daily limit is confirmed by exhausting the cheapest model once, late, when no other run needs quota — or Table 1 says how it was found otherwise (BRIEF: Table 1 requests/tokens per day; PLAN 4.1)

### Pipeline (PIPE)

- [ ] **PIPE-01**: A request runs five steps — understand, retrieve (tool call), decide, draft, check — at least four steps, one tool call, one branch or loop (BRIEF: what to build)
- [ ] **PIPE-02**: The decide step re-queries at most once when retrieval is weak and refuses without a model call if still weak (BRIEF: branch or loop; some loop)
- [ ] **PIPE-03**: The draft step streams an answer only from numbered pieces, citing piece ids that code maps to "paper, version, section"; output capped (~250 tokens) (BRIEF: every answer must cite)
- [ ] **PIPE-04**: The check step verifies in code that every cited id was retrieved and every number in the answer appears in a cited piece; a failed check becomes a refusal, never a guess (BRIEF: never send a wrong or embarrassing answer)
- [ ] **PIPE-05**: When the papers do not say, the assistant says so instead of guessing (retrieval threshold + prompt permission + check) (BRIEF: if the papers do not say)
- [ ] **PIPE-07**: One command (`uv run relay ask "question"`) runs the full pipeline on a single question and prints the streamed answer, citations mapped to paper/section, timing and tokens (BRIEF: we will ask questions; live follow-up)
- [ ] **PIPE-06**: One byte-identical system prompt across requests (PLAN 2.4)

### Gateway (GW)

- [ ] **GW-01**: The gateway is the only door to the model: it keeps its own requests/tokens per-minute and per-day counters per model, corrected from response headers, and reserves estimated cost before each call (BRIEF: provider limits RPM/TPM/RPD; PLAN 3.1)
- [ ] **GW-02**: Each request carries a deadline (proposed first token 2,000 ms p50 / 5,000 ms p95, give-up 15,000 ms); requests predicted to miss it are refused at once with an honest message and retry time (BRIEF: people give up; define fast; PLAN 3.2)
- [ ] **GW-03**: Bounded queue; expired requests dropped before spending tokens; queue order (oldest vs newest first) is configurable (PLAN 3.3)
- [ ] **GW-04**: A three-level degradation ladder (Normal, Lean, Day-gone) chosen from remaining budget; waiting for the minute to refill is queue behaviour, not a level; citations, check and refusal never change; a daily reserve is held back (BRIEF: who gets a weaker answer; PLAN 3.4)
- [ ] **GW-05**: Retry policy: only 429 (after retry-after), 500, 502, 503 and first-token timeouts; exponential backoff with full jitter; at most 2 retries; never past the deadline; retry budget 10% of recent calls; no retry after tokens shown; budget switchable off for the storm comparison (BRIEF: heading Retries; PLAN 3.5)
- [ ] **GW-06**: Two timeouts — first-token and stall-between-chunks — set from probe percentiles (BRIEF: calls succeed slowly; PLAN 3.6)
- [ ] **GW-07**: Finished answers are cached by exact normalised question; coalescing of concurrent identical questions is deliberately not built and its cost is measured from the burst run (PLAN 3.7, revised 10 Nov)
- [ ] **GW-09**: Tool timeouts are simulated: a config setting injects delay or failure into the retrieve step, which has its own timeout and a rule (retry once, else refuse honestly; never answer without passages), recorded as a trace span (BRIEF: tools time out)
- [ ] **GW-08**: At the Day-gone level a waiting person receives cached answers or the most relevant cited passages with no model call, plus when generated answers return (BRIEF: heading 7, 3pm daily budget gone)

### Stand-in (STAND)

- [ ] **STAND-01**: A stand-in server speaks the same chat-completions API as Groq, streams the reply a piece at a time, and sends the same rate-limit headers and 429 with retry-after (BRIEF: stand-in must send reply a piece at a time, refuse at a limit)
- [ ] **STAND-02**: Latency is resampled from the real probe's recorded values; it can be slow, fail, stall mid-stream, and slow down as in-flight requests rise (BRIEF: be slow, fail, slower under load; calibrate from measurements)
- [ ] **STAND-03**: Its limits are settings, enabling "per-minute limit halved" and "daily budget exhausted" scenarios (BRIEF: Table 2a rows)
- [ ] **STAND-04**: A side-by-side real vs stand-in latency comparison exists, and where it differs most is stated (BRIEF: heading 2, say where least like the real thing)

### Load and scenarios (LOAD)

- [ ] **LOAD-01**: Open-loop load generator sends on schedule regardless of reply speed; latency measured from scheduled arrival (PLAN 4.4, measurement honesty)
- [ ] **LOAD-02**: Arrival times come from a slice of a confirmed, licensed public LLM traffic trace compressed in time, or a stated arrival process if none can be confirmed (PLAN 4.2)
- [ ] **LOAD-03**: Six scenarios run: steady (real, small), steady (stand-in), burst, sustained overload (with a paired retry-budget off/on variant for the retry-storm case), per-minute limit halved, daily budget exhausted; queue-order comparison dropped (BRIEF: at least three load shapes; Table 2a required rows)
- [ ] **LOAD-04**: Each stand-in scenario sends at least 1,000 requests; real-run percentiles carry their request count and are labelled weak (BRIEF: say which percentiles and how many requests)
- [ ] **LOAD-05**: Raw results are kept for both real and stand-in runs (BRIEF: keep the raw results for both)

### Evaluation (EVAL)

- [ ] **EVAL-01**: Tanush writes at least 18 questions with an answer key (≈10 prose, 3 table, 2 cross-paper, 3 unanswerable); no agent writes questions, key or grades (BRIEF: at least 15 questions you wrote yourself)
- [ ] **EVAL-02**: Answers are graded by hand as correct, wrong, refused_correctly or refused_wrongly via a grading sheet (BRIEF: answer_grade column)
- [ ] **EVAL-03**: All three retrieval settings are run on real Groq over the questions (spread over two days for quota) (BRIEF: retrieval quality versus cost)
- [ ] **EVAL-04**: Table 3 is produced with columns Setting, Questions asked, Correct and cited %, Wrong %, Correctly refused %, Tokens per answer, First token p50/p95 (ms), Total time p50/p95 (ms) (BRIEF: Table 3)
- [ ] **EVAL-05**: The refusal threshold is set from the questions and the wrong-answer vs wrong-refusal trade is reported (PLAN 2.5)
- [ ] **EVAL-07**: Three ways the library misleads a naive retriever are each shown with an example question confirmed by runs (BRIEF: heading "How this library will mislead a naive retriever")

### Results data and reporting (DATA)

- [ ] **DATA-01**: results.csv has exactly the twelve brief columns: request_id, scenario, source (real/stand-in), start_time, first_token_ms, total_ms, status (ok/rate_limited/timeout/error), retries, tokens_in, tokens_out, retrieval_setting, answer_grade (BRIEF: raw file)
- [ ] **DATA-02**: Status mapping rule applied and stated: admission refusal or unabsorbed 429 = rate_limited; give-up or passed deadline = timeout; else error; honest "papers do not say" = ok + refused_correctly (PLAN 4.3, pending sign-off)
- [ ] **DATA-03**: start_time is arrival time, so peak queue length is rebuildable from start_time + total_ms (PLAN 4.3, pending sign-off)
- [ ] **DATA-04**: Cost per 1,000 answers is computed at Groq's published list price for the model used, with the price stated (PLAN 4.3, pending sign-off)
- [ ] **DATA-05**: Richer per-step spans go to traces.jsonl (arrival, queue wait, step starts/ends, attempts, first and last token) (PLAN 3.9)
- [ ] **DATA-06**: One report command prints Tables 1, 2a, 2b and 3 from results.csv (and probe files); write-up tables are pasted from it; times in ms, percentages one decimal, "not measured" where not measured (BRIEF: tables must match the raw file)
- [ ] **DATA-07**: Table 2a has columns Scenario, Real or stand-in, Requests sent, Duration (s), Offered rate (per min), First token p50/p95/p99 (ms), Total time p50/p95/p99 (ms) (BRIEF: Table 2a)
- [ ] **DATA-08**: Table 2b has columns Scenario, Succeeded %, Rate-limited %, Timed out or given up %, Retries per request, Peak queue length, Tokens per answer, Cost per 1,000 answers (BRIEF: Table 2b)
- [ ] **DATA-10**: Empty-field rule: a results.csv field that does not apply is left empty, never guessed (ungraded load rows have empty answer_grade; replies with no model call have empty first_token_ms but a real total_ms; probe rows use their own scenario names); the validator accepts empty only where the rule allows, and the rule is stated in the write-up
- [ ] **DATA-09**: A validator checks results.csv against the brief's columns and allowed values and that every write-up figure recomputes (BRIEF: reviewers recompute)

### Write-up (DOC)

- [ ] **DOC-01**: Heading 1 "What I built and why" — design and the one decision that shaped it most (BRIEF heading 1)
- [ ] **DOC-02**: Heading 2 "The real service and my stand-in" — limits found and how, stand-in behaviour, calibration, biggest difference (BRIEF heading 2)
- [ ] **DOC-03**: Heading 3 "Results" — TTFT and total time at median and slow end per load shape with percentiles and counts, failures, given-up requests, real vs stand-in, a number we could not have guessed, quality on ≥15 own questions, tokens per answer (BRIEF heading 3)
- [ ] **DOC-04**: Heading 4 "Where the time goes" — one slow request split into waiting, working, retrying; before or after first token; shown from traces (BRIEF heading 4)
- [ ] **DOC-05**: Heading 5 "When a limit is hit" — per-minute and per-day behaviour; who is delayed, dropped, gets a weaker answer, and why (BRIEF heading 5)
- [ ] **DOC-06**: Heading "Retrieval: quality versus cost" after heading 5 — three settings, chosen setting and why, retrieval when the limit is close (BRIEF)
- [ ] **DOC-07**: Heading "How this library will mislead a naive retriever" after heading 5 — three ways with example questions (BRIEF)
- [ ] **DOC-08**: Heading 6 "Retries" — policy and one case where retrying made things worse (BRIEF heading 6)
- [ ] **DOC-09**: Heading 7 "What the person sees" — the reply at 3pm with the daily budget gone (BRIEF heading 7)
- [ ] **DOC-10**: Heading 8 "What I'm unsure about, what I left out, what I learned" — least certain assumption and what breaks, two things not built, one thing taught in own words (BRIEF heading 8)
- [ ] **DOC-11**: Heading "Your feedback on Vaani" — written by Tanush after visiting vaani.dev (BRIEF)
- [ ] **DOC-12**: Section "How I worked with the assistant" — real unedited conversation history, three prompts that mattered, one error caught, one overrule, what is distinctly his; fed by docs/DECISIONS.md (BRIEF)
- [ ] **DOC-13**: Write-up is at most 2 pages of writing, headings in the brief's order, tables 1, 2a, 2b, 3 included and fully filled (BRIEF ground rules; tables required)

### Submission (SUB)

- [ ] **SUB-01**: One Google Drive folder with write-up, code and results.csv, "Anyone with the link can view", submitted via the form by Tanush by 3 PM Fri 13 Nov 2026 (hard deadline 5:22 PM IST) (BRIEF email; ground rule 4 days)
- [ ] **SUB-02**: Submission contains no key anywhere, including conversation history; README gives one command per table; paper checksums included (BRIEF ground rule; PLAN 5.8)
- [ ] **SUB-03**: Tanush rehearses live changes (halve a limit, add a ladder level, swap retrieval setting, change give-up time, explain a slow request), each a one-line config change or small edit in one file (BRIEF: live conversation; PLAN 5.7)

## v2 Requirements

- **V2-01**: Shared budget counters across multiple workers
- **V2-02**: Per-tenant fairness in the queue

## Out of Scope

| Feature | Reason |
|---------|--------|
| Hedged requests | Spend scarce quota under a token limit |
| Second provider or extra accounts | Forbidden by the brief and Groq terms |
| Smaller-model quality eval (EVAL-06) | Dropped with the Minimal ladder rung (10 Nov) |
| Request coalescing | Exact-match cache only; cost measured from burst run (10 Nov) |
| Queue-order comparison | Dropped to cut scenario runtime (10 Nov) |
| Model-based grader | Costs quota; hand grading is defensible |
| Web interface | Measures nothing |
| Multi-worker deployment | One asyncio process is the right size; described as not built |
| LangChain / agent frameworks | Code must be explainable line by line |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENV-01 | Phase 1 | Complete |
| ENV-02 | Phase 1 | Complete |
| ENV-03 | Phase 1 | Complete |
| ENV-04 | Phase 1 | Complete |
| ENV-05 | Phase 1 | Pending |
| LIB-01 | Phase 1 | Complete |
| LIB-02 | Phase 1 | Complete |
| LIB-03 | Phase 1 | Complete |
| LIB-04 | Phase 1 | Complete |
| LIB-05 | Phase 1 | Complete |
| REAL-01 | Phase 1 | Pending |
| REAL-02 | Phase 1 | Pending |
| REAL-03 | Phase 1 | Pending |
| REAL-04 | Phase 1 | Pending |
| REAL-05 | Phase 4 | Pending |
| PIPE-01 | Phase 2 | Pending |
| PIPE-02 | Phase 2 | Pending |
| PIPE-03 | Phase 2 | Pending |
| PIPE-04 | Phase 2 | Pending |
| PIPE-05 | Phase 2 | Pending |
| PIPE-07 | Phase 2 | Pending |
| PIPE-06 | Phase 2 | Pending |
| GW-01 | Phase 3 | Pending |
| GW-02 | Phase 3 | Pending |
| GW-03 | Phase 3 | Pending |
| GW-04 | Phase 3 | Pending |
| GW-05 | Phase 3 | Pending |
| GW-06 | Phase 3 | Pending |
| GW-07 | Phase 3 | Pending |
| GW-09 | Phase 3 | Pending |
| GW-08 | Phase 3 | Pending |
| STAND-01 | Phase 3 | Pending |
| STAND-02 | Phase 3 | Pending |
| STAND-03 | Phase 3 | Pending |
| STAND-04 | Phase 3 | Pending |
| LOAD-01 | Phase 3 | Pending |
| LOAD-02 | Phase 3 | Pending |
| LOAD-03 | Phase 4 | Pending |
| LOAD-04 | Phase 4 | Pending |
| LOAD-05 | Phase 4 | Pending |
| EVAL-01 | Phase 2 | Pending |
| EVAL-02 | Phase 2 | Pending |
| EVAL-03 | Phase 4 | Pending |
| EVAL-04 | Phase 4 | Pending |
| EVAL-05 | Phase 2 | Pending |
| EVAL-07 | Phase 4 | Pending |
| DATA-01 | Phase 2 | Pending |
| DATA-02 | Phase 2 | Pending |
| DATA-03 | Phase 2 | Pending |
| DATA-04 | Phase 4 | Pending |
| DATA-05 | Phase 3 | Pending |
| DATA-06 | Phase 2 | Pending |
| DATA-07 | Phase 2 | Pending |
| DATA-08 | Phase 2 | Pending |
| DATA-10 | Phase 2 | Pending |
| DATA-09 | Phase 2 | Pending |
| DOC-01 | Phase 4 | Pending |
| DOC-02 | Phase 4 | Pending |
| DOC-03 | Phase 4 | Pending |
| DOC-04 | Phase 4 | Pending |
| DOC-05 | Phase 4 | Pending |
| DOC-06 | Phase 4 | Pending |
| DOC-07 | Phase 4 | Pending |
| DOC-08 | Phase 4 | Pending |
| DOC-09 | Phase 4 | Pending |
| DOC-10 | Phase 4 | Pending |
| DOC-11 | Phase 4 | Pending |
| DOC-12 | Phase 4 | Pending |
| DOC-13 | Phase 4 | Pending |
| SUB-01 | Phase 4 | Pending |
| SUB-02 | Phase 4 | Pending |
| SUB-03 | Phase 4 | Pending |

**Coverage:**

- v1 requirements: 72 total (revised 10 Nov: EVAL-06 dropped; PIPE-07, GW-09, DATA-10 added)
- Mapped to phases: 72 (Phase 1: 14, Phase 2: 18, Phase 3: 16, Phase 4: 24)
- Unmapped: 0

---
*Requirements defined: 2026-11-10*
*Last updated: 2026-11-10 after roadmap creation (traceability filled)*
