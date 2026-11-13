# Daily window: what the headers and the console say (13 Nov, 08:42 IST)

From data/traces/traces.jsonl, every real Groq response of 12 Nov (eval-*, ask): 74 responses
carry rate-limit headers, the first at 12:00:22 UTC, the last at 13:52:39 UTC.

| Response (UTC, 12 Nov) | Run | remaining-requests / limit | reset-requests | remaining-tokens / limit (per minute) | reset-tokens |
| --- | --- | --- | --- | --- | --- |
| 13:03:54 | eval-C2 (last of that run) | 956 / 1000 | 1h3m21.6s | 1556 / 8000 | 48.33s |
| 13:52:36 | eval-final-interrupted | 988 / 1000 | 17m16.8s | 5547 / 8000 | 18.397s |
| 13:52:39 | eval-final-interrupted (last real call) | 987 / 1000 | 18m43.2s | 3778 / 8000 | 31.665s |

- Requests per day refill continuously, not at a fixed time: 956 remaining at 13:03 rose to
  988 by 13:52 with only 1 call in between (32 refilled in 49 min, about one per 86 s =
  1000 / 24 h), and reset-requests counts down the time to a full bucket.
- Groq's console (Tanush, 13 Nov 03:12 UTC = 08:42 IST) still showed 74 API calls: exactly
  the 74 real responses above, made since 12:00 UTC on 12 Nov. The console's count is a
  rolling 24 h window, not a calendar day.
- Tokens per day is not in any header. Real tokens on 12 Nov: 182,969 (docs/QUOTA.md) plus
  4,687 in the 2 interrupted rows = 187,656, with no 429. If the documented 200,000 a day is
  the same rolling 24 h window, about 12,000 tokens are free before ~17:30 IST today.
  This is an inference, not a measurement: Table 1's tokens-per-day row stays at
  "not measured (no 429 at 187,656 tokens in about 2 h)".

## Update after eval-final-C (13 Nov, 03:24-03:29 UTC)

- First response at 03:24:04 UTC: remaining-requests 999 / 1000, reset-requests 1m26.4s;
  remaining-tokens 5,529 / 8,000. The header's request bucket was full again, while the console
  still counted 74 calls in 24 h: the console count and the header bucket measure different things.
- 18 calls, 48,026 tokens, no 429 of any kind. Tokens in the 24 h before 03:29 UTC: 187,656
  (12 Nov, from 12:00 UTC) + 48,026 = 235,682, all inside one rolling 24 h window. So the
  "about 12,000 tokens left" inference above was wrong: no daily-limit 429 at 235,682 tokens.
  Table 1 tokens per day: "not reached at 235,682 tokens in a rolling 24 h (no 429)", low confidence.

## The daily limit, reached (13 Nov, 03:51:07 UTC, eval-final-B question 18)

Groq's 429 body (organisation id removed): "Rate limit reached for model `openai/gpt-oss-20b` ...
on tokens per day (TPD): Limit 200000, Used 199263, Requested 3516. Please try again in
20m0.528s." Headers: retry-after 1201, x-should-retry false, remaining-requests 953 / 1000,
remaining-tokens 8000 / 8000 (the minute budget was full; only the day was spent).
Full body and headers: data/traces/traces.jsonl, request of eval-final-B at 03:51:07.

- Tokens per day = 200,000 (high confidence: named in the 429 body).
- Refill: 199,263 + 3,516 - 200,000 = 2,779 tokens over, ready in 1,201 s = ~8,330 tokens an
  hour = 200,000 / 24 h. The daily budget is a bucket that refills continuously.
- That is why no 429 came at 235,682 tokens in 24 h earlier: by then about 8,300 tokens an hour
  had flowed back in since 12 Nov. Our ledger has 331,195 real tokens from 12 Nov 12:00 UTC to
  this 429; Groq counted 199,263 in the bucket.
