# The Relay — write-up

> SKELETON, prepared 13 Nov. Headings are the brief's, in its order. Under each: the evidence we
> have and where it recomputes from. Every `TODO(Tanush)` is his to write: judgements, the
> Vaani feedback, and anything that depends on his grades. Numbers marked `[fill from report]`
> are filled by copying from `uv run python -m relay report` after the final run; never typed.
> Limit: 2 pages of writing (tables and history are extra).

## 1. What I built and why

Evidence:
- Five steps per question (relay/pipeline.py): understand (normalise), retrieve (local tool
  call, own timeout and one retry), decide (branch: strong enough evidence → draft; weak →
  one re-query from the first search's section titles → else refuse with no model call),
  draft with citations (Groq openai/gpt-oss-20b, streamed), check (each paragraph judged
  by meaning with a local NLI model plus a number check; unsupported paragraphs withheld,
  the rest shown as they pass).
- Gateway (relay/gateway.py): its own refilling budgets for RPM, TPM, RPD, TPD, corrected
  from response headers; queue with a 15 s give-up deadline; three levels Normal / Lean /
  Day-gone; exact-match cache of checked answers.
- Local models only for retrieval, re-ranking and checking; every answer is written by Groq.

TODO(Tanush): the one decision that shaped it most, in your words (candidates from the log:
"show only checked text, paragraph by paragraph", or "budget tokens in the gateway, not just
retry 429s").

## 2. The real service and my stand-in

Evidence:
- Table 1 (below) from the probe of 10 Nov (`uv run python table1.py`): RPM 30 (429 body),
  TPM 8,000 and RPD 1,000 (headers), no in-flight cap up to 8, recovery 6.2 s after an RPM
  429 (retry-after 2). Tokens per day 200,000, from the real daily 429 at 03:51:07 UTC on
  13 Nov (eval-final-B, question 18): "Limit 200000, Used 199263, Requested 3516", retry-after
  1,201 s. 2,779 tokens over / 1,201 s = ~8,330 tokens an hour = 200,000 / 24 h: the day is a
  bucket that refills continuously, not a reset at midnight. Groq counted 199,263 in the bucket
  while our ledger shows 331,195 real tokens since 12 Nov 12:00 UTC (docs/QUOTA.md,
  data/runs/daily_window_evidence.md).
- A per-minute 429 our gateway did not prevent: eval-final-B question 1, "Limit 8000, Used
  4396, Requested 3609" (Groq's prompt count ran above our estimate; 0 tokens spent).
- Stand-in calibration (data/standin/calibration.md, `uv run python -m relay calibrate`):
  first event p50 502 ms real probe vs 616 ms stand-in at x50; large prompts 906 vs 1,002 ms.
- Least like the real thing: (a) slowdown under load is ASSUMED (+5% per request above 8 in
  flight; never measured, the probe saw none up to 8); (b) 50x time compression adds ~100 ms
  at p50; (c) slow successes and failures are INJECTED, rates chosen not measured; (d) the
  real TPD refill behaviour is not measured.

TODO(Tanush): one sentence on which difference you trust least.

## 3. Results

Evidence: Tables 2a, 2b, 3 below. Real: eval-* rows (Groq). Stand-in: all load scenarios.
`[fill from report]` medians and p95/p99 with n.

A number we could not have guessed: candidates (pick one, TODO(Tanush)):
- the daily limit refills at ~8,330 tokens an hour: Groq counted 199,263 of 200,000 used
  when our own ledger had sent 331,195 tokens in the same ~16 h;
- retry budget off vs on under injected slow successes `[fill from Table 2b]`;
- the slow request in heading 4: 4.1 s lost to a retried attempt that the provider charged.

Answer quality on 18 questions you wrote: Table 3 (eval-final-A, -B, -C, 13 Nov, all on Groq).
Outcomes before grading (traces.jsonl): A 4 answered / 6 in part / 5 withheld by the check /
3 refused by the model; B 0 / 5 / 9 / 2 plus 2 refused by Groq (TPM 429 on Q1, TPD 429 on
Q18); C 4 / 6 / 5 / 3. Tokens per answer: A 2,326, B 2,981, C 2,668.
TODO(Tanush): grade data/grading/eval-final-{A,B,C}.csv, then
`uv run python -m relay grade data/grading/eval-final-C.csv` (and A, B).

## 4. Where the time goes

Evidence (`uv run python -m relay anatomy retry_budget_on`, request 8feeb1e7…, stand-in,
model time): total 15,195 ms; first thing shown at 15,191 ms ("The papers do not say.").
Before the first token: waiting 7,810 ms (queue 2 + back-off 456 + queue again 7,352),
working 3,245 ms (retrieve 919, the answering attempt 2,327), retrying 4,114 ms (attempt 0
hit the 4 s first-token timeout), handoffs 22 ms. After the first token: 4 ms.
All of the delay came before the first token. How we know: spans written by the gateway at
each state change (data/traces/traces.jsonl), recomputed by relay/anatomy.py.

TODO(Tanush): one line on what you would change because of it.

## 5. When a limit is hit

Evidence: gateway levels (relay/gateway.py). Per-minute: requests queue for the refill up to
the 15 s deadline; below LEAN_BELOW_ANSWERS affordable answers, Lean (2 pieces, 120-token
answer, no re-query); a request whose first token is predicted to miss the 15 s give-up
is refused on arrival with a retry time ("[busy: please ask again in about 15 s]"), and
one whose deadline passes while queued is dropped; neither spends tokens. Per-day: Day-gone, retrieved passages quoted with no generated
answer (see heading 7). Scenario numbers: overload, overload_small_first, limit_halved,
day_exhausted rows of Table 2b.

TODO(Tanush): who is delayed, dropped, weakened, and why, in your words.

## Retrieval: quality versus cost

Evidence: Table 3 (A small fixed, B large fixed, C section-aware + re-rank + MMR).
Earlier runs eval-A/B/C/C2 stay in results.csv as the history. Offline key-figure coverage
with MMR: A 204, B 218, C 217 of 291 (docs/DECISIONS.md).
Near the limit: Lean level, 2 pieces and a 120-token answer.

TODO(Tanush): which setting and why (grades-dependent).

## How this library will mislead a naive retriever

Evidence: docs/TRAPS.md, three traps with real failing examples on setting A: (1) the same
words name different things in different papers; (2) table rows cut away from their headers;
(3) baselines and related work that look like answers.

TODO(Tanush): compress to three lines with one example question each.

## 6. Retries

Evidence: policy in config.py: at most 2 retries, back-off 0.5 s base, retry budget 10% of
the last 100 model calls, never retry past the person's deadline. Worse case: the
retry_budget_on / retry_budget_off pair `[fill from Table 2b: succeeded %, timed out %,
retries per request, tokens per answer]`.

TODO(Tanush): the one case where retrying made it worse, in your words.

## 7. What the person sees

The real Day-gone reply (day_exhausted scenario, traces.jsonl), first lines verbatim:

> Generated answers are paused: today's model budget is used up. They return in about 7
> minutes. Here are the most relevant passages from the papers, quoted as they are, without
> a generated answer:
>
> [H-Net v2, §3.3 Ablation Studies] …

90 of 300 day_exhausted requests got this reply; 111 waited past the deadline in the queue;
15 were refused as busy.

TODO(Tanush): one line on why passages and not a weaker answer.

## 8. What I'm unsure about, what I left out, what I learned

Evidence: least certain assumption candidate: the stand-in's slowdown under load (ASSUMED,
section 2). Deliberately not built (log): request coalescing, a model grader (others listed:
hedged requests, second provider, web UI).

TODO(Tanush): all three parts in your words, including the thing new to you.

## Your feedback on Vaani

TODO(Tanush): entirely yours (visit https://www.vaani.dev/): what stood out, what confused
you, one thing you would change.

## How I worked with the assistant

Evidence: conversation history exported by `uv run python scripts/export_history.py`
(export/conversation/, raw JSONL plus readable Markdown, keys redacted and re-scanned).
Decision log with your calls in your words: docs/DECISIONS.md.

TODO(Tanush): three prompts that mattered most and why; one thing it got wrong that you
caught and how; one decision where you overruled it; what is distinctly yours.

## Results tables

Paste from `uv run python -m relay report` (Tables 1, 2a, 2b, 3). Do not retype numbers.

`[Table 1]`

`[Table 2a]`

`[Table 2b]`

`[Table 3]`
