# The Relay — Tanush

> DRAFT 13 Nov. Numbers recompute from data/results.csv, the probe and traces (README.md).
> **TODO(Tanush)**: only Tanush can write it. *(reword)*: his notes, to put in his words.

## 1. What I built and why

Five steps: understand; retrieve (local tool, 1 s timeout, one retry); decide (weak evidence
→ one re-query → honest refusal, no model call); draft a cited answer with Groq
openai/gpt-oss-20b, streamed; check each paragraph before showing it (local NLI model
nli-MiniLM2-L6-H768 plus a number check; unsupported paragraphs are withheld). A gateway keeps
its own per-minute and per-day budgets, a queue with a 15 s give-up, and three levels: Normal,
Lean, Day-gone. The check favours precision: at threshold 0.4 it keeps 48% of supported
paragraphs and passes 4% (1 of 23) of swapped-evidence tests. It is not a guarantee (A Q5,
last section). **TODO(Tanush):** the one decision that shaped it most.

## 2. The real service and my stand-in

Probe (99 calls, 10 Nov) and real runs, Table 1: 30 requests/min (429 body), 8,000 tokens/min
and 1,000 requests/day (headers), no in-flight cap up to 8, recovery 6.2 s after a per-minute
429. The daily limit was reached for real (13 Nov 03:51 UTC): "Limit 200000, Used 199263,
Requested 3516", retry-after 1,201 s, so 2,779 tokens refill in 1,201 s, ~8,330 an hour =
200,000/24 h: the day refills continuously, not at midnight. Once Groq refused a call our
gateway admitted ("Used 4396, Requested 3609"): its prompt count beat our estimate. The stand-in
streams, enforces the same limits, fails, stalls and slows under load; first-event times are
resampled from the probe and the 54 real replies (p50 502 vs 616 ms; ~2,000-token prompts 906
vs 1,002 ms). Least real: slowdown under load is assumed (+5% per request above 8 in flight),
failures and slow successes are injected, 50x time compression adds ~100 ms at p50.

## 3. Results

Real, final system, 18 questions per setting: first text p50 / p95 1,518 / 2,537 ms (A),
1,635 / 4,515 (B), 2,187 / 4,068 (C); no time-outs. Stand-in, 1,000 requests each: steady
2,523 / 5,403 / 9,643 ms (p50/p95/p99), 98.1% succeeded; burst 93.7%, 6.3% rate-limited;
overload (8/min, ~3x what the budget pays for) 54.0% succeeded, 45.0% turned away at once;
limit halved 86.6%, p99 14,011 ms. Five scenarios ran before MMR retrieval and are labelled
pre-MMR. Quality (Tanush's grades, Table 3): correct and cited 27.8% (A), 22.2% (B), 38.9% (C);
wrong 27.8 / 11.1 / 16.7%; wrongly refused 27.8 / 50.0 / 27.8%; all 3 unanswerable questions
refused in every setting; tokens per answer 2,326 / 3,335 / 2,668. B's Q1 and Q18 were refused
by Groq (429s) and re-asked once budget allowed. Unguessable number: Groq counted 199,263 daily
tokens used while we had sent 331,195 in ~16 h.

## 4. Where the time goes

Request 8feeb1e7 (stand-in, pre-MMR, `relay anatomy`), 15,195 ms in all. Before the first
token: waiting 7,810 ms (queue, 456 ms back-off, 7,352 ms queued again), working 3,245 ms
(retrieval 919, answering attempt 2,327), retrying 4,114 ms (first attempt hit the 4 s
first-token timeout). After it: 4 ms. Known from the spans the gateway writes at every state
change (traces.jsonl).

## 5. When a limit is hit

Per minute: wait in the queue for refill; if the first token cannot come before the 15 s
give-up, refuse at once with a retry time, spending nothing; with under 1.5 answers affordable,
answer Lean (2 pieces, 120 tokens). Per day: Day-gone, no model call. Overload: 45.0% refused
on arrival, 1.0% gave up queued. **TODO(Tanush):** who is delayed, dropped, weakened, and why.

## Retrieval: quality versus cost

A: fixed 180-token pieces, 8 fetched. B: fixed 600, 4 fetched. C: section-aware up to 600, 4 of
20 after re-rank, diverse (MMR). C is best (38.9% correct and cited) at mid cost; B costs most
and refuses most. Near the limit, Lean fetches 2. **TODO(Tanush, reword):** why C.

## How this library will mislead a naive retriever

(1) Same words, different things: "encoder and decoder layers" pulls Attention's N = 6 next to
H-Net's ablations. (2) Table rows cut from their headers. (3) Baselines and related work that
look like answers. Final-run case: B Q13 "compare tokenization in all three papers" retrieved 4
pieces, all H-Net (docs/TRAPS.md).

## 6. Retries

At most 2, 0.5 s base back-off, budget 10% of the last 100 calls, never past the person's
deadline. With 30% slow successes injected, budget on vs off: 75.5 vs 74.9% succeeded, 0.05 vs
0.03 retries per request (pre-MMR): the deadline rule already blocks most retries. Worse case:
heading 4's retry cost 4.1 s, a second queue, a charged prompt, and the person got "The papers
do not say" at 15.2 s, past the give-up.

## 7. What the person sees

> Generated answers are paused: today's model budget is used up. They return in about 7
> minutes. Here are the most relevant passages from the papers, quoted as they are, without a
> generated answer: [H-Net v2, §3.3 Ablation Studies] …

(real text, day_exhausted run; 90 of 300 got it). **TODO(Tanush):** why passages.

## 8. What I'm unsure about, what I left out, what I learned

Least certain: the stand-in's slowdown under load; if real slowdown starts earlier, burst and
overload tails are optimistic. Not built: request coalescing, a model grader. Unfixed
*(reword)*: the check withholds correct dense answers (Q4, Moshi K = 17, in all settings); a
paragraph checked against a later citation was shown without it (A Q6, C Q6, B Q2; offline fix
ready, not applied, data/runs/citation_fix); cross-paper answers cut at 450 tokens.
**TODO(Tanush):** one thing new to you.

## Your feedback on Vaani

**TODO(Tanush).**

## How I worked with the assistant

History: conversation_history/; my calls: docs/DECISIONS.md. Caught in grading: A Q5 cited
hnet-A-036 but gave a squared-error ratio loss, not the paper's Eq. 10, and the check passed
it. **TODO(Tanush):** three prompts, one thing it got wrong, one overrule, what is yours.

## Results tables

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

### Side table: earlier evaluation runs (not the final system)

| Earlier run | Setting | Questions | correct | wrong | refused_correctly | refused_wrongly | Ungraded | Tokens per answer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| eval-C | C | 18 | 0 | 0 | 0 | 0 | 18 | 2427 |
| eval-A | A | 18 | 0 | 0 | 0 | 0 | 18 | 2079 |
| eval-B | B | 18 | 0 | 0 | 0 | 0 | 18 | 3114 |
| eval-C2 | C | 18 | 0 | 0 | 0 | 0 | 18 | 2545 |
| eval-final-interrupted | C | 2 | 0 | 0 | 0 | 0 | 2 | 2344 |
