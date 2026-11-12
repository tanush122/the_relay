| Source | First event p50 / p95 / p99 (ms) | Total p50 / p95 / p99 (ms) |
| --- | --- | --- |
| Real Groq probe (50 spaced tiny requests) | 502 / 752 / 2001 (n=50) | 516 / 753 / 2003 (n=50) |
| Stand-in, same request, time compressed x10 | 536 / 1713 / 2029 (n=200) | 546 / 1724 / 2041 (n=200) |
| Stand-in, same request, time compressed x50 | 616 / 1774 / 2130 (n=200) | 638 / 1790 / 2153 (n=200) |
| Real Groq evaluation replies (prompts 1,601-3,103 tokens) | 906 / 2292 / 3167 (n=54) | 1168 / 2608 / 3576 (n=54) |
| Stand-in, ~2,000-token prompt, x50 | 1002 / 2400 / 3296 (n=200) | 1088 / 2459 / 3365 (n=200) |

Small prompts: the stand-in resamples the first-event times of the probe's 50 spaced requests; large prompts: those of the 54 real evaluation replies. What it adds is its own Python overhead, multiplied by the time compression. Load scenarios run at x50. The p95 gap is the probe's small sample, not the stand-in: 2 of its 50 values are 1.8-2.0 s, so its own p95 (752 ms) sits just below them and its p96 is already 1,819 ms; 200 resamples land on them.
