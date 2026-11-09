# The Relay: project explainer and research

Nov 9, 2026 · @Tanush

## What this project is

The Relay is a reliability engineering test dressed up as a question-answering bot. You build a small assistant that answers questions about three research papers, then you prove with measurements how it behaves when too many people use it at once and the model provider starts refusing requests.

The assistant itself is a chain of model calls and tools, often called a RAG pipeline (retrieval-augmented generation). A typical request flows like this:

1. **Understand** the question (classify it, rewrite it, decide if it is in scope).
2. **Retrieve** passages from the three papers (this is the required tool call).
3. **Decide** what to do: answer, retrieve again with a better query (the loop), or refuse because the papers do not say.
4. **Draft** a reply that cites the paper and section each claim came from.
5. **Check** the draft against the retrieved passages before sending it.

That part is maybe 30% of the work. The other 70% is what the brief's first two paragraphs describe: requests arrive in bursts, the provider caps requests per minute, tokens per minute and requests per day, calls are sometimes slow or hang, and users give up. The company wants four things that cannot all be had: fast, good, cheap, and nobody turned away. Your job is to pick which to sacrifice, when, and to show numbers that justify it.

Because Groq's free tier cannot survive a load test, you also build a **stand-in model service**: a fake LLM server you control that can be slow, fail, return rate-limit errors, slow down under load, and stream tokens. You calibrate it from real Groq measurements, then run the heavy load scenarios against it.

### What is actually being judged

- **Judgment under conflict.** The brief leaves numbers out on purpose. They want you to define "fast", pick a give-up time, choose who gets dropped at a limit, and say what each choice costs.
- **Measurement honesty.** Every number in the write-up must be recomputable from results.csv. Reviewers recompute the tables first.
- **How you direct the AI.** They ask for the raw conversation history, three prompts that mattered, one thing the AI got wrong that you caught, and one decision where you overruled it.
- **You in the submission.** There is a live follow-up where you explain results and change the system, so anything submitted must be something you can defend line by line.
- **Depth over coverage.** "Pick the few that matter for your measurements and go deep."

## Deliverables checklist

One Google Drive folder, set to "Anyone with the link can view", submitted by Fri 13 Nov 2026, 5:22 PM IST with the email you applied with.

**Code**

- [ ] Pipeline in Python with at least 4 steps, 1 tool call, 1 branch or loop, and a retrieval step over the library
- [ ] Library fetched at exact versions: arXiv 1706.03762v7, 2410.00037v1, 2507.07955v2
- [ ] Every answer cites where in the papers it came from, and refuses when the papers do not say
- [ ] Real model calls on Groq's free tier with your own key (key never included in the submission)
- [ ] Stand-in model service that can be slow, fail, refuse on a limit, slow down under load, and stream
- [ ] Load generator with at least 3 shapes of your own design

**Runs**

- [ ] A modest real probe of Groq: latency spread, limits, what a limit response looks like, recovery time
- [ ] Five scenario rows minimum in Table 2: steady, burst, sustained overload, per-minute limit halved, daily budget exhausted
- [ ] At least 3 retrieval settings (piece size, pieces fetched, re-rank) each graded
- [ ] At least 15 questions you wrote yourself, graded correct / wrong / refused correctly / refused wrongly

**results.csv** (one row per request)

- [ ] Columns: request\_id, scenario, source, start\_time, first\_token\_ms, total\_ms, status, retries, tokens\_in, tokens\_out, retrieval\_setting, answer\_grade
- [ ] Every table figure computable from this file

**Write-up, 2 pages maximum, headings in this order**

1. What I built and why
2. The real service and my stand-in
3. Results (Tables 1, 2a, 2b, 3, plus "a number we could not have guessed")
4. Where the time goes (one slow request split into waiting, working, retrying, before or after first token)
5. When a limit is hit (per-minute and per-day: who is delayed, dropped, or degraded)
6. Retrieval: quality versus cost
7. How this library will mislead a naive retriever (3 ways, each with an example question)
8. Retries (policy, plus one case where retrying made things worse)
9. What the person sees (3pm, daily budget gone)
10. What I'm unsure about, what I left out, what I learned
11. Your feedback on Vaani (visit vaani.dev)
12. How I worked with the assistant (raw history, 3 prompts, 1 caught error, 1 overrule, what is distinctly yours)

The brief's heading order is ambiguous: it says to add the two retrieval headings "after heading 5". The order above follows that reading. The conversation history sits outside the 2 page limit.

## Groq free tier: what the docs say today

Tokens, not requests, are the limit that will bite. At roughly 8,000 tokens per minute and 200,000 per day, a pipeline that spends 4,000 tokens per answer manages about 2 answers a minute and 50 a day. That single fact should shape the whole design.

The [rate limits page](https://console.groq.com/docs/rate-limits) lists these per-model values. The page calls them base limits and never uses the words "free tier", while the [models page](https://console.groq.com/docs/models) quotes 250K TPM for gpt-oss-120b on the Developer plan. Treat the table as a starting guess and read your real numbers at console.groq.com/settings/limits once you have an account.

| Model | Requests/min | Requests/day | Tokens/min | Tokens/day |
| --- | --- | --- | --- | --- |
| openai/gpt-oss-120b | 30 | 1,000 | 8,000 | 200,000 |
| openai/gpt-oss-20b | 30 | 1,000 | 8,000 | 200,000 |
| qwen/qwen3.8-27b | 30 | 1,000 | 8,000 | 200,000 |
| openai/gpt-oss-safeguard-20b | 3 | 1,000 | 2,000 | 200,000 |
| meta-llama/llama-prompt-guard-2-86m | 30 | 14,400 | 15,000 | 500,000 |

llama-3.1-8b-instant and llama-3.3-70b-versatile are production models on the models page but were missing from the limits table I read. Check them on your limits page, since the 8b model has historically had the most generous daily allowance.

### Facts that matter for the design

- **Limits are per organization and per model.** "Rate limits apply at the organization level, not individual users." A second API key does not help. Each model has its own bucket.
- **You hit whichever limit comes first.** Requests and tokens are counted separately.
- **The headers only show two of the four limits.** `x-ratelimit-limit-requests`, `-remaining-requests` and `-reset-requests` always refer to requests per day. `x-ratelimit-limit-tokens`, `-remaining-tokens` and `-reset-tokens` always refer to tokens per minute. Requests per minute and tokens per day are invisible until you hit them. This is a ready-made answer for the "How you found it" column in Table 1.
- **A limit returns HTTP 429** with a `retry-after` header in seconds. That header only appears on a 429. The other headers come on every response, so the client can throttle before it is refused.
- **Cached tokens do not count** towards rate limits, per the docs. A stable system prompt prefix may therefore stretch the budget. Worth measuring.
- **Other errors to handle:** 498 (flex capacity, paid only), 499 (client cancelled), 500, 502, 503. Error bodies look like `{"error": {"message": "...", "type": "..."}}`.
- **Flex and batch tiers are paid only**, so they are not an escape route.
- **Streaming** is `stream=True` and yields deltas. Time to first token is measured client-side as the gap between sending and the first content delta.

### To verify with the first probe (from my memory, not confirmed in the docs I read)

- The 429 body usually names the exact limit hit, the limit value, tokens used and requested, and a "try again in X s" hint. If so, it reveals requests per minute and tokens per day.
- The final streamed chunk usually carries `x_groq.usage` with `queue_time`, `prompt_time`, `completion_time` and `total_time`. If so, Groq itself tells you how long a request waited in its queue, which feeds heading 4 directly.
- Whether a request refused with 429 still consumes request or token quota.
- Whether there is a concurrency cap ("requests in flight at once" in Table 1). The docs do not mention one.

### Terms

The [Services Agreement](https://console.groq.com/docs/legal/services-agreement) says Groq "has no obligation to provide multiple accounts" (3.2) and bars use "in a manner intended to avoid incurring Fees" (6.3). The brief also forbids extra accounts. One account, one organization, and switching between models inside it is the only legitimate lever.

## The three papers

All three are about sequence models, so they share vocabulary while meaning different things by it. That overlap is deliberate, and it is what heading 7 ("How this library will mislead a naive retriever") is asking about.

| Paper | Version to fetch | Latest on arXiv | What it is about |
| --- | --- | --- | --- |
| [Attention Is All You Need](https://arxiv.org/abs/1706.03762v7) (Vaswani et al.) | v7, 2 Aug 2023 | v7 | The original Transformer: attention-only encoder and decoder for machine translation |
| [Moshi](https://arxiv.org/abs/2410.00037v1) (Défossez et al., Kyutai) | v1, 17 Sep 2024 | v2, 2 Oct 2024 | A real-time, full-duplex speech-to-speech dialogue model, with the Mimi audio codec and Helium text LLM |
| [Dynamic Chunking / H-Net](https://arxiv.org/abs/2507.07955v2) (Hwang, Wang, Gu) | v2, 15 Jul 2025 | v2 as far as I could see | A byte-level model that learns its own chunk boundaries instead of using a tokenizer |

**Version trap.** Moshi v1 is not the latest. Fetching `arxiv.org/abs/2410.00037` without the suffix gives v2. Always put the version in the URL (`arxiv.org/pdf/2410.00037v1`) and record a checksum of each file in the repo. I could not see the full version history for the H-Net paper, so confirm v2 is what you download.

**Fetching.** Each paper has a PDF (`arxiv.org/pdf/<id>v<n>`) and an HTML rendering (`arxiv.org/html/<id>v<n>`). The HTML keeps section headings, tables and equations as structure, which makes section-level citations much easier than PDF text extraction. The LaTeX source (`arxiv.org/e-print/<id>v<n>`) is the cleanest of all. Fetch each file once and keep it locally.

### Structure you can cite against

- **Attention:** sections 1 to 7, with the dense detail in 3.1 to 3.5 (architecture), 5.1 to 5.4 (training) and 6.1 to 6.3 (results). Tables 1 to 4. No appendix beyond attention visualisations.
- **Moshi:** sections 1 to 7 plus appendices A to F. Section 3 covers Helium (3.2), Mimi audio tokenization (3.3) and generative audio modeling with the RQ-Transformer and Inner Monologue (3.4). Tables run to at least Table 18.
- **H-Net:** sections 1 to 5 plus appendices A to F. Section 2.2 is dynamic chunking itself (routing module, downsampler, smoothing module, upsampler, ratio loss). Appendix A is a long related-work survey of other people's models.

### Candidate ways the library misleads a naive retriever

These are hypotheses to test, not conclusions. Keep the ones your own runs confirm.

1. **Same word, different paper.** "Encoder", "decoder", "Transformer", "layers", "tokens", "latency" and "chunk" appear in all three with different meanings. *"How many layers does the encoder have?"* matches the Transformer (N = 6), H-Net (about four layers per encoder network) and Mimi's encoder. A similarity search returns a blend and the model answers with whichever comes first.
2. **The answer is in a table or equation, not a sentence.** Hyperparameters live in Attention Table 3, Moshi Table 1 and the H-Net appendices. PDF extraction scrambles table rows, and a table row has almost no words in common with the question. *"What feed-forward dimension does the big Transformer use?"* needs Table 3, while section 3.3 prominently says 2048, which is the base model.
3. **A paper describing somebody else's work.** Moshi and H-Net both spend pages on prior models, and H-Net's Appendix A is all prior work. *"Does H-Net pick chunk boundaries using entropy?"* retrieves the related-work passage about entropy-based methods in other models and invites a confident wrong yes.
4. **Two different numbers for what sounds like one fact.** Moshi quotes 160 ms theoretical latency and 200 ms in practice. H-Net says "nearly 4x" DNA data efficiency in the abstract and "3.6x" in the introduction. The Transformer has base and big BLEU scores (27.3 and 28.4 on English to German). A small chunk carries one number without its qualifier.
5. **Questions the model knows but the papers do not answer.** *"How many parameters does GPT-4 have?"* or *"Who funds Kyutai?"* The retriever still returns its top passages, they look relevant, and the model fills the gap from memory. Refusal has to be a decision the pipeline makes from retrieval scores and the checker step, not something left to the model's mood.
6. **"Chunking" collides with your own vocabulary.** The H-Net paper is about chunking, so a question about how your assistant splits documents and a question about the paper's method look identical to a retriever.

## Techniques that matter

The brief says to pick a few and go deep. These are the ideas each write-up heading is fishing for, in rough order of payoff for this assignment.

**1. A client-side token budget, not just retry on 429.** Keep your own count of requests and tokens per minute and per day, per model, seeded from the response headers. Decide before sending whether a request fits. Reacting to 429s wastes quota and time. Estimating tokens before the call (prompt length plus a cap on output) is the hard part and worth a sentence in the write-up.

**2. Admission control with a deadline.** Every request gets a deadline when it arrives (your definition of "people give up"). If the queue plus expected service time already exceeds the deadline, refuse immediately with an honest message. A fast no beats a slow no. An unbounded queue is the classic failure: under sustained overload everyone waits and everyone times out.

**3. Queue order under overload.** First-in-first-out serves the request most likely to have been abandoned already. Serving newest-first, or dropping requests whose deadline has passed before spending tokens on them, raises the share of answers that reach someone still waiting. This is a strong candidate for "a number we could not have guessed".

**4. A degradation ladder.** Before dropping anyone, make each answer cheaper: skip the query-rewrite step, fetch fewer passages, cap output length, fall back to a smaller model with its own bucket. The checker step and the refusal rule stay on at every rung, because the brief says a wrong answer is never acceptable. This is the answer to "who gets a weaker answer" under heading 5, and to "what you do with retrieval when the limit is close".

**5. Retries with backoff, jitter and a budget.** Retry only what is retryable (429 after `retry-after`, 500, 502, 503, timeouts). Use exponential backoff with full jitter so a burst of failures does not retry in lockstep. Cap retries with a retry budget (for example, retries may be at most 10% of traffic), otherwise retries multiply load exactly when the service is weakest. That retry storm is your "case where retrying made things worse", and the stand-in lets you reproduce it on demand.

**6. Timeouts that know about streaming.** One total timeout is the wrong tool. Use a short time-to-first-token timeout (detects a stuck call early) and a separate stall timeout between chunks. This handles the brief's "calls that succeed slowly instead of failing quickly". Retrying after the first token has been shown to the user is a different problem from retrying before it.

**7. Hedging, used carefully.** Sending a second copy of a slow request cuts tail latency, but each hedge spends quota. Under a token limit it is usually the wrong trade. Saying why you did not build it is a legitimate "deliberately left out".

**8. Loop caps.** The brief says "a few loop". The retrieve-again loop needs a hard cap on iterations and on tokens per request, or one bad question eats the minute's budget for everyone.

**9. Honest measurement.** Three traps reviewers will check:

- *Coordinated omission.* The load generator must send on schedule regardless of how slow replies are (open loop), and latency must be measured from the scheduled arrival time, including time in your queue. Otherwise an overloaded system looks fast.
- *Percentiles on small samples.* A p99 from 50 requests is just the maximum. State the request count beside every percentile, as the brief demands.
- *First token of what.* With a multi-step pipeline, first token means the first token the user sees, which comes after understanding, retrieval and deciding. Log each step's start and end so heading 4 falls straight out of the trace.

**10. Caching.** Identical questions arrive in bursts "right after something goes wrong for many users at once". An answer cache and request coalescing (one model call serves ten identical waiting questions) is the cheapest capacity you can add, and the brief hints at it.

## The stand-in model service and real data

The stand-in is a small HTTP server that speaks the same chat-completions API as Groq, so the pipeline switches between real and stand-in by changing one base URL. Everything about its behaviour should come from a measurement, which fits your rule of no made-up data.

### What it must do, and where each behaviour comes from

| Required behaviour | How to build it | Calibrated from |
| --- | --- | --- |
| Be slow | Sample time-to-first-token and per-token gap from recorded distributions | The real Groq probe: resample the actual measured values rather than fitting a neat curve |
| Fail | Return 500 / 503 or drop the connection at a set rate | Error rate seen in the probe. If the probe saw none, say so and label the rate as an assumption |
| Refuse on a limit | Same four counters as Groq (requests and tokens, per minute and per day), 429 with `retry-after` and the same headers | Limits and header behaviour found in the probe |
| Slow down under load | Latency grows with requests in flight | The least measurable part on a free tier. This is probably "where it differs most from the real thing" |
| Stream | Server-sent events, one chunk per token group | Chunk sizes and gaps seen in real streams |
| Succeed slowly | Occasionally stall mid-stream for seconds | Slowest real requests in the probe |

The reply text can be canned for load runs, because those runs measure timing and outcomes, not answer quality. Answer quality (Table 3 and the 15 questions) must come from real Groq calls. The write-up should say this split out loud.

### Where the stand-in will be least like Groq

- Its limiter is your guess at Groq's algorithm (fixed window, sliding window or token bucket). The reset headers in the probe hint at which.
- Real slowness comes from other customers' traffic, which you cannot see. Yours comes from your own load.
- Output length on the real service depends on the question. A canned reply has a fixed length unless you sample lengths from real answers.

### Real traces for the load shapes

Instead of inventing arrival patterns, replay real ones, scaled to your capacity. Two public datasets of real LLM traffic exist (cited from memory, so confirm before relying on them):

- **BurstGPT** (github.com/HPMLL/BurstGPT): months of real request traces from a university's Azure OpenAI deployment, with timestamps and token counts. Its whole point is that real LLM traffic is bursty.
- **Azure LLM inference traces** (github.com/Azure/AzurePublicDataset): arrival times with input and output token counts from production Azure OpenAI services.

Steady, burst and overload scenarios can each be a slice of a real trace with the time axis compressed. That is a design choice most candidates will not make, and it is easy to defend.

### Budgeting the real service

Running out is part of the problem, and the daily limit is shared by everything you run. Rough spend, assuming 200,000 tokens a day per model:

- Latency probe: 40 to 60 small requests, about 15,000 tokens.
- Finding the per-minute limits: one deliberate burst, about 10,000 tokens. Do this once.
- Finding the per-day limit: do not burn a day to find it. Read it from the limits page and from the 429 message, and say so. Or exhaust it on purpose late on the final evening using the cheapest model, when nothing else needs the quota.
- Retrieval evaluation: 15 questions x 3 settings x roughly 3 calls x 1,500 tokens is about 200,000 tokens. That is a whole day of one model, so spread it over two days or two models.

The daily window's reset time is unknown until the probe. Find it early, because it decides how many "days" of quota remain before Friday.

## Retrieval design options

Retrieval should run entirely on your own machine and spend zero Groq tokens, because every token saved there is an answer you can afford later. The model list I read shows no embedding model on Groq, so embeddings would be local anyway.

**Splitting the papers.** Three families worth comparing for Table 3:

- *Small fixed pieces* (about 150 to 200 tokens, slight overlap). Precise, cheap per piece, but splits tables and separates a number from its qualifier.
- *Large fixed pieces* (about 500 to 800 tokens). Keeps context together but costs three to four times the tokens per answer.
- *Section-aware pieces.* Split on the paper's own headings, keep each table and its caption whole, and prefix every piece with paper title and section path ("Moshi > 3.3.1 Architecture"). This directly attacks the "same word, different paper" trap and gives citations for free.

**Finding pieces.**

- *BM25* (keyword scoring). No model, instant, and strong on exact terms such as "d\_ff", "RVQ" or "ratio loss". Weak on paraphrased questions.
- *Local embeddings* (a small sentence-transformers model on CPU). Handles paraphrase, weak on exact numbers and symbols.
- *Hybrid.* Run both and merge the rankings (reciprocal rank fusion). Usually the best of the cheap options.

**Re-ranking.** A local cross-encoder re-scores the top 20 pieces and keeps the best 3 to 5. It adds local compute time before the first token but lets you send fewer pieces, which saves Groq tokens. That trade (milliseconds for tokens) is exactly what Table 3 asks you to measure. Re-ranking with a Groq model call is possible but spends the scarce resource.

**How many pieces.** At 8,000 tokens a minute, the difference between 3 pieces and 8 pieces of 400 tokens is 2,000 tokens per answer, which is a quarter of a minute's budget. This is the knob the degradation ladder turns when the limit is close.

**Citations.** Carry metadata on every piece: paper, version, section number and title, page, and piece id. Ask the model to cite piece ids, then map ids back to "Moshi v1, section 3.3.2" in code. The checker step can then verify mechanically that every cited id was actually retrieved, and that quoted numbers appear in the cited piece.

**Refusing.** Three signals, cheapest first:

1. Retrieval score below a threshold: refuse without calling the model at all. This costs zero tokens, which also makes it the fastest possible reply.
2. The drafting prompt allows "the papers do not say".
3. The checker step fails the draft if a claim has no supporting piece.

The threshold in signal 1 trades wrongly refused answers against wrong answers. Your 15 questions should include several unanswerable ones and several that look answerable but are not, so that the threshold is set from data.

**Grading.** The brief's grades are correct, wrong, refused\_correctly, refused\_wrongly. For 15 to 45 answers, grade by hand against a key you wrote from the papers. A model grader would spend quota and add a second thing to defend. The questions must be your own: the brief says "questions you wrote yourself", and the live follow-up will probe them.

## Vaani the company

Vaani sells a platform for AI voice agents that make and take phone calls, and The Relay is their daily engineering problem with the audio removed. Knowing that tells you what they mean by "fast".

**What they build.** [vaani.dev](https://www.vaani.dev/) (legal name Vaani AI Research Pvt Ltd, Bengaluru) offers a console, API, webhooks and outbound campaigns for voice agents in sales, support and scheduling, aimed at enterprises and BPOs in banking, insurance, healthcare and mobility. The site lists English, Hindi, Tamil, Telugu, Bengali, Spanish and Arabic. The founders named on the About page are Tushar Shinde (CEO), Nitesh Tripathi (CTO) and Nitish Mishra (CPO). [Entrackr](https://entrackr.com/snippets/vaani-ai-research-raises-400k-pre-seed-round-led-by-venture-catalysts-10512994) and [YourStory](https://yourstory.com/2025/11/vaani-ai-voice-infrastructure-human-digital-future) report a $400K pre-seed round led by Venture Catalysts.

**Why the assignment looks the way it does.**

- Their product is a chain: speech to text, then an LLM, then text to speech. Each link is a hosted provider with rate limits and tail latency. The Relay's "several model calls and a few tools" is the same shape.
- Their pricing page lists Groq among the selectable LLM providers. The limits you are asked to discover are limits they live with.
- On a phone call, silence is failure. Their site quotes latency in hundreds of milliseconds, and the Moshi paper in your library notes that the average gap in human conversation is about 230 ms. So time to first token is the metric they care most about, and "people give up sooner than you expect" is literal for a caller.
- "Requests arrive in bursts" matches outbound calling campaigns, where thousands of calls start inside a time window.
- Two of the three papers (Moshi, and H-Net's work on chunking raw sequences) are close to speech modelling, which is the company's research interest.

A sensible consequence: define "fast" in terms of time to first token, treat total time as secondary, and say that you chose it because of what the company does.

**Raw material for the feedback heading.** The brief wants your honest view in a few lines, so open the site yourself and form your own. Things I noticed that you can check:

- The homepage card says "Best-in-class p90 latency of \~450ms", while the Developers page says full-turn latency is "p50 is 600ms and p90 is 900–1200ms". For a company testing candidates on honest percentiles, that mismatch is worth raising politely.
- The headline is "The only voice AI harness that you'll ever need." "Harness" is jargon, and it takes a scroll to learn the product makes phone calls.
- Sign-up, product and docs are spread over several addresses (platform.vaani.dev, app.vaanivoice.ai, docs.vaani.dev, vaaniresearch.com).
- YourStory describes the voice stack as built in-house, while the pricing page lists third-party providers for every component. The site does not say which parts are Vaani's own.
- The homepage statistics read as zeros in the text I fetched. That is probably a count-up animation, so check in a browser before mentioning it.

## Useful resources

**Opened and read for this doc**

- [Groq rate limits](https://console.groq.com/docs/rate-limits): limit table, header meanings, 429 behaviour
- [Groq error codes](https://console.groq.com/docs/errors): status codes and error body shape
- [Groq models](https://console.groq.com/docs/models): model ids, context windows, speeds, prices
- [Groq text chat](https://console.groq.com/docs/text-chat): streaming usage
- [Groq flex processing](https://console.groq.com/docs/flex-processing): paid only, 498 on capacity
- [Groq Services Agreement](https://console.groq.com/docs/legal/services-agreement): account and usage restrictions
- arXiv pages for [1706.03762v7](https://arxiv.org/abs/1706.03762v7), [2410.00037v1](https://arxiv.org/abs/2410.00037v1), [2507.07955v2](https://arxiv.org/abs/2507.07955v2) and their HTML renderings at arxiv.org/html/
- [vaani.dev](https://www.vaani.dev/) homepage, About, Pricing, Developers, Platform and Demo pages

**Recommended reading, cited from memory and not opened in this session.** Search for the titles if a link has moved.

| Topic | Resource | Why read it |
| --- | --- | --- |
| Retries | AWS Builders' Library, "Timeouts, retries, and backoff with jitter" | The standard reference for heading 8. Explains retry storms |
| Retries | AWS Architecture Blog, "Exponential Backoff And Jitter" | Shows with simulations why full jitter wins |
| Retries | Marc Brooker's blog, "Fixing retries with token buckets and circuit breakers" | Retry budgets in a few paragraphs |
| Overload | Google SRE Book, chapters "Handling Overload" and "Addressing Cascading Failures" | Load shedding, deadlines, graceful degradation |
| Overload | AWS Builders' Library, "Using load shedding to avoid overload" | Why a fast refusal beats a slow one |
| Tail latency | Dean and Barroso, "The Tail at Scale" (2013) | Hedged requests and why p99 dominates multi-step pipelines |
| Measurement | Gil Tene, "How NOT to Measure Latency" (talk), and the wrk2 README | Coordinated omission, the commonest load-test mistake |
| Queues | Facebook Engineering, "Fail at Scale" (2015) | Newest-first queueing and controlled delay under overload |
| Real traces | BurstGPT dataset (HPMLL on GitHub) | Real bursty LLM arrival traces with token counts |
| Real traces | Azure LLM inference traces (Azure/AzurePublicDataset on GitHub) | Production arrival and token-length traces |
| Retrieval | Anthropic, "Contextual Retrieval" (2024) | Prefixing pieces with document context, hybrid BM25 plus embeddings, re-ranking |
| Retrieval | rank\_bm25 and sentence-transformers documentation | The two local libraries most likely to be used |
| Stand-in | FastAPI docs on StreamingResponse, and the OpenAI streaming format | What the fake server has to emit |

## Open decisions and a proposed schedule

These decisions are yours, because they are what the reviewers will ask you to defend. My recommendation follows each one.

1. **What does "fast" mean?** Recommend: first visible token within 2 seconds at the median and 5 seconds at p95, and a person gives up at 15 seconds with no token. Revise after the probe shows what Groq can actually do.
2. **Which goal gives way first?** Recommend this order under pressure: spend less per answer (fewer passages, skip rewrite, smaller model), then make people wait with an honest estimate, then refuse new arrivals quickly. Never relax the check or the refusal rule.
3. **Which models?** Recommend one stronger model for drafting and a small fast one for the understand and check steps, each with its own quota bucket. Choose after reading your limits page.
4. **Retrieval baseline.** Recommend section-aware pieces with hybrid BM25 plus local embeddings, compared against small-fixed and large-fixed pieces for Table 3.
5. **Load shapes.** Recommend replaying slices of a real public LLM traffic trace instead of invented arrival patterns.
6. **What to leave out on purpose.** Candidates: hedged requests, multi-provider fallback, a model-based grader.
7. **Where the code runs.** My cloud workspace cannot reach Groq or arXiv (outbound requests are blocked), so real runs have to happen on your computer, which is linked to this thread, or the workspace's network policy needs opening up.

### What only you can do

- Create the Groq account and API key, and keep the key out of the repo and out of this chat.
- Write the 15 or more questions and the answer key.
- Visit vaani.dev and write the feedback lines.
- Make the calls in the list above, and overrule me where you disagree. The brief asks for one such case.

### Schedule to Friday 13 Nov, 5:22 PM IST

| Day | Goal | Done when |
| --- | --- | --- |
| Tue 10 Nov | Groq key, limits page read, real probe run, papers fetched at exact versions and split into pieces, first end-to-end answer with citations | One real question answered with a correct citation, and Table 1 mostly filled |
| Wed 11 Nov | Stand-in service calibrated from the probe, load generator, token budget, queue, deadlines, retries. You write the questions | Stand-in passes a side-by-side comparison with real latency data, and one load scenario runs end to end |
| Thu 12 Nov | All five scenarios on the stand-in, three retrieval settings on real Groq, results.csv, script that rebuilds every table from the csv | Tables 2a, 2b and 3 generated from results.csv with no hand-typed numbers |
| Fri 13 Nov | Write the 2 pages, export this conversation, assemble the Drive folder, submit by 3 PM to leave a buffer | Confirmation email received |

The real-service work is front-loaded on purpose: daily quota that goes unused on Tuesday cannot be recovered on Thursday.
