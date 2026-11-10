"""Run Tanush's questions under one retrieval setting and write a sheet he grades by hand.

Questions come from data/questions.csv (question, expected, type), written by Tanush; this
code never writes questions, answers or grades. Each run appends one results.csv row and
one trace line per question, and writes data/grading/<scenario>_<time>.csv with an empty
"grade" column. `python -m relay grade <sheet>` copies his grades into results.csv.

Spending: the estimate for every question is printed first (retrieval is local and free).
The run refuses without --confirm and --max-tokens-total, and stops before a question
whose estimate would take actual spend past the cap. It paces itself on Groq's headers:
when the tokens left this minute are fewer than the next estimate, it waits for the reset
Groq reports. That is the only rate control here; the gateway arrives in phase 3.
"""

import asyncio
import csv
import re
from datetime import datetime, timezone

import config
from relay import llm, pipeline, results

QUESTION_COLUMNS = ["question", "expected", "type"]
TYPES = {"prose", "table", "cross-paper", "unanswerable"}
SHEET_COLUMNS = ["request_id", "setting", "type", "question", "expected", "outcome", "reply",
                 "citations", "strength", "grade"]


def load_questions(path=None):
    """Rows of data/questions.csv; raises ValueError naming the first problem."""
    path = path or config.QUESTIONS_PATH
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != QUESTION_COLUMNS:
            raise ValueError(f"{path} must have the columns {QUESTION_COLUMNS}")
        rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    for line, row in enumerate(rows, start=2):
        if not row["question"].strip() or not row["expected"].strip():
            raise ValueError(f"{path} line {line}: question and expected must both be filled")
        if row["type"] not in TYPES:
            raise ValueError(f"{path} line {line}: type must be one of {sorted(TYPES)}")
    if not rows:
        raise ValueError(f"{path} has no questions yet")
    return rows


def estimate(index, question):
    """Upper-bound tokens for one question; 0 if it would be refused before any model call."""
    try:
        cleaned, papers = pipeline.understand(question)
    except ValueError:
        return 0
    pieces, _ = pipeline.retrieve_and_decide(index, cleaned, papers)
    return 0 if pieces is None else pipeline.fit_to_ceiling(cleaned, pieces)[2]


def reset_seconds(text):
    """Groq's reset header ("7.66s", "1m26.4s", "250ms") in seconds; None if unreadable."""
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", text or "")
    if not parts:
        return None
    scale = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return sum(float(n) * scale[unit] for n, unit in parts)


async def run(questions, index, api_key, cap, base_url=None, sheet_path=None):
    """Ask every question once; return (results, spent). Stops before passing the cap."""
    scenario = f"eval-{index['setting']}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sheet_path = sheet_path or config.GRADING_DIR / f"{scenario}_{stamp}.csv"
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    spent, done, headers = 0, [], {}
    async with llm.make_client() as client:
        for q in questions:
            need = estimate(index, q["question"])
            if spent + need > cap:
                print(f"Stopping before passing the cap: {spent} spent, next needs ~{need}")
                break
            left = headers.get("x-ratelimit-remaining-tokens", "")
            wait = reset_seconds(headers.get("x-ratelimit-reset-tokens"))
            if headers.get("retry-after"):  # the last call was refused: wait as Groq asks
                wait, left = float(headers["retry-after"]), "0"
            if need and left.isdigit() and int(left) < need and wait:
                print(f"Waiting {wait:.1f} s for the per-minute token budget to refill")
                await asyncio.sleep(wait)
            result = await pipeline.answer(q["question"], index, client, api_key, base_url)
            spent += result["tokens_in"] + result["tokens_out"]
            if result["model_record"]:  # a refusal before any model call leaves headers as they were
                headers = result["model_record"]["headers"]
            results.append([results.row_from(result, scenario, base_url or config.BASE_URL)])
            results.trace(result, scenario)
            done.append((q, result))
            print(f"{len(done):3d} {result['outcome']:<18} {result['total_ms']:>9} ms "
                  f"{result['tokens_in'] + result['tokens_out']:>5} tok  {q['question'][:60]}")
    write_sheet(done, sheet_path)
    print(f"Spent {spent} tokens (cap {cap}). Grade by hand: {sheet_path}")
    return done, spent


def write_sheet(done, path):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for q, r in done:
            strength = r["attempts"][-1]["strength"] if r["attempts"] else ""
            writer.writerow({"request_id": r["request_id"], "setting": r["setting"],
                             "type": q["type"], "question": q["question"],
                             "expected": q["expected"], "outcome": r["outcome"],
                             "reply": r["reply"], "citations": " | ".join(r["citations"]),
                             "strength": strength, "grade": ""})


def apply_grades(sheet_path, results_path=None):
    """Copy the sheet's hand grades into results.csv by request_id; returns how many."""
    with sheet_path.open(newline="") as f:
        grades = {r["request_id"]: r["grade"].strip() for r in csv.DictReader(f)}
    wrong = {g for g in grades.values() if g and g not in results.GRADES}
    if wrong:
        raise ValueError(f"grades must be one of {sorted(results.GRADES)}, got {sorted(wrong)}")
    rows = results.read(results_path)
    count = 0
    for row in rows:
        if grades.get(row["request_id"]):
            row["answer_grade"] = grades[row["request_id"]]
            count += 1
    results.write_all(rows, results_path)
    return count
