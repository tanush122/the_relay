Source: probe run run_20261110T133218Z against api.groq.com, stopped: done.

| Limit | Value found | How found | Confidence |
| --- | --- | --- | --- |
| Requests per minute | 30 (openai/gpt-oss-20b) | 429 body during rpm_burst [run run_20261110T133218Z, host api.groq.com] | high |
| Tokens per minute | openai/gpt-oss-120b=8000; openai/gpt-oss-20b=8000; qwen/qwen3.8-27b=8000 | x-ratelimit-limit-tokens header on 98 responses (docs: per-minute) [run run_20261110T133218Z, host api.groq.com] | medium |
| Requests per day | openai/gpt-oss-120b=1000; openai/gpt-oss-20b=1000; qwen/qwen3.8-27b=1000 | x-ratelimit-limit-requests header on 99 responses (docs: per-day) [run run_20261110T133218Z, host api.groq.com] | medium |
| Tokens per day | 200000 (openai/gpt-oss-20b) | 429 body during real run eval-final-B at 2026-11-13T03:51:07Z | high |
| Requests in flight at once | >= 8 (no cap observed up to 8) | concurrency ramp; 1: total median 1176 ms, statuses 200, 1 of 1 with visible text; 2: total median 595 ms, statuses 200,200, 0 of 2 with visible text; 4: total median 508 ms, statuses 200,200,200,200, 0 of 4 with visible text; 8: total median 560 ms, statuses 200,200,200,200,200,200,200,200, 1 of 8 with visible text [run run_20261110T133218Z, host api.groq.com] | low |
| What it returns when a limit is hit | HTTP 429 (RPM), retry-after: 2, error type: requests; "Rate limit reached for model `openai/gpt-oss-20b` in organization `org_[REDACTED]` service tier `on_demand` on requests " | first 429 response, stage rpm_burst [run run_20261110T133218Z, host api.groq.com] | high |
| Time until it recovers | RPM: 6.187 s after a 429 naming RPM (its retry-after: 2); TPM: not measured; TPD: retry-after 1201 s for 2779 tokens over the limit, i.e. a continuous refill of ~8,330 tokens/h (limit/24 h = 8,333), not a reset at a fixed time (real run eval-final-B at 2026-11-13T03:51:07Z) | from the arrival of a burst's first 429 to the sending of the first re-admitted tiny request; polled every 5.0 s, so the true value is up to one poll earlier [run run_20261110T133218Z, host api.groq.com] | medium |
