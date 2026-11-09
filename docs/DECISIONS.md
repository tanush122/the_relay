# Decision log

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
