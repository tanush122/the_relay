"""results.csv: the brief's raw file, one row per request, and its validator.

Exactly the twelve columns the brief names, in its order. Richer detail (steps, retrieved
piece ids, reasoning tokens, the model's own TTFT) goes to traces.jsonl instead.
Rules (docs/DECISIONS.md):
- start_time is the request's arrival time, so the number of requests in the system at
  any moment can be rebuilt from start_time and total_ms (peak queue length).
- Empty-field rule: a field that does not apply is left empty, never guessed. Only two may
  be empty: first_token_ms when nothing model-backed was shown (a refusal before any
  model call, or a failed call), and answer_grade until Tanush grades the row by hand.
- source is "real" only when the request went to api.groq.com; anything else is "stand-in".
"""

import csv
import json
from datetime import datetime

import config
from relay import llm

COLUMNS = ["request_id", "scenario", "source", "start_time", "first_token_ms", "total_ms",
           "status", "retries", "tokens_in", "tokens_out", "retrieval_setting", "answer_grade"]
STATUSES = {"ok", "rate_limited", "timeout", "error"}
GRADES = {"correct", "wrong", "refused_correctly", "refused_wrongly"}
SOURCES = {"real", "stand-in"}
MAY_BE_EMPTY = {"first_token_ms", "answer_grade"}


def row_from(result, scenario, base_url):
    """One results.csv row from a pipeline result (relay.pipeline.new_result)."""
    return {"request_id": result["request_id"], "scenario": scenario,
            "source": "real" if llm.is_real_groq(base_url) else "stand-in",
            "start_time": result["start_time"],
            "first_token_ms": "" if result["first_token_ms"] is None else result["first_token_ms"],
            "total_ms": result["total_ms"], "status": result["status"],
            "retries": result["retries"], "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"], "retrieval_setting": result["setting"],
            "answer_grade": ""}


def append(rows, path=None):
    path = path or config.RESULTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def read(path=None):
    with (path or config.RESULTS_PATH).open(newline="") as f:
        return list(csv.DictReader(f))


def write_all(rows, path=None):
    """Rewrite the whole file (used only to fill in hand grades)."""
    with (path or config.RESULTS_PATH).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def trace(result, scenario, path=None):
    """One JSON line of everything the csv row leaves out."""
    llm.write_trace({"scenario": scenario, **result}, path or config.TRACE_PATH)


def _number(value, integer=False):
    number = int(value) if integer else float(value)
    if number < 0:
        raise ValueError("negative")
    return number


def validate(path=None):
    """A list of problems; empty means the file follows the brief and the rules above."""
    path = path or config.RESULTS_PATH
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)
    if header != COLUMNS:
        return [f"columns are {header}, expected exactly {COLUMNS}"]
    problems, seen = [], set()
    allowed = {"status": STATUSES, "source": SOURCES, "retrieval_setting": set(config.SETTINGS),
               "answer_grade": GRADES | {""}}
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        def bad(text):
            problems.append(f"line {line}: {text}")
        for column in COLUMNS:
            if row[column] == "" and column not in MAY_BE_EMPTY:
                bad(f"{column} is empty")
        for column, values in allowed.items():
            if row[column] not in values:
                bad(f"{column}={row[column]!r} not in {sorted(values)}")
        if row["request_id"] in seen:
            bad(f"duplicate request_id {row['request_id']}")
        seen.add(row["request_id"])
        try:
            datetime.fromisoformat(row["start_time"])
            total = _number(row["total_ms"])
            for column in ("retries", "tokens_in", "tokens_out"):
                _number(row[column], integer=True)
            if row["first_token_ms"] != "" and _number(row["first_token_ms"]) > total:
                bad("first_token_ms is after total_ms")
            if (row["first_token_ms"] == "" and row["status"] == "ok"
                    and _number(row["tokens_out"], integer=True) > 0):
                bad("first_token_ms is empty although a model reply was shown")
        except ValueError as exc:
            bad(f"not a valid time or non-negative number ({exc})")
    return problems


def validate_and_print(path=None):
    if not (path or config.RESULTS_PATH).exists():
        print("No results.csv yet: nothing to validate.")
        return True
    problems = validate(path)
    rows = read(path)
    print(json.dumps({"rows": len(rows), "problems": len(problems)}))
    for problem in problems[:50]:
        print(problem)
    return not problems
