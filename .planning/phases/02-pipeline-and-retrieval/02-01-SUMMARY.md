---
phase: 02-pipeline-and-retrieval
plan: 01
subsystem: pipeline
tags: [pipeline, check, results-csv, report, evaluation]
provides:
  - "relay/pipeline.py: understand, retrieve_and_decide, fit_to_ceiling, Release (per-sentence check), answer"
  - "relay/results.py: COLUMNS, row_from, append, validate, trace"
  - "relay/report.py: tables 2a, 2b, 3 from results.csv"
  - "relay/evaluate.py: load_questions, estimate, run (cap + header pacing), write_sheet, apply_grades"
  - "relay/__main__.py: python -m relay ask|eval|grade|report|validate"
  - "data/questions.csv: empty template (header only) for Tanush"
removed: [ask.py, tests/test_ask.py, probe "full" profile]
metrics:
  completed: 2026-11-10
  groq_tokens: 0
  tests: "105 passed, 1 xfailed"
  source_lines: 2207
---

# Phase 2 Plan 01 Summary

## A vs B, settled from the tests
Before phase 2 the strict xfail was B on H-Net's ratio loss (the STATE.md line saying A was
stale: A's miss ended when figure captions were parsed). After ME-01 (best-window scoring),
B finds the ratio loss and misses Moshi's 12.5 Hz instead. Not tuned; Table 3 finding.

## Deviations
- REQUEST_TOKEN_CEILING raised 4,000 -> 6,000: at 4,000 it silently cut setting B to 3 pieces.
- `python -m relay` instead of `uv run relay`: the latter needs a packaging backend download.
- Abbreviations (e.g., Fig.) would have ended a sentence and failed the check; now joined.

## Not done here (needs Tanush or later phases)
- His questions and answer key (data/questions.csv is an empty template); real eval runs
  need his yes with caps; MIN_STRENGTH 0.30 is provisional until those runs.
- PRICE_PER_MILLION_TOKENS unset (cost column prints "not measured (price not set)").
- Gateway, retries, deadlines, stand-in: phase 3.
