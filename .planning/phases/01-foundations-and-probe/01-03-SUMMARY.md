---
phase: 01-foundations-and-probe
plan: 03
subsystem: relay-client
tags: [httpx, sse, streaming, rate-limit-headers, traces, spend-gate]
requires: ["01-01 config.py", "01-02 library.parse/search/pieces"]
provides:
  - "relay/llm.py: load_api_key, redact, estimate_tokens, check_spend, make_client, list_models, stream_chat, write_trace"
  - "ask.py: question -> retrieve -> one streamed cited draft -> mapped citations; --dry-run, --confirm, --max-tokens-total"
  - "tests/fake_groq.py: local 127.0.0.1 SSE fixture server with x-ratelimit-* headers and 429"
affects: [01-04, 01-05, phase-3 stand-in]
tech-stack:
  added: []
  patterns: ["one base URL switch (config.BASE_URL / RELAY_BASE_URL)", "refuse before any work unless confirmed and capped", "request headers never recorded"]
key-files:
  created: [relay/llm.py, ask.py, tests/fake_groq.py, tests/test_llm.py, tests/test_ask.py]
  modified: []
decisions:
  - "ask.py dry-run estimate = estimate_tokens(all message text) + ANSWER_MAX_TOKENS (upper bound on output)"
metrics:
  duration: "~3 min"
  completed: 2026-11-10
  tasks: 2
  files: 5
---

# Phase 1 Plan 03: Streaming client and thin cited path Summary

This plan adds an async httpx client that streams one OpenAI-compatible chat call. For each call it records time to first content token (TTFT), total time, usage, every response header, the status, a redacted error body and a redacted exception, and writes them as one JSON trace line. It also adds `ask.py`, which runs question → retrieve → one streamed draft → citations mapped in code. Real mode refuses unless both `--confirm` and `--max-tokens-total` are given. Everything was tested against a local fake server only. No real Groq call was made.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Streaming client, trace lines, fake server, 9 tests | 93b8805 |
| 2 | ask.py thin path, dry run, spend gate, 5 tests | 9af2fa9 |

## Record fields (stream_chat)

request_id, tag, model, url, sent_at (UTC ISO), status, headers (every response header, verbatim), ttft_ms (first non-empty delta.content), first_reasoning_ms, total_ms, content, reasoning_chars, delta_keys, usage (from `usage` or `x_groq.usage`, last one seen), x_groq, final_chunk, error_body (redacted), exception (redacted, as "Type: message").

`list_models` records: url, sent_at, status, headers, ids, error_body, exception, total_ms.

httpx lowercases header names and joins repeated headers with ", " (noted in a code comment). Request headers are never put in the record, so the Authorization header cannot reach a trace.

## Dry-run output (real retrieval over the downloaded papers; no request sent)

```
$ uv run python ask.py "What is d_ff in Attention Is All You Need?" --setting C --dry-run
attention-C-010    0.5368  Attention v7, §3.3 Position-wise Feed-Forward Networks
attention-C-024   -2.6851  Attention v7, §6.2 Model Variations
attention-C-008   -4.3685  Attention v7, §3.2.2 Multi-Head Attention
attention-C-013   -4.4617  Attention v7, §4 Why Self-Attention
Estimated spend: 1903 tokens (dry run: no request sent)
```

The run took 10.9 s, mostly model load and index build.

Refusal without flags:

```
$ uv run python ask.py "What is d_ff in Attention Is All You Need?"
Refusing real call: pass --confirm after reviewing the estimate
```

It exited with code 2 in 0.44 s, before any model load. `data/traces/` does not exist, which confirms that no real call and no dry run wrote a trace.

## Verification

- `pytest -q tests/test_llm.py`: 9 passed.
- `pytest -q tests/test_ask.py tests/test_llm.py -rs`: 14 passed, none skipped.
- Full suite: 37 passed, 1 xfailed. The xfail is the setting-A H-Net ratio-loss miss from 01-02, kept on purpose.
- Grep checks:
  - `api_key` together with print/log in relay/llm.py: 0 matches.
  - `groq.com` in relay/llm.py: 0 matches.
  - Key-shaped `gsk_` strings in llm.py, test_llm.py and fake_groq.py: 0 matches each.
- No proxy environment variables are set. All test traffic goes to 127.0.0.1.

## Line counts (non-blank)

| File | Lines | Target |
|------|-------|--------|
| relay/llm.py | 132 | ~95 |
| ask.py | 77 | ~55 |
| tests/fake_groq.py | 111 | — |
| tests/test_llm.py | 86 | — |
| tests/test_ask.py | 60 | — |

Overruns were not compressed:
- llm.py is over because the record dict is spelled out field by field, `list_models` has its own error handling, and the docstrings explain the reasoning.
- ask.py is over because of the argparse flags and the explicit early-refusal lines.

Non-test code so far (config, library, relay, ask.py) is 627 lines, against the phase-1 target of about 400–500.

## Deviations from Plan

1. `fake_groq` runs `serve_forever` with `poll_interval=0.05`. This cuts each test teardown from 0.5 s to about 0.05 s and does not change behaviour.
2. `ask.draft` also prints a "Request failed: status … " line when the status is not 200 or an exception was recorded. Without it, a real 429 would show only empty output.
3. The dry run and ask.py still let sentence-transformers contact huggingface.co to check the model (the unauthenticated-request warning appears). This is not Groq traffic and spends no tokens. Setting `HF_HUB_OFFLINE=1` once the models are cached would stop it; that is left for Tanush to decide.

## Known Stubs

None.

## Self-Check: PASSED

All files exist. Commits 93b8805 and 9af2fa9 are in git log. No file was written under data/traces.
