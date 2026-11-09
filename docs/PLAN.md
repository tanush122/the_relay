# The Relay: build plan

Plan of record: the Claude Doc above (https://claude.ai/artifact/PhKNHthH7xc1J3Wc2KDNxQ). Status: approved with the revisions below (10 Nov).

> **Revisions applied 10 Nov on Tanush's instruction (pragmatic real-world option). These override the text further down where they conflict:**
> 1. Degradation ladder (3.4) has three levels: Normal, Lean (absorbs Minimal: fewer pieces, shorter output, no rewrite), Day-gone. Waiting for the minute to refill is queue behaviour, not a level. No smaller-model rung, so the smaller-model quality eval is dropped.
> 2. Cache (3.7): exact-match answer cache only. Coalescing of concurrent identical questions is deliberately not built; its cost is measured from the burst run.
> 3. Scenarios (4.2): six — real steady; stand-in steady, burst, sustained overload (paired retry-budget off/on variant for the retry-storm case), per-minute limit halved, daily budget exhausted. Queue-order comparison dropped.
> 4. Report script (4.5) is built in phase 2 next to the csv writer; write-up drafting starts Wednesday evening.
> 5. New: tool-timeout injection on the retrieve step (own timeout; retry once, else refuse honestly), phase 3.
> 6. New: `uv run relay ask "question"` — one command to run the full pipeline on a single question, phase 2.
> 7. New: empty-field rule for results.csv (a field that does not apply is left empty, never guessed), enforced by the validator, phase 2.
> 8. Evaluation keeps 18 questions.

Nov 10, 2026 · @Tanush

The plan is a small, readable Python system whose every design choice traces to a measurement, delivered in four phases by Nov 13, 2026. "Production level" here means honest numbers, predictable behaviour at every limit, and code you can change live, not a large codebase.

## 1. High-level architecture

One process, six small modules, and one switch that points the model client at either Groq or the stand-in. Everything else is identical between real and simulated runs, which is what makes the stand-in results believable.

&#91;embedded content: system architecture · 8 parts\]

Requests enter through the gateway, the pipeline's model calls draw on the gateway's budget, and one setting decides whether those calls reach Groq or the stand-in.

| Module | Job | Spends Groq tokens? |
| --- | --- | --- |
| `library/` | Fetch the three papers at fixed versions, split into pieces with paper, section and page attached, build the search indexes | No |
| `pipeline/` | The five steps of one request: understand, retrieve, decide, draft, check | Yes, in at most three steps |
| `gateway/` | The only door to the model: token budget, queue, deadlines, retries, timeouts, degradation level | No |
| `standin/` | A fake model server with the same API as Groq, driven by measured data | No |
| `loadgen/` | Replays arrival traces on schedule and records every request | No |
| `report/` | Turns results.csv into the four tables. No hand-typed numbers | No |

**The request path.**

1. **Understand** (local rules first, model only if needed): is the question in scope, which paper does it name, does it need rewriting?
2. **Retrieve** (the tool call, local): find candidate pieces, re-rank, keep the best few.
3. **Decide** (the branch and loop, local): if the best score is strong, go on. If it is weak, rewrite the query and retrieve once more. If it is still weak, refuse now without spending a token.
4. **Draft** (model, streamed): answer only from the pieces, citing piece ids. This is where the user sees the first token.
5. **Check** (code first, model only if needed): every cited id was retrieved, every number in the answer appears in a cited piece. A failed check becomes a refusal, never a guess.

**The decision that shapes everything:** the gateway is the single place that knows the budget. No step calls the model directly. Because tokens are the scarce resource (about 8,000 a minute), three of the five steps are designed to run without the model in the normal case, so a typical answer costs one model call.

## 2. Machine learning parts

Six pieces of ML work, each ending in a number for the write-up.

**2.1 Ingestion.** Fetch the arXiv HTML rendering of each exact version (v7, v1, v2), keep the PDF as a fallback, store a checksum of each file. Parse into a tree of sections so every piece knows its paper, version, section number and title. Tables and their captions are kept whole and stored as text rows.

**2.2 Splitting, three settings for Table 3.**

| Setting | Piece size | Pieces sent to the model | Re-rank | What it tests |
| --- | --- | --- | --- | --- |
| A. Small fixed | about 180 tokens, 30 overlap | 8 | No | The naive baseline, cheap per piece |
| B. Large fixed | about 600 tokens, 80 overlap | 4 | No | More context per piece, more tokens |
| C. Section-aware | Split on headings, tables whole, each piece prefixed with paper and section path | 4, chosen from 20 | Yes, local cross-encoder | The design I expect to win |

The sizes are starting points. The probe and the first runs may move them.

**2.3 Retrieval.** BM25 for exact terms plus a small local embedding model for paraphrase, merged by reciprocal rank fusion. All local, zero Groq tokens. If a question names a paper, search is filtered to that paper, which removes the "same word, different paper" failure cheaply.

**2.4 Generation.** One system prompt, kept byte-identical across requests so Groq's prompt caching can apply. The model must answer only from numbered pieces and cite ids. Output is capped (about 250 tokens) because output length is both latency and budget. Citations are mapped back to "paper, version, section" in code.

**2.5 Refusal and checking.** Three gates: a retrieval-score threshold before any model call, permission to say "the papers do not say" in the prompt, and a code check after drafting. The threshold is set from your questions, and the write-up reports the trade it makes between wrong answers and wrong refusals.

**2.6 Evaluation.** You write at least 18 questions with an answer key: about 10 answerable from prose, 3 whose answer lives in a table, 2 that span or confuse two papers, and 3 the papers do not answer. Each is graded by hand as correct, wrong, refused\_correctly or refused\_wrongly. Runs are 18 questions x 3 settings = 54 real answers, which fits the token budget only if spread over two days.

**Model choice.** One model for drafting, chosen after the probe from what your limits page actually offers. A second, smaller model is used only as a rung on the degradation ladder, and its quality is measured on the same questions so "weaker answer" is a number.

## 3. System design for speed and reliability

The gateway makes four decisions for every request, in this order: can we afford it, is there time, how cheaply should we answer, and what do we do when the call misbehaves.

**3.1 Token budget.** The gateway keeps its own counters for requests and tokens, per minute and per day, per model. They are corrected after every response from Groq's headers. Before a call it estimates the cost (prompt tokens counted locally plus the output cap) and reserves it. The point is to almost never see a 429.

**3.2 Admission and deadlines.** Each request arrives with a deadline. Proposed numbers, to be revised after the probe: first token within 2,000 ms at the median and 5,000 ms at p95, and the person gives up at 15,000 ms with no token. On arrival the gateway predicts the wait from queue length and budget refill rate. If the prediction exceeds the deadline, it refuses at once with an honest message and a suggested retry time.

**3.3 Queue.** A bounded queue. Requests whose deadline has passed are dropped before any tokens are spent on them. The order (oldest first versus newest first) is an experiment, because under overload it changes how many answers reach someone still waiting.

**3.4 Degradation ladder.** The gateway picks a level from how much budget remains:

| Level | Trigger (proposed) | What changes | What never changes |
| --- | --- | --- | --- |
| 0. Normal | Over 50% of the minute's tokens left | Setting C, 4 pieces, 250 output tokens | Citations, check, refusal rule |
| 1. Lean | 20 to 50% left | 3 pieces, 150 output tokens, no query rewrite | Same |
| 2. Minimal | Under 20% left | 2 pieces, smaller model if it has its own budget | Same |
| 3. Queue only | Minute budget empty | Wait for refill if the deadline allows, otherwise refuse | Same |
| 4. Day gone | Daily budget empty | Cached answers, or the most relevant cited passages shown as they are with no model call, plus a clear message saying when generated answers return | Same |

Level 4 is the answer to "at 3pm the daily budget is gone". A small reserve of the daily budget is held back so the last hour degrades instead of falling off a cliff.

**3.5 Retries.** Retry only 429 (after the `retry-after` value), 500, 502, 503 and first-token timeouts. Exponential backoff with full jitter, at most 2 retries, never past the deadline, and a retry budget of 10% of recent calls. No retry once tokens have been shown to the user. The "retry made it worse" case is produced on purpose: the same overload run with the retry budget switched off.

**3.6 Timeouts.** Two clocks instead of one: a first-token timeout and a stall timeout between chunks. Both are set from the probe's measured percentiles, not guessed.

**3.7 Cache and coalescing.** Identical questions that arrive together share one model call, and finished answers are cached. Bursts after an incident are mostly the same question, so this is free capacity.

**3.8 The stand-in.** Same API as Groq, including streaming, the rate-limit headers and 429 with `retry-after`. Latency is resampled from the real probe's recorded values. It can inject failures and mid-stream stalls, and it slows as in-flight requests rise. Its limits are settings, which is how the "per-minute limit halved" and "daily budget exhausted" scenarios are run.

**3.9 Tracing.** Every request writes a span log: arrival, queue wait, each step's start and end, each attempt, first token, last token. The "where the time goes" heading and the peak queue length both come from this log.

**Scale, honestly.** One process with asyncio is the right size here. The write-up will say what changes at real scale (shared budget counters across workers, a real queue, per-tenant fairness) as things deliberately not built.

## 4. Experiments and evidence

Reviewers recompute the tables from results.csv before reading anything else, so the experiment plan is built backwards from that file.

**4.1 The real probe (fills Table 1).** About 50 small streamed requests spaced out to record time to first token, total time and every header. Then one deliberate burst to hit the per-minute limit and record the 429 body, `retry-after` and how long recovery takes. Requests per minute and tokens per day are not in the headers, so they come from the limits page and the 429 message. The daily limit is confirmed by exhausting the cheapest model once, late on Thursday. Every raw response is kept.

**4.2 Scenarios (fill Tables 2a and 2b).**

| Scenario | Source | Shape | What it should show |
| --- | --- | --- | --- |
| Steady | Real Groq, small | Below the per-minute budget | Baseline latency with no pressure, and that real and stand-in agree |
| Steady | Stand-in | Same shape, more requests | The stand-in reproduces the real numbers |
| Burst | Stand-in | Slice of a real traffic trace with a spike | Queue growth, the ladder engaging, recovery time |
| Sustained overload | Stand-in | 2 to 3 times capacity for several minutes | Fast refusals instead of universal timeouts |
| Per-minute limit halved | Stand-in | Steady load, limit cut mid-run | Detection from headers and adaptation without a 429 storm |
| Daily budget exhausted | Stand-in | Budget runs out mid-run | Level 4 behaviour and what the person sees |
| Retry storm (comparison) | Stand-in | Overload with retry budget off, then on | The case where retrying made things worse |
| Queue order (comparison) | Stand-in | Overload, oldest-first versus newest-first | A candidate "number you could not have guessed" |

Arrival times come from a public trace of real LLM traffic, compressed in time. If neither public dataset can be confirmed and licensed for this use, the fallback is to say so and use a stated arrival process.

**4.3 Rules for results.csv.** Three places where the brief's format forces a decision. Each needs your sign-off because each will be questioned.

- *Status has four values only* (ok, rate\_limited, timeout, error). Proposed mapping: refused by our own admission control or by a 429 we could not absorb is `rate_limited`, the person giving up or a deadline passing is `timeout`, everything else is `error`. An honest refusal because the papers do not say is `ok` with grade `refused_correctly`.
- *Peak queue length must be computable from the file.* Proposed: `start_time` is the arrival time, not the time the model call began, so the number of requests in the system at any moment can be rebuilt from `start_time` and `total_ms`. The write-up states this definition.
- *Cost per 1,000 answers* on a free tier is zero, which says nothing. Proposed: report it at Groq's published list price for the model used and state the price.

The file keeps exactly the twelve required columns. Richer detail goes in a second file, `traces.jsonl`.

**4.4 Percentiles.** Each stand-in scenario sends at least 1,000 requests so p99 means something. Real runs will be small, so their p99 is reported with the request count beside it and labelled as weak.

**4.5 One command.** `report/` reads results.csv and prints all four tables in the write-up's format. The tables in the write-up are pasted from that output.

## 5. Product manager additions

Things outside the code that decide whether this submission wins.

**5.1 What "production level" means for this reviewer.** They said they are not scoring time spent and that you need not cover every technique. The bar is: tables that recompute exactly, behaviour at each limit that is designed and explained, and a candidate who can change the system live. A large codebase works against that. Target under about 1,500 lines of Python, few dependencies, no framework doing the thinking (no LangChain), tests on the gateway's budget and retry logic only.

**5.2 Scope cuts, decided now.**

- Not built: hedged requests, a second provider, a model-based grader, a web interface, multi-worker deployment.
- Two of these become the "two things I deliberately did not build", each with its reason and its cost.

**5.3 Real-quota budget.** The daily token limit is the scarcest thing in the project and it is shared by every run.

| Day | Real Groq spend | Purpose |
| --- | --- | --- |
| Tue 10 Nov | About 30,000 tokens | Probe, per-minute limit burst, first end-to-end answers |
| Wed 11 Nov | About 120,000 tokens | Retrieval settings A and B on your questions |
| Thu 12 Nov | About 150,000 tokens, then exhaust one model on purpose | Setting C, small real steady run, daily-limit confirmation |
| Fri 13 Nov | Reserve only | Re-runs if something was wrong |

Every real run prints its estimated token cost first and needs your yes.

**5.4 Risks.**

| Risk | Chance | What we do |
| --- | --- | --- |
| Your real limits differ from the docs table | High | Probe first, and every limit is a setting, not a constant |
| Daily quota burned by a bug | Medium | Hard cap per run in the gateway, dry runs against the stand-in first |
| Paper parsing eats a day | Medium | HTML first, PDF only as fallback, tables allowed to be imperfect and reported as a known gap |
| Stand-in looks made up | Medium | Side-by-side real versus stand-in latency numbers in the write-up |
| Two pages is too short for 12 headings | High | Tables carry the numbers, each heading gets three to five sentences, draft early on Thursday |
| You cannot explain a piece of the code | Medium | You approve each phase plan, and each phase ends with a 10 minute walkthrough from me |

**5.5 Your part, which cannot be delegated.** The questions and answer key, the final numbers for "fast" and "give up", the three sign-offs in section 4.3, the Vaani feedback, and the write-up's judgments. I draft structure and supply measurements. The sentences that say "I chose" should be yours.

**5.6 Evidence of how you directed the AI.** The brief wants three prompts that mattered, one error you caught and one overrule. I will keep a running `docs/DECISIONS.md` in the repo: each decision, who made it, what I recommended, and what you changed. Your rule about real data only and this request for a plan split by architecture, ML and system design are already two entries.

**5.7 Interview readiness.** They will ask you to change the system live. Likely requests: halve a limit, add a ladder level, swap the retrieval setting, change the give-up time, explain one slow request. Each should be a one-line settings change or a small edit in one file. Friday morning includes a rehearsal where I ask you these.

**5.8 Submission hygiene.** No key anywhere in the folder or the history. A README with one command per table. Checksums for the three papers. The full conversation history from this thread and from the laptop work. Submit by 3 PM Friday, not 5:22.

## 6. Phases and timeline

Four phases, run through GSD on your laptop in `~/Desktop/the-relay`. For each phase you see the plan first, approve it, and get a walkthrough at the end.

| Phase | Day | Builds | Done when |
| --- | --- | --- | --- |
| 1. Foundations and probe | Tue 10 Nov | Python 3.12 setup, papers fetched and split, search indexes, Groq client with streaming and header capture, probe script | Table 1 is filled from real responses, and one real question gets a correctly cited answer |
| 2. Pipeline and retrieval | Wed 11 Nov | The five steps, three retrieval settings, refusal gates, grading sheet, results.csv writer | Settings A and B are run and graded on your questions, and the csv validates against the brief's columns |
| 3. Gateway, stand-in and load | Wed 11 to Thu 12 Nov | Budget, queue, deadlines, ladder, retries, timeouts, cache, stand-in calibrated from the probe, trace replay | Stand-in latency matches the probe side by side, and one overload run completes |
| 4. Experiments and write-up | Thu 12 to Fri 13 Nov | All scenarios, setting C, report script, slow-request breakdown, write-up skeleton, history export, rehearsal | All four tables print from results.csv, the 2 pages are written, and the folder is submitted by 3 PM Friday |

Phases 2 and 3 overlap on Wednesday on purpose: the gateway and stand-in do not need real quota, so they fill the hours while the day's tokens are spent.

## 7. What I need from you to start

- [ ] **Go or edits on this plan.** In particular the three numbers in 3.2 (2,000 ms, 5,000 ms, 15,000 ms), the ladder in 3.4, the retrieval settings in 2.2 and the three csv rules in 4.3.
- [ ] **A Groq account and API key.** Create it at console.groq.com and keep the key to yourself. I will tell you exactly where to paste it on your laptop when phase 1 reaches that point. Never paste it into this chat.
- [ ] **A screenshot or copy of your limits page** (console.groq.com/settings/limits), so the plan uses your real numbers.
- [ ] **OK to install `uv` and Python 3.12** inside the project on your laptop.
- [ ] **Start drafting your questions.** Eighteen, in the mix described in 2.6. They are needed by Wednesday morning.
