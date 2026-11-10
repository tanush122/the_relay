# Groq quota ledger

One row per real Groq run. Token counts are as reported by Groq (usage / headers), never estimated after the fact. Running total is per day (Groq's daily window; reset behaviour to be confirmed by the probe).

| Date and time (IST) | Purpose | Model | Requests | Tokens in | Tokens out | Running total today | What it taught us |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-10 11:33 | Lean probe attempt 1: free models list only, then abort (planned main model llama-3.1-8b-instant not listed) | — | 1 (models list, free) | 0 | 0 | 0 | The Llama chat models assumed by the plan are not on the account; available chat models: openai/gpt-oss-20b, openai/gpt-oss-120b, qwen/qwen3.8-27b (all reasoning-capable). Abort-on-surprise worked: 0 tokens spent. |
