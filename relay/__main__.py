"""The one command: `uv run python -m relay <ask|eval|grade|report|validate>`.

  ask "question"   one question through the five steps, answer shown as it is checked
  eval             Tanush's questions (data/questions.csv) under one setting, then a sheet
  grade SHEET      copy hand grades from a grading sheet into results.csv
  report           Tables 1, 2a, 2b and 3 from the probe files and results.csv
  load SCENARIO    one load scenario against the stand-in (no Groq), rows into results.csv
  calibrate        the stand-in's latency next to the real probe's, side by side
  validate         check results.csv against the brief's columns and the empty-field rule

ask and eval spend real Groq tokens, so they print the estimate first and refuse without
--confirm and --max-tokens-total; --dry-run retrieves and estimates for free.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import config
import table1
from library import parse, search
from relay import evaluate, llm, loadgen, pipeline, report, results, standin


def spend_gate(args, estimate):
    """Print where requests go and the estimate; exit unless confirmed and capped."""
    print(llm.describe_target(config.BASE_URL))
    llm.check_spend(estimate, args.confirm, args.max_tokens_total)
    api_key = llm.key_for(config.BASE_URL)
    if not api_key:
        print("No key: paste it into .env after GROQ_API_KEY= (never into chat)")
        raise SystemExit(2)
    return api_key


def refuse_early(args):
    """Refuse before loading any model, so a forgotten flag costs nothing."""
    if not args.dry_run and not (args.confirm and args.max_tokens_total):
        print("Refusing real call: pass --confirm and --max-tokens-total N "
              "after reviewing the estimate (or use --dry-run)")
        raise SystemExit(2)


def ask(args):
    refuse_early(args)
    index = search.build_index(parse.load_all_blocks(), args.setting)
    need = evaluate.estimate(index, args.question)
    if args.dry_run:
        print(f"Estimated spend: {need} tokens (dry run: no request sent)")
        return
    api_key = spend_gate(args, need)

    async def go():
        async with llm.make_client() as client:
            return await pipeline.answer(args.question, index, client, api_key,
                                         show=lambda text: print(text, end="", flush=True))
    result = asyncio.run(go())
    print("\n")
    for label in result["citations"]:
        print(f"  cited: {label}")
    if result["check"]:
        print(f"  check stopped the reply: {result['check']}")
    print(f"  outcome {result['outcome']}, status {result['status']}, first token "
          f"{result['first_token_ms']} ms, total {result['total_ms']} ms, tokens in "
          f"{result['tokens_in']} out {result['tokens_out']} (reasoning "
          f"{result['reasoning_tokens']}), cap {args.max_tokens_total}")
    results.append([results.row_from(result, "ask", config.BASE_URL)])
    results.trace(result, "ask")


def run_eval(args):
    try:
        questions = evaluate.load_questions(Path(args.questions))
    except ValueError as problem:
        print(problem)
        raise SystemExit(2)
    refuse_early(args)
    index = search.build_index(parse.load_all_blocks(), args.setting)
    needs = [evaluate.estimate(index, q["question"]) for q in questions]
    for q, need in zip(questions, needs):
        print(f"{need:6d}  {q['type']:<13} {q['question'][:70]}")
    total = sum(needs)
    print(f"Setting {args.setting}: {len(questions)} questions, upper-bound estimate {total} "
          f"tokens (about {total / len(questions):.0f} per question)")
    if args.dry_run:
        return
    api_key = spend_gate(args, total)
    asyncio.run(evaluate.run(questions, index, api_key, args.max_tokens_total))


def calibrate():
    """Stand-in vs probe, side by side; also saved to data/standin/calibration.md."""
    spaced = [r for r in table1.load_run(config.STANDIN_PROBE_RUN)[0]
              if r.get("stage") == "spaced" and r.get("status") == 200]
    rows = [["Real Groq probe (50 spaced tiny requests)", report.spread([min(
        t for t in (r["first_reasoning_ms"], r["ttft_ms"]) if t) for r in spaced], (50, 95, 99)),
        report.spread([r["total_ms"] for r in spaced], (50, 95, 99))]]
    for scale in (0.1, config.LOAD_TIME_SCALE):
        first, total = asyncio.run(loadgen.calibrate(scale=scale))
        rows.append([f"Stand-in, same request, time compressed x{1 / scale:.0f}",
                     report.spread(first, (50, 95, 99)), report.spread(total, (50, 95, 99))])
    text = report.table(["Source", "First event p50 / p95 / p99 (ms)",
                         "Total p50 / p95 / p99 (ms)"], rows)
    note = ("\nThe stand-in resamples the first-event times of these same 50 spaced requests. "
            "What it adds is its own Python overhead, multiplied by the time compression, "
            "plus 0.24 ms per prompt token. Load scenarios run at "
            f"x{1 / config.LOAD_TIME_SCALE:.0f}. The p95 gap is the probe's small sample, "
            "not the stand-in: 2 of its 50 values are 1.8-2.0 s, so its own p95 (752 ms) sits "
            "just below them and its p96 is already 1,819 ms; 200 resamples land on them.\n")
    print(text + note)
    out = config.DATA_DIR / "standin" / "calibration.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text + "\n" + note)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m relay", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("ask", "eval"):
        p = sub.add_parser(name)
        if name == "ask":
            p.add_argument("question")
        else:
            p.add_argument("--questions", default=str(config.QUESTIONS_PATH))
        p.add_argument("--setting", default=config.RETRIEVAL_SETTING, choices=sorted(config.SETTINGS))
        p.add_argument("--dry-run", action="store_true", help="retrieve and estimate; no request")
        p.add_argument("--confirm", action="store_true", help="allow real model calls")
        p.add_argument("--max-tokens-total", type=int, help="hard cap on this run's tokens")
    sub.add_parser("grade").add_argument("sheet")
    sub.add_parser("report")
    sub.add_parser("validate")
    load = sub.add_parser("load")
    load.add_argument("scenario", choices=sorted(config.SCENARIOS))
    load.add_argument("--requests", type=int, help="fewer requests for a short check")
    load.add_argument("--results", help="write rows here instead of data/results.csv")
    sub.add_parser("calibrate")
    args = ap.parse_args(argv)

    if args.command == "ask":
        ask(args)
    elif args.command == "eval":
        run_eval(args)
    elif args.command == "grade":
        print(f"{evaluate.apply_grades(Path(args.sheet))} grades copied into results.csv")
    elif args.command == "report":
        table1.main([])
        report.print_report()
    elif args.command == "load":
        path = Path(args.results) if args.results else None
        traces = path.with_name(path.stem + "_traces.jsonl") if path else None
        rows, gate, _, wall = asyncio.run(loadgen.run(args.scenario, args.requests, path, traces))
        print(f"{args.scenario}: {len(rows)} requests in {wall:.0f} wall s; "
              f"peak gateway queue {gate.peak_queue}")
        report.print_report(path)
    elif args.command == "calibrate":
        calibrate()
    elif args.command == "validate":
        sys.exit(0 if results.validate_and_print() else 1)


if __name__ == "__main__":
    main()
