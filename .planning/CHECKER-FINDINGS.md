# Roadmap checker findings (2026-11-10)

From gsd-roadmapper notes, gsd-plan-checker (roadmap review) and gsd-assumptions-analyzer. All on Opus. **Nothing below has been applied to the plan or roadmap**; these are for Tanush to accept, reject or defer.

## Gaps
1. [gap] results.csv value rules for rows the brief's enums don't fit: answer_grade on ungraded rows (stand-in load, probe, rate-limited, timed out), first_token_ms for zero-token refusals and level-4 replies, retrieval_setting on probe rows. Needs a DATA rule (e.g. empty = not graded / no token) and validator support.
2. [gap] Table 1 is not computable from results.csv as specified. Fix: write probe requests as csv rows (scenario=probe_spaced / probe_burst, source=real); header-only facts come from kept raw probe files, stated.
3. [gap] "Requests in flight at once" and daily "time until it recovers" have no measuring task. Add a small concurrency ramp (1/2/4/8) or mark them not measured / low confidence.
4. [gap] No one-command way to ask a single arbitrary question live (e.g. `relay ask "..."`). Proposed for phase 2.
5. [gap] SUB-01 cites the hiring email, which is not in docs/; DOC-12 has no task to export conversation history (claude.ai thread, Claude Code session logs, GSD subagent logs) with a key scan.
6. [gap] "Tools time out" in the brief: retrieval is local and never times out; no tool timeout or fault injection. Add one or name it as an assumption.
7. [gap] Requirements count was 63 in the header but 70 IDs exist (my miscount; corrected to 70 by the roadmapper, nothing dropped).
8. [gap] No requirement for: gateway budget/retry tests (PLAN 5.1), the ~1,500-line / no-LangChain constraint, calling out "a number we could not have guessed".

## Too big
1. [too big] Phase 4 holds 28 of 70 requirements in ~1.5 days. Suggested: move the report command (DATA-06/07/08) into phase 2 or 3; start the write-up skeleton Wednesday evening; take REAL-05 off the critical path.
2. [too big] 8 scenarios × ≥1,000 requests in real time is hours of wall clock. Suggested: keep the 5 required rows + retry-storm on/off, drop the queue-order comparison, add a time-compression factor to the stand-in.
3. [too big] Retrieval stack (BM25 + embeddings + RRF + cross-encoder + HTML section tree) is heavy for the line budget and pulls in torch. Suggested: BM25 for all settings, cross-encoder only for C.
4. [too big] Gateway (5 ladder levels, wait prediction, coalescing + cache, 2 timeouts, retry budget). Suggested: exact-match cache only; ladder of 3 levels.
5. [too big] EVAL-06 (small-model quality) and REAL-05 (exhaust daily limit) need real quota not in the PLAN 5.3 budget. Cut or make conditional.
6. [too big] Phase 2 depends on Tanush writing 18 questions + key by Wednesday morning and ~36 hand grades. Suggested: 15 questions (the brief's minimum).

## Risky assumptions (the first probe may overturn)
1. [risky assumption] Drafting model is not a reasoning model. gpt-oss / qwen may emit reasoning tokens before the first content token: TTFT inflates, the 250-token cap gets eaten, tokens_out multiplies. Probe each candidate with reasoning controls.
2. [risky assumption] Limits 30 RPM / 8K TPM / 1K RPD / 200K TPD hold for the chosen model. Other models may be ~100K TPD or different TPM; the 5.3 spend plan and ladder would move. Check the limits page + first-response headers per model.
3. [risky assumption] "Per day" is a fixed daily reset. It may be a rolling refill; the 3pm story, level 4 and the exhaust-on-Thursday test change.
4. [risky assumption] Headers expose exactly RPD and TPM; reset value format unknown. Save every header verbatim.
5. [risky assumption] Token accounting: max_tokens may be charged at admission; 429s may or may not consume quota. Probe with max_tokens 50 vs 1,000 pairs and before/after a 429.
6. [risky assumption] The 429 body names the limit hit. With small requests, RPM and TPM trip together — use two bursts (many tiny requests; few large prompts).
7. [risky assumption] Final stream chunk carries x_groq.usage with queue_time etc. If not, token counts need a local tokenizer and heading 4 loses the Groq-side queue split.
8. [risky assumption] TTFT magnitude makes 2,000/5,000/15,000 ms meaningful. If TTFT is ~200 ms, tighten targets; 50 samples give a weak p95.
9. [risky assumption] No concurrency cap and no slowdown under own load; the stand-in's slowdown curve has no real anchor. Fire part of the burst truly concurrently.
10. [risky assumption] Prompt caching helps. Likely minimal; do not claim it without cached_tokens evidence.
11. [risky assumption] arXiv HTML exists at the exact versions and is checksum-stable. 1706.03762v7 HTML may be back-filled; HTML may be regenerated. Store sha256 for both PDF and HTML.
12. [risky assumption] Local models are fast and installable; sentence-transformers pulls torch and a one-time Hugging Face download. Load once at startup; time cold/warm.
13. [risky assumption] llama-3.1-8b-instant still exists in Nov 2026. Confirm with the free models-list call.
14. [risky assumption] One model call per answer (PLAN) vs ~3 calls (RESEARCH budget). Measure calls per answer before Wednesday's spend.
15. [risky assumption] BurstGPT / Azure trace licences unverified (LOAD-02).
