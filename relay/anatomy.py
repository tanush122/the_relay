"""Where one slow request's time went: waiting, working, retrying, before and after the
first token. Read from its trace spans (data/traces/traces.jsonl), nothing estimated.

  waiting   = time in the gateway queue and in back-off pauses between attempts
  working   = retrieval and the model attempt that produced the reply
  retrying  = model attempts that failed (timeout, 429, 5xx), whose time was lost
  handoffs  = the small gaps between spans (task switches inside the gateway)

"Before first token" ends at the request's first_token_ms, measured from its arrival:
the moment the person first saw anything (shown text, a gap note or a refusal).
"""

import json

import config


def category(span):
    if span["name"] in ("queue", "backoff"):
        return "waiting"
    if span["name"] == "model" and span.get("exception"):
        return "retrying"
    if span["name"] == "model" and span.get("status") not in (None, 200):
        return "retrying"
    return "working"


def split(trace):
    """Milliseconds per category, before and after the first token."""
    cut = trace["first_token_ms"] if trace["first_token_ms"] is not None else trace["total_ms"]
    parts, cursor = [], 0.0
    for span in sorted(trace["spans"], key=lambda s: s["start_ms"]):
        if span["start_ms"] > cursor:
            parts.append(("handoffs", cursor, span["start_ms"]))
        parts.append((category(span), span["start_ms"], span["end_ms"]))
        cursor = max(cursor, span["end_ms"])
    if trace["total_ms"] > cursor:
        parts.append(("handoffs", cursor, trace["total_ms"]))
    out = {}
    for name, start, end in parts:
        before = max(0.0, min(end, cut) - start)
        after = max(0.0, end - max(start, cut))
        b, a = out.get(name, (0.0, 0.0))
        out[name] = (b + before, a + after)
    return out, parts


def load(scenario):
    with config.TRACE_PATH.open() as f:
        return [t for t in map(json.loads, f) if t["scenario"] == scenario]


def slowest(scenario, request_id=None):
    traces = load(scenario)
    if request_id:
        return next(t for t in traces if t["request_id"] == request_id)
    answered = [t for t in traces if t["status"] == "ok"]
    retried = [t for t in answered if t["retries"]]  # the slowest one that shows all three parts
    return max(retried or answered, key=lambda t: t["total_ms"])


def print_anatomy(scenario, request_id=None):
    t = slowest(scenario, request_id)
    out, parts = split(t)
    scale = 1 / config.LOAD_TIME_SCALE if scenario in config.SCENARIOS else 1
    print(f"Request {t['request_id']} ({scenario}, {t['status']}, {t['outcome']}, "
          f"{t['retries']} retries)")
    print(f"First token {t['first_token_ms']:.0f} ms, total {t['total_ms']:.0f} ms after arrival"
          + (f" (model time; x{scale:.0f} compressed on the stand-in)" if scale != 1 else ""))
    print("\n| Part | Before first token (ms) | After first token (ms) |\n| --- | --- | --- |")
    for name in ("waiting", "working", "retrying", "handoffs"):
        b, a = out.get(name, (0.0, 0.0))
        print(f"| {name} | {b:.0f} | {a:.0f} |")
    print("\nSpans in order (ms after arrival):")
    for name, start, end in parts:
        print(f"  {start:8.0f} - {end:8.0f}  {name}")
    print(f"\nShown to the person (ms after arrival, what): {t.get('release_ms')}")
    print(f"Reply: {t['reply'][:300]!r}")
