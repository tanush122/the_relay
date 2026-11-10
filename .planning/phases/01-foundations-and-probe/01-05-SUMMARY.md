---
phase: 01-foundations-and-probe
plan: 05
subsystem: real-run
tags: [probe, groq, table1, cited-answer, quota]
requires: ["01-04 probe.py, table1.py, ask.py"]
provides:
  - "data/probe/run_20261110T133218Z: 101 raw records, run.json, table1_draft.md (real)"
  - "data/traces/ask.jsonl: first real cited answer"
affects: [02, 03]
key-files:
  created: [data/probe/run_20261110T133218Z/requests.jsonl, data/probe/run_20261110T133218Z/run.json, data/probe/run_20261110T133218Z/table1_draft.md, data/traces/ask.jsonl]
  modified: [probe.py, ask.py, tests/test_probe.py, tests/test_ask.py, config.py, docs/QUOTA.md]
decisions:
  - "Attempt 1 (11:33 IST) aborted after the free models list: the plan's Llama models are not on the account; candidates switched to gpt-oss-20b (main), gpt-oss-120b, qwen3.8-27b"
  - "Probe cap raised 6,000 -> 10,000 (Tanush 'go', 13:32 UTC) because the lean upper bound on these models was 12,420"
  - "probe.py pauses if header samples (or the first 3 spaced replies) carry reasoning but no visible text"
  - "ask.py accepts gpt-oss lenticular citations 【id】 and prints NO CITATION FOUND for an uncited answer"
metrics:
  completed: 2026-11-10
  probe_tokens: "9,150 reported (ledger 9,236 incl. 86 reserved for the one 429) vs cap 10,000, upper-bound estimate 12,420"
  ask_tokens: "2,437 vs cap 3,000, estimate 2,677"
---

# Phase 1 Plan 05: Human-gated real run Summary

## What ran

- Gate: Tanush typed "go" in the project thread after seeing the per-stage estimate (12,420 upper bound), the ask estimate (2,677) and the caps (10,000 + 3,000).
- Probe run_20261110T133218Z, lean profile: models list (free), 3 header samples, 50 spaced requests at 4 s, rpm_burst (29 x 200 then one 429), one recovery poll admitted, concurrency 1/2/4/8 (15 x 200). Stopped "done", 100 chat requests.
- One cited answer, setting C, "What is the frame rate of the Mimi codec in Moshi?": "12.5 Hz【moshi-C-040】", TTFT 1,066 ms, 2,437 tokens.

## Deviations

1. **[Rule 1 - Bug] Citation parser missed the real answer's citation.** gpt-oss wrote 【moshi-C-040】, not [moshi-C-040]; map_citations returned nothing and printed nothing. Fixed in ask.py (both bracket kinds; NO CITATION FOUND flag) with a test; the saved answer re-maps offline to "Moshi v1, §5.1 Text Language Modeling", whose text contains 12.5 Hz. No second real call.
2. **[Finding] Reasoning ate max_tokens 16.** 33 of 50 spaced replies (and 11 of 15 concurrency replies) finished with finish_reason "length" and no visible text, so TTFT exists for only 17 spaced replies. The pause guard did not fire because some replies did have text. Table 1's concurrency TTFT medians are therefore thin; total time is available for all.

## Known gaps (for phase 2)

- Tokens per day and daily refill are not in headers; reset-requests (86.4 s per request) suggests a rolling refill, to be confirmed in phase 4.
- RPM measured on gpt-oss-20b only; TPM-limit 429 and recovery not measured (lean profile).
- ask.jsonl trace does not record the retrieved piece ids; add in phase 2.
- REQUEST_OVERHEAD_TOKENS 60 is slightly low for gpt-oss (78 prompt tokens for an ~8-word prompt); the ask estimate was still high overall.
