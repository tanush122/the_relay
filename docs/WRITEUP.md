# The Relay — Tanush

## 1. What I built and why

Five steps: understand; retrieve (local tool, 1 s timeout, one retry); decide (weak evidence → one re-query → honest refusal, no model call); draft a cited answer with Groq openai/gpt-oss-20b, streamed; check each paragraph before showing it (local NLI model nli-MiniLM2-L6-H768 plus a number check; unsupported paragraphs are withheld). A gateway keeps its own per-minute and per-day budgets, a queue with a 15 s give-up, and three levels: Normal, Lean, Day-gone. The check favours precision: at threshold 0.4 it keeps 48% of supported paragraphs and passes 4% (1 of 23) of swapped-evidence tests. It is not a guarantee (A Q5, last section).

The one decision that shaped it most: decoupling pipeline steps from remote LLM calls—spending Groq quota only on the single streamed drafting call while running routing, hybrid retrieval, cross-encoder re-ranking, and paragraph-level NLI/numeric verification locally on CPU. At 8,000 tokens/min, a multi-LLM-call agent chain would cap throughput near one question a minute and multiply tail latency; keeping four of the five steps local preserves p50 latency around 1.5–2.2 s and withholds unverified claims before they reach the user.

## 2. The real service and my stand-in

Probe (99 calls, 10 Nov) and real runs, Table 1: 30 requests/min (429 body), 8,000 tokens/min and 1,000 requests/day (headers), no in-flight cap up to 8, recovery 6.2 s after a per-minute 429. The daily limit was reached for real (13 Nov 03:51 UTC): "Limit 200000, Used 199263, Requested 3516", retry-after 1,201 s, so 2,779 tokens refill in 1,201 s, ~8,330 an hour = 200,000/24 h: the day refills continuously, not at midnight. Once Groq refused a call our gateway admitted ("Used 4396, Requested 3609"): its prompt count beat our estimate. The stand-in streams, enforces the same limits, fails, stalls and slows under load; first-event times are resampled from the probe and the 54 real replies (p50 502 vs 616 ms; ~2,000-token prompts 906 vs 1,002 ms). Least real: slowdown under load is assumed (+5% per request above 8 in flight), failures and slow successes are injected, 50x time compression adds ~100 ms at p50.

## 3. Results

Real, final system, 18 questions per setting: first text p50 / p95 1,518 / 2,537 ms (A), 1,635 / 4,515 (B), 2,187 / 4,068 (C); no time-outs. Stand-in, 1,000 requests each: steady 2,523 / 5,403 / 9,643 ms (p50/p95/p99), 98.1% succeeded; burst 93.7%, 6.3% rate-limited; overload (8/min, ~3x what the budget pays for) 54.0% succeeded, 45.0% turned away at once; limit halved 86.6%, p99 14,011 ms. Five scenarios ran before MMR retrieval and are labelled pre-MMR. Quality (Table 3): correct and cited 27.8% (A), 22.2% (B), 38.9% (C); wrong 27.8 / 11.1 / 16.7%; wrongly refused 27.8 / 50.0 / 27.8%; all 3 unanswerable questions refused in every setting; tokens per answer 2,326 / 3,335 / 2,668. B's Q1 and Q18 were refused by Groq (429s) and re-asked once budget allowed. Unguessable number: Groq counted 199,263 daily tokens used while we had sent 331,195 in ~16 h. Tables 1–3: RESULTS_TABLES.pdf.

## 4. Where the time goes

Request 8feeb1e7 (stand-in, pre-MMR, relay anatomy), 15,195 ms in all. Before the first token: waiting 7,810 ms (queue, 456 ms back-off, 7,352 ms queued again), working 3,245 ms (retrieval 919, answering attempt 2,327), retrying 4,114 ms (first attempt hit the 4 s first-token timeout). After it: 4 ms. Known from the spans the gateway writes at every state change (traces.jsonl).

## 5. When a limit is hit

Per minute: wait in the queue for refill; if the first token cannot come before the 15 s give-up, refuse at once with a retry time, spending nothing; with under 1.5 answers affordable, answer Lean (2 pieces, 120 tokens). Per day: Day-gone, no model call. Overload: 45.0% refused on arrival, 1.0% gave up queued. Who is delayed, dropped, or weakened, and why: callers whose predicted queue wait plus generation fits inside the 15 s patience window are delayed in the queue until the minute bucket refills; callers whose predicted wait would exceed 15 s (or whose deadline expires in queue) are dropped fast with an estimated retry time so we never spend tokens on an abandoned request; callers arriving when under 1.5 answers remain in the minute budget get a weakened Lean reply (2 pieces, 120-token output cap, no re-query).

## Retrieval: quality versus cost

A: fixed 180-token pieces, 8 fetched. B: fixed 600, 4 fetched. C: section-aware up to 600, 4 of 20 after re-rank, diverse (MMR). Why I chose C: C delivered the highest accuracy (38.9% correct and cited, 16.7% wrong) at a middle token cost (2,668 tokens/answer vs. 3,335 for B) because keeping sections and tables whole while combining cross-encoder re-ranking with MMR diversity (λ = 0.5) covered every sub-part of multi-part questions. A's 180-token windows split equations from their surrounding text (27.8% wrong), while B's 600-token windows without re-ranking burned the most quota, triggered two real 429s, and suffered a 50.0% false-refusal rate. Near the limit, Lean fetches 2 pieces.

## How this library will mislead a naive retriever

(1) Same words, different things: "encoder and decoder layers" pulls Attention's N = 6 next to H-Net's 4-layer Mamba-2 outer encoder/decoder ablations and Moshi's 8-layer Mimi codec bottleneck. (2) Table rows cut from their headers: fixed windows separate H-Net Table 3's 42.8 Robustness Score row from its caption and column names. (3) Baselines and dominant-term crowding: in final run B Q13 ("Compare the tokenization approaches in all three papers"), retrieval returned 4 pieces all from H-Net (hnet-B-001, -039, -034, -038) because H-Net mentions tokenization constantly, starving Attention and Moshi (docs/TRAPS.md).

## 6. Retries

At most 2, 0.5 s base back-off, budget 10% of the last 100 calls, never past the person's deadline. With 30% slow successes injected, budget on vs off: 75.5 vs 74.9% succeeded, 0.05 vs 0.03 retries per request (pre-MMR): the deadline rule already blocks most retries. Worse case: heading 4's retry cost 4.1 s, a second queue, a charged prompt, and the person got "The papers do not say" at 15.2 s, past the give-up.

## 7. What the person sees

> Generated answers are paused: today's model budget is used up. They return in about 7 minutes. Here are the most relevant passages from the papers, quoted as they are, without a generated answer: [H-Net v2, §3.3 Ablation Studies] …

(real text, day_exhausted run; 90 of 300 got it). Why passages: returning the top 2 retrieved passages verbatim with their exact [Paper, §Section] headers costs zero model tokens, cannot hallucinate, and gives a waiting engineer the primary equation or table immediately while stating when continuous token refill (~8,330 tokens/h) will restore generated answers.

## 8. What I'm unsure about, what I left out, what I learned

Least certain: the stand-in's slowdown under load; if real slowdown starts earlier, burst and overload tails are optimistic. Not built: request coalescing, a model grader. Unfixed in the final runs: our local NLI verifier still over-withholds dense multi-part answers when LaTeX notation differs from parsed HTML (withholding Q4 on Moshi's K = 17 streams across all three settings); paragraphs verified against a citation in the next paragraph were displayed without that citation attached in A Q6, C Q6, and B Q2 (an offline fix is verified in data/runs/citation_fix, but left unapplied so graded outputs stay untouched); and the 450-token output cap truncates three-paper comparisons mid-sentence. One thing new to me: learning from our real 429 headers and the Limit 200000, Used 199263, Requested 3516 (retry-after: 1201 s) error that Groq's daily and per-minute quotas are continuous leaky buckets (~8,330 tokens/h refill) rather than midnight resets, and that gpt-oss-20b streams hidden reasoning tokens before its first visible word—which consumed our entire 16-token allowance on 33 of 50 probe requests before any visible text appeared.

## Your feedback on Vaani

Visiting vaani.dev (https://www.vaani.dev/), what stood out immediately is the live interactive voice demo on the landing page paired with concrete enterprise relationship-manager call handoff metrics (Calls placed, Automated talk time, Qualified RM callbacks), which grounds the product in real full-duplex conversational utility rather than generic voice synthesis. What confused me slightly is how the enterprise banking/RM outbound workflow on the main site connects to the developer platform positioning (Voice AI Harness), as the boundary between self-serve API primitives and managed deployments is not immediately obvious. One thing I would change is adding a technical latency and turn-taking benchmark card on the developer page—reporting p50/p95 voice-to-voice latency, barge-in interruption response times, and codec frame rates—so systems engineers evaluating the platform can see its real-time voice performance at a glance.

## How I worked with the assistant

History: conversation_history.md (raw: conversation_history_raw.zip); my calls: docs/DECISIONS.md.

**Three prompts that mattered most:** (1) Token-thrift probe redesign (10 Nov 05:32 UTC): instructing the assistant that Groq free-tier token discipline is itself graded, which cut the probe from a 17,179-token plan (with a 10,124-token TPM burst) down to a 9,150-token lean probe and preserved quota for the 54 evaluation runs. (2) Meaning-based paragraph verification (12 Nov 12:27 UTC): rejecting the assistant's rigid sentence-by-sentence regex checker ("analyse the wordings or the results based on their meaning and not just word matching. Do not hardcode anything"), which led to per-paragraph NLI checking (nli-MiniLM2-L6-H768), numeric format equivalence (0.766 = 76.6%, 1.1 kbps = 1,100 bps), and partial-answer prompting that cut C's whole-question model refusals from 8 to 4. (3) Diagnosing false refusals on multi-part queries (12 Nov 13:49 UTC): questioning why Q1 failed ("can we resolve this issue because this makes our model or infra look bad"), which revealed that top-4 similarity pulled four near-duplicate chunks on attention scaling and led to adding MMR diversity (λ = 0.5), raising C's key-figure recall from 201/291 to 217/291 (and Q1 to 9/9).

**One thing it got wrong that I caught:** in eval-final-A Q5 (eb1e64e8), Groq cited hnet-A-036 (which holds the outer sum L = L_AR + α Σ_s L_ratio^s with α = 0.03, but omits Eq. 10) and hallucinated a squared-error formula L_ratio^s = (N^(s+1)/N^s)(desired − actual)² instead of H-Net's MoE-style load-balancing loss N/(N−1) · ((N−1)FG + (1−F)(1−G)). The local checker passed it because no numbers conflicted; I caught it while grading against my ground-truth answer key from H-Net §2.2.3.

**One decision where I overruled it:** the assistant initially assumed llama-3.1-8b-instant was available on our account, spawned subagents that burned usage limits, and enforced a brittle every-sentence citation rule that rejected valid multi-line equations and bullet lists; I overruled subagent spawning ("dont deploy any subagent, work on yourself"), overruled sentence-stop checking in favor of paragraph-skip NLI verification, and directed timed retries for B's Q1 and Q18 (eval-final-B-retry) calculated from the continuous TPD refill rate.

**What is distinctly mine:** the scope trim from a 5-rung ladder to 3 levels (Normal, Lean, Day-gone), the token-budgeting and probe abort rules, the 18 multi-hop/trap/refusal evaluation questions and ground-truth key, the manual grading of all 54 responses (catching the Q5 formula hallucination, the B Q13 single-paper crowding trap, and the Q6 citation-stripping bug), and the Vaani critique.

## Appendix: results tables (computed from results.csv)

Generated by `uv run python scripts/fill_tables.py` from data/results.csv (8430 rows) and run_20261110T133218Z. Do not edit by hand.

### Table 1: Limits found in the real service

| Limit | Value found | How found | Confidence |
| --- | --- | --- | --- |
| Requests per minute | 30 (openai/gpt-oss-20b) | 429 body during rpm_burst [run run_20261110T133218Z, host api.groq.com] | high |
| Tokens per minute | openai/gpt-oss-120b=8000; openai/gpt-oss-20b=8000; qwen/qwen3.8-27b=8000 | x-ratelimit-limit-tokens header on 98 responses (docs: per-minute) [run run_20261110T133218Z, host api.groq.com] | medium |
| Requests per day | openai/gpt-oss-120b=1000; openai/gpt-oss-20b=1000; qwen/qwen3.8-27b=1000 | x-ratelimit-limit-requests header on 99 responses (docs: per-day) [run run_20261110T133218Z, host api.groq.com] | medium |
| Tokens per day | 200000 (openai/gpt-oss-20b) | 429 body during real run eval-final-B at 2026-11-13T03:51:07Z | high |
| Requests in flight at once | >= 8 (no cap observed up to 8) | concurrency ramp; 1: total median 1176 ms, statuses 200, 1 of 1 with visible text; 2: total median 595 ms, statuses 200,200, 0 of 2 with visible text; 4: total median 508 ms, statuses 200,200,200,200, 0 of 4 with visible text; 8: total median 560 ms, statuses 200,200,200,200,200,200,200,200, 1 of 8 with visible text [run run_20261110T133218Z, host api.groq.com] | low |
| What it returns when a limit is hit | HTTP 429 (RPM), retry-after: 2, error type: requests; "Rate limit reached for model `openai/gpt-oss-20b` in organization `org_[REDACTED]` service tier `on_demand` on requests " | first 429 response, stage rpm_burst [run run_20261110T133218Z, host api.groq.com] | high |
| Time until it recovers | RPM: 6.187 s after a 429 naming RPM (its retry-after: 2); TPM: not measured; TPD: retry-after 1201 s for 2779 tokens over the limit, i.e. a continuous refill of ~8,330 tokens/h (limit/24 h = 8,333), not a reset at a fixed time (real run eval-final-B at 2026-11-13T03:51:07Z) | from the arrival of a burst's first 429 to the sending of the first re-admitted tiny request; polled every 5.0 s, so the true value is up to one poll earlier [run run_20261110T133218Z, host api.groq.com] | medium |

### Table 2a: Latency

| Scenario | Real or stand-in | Requests sent | Duration (s) | Offered rate (per min) | First token p50 / p95 / p99 (ms) | Total time p50 / p95 / p99 (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| eval-final-A | real | 18 | 280.2 | 3.9 | 1518 / 2537 / 2537 (n=18) | 1518 / 2537 / 2537 (n=18) |
| eval-final-B | real | 18 | 487.8 | 2.2 | 1635 / 4515 / 4515 (n=16) | 1878 / 4515 / 4515 (n=18) |
| eval-final-B-retry | real | 2 | 1442.1 | 0.1 | 1245 / 2601 / 2601 (n=2) | 1245 / 3352 / 3352 (n=2) |
| eval-final-C | real | 18 | 350.0 | 3.1 | 2187 / 4068 / 4068 (n=18) | 2260 / 4069 / 4069 (n=18) |
| steady | stand-in | 1000 | 29487.9 | 2.0 | 2523 / 5403 / 9643 (n=981) | 2597 / 5411 / 9665 (n=1000) |
| burst | stand-in | 1000 | 36462.2 | 1.6 | 2598 / 4830 / 8197 (n=937) | 2599 / 4786 / 8052 (n=1000) |
| burst_cached | stand-in | 1000 | 36460.1 | 1.6 | 1956 / 4356 / 6841 (n=960) | 1916 / 4484 / 6777 (n=1000) |
| overload (pre-MMR) | stand-in | 1000 | 7373.1 | 8.1 | 6722 / 13340 / 14917 (n=540) | 2032 / 12852 / 15075 (n=1000) |
| overload_small_first (pre-MMR) | stand-in | 1000 | 7373.2 | 8.1 | 6114 / 13787 / 15365 (n=542) | 1911 / 13171 / 15229 (n=1000) |
| retry_budget_on (pre-MMR) | stand-in | 1000 | 19660.1 | 3.1 | 3299 / 11970 / 14794 (n=755) | 3345 / 12736 / 15142 (n=1000) |
| retry_budget_off (pre-MMR) | stand-in | 1000 | 19659.9 | 3.1 | 3160 / 11920 / 14868 (n=749) | 3208 / 12874 / 15142 (n=1000) |
| limit_halved | stand-in | 1000 | 29487.9 | 2.0 | 2661 / 9075 / 14011 (n=867) | 2761 / 11511 / 14225 (n=1000) |
| day_exhausted (pre-MMR) | stand-in | 300 | 9231.4 | 2.0 | 2529 / 5121 / 14190 (n=84) | 2685 / 14242 / 14286 (n=300) |

### Table 2b: Outcomes

| Scenario | Succeeded % | Rate-limited % | Timed out or given up % | Retries per request | Peak queue length | Tokens per answer | Cost per 1,000 answers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| eval-final-A | 100.0 | 0.0 | 0.0 | 0.00 | 1 | 2326 | $0.26 |
| eval-final-B | 88.9 | 11.1 | 0.0 | 0.00 | 1 | 2981 | $0.31 |
| eval-final-B-retry | 100.0 | 0.0 | 0.0 | 0.00 | 1 | 3190 | $0.29 |
| eval-final-C | 100.0 | 0.0 | 0.0 | 0.00 | 1 | 2668 | $0.28 |
| steady | 98.1 | 1.9 | 0.0 | 0.00 | 3 | 2243 | $0.23 |
| burst | 93.7 | 6.3 | 0.0 | 0.00 | 4 | 2216 | $0.23 |
| burst_cached | 96.0 | 3.9 | 0.1 | 0.00 | 4 | 1388 | $0.13 |
| overload (pre-MMR) | 54.0 | 45.0 | 1.0 | 0.00 | 3 | 871 | $0.09 |
| overload_small_first (pre-MMR) | 54.2 | 45.2 | 0.6 | 0.00 | 3 | 881 | $0.09 |
| retry_budget_on (pre-MMR) | 75.5 | 22.3 | 2.2 | 0.05 | 3 | 1541 | $0.15 |
| retry_budget_off (pre-MMR) | 74.9 | 23.5 | 1.6 | 0.03 | 3 | 1516 | $0.15 |
| limit_halved | 86.6 | 11.8 | 1.6 | 0.04 | 3 | 1877 | $0.19 |
| day_exhausted (pre-MMR) | 28.0 | 35.0 | 37.0 | 0.00 | 3 | 658 | $0.06 |

### Table 3: Retrieval settings

| Setting (piece size, pieces fetched, re-rank yes or no) | Questions asked | Correct and cited % | Wrong % | Correctly refused % | Tokens per answer | First token p50 / p95 (ms) | Total time p50 / p95 (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A (fixed 180 tokens, 8 pieces, re-rank no) | 18 | 27.8 | 27.8 | 16.7 | 2326 | 1518 / 2537 (n=18) | 1518 / 2537 (n=18) |
| B (fixed 600 tokens, 4 pieces, re-rank no) | 18 | 22.2 | 11.1 | 16.7 | 3335 | 1635 / 4515 (n=18) | 1887 / 4515 (n=18) |
| C (section-aware, up to 600 tokens, 4 of 20 pieces, re-rank yes) | 18 | 38.9 | 16.7 | 16.7 | 2668 | 2187 / 4068 (n=18) | 2260 / 4069 (n=18) |
