"""Print the brief's Tables 2a, 2b and 3 from results.csv, and nothing else.

Every number is computed from the file, so a reviewer can recompute it. Conventions:
- Percentiles are nearest-rank (the smallest value with at least p% of values at or
  below it), printed with the count they rest on: "512 / 690 / 690 (n=17)".
- Times in whole milliseconds, percentages with one decimal.
- "not measured" wherever the file has nothing to compute from.
- Tokens per answer = mean of tokens_in + tokens_out over all rows of the group; a
  refusal made before any model call counts as 0 tokens.
- Peak queue length = the most requests in the system at once, rebuilt from start_time
  (arrival) and total_ms.
"""

import math
from datetime import datetime, timedelta

import config
from relay import results

NM = "not measured"


def percentile(values, p):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def spread(values, ps):
    if not values:
        return NM
    return " / ".join(f"{percentile(values, p):.0f}" for p in ps) + f" (n={len(values)})"


def pct(part, whole):
    return f"{100 * part / whole:.1f}" if whole else NM


def times(rows, column):
    return [float(r[column]) for r in rows if r[column] != ""]


def arrivals(rows):
    return [datetime.fromisoformat(r["start_time"]) for r in rows]


def peak_in_system(rows):
    events = []
    for r, start in zip(rows, arrivals(rows)):
        events += [(start, 1), (start + timedelta(milliseconds=float(r["total_ms"])), -1)]
    level = peak = 0
    for _, change in sorted(events):  # at the same instant, a leaving (-1) sorts first
        level += change
        peak = max(peak, level)
    return peak


def groups(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


def table(header, lines):
    out = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in line) + " |" for line in lines])


def table_2a(rows):
    lines = []
    for name, rs in groups(rows, "scenario").items():
        starts = arrivals(rs)
        ends = [s + timedelta(milliseconds=float(r["total_ms"])) for s, r in zip(starts, rs)]
        span_min = (max(starts) - min(starts)).total_seconds() / 60
        rate = f"{len(rs) / span_min:.1f}" if span_min > 0 else NM
        lines.append([name, " + ".join(sorted({r["source"] for r in rs})), len(rs),
                      f"{(max(ends) - min(starts)).total_seconds():.1f}", rate,
                      spread(times(rs, "first_token_ms"), (50, 95, 99)),
                      spread(times(rs, "total_ms"), (50, 95, 99))])
    return table(["Scenario", "Real or stand-in", "Requests sent", "Duration (s)",
                  "Offered rate (per min)", "First token p50 / p95 / p99 (ms)",
                  "Total time p50 / p95 / p99 (ms)"], lines)


def tokens_per_answer(rs):
    return f"{sum(int(r['tokens_in']) + int(r['tokens_out']) for r in rs) / len(rs):.0f}"


def table_2b(rows):
    lines = []
    for name, rs in groups(rows, "scenario").items():
        count = {s: sum(r["status"] == s for r in rs) for s in results.STATUSES}
        lines.append([name, pct(count["ok"], len(rs)), pct(count["rate_limited"], len(rs)),
                      pct(count["timeout"], len(rs)),
                      f"{sum(int(r['retries']) for r in rs) / len(rs):.2f}",
                      peak_in_system(rs), tokens_per_answer(rs), cost_per_1000(rs)])
    return table(["Scenario", "Succeeded %", "Rate-limited %", "Timed out or given up %",
                  "Retries per request", "Peak queue length", "Tokens per answer",
                  "Cost per 1,000 answers"], lines)


def cost_per_1000(rs):
    price = config.PRICE_PER_MILLION_TOKENS  # list price, set from Groq's pricing page
    if not price:
        return f"{NM} (price not set)"
    dollars = sum(int(r["tokens_in"]) * price["in"] + int(r["tokens_out"]) * price["out"]
                  for r in rs) / 1e6
    return f"${1000 * dollars / len(rs):.2f}"


def setting_label(name):
    s = config.SETTINGS[name]
    split = "section-aware, up to" if s["split"] == "section" else "fixed"
    fetched = f"{s['pieces']} of {s['candidates']}" if s["rerank"] else str(s["pieces"])
    return (f"{name} ({split} {s['piece_tokens']} tokens, {fetched} pieces, "
            f"re-rank {'yes' if s['rerank'] else 'no'})")


def table_3(rows):
    lines = []
    # Only the final system's runs (Tanush, 12 Nov: grade the latest system); earlier
    # evaluation rows stay in results.csv as the record of how it got there.
    evaluated = [r for r in rows if r["scenario"] in config.TABLE3_RUNS]
    for name, rs in sorted(groups(evaluated, "retrieval_setting").items()):
        graded = [r for r in rs if r["answer_grade"]]
        grade = {g: sum(r["answer_grade"] == g for r in graded) for g in results.GRADES}
        note = "" if len(graded) == len(rs) else f" (graded {len(graded)} of {len(rs)})"
        lines.append([setting_label(name), f"{len(rs)}{note}",
                      pct(grade["correct"], len(graded)), pct(grade["wrong"], len(graded)),
                      pct(grade["refused_correctly"], len(graded)), tokens_per_answer(rs),
                      spread(times(rs, "first_token_ms"), (50, 95)),
                      spread(times(rs, "total_ms"), (50, 95))])
    return table(["Setting (piece size, pieces fetched, re-rank yes or no)", "Questions asked",
                  "Correct and cited %", "Wrong %", "Correctly refused %", "Tokens per answer",
                  "First token p50 / p95 (ms)", "Total time p50 / p95 (ms)"], lines)


def print_report(path=None):
    path = path or config.RESULTS_PATH
    if not path.exists():
        print(f"No {path.name} yet: every table is '{NM}'.")
        return
    rows = results.read(path)
    for title, build in (("Table 2a: Latency", table_2a), ("Table 2b: Outcomes", table_2b),
                         ("Table 3: Retrieval settings", table_3)):
        print(f"\n{title} (from {path.name}, {len(rows)} rows)\n")
        print(build(rows))
