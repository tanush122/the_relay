"""Draft Table 1 (Groq's real limits) from the raw probe files, and nothing else.

Every value comes from requests.jsonl or run.json written by probe.py; there are no
hand-typed numbers. Anything the files cannot show is written as "not measured", and
values that rest on Groq's docs rather than an observation are marked "medium".

  uv run python table1.py [data/probe/run_...]
"""

import json
import re
import statistics
import sys
from pathlib import Path

import config

ROWS = ["Requests per minute", "Tokens per minute", "Requests per day", "Tokens per day",
        "Requests in flight at once", "What it returns when a limit is hit",
        "Time until it recovers"]
LIMIT_IN_BODY = re.compile(r"\((RPM|TPM|RPD|TPD)\): Limit (\d+)")
NOT_MEASURED = "not measured"


def load_run(run_dir=None):
    """(records, summary) from a run directory; default is the newest run under PROBE_DIR."""
    if run_dir is None:
        runs = sorted(config.PROBE_DIR.glob("run_*"))
        if not runs:
            return [], {}
        run_dir = runs[-1]
    lines = (Path(run_dir) / "requests.jsonl").read_text().splitlines()
    summary = json.loads((Path(run_dir) / "run.json").read_text())
    return [json.loads(line) for line in lines], summary


def row(limit, value=NOT_MEASURED, how="no probe evidence", confidence=NOT_MEASURED):
    return {"Limit": limit, "Value found": value, "How found": how, "Confidence": confidence}


def limit_from_429(records, kind):
    """(value, how) from the first 429 body naming this limit, e.g. "(RPM): Limit N"."""
    for r in records:
        match = LIMIT_IN_BODY.search(r.get("error_body") or "")
        if r.get("status") == 429 and match and match.group(1) == kind:
            return f"{match.group(2)} ({r['model']})", f"429 body during {r['stage']}"
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
            seen.setdefault(r["model"], set()).add(r["headers"][header])
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


def in_flight(records):
    levels = {}
    for r in records:
        if r.get("stage") == "concurrency":
            levels.setdefault(int(r["group"].split("-")[1]), []).append(r)
    clean = [n for n, rs in sorted(levels.items()) if all(r["status"] == 200 for r in rs)]
    if not clean:
        return row(ROWS[4])
    per_level = []
    for n, rs in sorted(levels.items()):
        ttfts = [r["ttft_ms"] for r in rs if r["ttft_ms"]]
        statuses = ",".join(str(r["status"]) for r in rs)
        median = f"{statistics.median(ttfts):.0f} ms" if ttfts else "n/a"
        per_level.append(f"{n}: TTFT median {median}, statuses {statuses}")
    # A non-200 at a higher level may be the per-minute limit, not a concurrency cap.
    return row(ROWS[4], f">= {max(clean)} (no cap observed up to {max(clean)})",
               f"concurrency ramp; {'; '.join(per_level)}", "low")


def on_limit(errors):
    if not errors:
        return row(ROWS[5])
    first = errors[0]
    try:
        err = json.loads(first["error_body"])["error"]
    except (TypeError, ValueError, KeyError):
        err = {"type": "unparsed", "message": first.get("error_body") or ""}
    value = (f"HTTP 429, retry-after: {first['headers'].get('retry-after')}, error type: "
             f"{err.get('type')}; \"{(err.get('message') or '')[:120]}\"")
    return row(ROWS[5], value, f"first 429 response, stage {first['stage']}", "high")


def recovery(errors, summary):
    rpm, tpm = summary.get("recovery_rpm_s"), summary.get("recovery_tpm_s")
    if rpm is None and tpm is None:
        return row(ROWS[6], how="no recovery observed; daily reset not measured (phase 4)")
    shown = [f"{name}: {v} s" if v is not None else f"{name}: {NOT_MEASURED}"
             for name, v in (("RPM", rpm), ("TPM", tpm))]
    retry = errors[0]["headers"].get("retry-after") if errors else None
    value = "; ".join(shown) + f"; retry-after seen: {retry}; daily reset not measured (phase 4)"
    how = ("time from a burst's first 429 until a tiny request was re-admitted "
           f"(poll every {summary.get('recovery_poll_interval_s')} s)")
    return row(ROWS[6], value, how, "medium")  # poll granularity; tiny re-admission only


def build_table1(records, summary):
    errors = [r for r in records if r.get("status") == 429]
    tpd_value, tpd_how = limit_from_429(records, "TPD")
    return [
        per_minute_requests(records),
        from_header(records, ROWS[1], "x-ratelimit-limit-tokens", "TPM", "minute"),
        from_header(records, ROWS[2], "x-ratelimit-limit-requests", "RPD", "day"),
        row(ROWS[3], tpd_value, tpd_how, "high") if tpd_value else
        row(ROWS[3], how="not in headers; read limits page or confirm in phase 4"),
        in_flight(records),
        on_limit(errors),
        recovery(errors, summary),
    ]


def render_markdown(rows):
    lines = ["| Limit | Value found | How found | Confidence |", "| --- | --- | --- | --- |"]
    lines += [f"| {r['Limit']} | {r['Value found']} | {r['How found']} | {r['Confidence']} |"
              for r in rows]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    runs = sorted(config.PROBE_DIR.glob("run_*"))
    run_dir = Path(argv[0]) if argv else (runs[-1] if runs else None)
    records, summary = load_run(run_dir) if run_dir else ([], {})
    if not records:
        print("No probe has been run yet: every row is 'not measured'.")
    table = render_markdown(build_table1(records, summary))
    print(table)
    if records:
        (run_dir / "table1_draft.md").write_text(table + "\n")


if __name__ == "__main__":
    main()
