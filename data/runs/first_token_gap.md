| Run | Requests | Model's first visible token p50 / p95 (ms) | results.csv first_token_ms p50 / p95 (ms) | Median gap (ms) |
| --- | --- | --- | --- | --- |
| eval-C | 18 | 844 / 2088 | 1613 / 2602 | 642 |
| eval-A | 18 | 903 / 3215 | 1347 / 3764 | 64 |
| eval-B | 18 | 1061 / 2385 | 1855 / 3804 | 774 |
| eval-C2 | 18 | 930 / 2838 | 1711 / 3282 | 705 |

Model's first visible token: from sending the request. results.csv first_token_ms: from the question's arrival (before retrieval) to when the checked reply is shown; for these 72 replies, re-checked offline on 12 Nov, it is the end of the reply plus the measured check time (an upper bound: no per-chunk times were kept then). Since 12 Nov 19:10 IST traces record when each paragraph is shown.
