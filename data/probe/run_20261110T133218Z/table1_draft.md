Source: probe run run_20261110T133218Z against api.groq.com, stopped: done.

| Limit | Value found | How found | Confidence |
| --- | --- | --- | --- |
| Requests per minute | 30 (openai/gpt-oss-20b) | 429 body during rpm_burst [run run_20261110T133218Z, host api.groq.com] | high |
| Tokens per minute | openai/gpt-oss-120b=8000; openai/gpt-oss-20b=8000; qwen/qwen3.8-27b=8000 | x-ratelimit-limit-tokens header on 98 responses (docs: per-minute) [run run_20261110T133218Z, host api.groq.com] | medium |
| Requests per day | openai/gpt-oss-120b=1000; openai/gpt-oss-20b=1000; qwen/qwen3.8-27b=1000 | x-ratelimit-limit-requests header on 99 responses (docs: per-day) [run run_20261110T133218Z, host api.groq.com] | medium |
| Tokens per day | not measured | not in headers; read limits page or confirm in phase 4 [run run_20261110T133218Z, host api.groq.com] | not measured |
| Requests in flight at once | >= 8 (no cap observed up to 8) | concurrency ramp; 1: TTFT median 1176 ms, statuses 200; 2: TTFT median n/a, statuses 200,200; 4: TTFT median n/a, statuses 200,200,200,200; 8: TTFT median 283 ms, statuses 200,200,200,200,200,200,200,200 [run run_20261110T133218Z, host api.groq.com] | low |
| What it returns when a limit is hit | HTTP 429 (RPM), retry-after: 2, error type: requests; "Rate limit reached for model `openai/gpt-oss-20b` in organization `org_[REDACTED]` service tier `on_demand` on requests " | first 429 response, stage rpm_burst [run run_20261110T133218Z, host api.groq.com] | high |
| Time until it recovers | RPM: 6.187 s after a 429 naming RPM (its retry-after: 2); TPM: not measured; daily reset not measured (phase 4) | from the arrival of a burst's first 429 to the sending of the first re-admitted tiny request; polled every 5.0 s, so the true value is up to one poll earlier [run run_20261110T133218Z, host api.groq.com] | medium |
