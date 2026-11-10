"""Draft Table 1 (Groq's real limits) from the raw probe files, and nothing else.

Every value comes from requests.jsonl or run.json written by probe.py; there are no
hand-typed numbers. Anything the files cannot show is written as "not measured", and
values that rest on Groq's docs rather than an observation are marked "medium".
A run that did not target api.groq.com (the test fake, the phase-3 stand-in) is never
presented as Groq: the draft is headed NOT GROQ and every confidence becomes "none".

  uv run python table1.py [data/probe/run_...]
"""

import json
import statistics
import sys
from pathlib import Path

import config
from relay import llm

ROWS = ["Requests per minute", "Tokens per minute", "Requests per day", "Tokens per day",
        "Requests in flight at once", "What it returns when a limit is hit",
        "Time until it recovers"]
NOT_MEASURED = "not measured"


def load_run(run_dir):
    """(records, summary) from one run directory. A missing run.json means the run was cut off."""
    lines = (Path(run_dir) / "requests.jsonl").read_text().splitlines()
    summary_path = Path(run_dir) / "run.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
    else:
        summary = {"stopped_reason": "incomplete: run.json missing"}
    return [json.loads(line) for line in lines], summary


def row(limit, value=NOT_MEASURED, how="no probe evidence", confidence=NOT_MEASURED):
    return {"Limit": limit, "Value found": value, "How found": how, "Confidence": confidence}


def model_of(record):
    return record.get("model") or "models-endpoint"


def limit_from_429(records, kind):
    """(value, how) from the first 429 body naming this limit, e.g. "(RPM): Limit N"."""
    for r in records:
        match = llm.LIMIT_IN_BODY.search(r.get("error_body") or "")
        if r.get("status") == 429 and match and match.group(1) == kind:
            return f"{match.group(2)} ({model_of(r)})", f"429 body during {r.get('stage')}"
    return None, None


def per_minute_requests(records):
    value, how = limit_from_429(records, "RPM")
    if value:
        return row(ROWS[0], value, how, "high")
    burst = [r for r in records if r.get("stage") == "rpm_burst"]
    if any(r["status"] == 429 for r in burst):
        admitted = sum(r["status"] == 200 for r in burst)
        return row(ROWS[0], f"<= {len(burst)}, exact unconfirmed ({admitted} admitted)",
                   "429 during rpm_burst without a limit in the body", "low")
    return row(ROWS[0], how="not in headers; read limits page or confirm in phase 4")


def from_header(records, limit, header, kind, period):
    """A limit Groq's docs say a header reports; a 429 body naming it upgrades confidence."""
    seen = {}
    for r in records:
        if header in r.get("headers", {}):
            seen.setdefault(model_of(r), set()).add(r["headers"][header])
    count = sum(header in r.get("headers", {}) for r in records)
    body_value, body_how = limit_from_429(records, kind)
    if not seen and not body_value:
        return row(limit)
    values = [f"{m}={','.join(sorted(v))}" for m, v in sorted(seen.items())]
    hows = [f"{header} header on {count} responses (docs: per-{period})"] if seen else []
    if body_value:
        values.append(f"429 body: {body_value}")
        hows.append(body_how)
    return row(limit, "; ".join(values), "; ".join(hows), "high" if body_value else "medium")


def tokens_per_day(records):
    value, how = limit_from_429(records, "TPD")
    if value:
        return row(ROWS[3], value, how, "high")
    return row(ROWS[3], how="not in headers; read limits page or confirm in phase 4")


def in_flight(records):
    levels = {}
    for r in records:
        if r.get("stage") == "concurrency":
            levels.setdefault(int(r["group"].split("-")[1]), []).append(r)
    # The largest N such that every level up to and including N was all 200s.
    best = 0
    for n in sorted(levels):
        if not all(r["status"] == 200 for r in levels[n]):
            break
        best = n
    if best == 0:
        return row(ROWS[4])
    per_level = []
    for n, rs in sorted(levels.items()):
        ttfts = [r["ttft_ms"] for r in rs if r["ttft_ms"]]
        statuses = ",".join(str(r["status"]) for r in rs)
        median = f"{statistics.median(ttfts):.0f} ms" if ttfts else "n/a"
        per_level.append(f"{n}: TTFT median {median}, statuses {statuses}")
    # A non-200 at a higher level may be the per-minute limit, not a concurrency cap.
    return row(ROWS[4], f">= {best} (no cap observed up to {best})",
               f"concurrency ramp; {'; '.join(per_level)}", "low")


def on_limit(errors):
    if not errors:
        return row(ROWS[5])
    first = errors[0]
    try:
        err = json.loads(first["error_body"])["error"]
    except (TypeError, ValueError, KeyError):
        err = {"type": "unparsed", "message": first.get("error_body") or ""}
    value = (f"HTTP 429 ({first.get('limit_kind') or 'limit not named'}), retry-after: "
             f"{first['headers'].get('retry-after')}, error type: {err.get('type')}; "
             f"\"{(err.get('message') or '')[:120]}\"")
    return row(ROWS[5], value, f"first 429 response, stage {first['stage']}", "high")


def recovery(errors, summary):
    rpm, tpm = summary.get("recovery_rpm_s"), summary.get("recovery_tpm_s")
    if rpm is None and tpm is None:
        return row(ROWS[6], how="no recovery observed; daily reset not measured (phase 4)")
    shown = []
    for kind, seconds in (("RPM", rpm), ("TPM", tpm)):
        if seconds is None:
            shown.append(f"{kind}: {NOT_MEASURED}")
            continue
        retry = next((e["headers"].get("retry-after") for e in errors
                      if e.get("limit_kind") == kind), None)
        shown.append(f"{kind}: {seconds} s after a 429 naming {kind} "
                     f"(its retry-after: {retry})")
    value = "; ".join(shown) + "; daily reset not measured (phase 4)"
    how = ("from the arrival of a burst's first 429 to the sending of the first re-admitted "
           f"tiny request; polled every {summary.get('recovery_poll_interval_s')} s, "
           "so the true value is up to one poll earlier")
    return row(ROWS[6], value, how, "medium")  # poll granularity; tiny re-admission only


def build_table1(records, summary):
    errors = [r for r in records if r.get("status") == 429]
    return [
        per_minute_requests(records),
        from_header(records, ROWS[1], "x-ratelimit-limit-tokens", "TPM", "minute"),
        from_header(records, ROWS[2], "x-ratelimit-limit-requests", "RPD", "day"),
        tokens_per_day(records),
        in_flight(records),
        on_limit(errors),
        recovery(errors, summary),
    ]


def label_source(rows, summary, run_name):
    """Name the run and host in every row; a non-Groq run gets confidence "none". Returns a banner."""
    host = summary.get("base_url_host") or "unknown host"
    for r in rows:
        r["How found"] += f" [run {run_name}, host {host}]"
    banner = f"Source: probe run {run_name} against {host}, stopped: {summary.get('stopped_reason')}."
    if host != llm.GROQ_HOST:
        for r in rows:
            r["Confidence"] = f"none (NOT GROQ: {host})"
        banner = (f"NOT GROQ: run {run_name} targeted {host}, not {llm.GROQ_HOST}. "
                  "These are fixture or stand-in values, NOT Groq's limits.")
    return banner


def render_markdown(rows):
    lines = ["| Limit | Value found | How found | Confidence |", "| --- | --- | --- | --- |"]
    lines += [f"| {r['Limit']} | {r['Value found']} | {r['How found']} | {r['Confidence']} |"
              for r in rows]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    runs = sorted(config.PROBE_DIR.glob("run_*"))
    run_dir = Path(argv[0]) if argv else (runs[-1] if runs else None)
    if run_dir is None:
        print("No probe has been run yet: every row is 'not measured'.")
        print(render_markdown(build_table1([], {})))
        return
    records, summary = load_run(run_dir)
    rows = build_table1(records, summary)
    banner = label_source(rows, summary, run_dir.name)
    draft = f"{banner}\n\n{render_markdown(rows)}\n"
    print(draft, end="")
    (run_dir / "table1_draft.md").write_text(draft)


if __name__ == "__main__":
    main()
