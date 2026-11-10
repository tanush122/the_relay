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
