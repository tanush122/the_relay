# Roadmap: The Relay

## Overview

Four phases from Tue 10 to Fri 13 Nov 2026, fixed by the plan of record (docs/PLAN.md section 6). Phase 1 measures the real Groq service and proves one cited answer end to end. Phase 2 builds the full five-step pipeline with refusal gates and the results.csv writer, and runs settings A and B on Tanush's questions. Phase 3 (overlapping phase 2, no real quota needed) builds the gateway, the calibrated stand-in and the open-loop load generator. Phase 4 runs every scenario and setting C, prints all four tables from results.csv, writes the 2 pages and submits by 3 PM IST Friday (hard deadline 5:22 PM IST).

## Phases

- [ ] **Phase 1: Foundations and probe** - Environment, papers at exact versions, local retrieval, streaming Groq client, real probe, Table 1 draft, one cited answer (Tue 10 Nov)
- [ ] **Phase 2: Pipeline and retrieval** - Five-step pipeline with refusal gates, grading sheet, results.csv writer, validator and report command, `relay ask`; settings A and B run and graded; write-up drafting starts Wed evening (Wed 11 Nov)
- [ ] **Phase 3: Gateway, stand-in and load** - Budget-aware gateway, calibrated stand-in, open-loop trace replay, one overload run (Wed 11 to Thu 12 Nov)
- [ ] **Phase 4: Experiments and write-up** - All scenarios, setting C, daily-limit confirmation, four tables from one command, 2-page write-up, submission (Thu 12 to Fri 13 Nov, submit by 3 PM IST)

## Phase Details

### Phase 1: Foundations and probe

**Goal**: The real Groq service's limits and latency are measured from raw responses, and one real question gets a correctly cited, streamed answer from the three papers at their exact versions.
**Target**: Tue 10 Nov 2026
**Depends on**: Nothing (first phase)
**Requirements**: ENV-01, ENV-02, ENV-03, ENV-04, ENV-05, LIB-01, LIB-02, LIB-03, LIB-04, LIB-05, REAL-01, REAL-02, REAL-03, REAL-04
**Success Criteria** (what must be TRUE):

  1. `uv run` works on Python 3.12 with pinned deps; .env is git-ignored, .env.example has an empty `GROQ_API_KEY=`, and the `gsk_` guard fails when a test file containing `gsk_...` is tracked.
  2. The three papers are on disk at 1706.03762v7, 2410.00037v1 and 2507.07955v2 with a committed manifest (URL, version, bytes, sha256, fetch time), and the known fact from each paper is retrieved under settings A, B and C with zero Groq calls.
  3. The probe refuses to run without the confirmation flag and token cap, prints its estimated spend first, supports a dry run, and on a real run saves raw status, headers, timings, usage and error bodies for about 50 spaced requests plus one burst that reaches a 429.
  4. A script turns the raw probe files into a Table 1 draft with all seven rows and the columns Limit, Value found, How found, Confidence (rows not yet confirmable marked as such).
  5. One real question goes question → retrieve → one streamed Groq answer whose cited piece ids map to "paper, version, section", with TTFT, total time, usage and rate-limit headers written to a trace line.

**Plans**: 5 plans (sequential; plan 05 is the human-gated real run)

Plans:

- [x] 01-01-PLAN.md — uv + Python 3.12 pinned project, .env/.env.example, config.py, gsk_ guard (install gate first)
- [x] 01-02-PLAN.md — fetch exact paper versions + manifest, section parsing, settings A/B/C pieces, BM25+embedding RRF retrieval with C re-rank, known-fact tests
- [x] 01-03-PLAN.md — async streaming Groq client with header/usage/TTFT traces (fake-server tested), ask.py thin cited path with spend gate
- [ ] 01-04-PLAN.md — probe.py (dry run, gated real mode, cap), table1.py draft, full suite + line budget + dry-run estimate, runbook
- [ ] 01-05-PLAN.md — human-gated real run: spend approval gate, real probe under cap, Table 1 draft from real data, one real cited answer

### Phase 2: Pipeline and retrieval

**Goal**: Every request runs the five steps and either sends a cited answer that passes the code check or honestly refuses; settings A and B are run on real Groq over Tanush's questions, graded by hand, and recorded in a results.csv that validates against the brief.
**Target**: Wed 11 Nov 2026 (write-up skeleton and number-free prose start Wed evening, per 10 Nov revision)
**Depends on**: Phase 1
**Requirements**: PIPE-01, PIPE-02, PIPE-03, PIPE-04, PIPE-05, PIPE-06, PIPE-07, EVAL-01, EVAL-02, EVAL-05, DATA-01, DATA-02, DATA-03, DATA-06, DATA-07, DATA-08, DATA-09, DATA-10
**Success Criteria** (what must be TRUE):

  1. A question flows through understand, retrieve, decide, draft, check; a weak-retrieval question re-queries once and then refuses with no model call (visible in its trace).
  2. An answer citing an id that was not retrieved, or containing a number absent from its cited pieces, is turned into a refusal by the check step; an unanswerable question gets "the papers do not say" rather than a guess.
  3. Tanush's 18+ questions and answer key exist, settings A and B have been run on real Groq over them, and every answer has a hand grade (correct, wrong, refused_correctly, refused_wrongly) in the grading sheet.
  4. results.csv has exactly the twelve brief columns with only allowed values, start_time is arrival time, the status mapping rule is applied, and the validator passes on it.
  5. The refusal threshold is set from the question runs, with the count of wrong answers versus wrong refusals it produces recorded.
  6. `uv run relay ask "..."` answers or refuses one question end to end; the report command prints Tables 2a, 2b and 3 from results.csv, and the validator enforces the empty-field rule.

**Plans**: TBD

### Phase 3: Gateway, stand-in and load

**Goal**: All model calls go through one gateway that knows the budget, and a stand-in calibrated from the probe lets an open-loop load generator push the system past the real service's limits without spending real quota.
**Target**: Wed 11 to Thu 12 Nov 2026 (overlaps phase 2 on purpose: no real quota needed)
**Depends on**: Phase 1 (probe data, client); integrates with Phase 2 pipeline
**Requirements**: GW-01, GW-02, GW-03, GW-04, GW-05, GW-06, GW-07, GW-08, GW-09, STAND-01, STAND-02, STAND-03, STAND-04, LOAD-01, LOAD-02, DATA-05
**Success Criteria** (what must be TRUE):

  1. Pointing the client's base URL at the stand-in, unchanged code gets streamed replies, Groq-style rate-limit headers, and 429 with retry-after when the stand-in's configured limit is reached; halving that limit is a one-line config change.
  2. A side-by-side table of real probe versus stand-in TTFT and total time exists, and the largest difference is named.
  3. Under overload the gateway refuses requests predicted to miss their deadline immediately with a retry time, drops expired queued requests before spending tokens, steps down the three ladder levels (Normal, Lean, Day-gone) as budget falls, and at Day-gone returns cached answers or cited passages with no model call; gateway budget and retry tests pass; an injected retrieve-step timeout is handled by its rule and visible as a trace span.
  4. One open-loop overload run against the stand-in completes, with latency measured from scheduled arrival, arrivals from a confirmed licensed trace slice (or a stated arrival process), and per-step spans in traces.jsonl.

**Plans**: TBD

### Phase 4: Experiments and write-up

**Goal**: Every scenario and setting C have run, all four tables print from results.csv with one command, the 2-page write-up covers every brief heading in order, and Tanush submits the folder by 3 PM IST Fri 13 Nov.
**Target**: Thu 12 to Fri 13 Nov 2026; submit by 3 PM IST (hard deadline 5:22 PM IST)
**Depends on**: Phase 2, Phase 3
**Requirements**: REAL-05, LOAD-03, LOAD-04, LOAD-05, EVAL-03, EVAL-04, EVAL-07, DATA-04, DOC-01, DOC-02, DOC-03, DOC-04, DOC-05, DOC-06, DOC-07, DOC-08, DOC-09, DOC-10, DOC-11, DOC-12, DOC-13, SUB-01, SUB-02, SUB-03
**Success Criteria** (what must be TRUE):

  1. results.csv holds raw rows for every scenario (real steady; stand-in steady, burst, sustained overload with retry-budget off/on, limit halved, daily budget exhausted), each stand-in scenario with at least 1,000 requests, plus setting C runs on the questions; the daily limit has been confirmed (or Table 1 states how it was found).
  2. The report command (built in phase 2) prints Tables 1, 2a, 2b and 3 fully filled (ms, one-decimal percentages, "not measured" where applicable, cost at stated list price), and the validator confirms every write-up figure recomputes from results.csv.
  3. The write-up is at most 2 pages with every brief heading in order, including a traced slow-request breakdown, the retry-made-it-worse case, the 3pm level-4 reply, three misleading-retriever examples confirmed by runs, Tanush's Vaani feedback and the assistant-collaboration section with real history.
  4. Tanush has rehearsed the live changes (halve a limit, add a ladder level, ask a new question with `relay ask`, swap retrieval setting, change give-up time, explain a slow request), each a one-line config change or a small edit in one file.
  5. A Drive folder (write-up, code, results.csv, checksums, README with one command per table, no key anywhere including history) is shared "anyone with the link" and submitted via the form by 3 PM IST Fri 13 Nov.

**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundations and probe | 3/5 | In Progress|  |
| 2. Pipeline and retrieval | 0/TBD | Not started | - |
| 3. Gateway, stand-in and load | 0/TBD | Not started | - |
| 4. Experiments and write-up | 0/TBD | Not started | - |
