# Decision log

**Standing principle (Tanush, 9 Nov):** prefer what a working engineer would ship under real constraints — measured numbers, simple mechanisms, honest limits — over idealised designs. When two options are close, choose the one that is simpler to operate and explain. Applied to every later planning choice; the assistant says so when it decides something.

One row per decision. "Tanush's call" is filled only from his own words; "pending" means not yet decided.

| Decision | Recommended by assistant | Tanush's call | Date |
| --- | --- | --- | --- |
| Language: Python | Python | Python | 2026-11-10 |
| Real measured data only, no synthetic or invented numbers | — | Real data only | 2026-11-10 |
| Work locally on his laptop (~/Desktop/the-relay) | — | Local | 2026-11-10 |
| Use GSD agents to drive the build | GSD with a human gate per phase | "use gsd agents wherever needed" | 2026-11-10 |
| Plan structured as architecture, ML parts, system design, product additions | — | That structure | 2026-11-10 |
| Speed targets: first token 2,000 ms median, 5,000 ms p95; person gives up at 15,000 ms | As stated (PLAN 3.2), revise after probe | pending | |
| Order in which goals give way, and the degradation ladder (PLAN 3.4, levels 0–4) | As stated in PLAN 3.4 | pending | |
| Retrieval settings A small fixed / B large fixed / C section-aware + re-rank (PLAN 2.2) | As stated in PLAN 2.2 | pending | |
| results.csv rule: status mapping (admission refusal or unabsorbed 429 = rate_limited; give-up/deadline = timeout; honest "papers do not say" = ok + refused_correctly) (PLAN 4.3) | As stated | pending | |
| results.csv rule: start_time = arrival time, so peak queue length is rebuilt from start_time + total_ms (PLAN 4.3) | As stated | pending | |
| results.csv rule: cost per 1,000 answers at Groq's published list price for the model used (PLAN 4.3) | As stated | pending | |
| Model choice: one drafting model chosen after the probe; smaller model only as a ladder rung | As stated (PLAN 2.6) | pending | |
| Load shapes replayed from real public LLM traffic traces, with a stated arrival process as fallback (PLAN 4.2) | Replay real traces | pending | |
| The two things deliberately not built (from: hedged requests, second provider, model grader, web UI, multi-worker) | Hedged requests + model grader | pending | |
| Four phases from PLAN 6 (Foundations and probe; Pipeline and retrieval; Gateway, stand-in and load; Experiments and write-up) | Four phases | "divide the work into phases first, then start with phase 1" (via coordinator) | 2026-11-10 |
| Every GSD agent and subagent runs on an Opus model, not Fable, to save usage limits | — | Opus for all agents (via coordinator) | 2026-11-10 |
| GSD config: interactive mode (approve each phase plan), coarse granularity, sequential plans, commit planning docs, plan-check + verifier on, project research off, UI/AI-integration phases off | As listed | assistant default, pending Tanush | 2026-11-10 |
| Phase 1 discuss step answered from PLAN/DECISIONS (see .planning/phases/01-foundations-and-probe/01-CONTEXT.md) | As written there | assistant default, pending Tanush | 2026-11-10 |
| Probe design: models-list call, ~50 spaced requests, two bursts (RPM then TPM), concurrency ramp 1/2/4/8, reasoning detection, max_tokens 50 vs 1,000 pair, ~25–30k token cap | As listed | assistant default, pending Tanush | 2026-11-10 |
| Local models: MiniLM/bge-small embeddings + ms-marco MiniLM cross-encoder; HTML parsing with beautifulsoup4 | As listed | assistant default, pending Tanush | 2026-11-10 |
| Ladder: three levels (Normal, Lean, Day-gone); waiting for refill is queue behaviour; Minimal rung and small-model rung dropped | Three levels | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| Cache: exact-match only; coalescing listed as deliberately not built, cost measured from the burst run | Exact-match | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| Scenarios: six (real steady; stand-in steady, burst, sustained overload with retry-budget off/on variant, limit halved, day exhausted); queue-order comparison dropped | Six | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| Report script (Tables 2a/2b/3, DATA-06/07/08) moved to phase 2; write-up drafting starts Wednesday evening | Move | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| Tool-timeout injection on the retrieve step (new GW-09, phase 3) | Add | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| One-command live entry point `uv run relay ask "..."` (new PIPE-07, phase 2) | Add | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| Empty-field rule for results.csv fields that do not apply, enforced by the validator (new DATA-10, phase 2) | Add | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| Keep 18 evaluation questions (checker suggested 15) | 18 | Tanush: keep 18 | 2026-11-10 |
| EVAL-06 (smaller-model quality eval) dropped, follows from removing the small-model rung | Drop | applied on Tanush's instruction to prefer the pragmatic real-world option (9 Nov) | 2026-11-10 |
| uv installed with the official installer and UV_NO_MODIFY_PATH=1 (no shell profile edits; uv lives at ~/.local/bin/uv) | As done | assistant default, pending Tanush | 2026-11-10 |
| Hugging Face model cache kept inside the project (.cache/huggingface, git-ignored), not ~/.cache | As done | assistant default, pending Tanush | 2026-11-10 |
| DRAFT_MODEL provisionally llama-3.1-8b-instant until the probe shows the candidates | Provisional | assistant default, pending Tanush | 2026-11-10 |
| Piece id format paper-setting-NNN (e.g. moshi-C-012), cited in square brackets | As built | assistant default, pending Tanush | 2026-11-10 |
| Token counts for estimates are approximate (words x TOKENS_PER_WORD 1.33 + 8 per message); real counts come from Groq usage | As built | assistant default, pending Tanush | 2026-11-10 |
| Probe stage sizes live in config.PROBE; probe dry-run upper-bound estimate 17,179 tokens against the default cap 30,000; ask.py dry run (setting C, Mimi question) 2,617 tokens | As built | assistant default, pending Tanush | 2026-11-10 |
| Groq free-tier tokens are scarce and careful use is judged: keep a quota ledger (docs/QUOTA.md), learn limits from free sources (models list, headers) before bursting, smallest prompts/max_tokens that still trigger a limit, stop each stage once its question is answered, never rerun a real stage because of our own bug (dry-run against the fake server first), never spend real tokens on what the stand-in can answer | As stated | Tanush (10 Nov) | 2026-11-10 |
| A/B fixed windows that straddle a section boundary are cited under the block holding most of the window's words (earlier block on a tie), not the block of the first word (review ME-02) | Majority block | assistant default, pending Tanush | 2026-11-10 |
| Probe profiles: "lean" is the default (models list, one header sample per candidate, 50 spaced, RPM burst + recovery, concurrency 1/2/4/8); token-limit burst, its recovery and the max_tokens pair only with --profile full. Each stage stops once answered; the run aborts and reports on any unexpected answer | Lean default | Tanush (10 Nov) | 2026-11-10 |
| Spend estimates (supersedes "words x 1.33 + 8"): max(words x 1.33, characters / 3) + 60 tokens per request for the chat template, plus max_tokens; the probe reserves each estimate before sending and never sends past the cap; the overhead is checked against usage.prompt_tokens after the probe | As built | assistant default, pending Tanush | 2026-11-10 |
| TTFT is measured from just before the request is sent, including connection setup when one is opened; every record carries new_connection so the two populations can be separated (review ME-06) | Measure consistently + flag | assistant default, pending Tanush | 2026-11-10 |
| The real key is only sent to https://api.groq.com; any other base URL gets a dummy key, and table1 heads any non-Groq run "NOT GROQ" with confidence "none" (review HI-01, HI-05) | As built | assistant default, pending Tanush | 2026-11-10 |
| config.DOCUMENTED_LIMITS (abort threshold only, never reported): gpt-oss values from docs/RESEARCH.md; llama values from assistant memory of Groq's limits page, unverified, Tanush to confirm | As built | assistant default, pending Tanush | 2026-11-10 |
| No subagents: the assistant does all work itself in its own session (no GSD or other agents) until Tanush says otherwise; GSD file conventions are still kept by hand. Replaces the earlier "GSD agents on Opus" rule. One GSD verifier had already finished before this arrived. | — | Tanush: "right now dont deploy any subagent, work on yourself" (13:44 UTC) | 2026-11-10 |
| Probe cap raised from 6,000 to 10,000 tokens (lean profile unchanged) because the gpt-oss upper bound was 12,420; answer cap 3,000 | Raise to 10,000 | Tanush: "go" | 2026-11-10 |
| ask.py counts both [id] and gpt-oss's 【id】 as citations and prints NO CITATION FOUND for an uncited answer (first real answer used 【】) | As built | assistant default, pending Tanush | 2026-11-10 |
| Setting B's miss on H-Net's "ratio loss" passage is accepted as a Table 3 finding; B is not tuned to pass | Accept as a finding | Tanush: "accept B, start phase 2" | 2026-11-10 |
| The answer is shown one checked sentence at a time: a sentence reaches the person only if it cites retrieved pieces and every number in it appears in a piece it cites; the first failing sentence stops the reply with an honest note. So results.csv first_token_ms = arrival to the first checked text shown; the model's own first-visible-token time stays in traces.jsonl (switching the csv to it is one line) | As built | assistant default, pending Tanush | 2026-11-10 |
| Review ME-01 fixed: pieces are scored by their best 150-word window (the embedding model reads 256 word-pieces). Side effect: setting B now finds the H-Net ratio loss and instead misses Moshi's 12.5 Hz (windows from the Mimi results outrank the ones holding it). Kept as a Table 3 finding, not tuned | Keep the fix, report the moved miss | pending Tanush (his 16:33 acceptance named the ratio-loss miss) | 2026-11-10 |
| Decide step: retrieval strength = best cosine between the question and a window of the kept pieces; below MIN_STRENGTH 0.30 re-query once (drop the paper filter if one was applied, else keywords only), then refuse with no model call. 0.30 is provisional, from test probes only (off-topic 0.12-0.20, known facts 0.47-0.76); to be set from Tanush's question runs | 0.30 provisional | pending Tanush (EVAL-05) | 2026-11-10 |
| max_tokens = 250 visible + 150 reasoning headroom (probe: gpt-oss reasons first); per-request ceiling 6,000 estimated tokens (4,000 silently cut setting B to 3 pieces) | As built | assistant default, pending Tanush | 2026-11-10 |
| results.csv status: a 429 is rate_limited, a client timeout is timeout, any other failed call is error; an honest refusal ("The papers do not say", a failed check, weak retrieval) is ok and graded by hand. Empty fields: first_token_ms when nothing model-backed was shown, answer_grade until graded; tokens are 0 (not empty) for a refusal before any model call, because zero were spent | As built (PLAN 4.3) | pending Tanush (PLAN 4.3 sign-off) | 2026-11-10 |
| Tokens per answer (Tables 2b, 3) = mean over all requests in the group, refusals before any model call counting 0 | As built | assistant default, pending Tanush | 2026-11-10 |
| One command is `uv run python -m relay ...`, not `uv run relay ...`: the latter needs a packaging backend downloaded (a new install); switching is a two-line pyproject change if Tanush wants it | Practical option, no new install | assistant default, pending Tanush | 2026-11-10 |
| The probe's unused "full" profile (token-limit burst, max_tokens pair) and ask.py were deleted; the lean probe that actually ran is kept unchanged; relay ask replaces ask.py | Simplify | assistant default, pending Tanush | 2026-11-10 |
