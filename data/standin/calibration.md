| Source | First event p50 / p95 / p99 (ms) | Total p50 / p95 / p99 (ms) |
| --- | --- | --- |
| Real Groq probe (50 spaced tiny requests) | 502 / 752 / 2001 (n=50) | 516 / 753 / 2003 (n=50) |
| Stand-in, same request, time compressed x10 | 551 / 1729 / 2050 (n=200) | 562 / 1742 / 2060 (n=200) |
| Stand-in, same request, time compressed x50 | 634 / 1813 / 2118 (n=200) | 658 / 1836 / 2136 (n=200) |

The stand-in resamples the first-event times of these same 50 spaced requests. What it adds is its own Python overhead, multiplied by the time compression, plus 0.24 ms per prompt token. Load scenarios run at x50.
