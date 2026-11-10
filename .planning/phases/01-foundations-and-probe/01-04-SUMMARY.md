---
phase: 01-foundations-and-probe
plan: 04
subsystem: probe
tags: [rate-limits, probe, table1, dry-run, spend-cap]
requires: ["01-03 relay/llm.py (stream_chat, list_models, check_spend)", "tests/fake_groq.py"]
provides:
  - "probe.py: plan_requests, print_plan, run_probe (running cap, raw requests.jsonl + run.json), main"
  - "table1.py: load_run, build_table1 (7 rows x 4 columns from raw files only), render_markdown, main"
  - "README.md runbook incl. 'Human-gated real steps'; 6 DECISIONS rows"
affects: [01-05]
tech-stack:
  added: []
  patterns: ["reserve estimate before send, settle with real usage after", "table values only from raw files; gaps say 'not measured'"]
key-files:
  created: [probe.py, table1.py, tests/test_probe.py, tests/test_table1.py, README.md]
  modified: [docs/DECISIONS.md]
decisions:
  - "probe dry-run upper bound 17,179 tokens vs default cap 30,000; ask.py dry run (C, Mimi question) 2,617 tokens"
  - "max_tokens 50/1000 pair kept although probe.py is 152 lines (tests checker risk #5: is max_tokens charged at admission)"
  - "HF_HUB_OFFLINE not set as a config default (would block the first model download on a fresh clone); documented as an optional env prefix in README"
metrics:
  duration: "~5 min"
  completed: 2026-11-10
  tasks: 3
  files: 6
---

# Phase 1 Plan 04: Probe, Table 1 drafter and phase gate Summary

`probe.py` plans and prints every request it may send, with an upper-bound estimate of 17,179 tokens. Its real mode refuses to run without both `--confirm` and `--max-tokens-total`, enforces a running cap, and saves every raw response. `table1.py` drafts all seven Table 1 rows from those raw files only. Both were tested against the local fake server only. No real Groq call was made: `data/probe/` and `data/traces/` do not exist.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | probe.py, dry run, gated real mode, running cap, 5 tests | ef9a3c4 |
| 2 | table1.py from raw files, 3 tests (+ probe records poll interval) | 19c7999 |
| 3 | Phase gate: suite, line budget, dry runs, README, DECISIONS | 064b872 |

## Dry-run estimates for plan 05's gate (estimates, not measurements)

`uv run python probe.py --dry-run` prints 176 request lines (excerpt):

```
   1  models           -                          in~0     max_out 0     est 0
   2  header_sample    llama-3.1-8b-instant       in~15    max_out 200   est 215
   ...
 175  max_tokens_pair  llama-3.1-8b-instant       in~15    max_out 50    est 65
 176  max_tokens_pair  llama-3.1-8b-instant       in~15    max_out 1000  est 1015
subtotal models             1 requests  0 tokens
subtotal header_sample      4 requests  860 tokens
subtotal spaced            50 requests  1550 tokens
subtotal rpm_burst         40 requests  1240 tokens
subtotal recovery_rpm      30 requests  930 tokens
subtotal tpm_burst          4 requests  10124 tokens
subtotal recovery_tpm      30 requests  930 tokens
subtotal concurrency       15 requests  465 tokens
subtotal max_tokens_pair    2 requests  1080 tokens
ESTIMATED TOTAL: 17179 tokens (upper bound; default cap 30000)
```

The total is an upper bound for two reasons: both recovery stages are counted at their maximum of 30 polls each, and every request is counted at its full max_tokens. Requests rejected with 429 are counted at their estimate, because whether a 429 consumes quota is unknown.

`uv run python ask.py "What frame rate does the Mimi codec in Moshi produce tokens at?" --setting C --dry-run`:

```
moshi-C-015    5.2415  Moshi v1, §3.3.1 Architecture
moshi-C-036    3.8971  Moshi v1, §5.1 Text Language Modeling
moshi-C-038    3.5979  Moshi v1, §5.2 Audio Tokenization
moshi-C-037    3.5273  Moshi v1, §5.2 Audio Tokenization
Estimated spend: 2617 tokens (dry run: no request sent)
```

Together: 17,179 + 2,617 = 19,796 tokens upper bound, inside PLAN 5.3's ~30k Tuesday budget.

## Fake-server demonstration (fixture data, not a measurement)

The small probe was run against the fake server, configured for 4 requests per 1 s window.
- Summary: spent 1,652, 23 requests sent, stopped_reason "done", recovery_rpm_s 1.029, `missing-model` listed as missing.
- The Table 1 draft showed:
  - RPM "4 (fake-model)", from the 429 body, high confidence.
  - TPM and RPD from the headers, medium confidence.
  - TPD "not measured".
  - The 429 shape with `retry-after` 1.
  - Recovery "RPM: 1.029 s; TPM: not measured".
- In one run the fake's 1 s window also rejected the concurrency levels with 429, so "Requests in flight" honestly came out as "not measured".

## Verification

- `uv run pytest -q tests/test_probe.py`: 5 passed.
- `uv run pytest -q tests/test_table1.py tests/test_probe.py`: 8 passed.
- Full suite `uv run pytest -q -rs`: 45 passed, 1 xfailed, no SKIPPED. The xfail is the setting-A H-Net ratio-loss miss from 01-02, kept on the coordinator's instruction. The suite is also green with `HF_HUB_OFFLINE=1`.
- `uv run python probe.py` with no flags prints the plan and "Estimated spend: 17179 tokens", then "Refusing real call: pass --confirm after reviewing the estimate", and exits 2.
- `uv run python table1.py` with no runs prints 7 rows, all "not measured", and exits 0.
- Grep checks:
  - Hard-coded probe sizes in probe.py: none.
  - `config.PROBE` appears 4 times in probe.py.
  - Limit numbers in table1.py: none.
- Key hygiene: `test -e .env` succeeds; `git check-ignore .env` prints `.env`; `tests/test_no_keys.py` passes (5 tests). `.env` was not opened.

## Line budget (non-blank, non-test Python)

| File | Lines | Target |
|------|-------|--------|
| config.py | 102 | ~75 |
| library/fetch.py | 94 | ~70 |
| library/parse.py | 95 | ~85 |
| library/pieces.py | 53 | ~50 |
| library/search.py | 72 | ~75 |
| library/__init__.py | 1 | — |
| relay/llm.py | 132 | ~95 |
| relay/__init__.py | 1 | — |
| ask.py | 77 | ~55 |
| probe.py | 152 | ~110 |
| table1.py | 132 | ~65 |
| **Total** | **911** | **~650–750** |

The total is 161 over the top of the target range. Nothing was compressed and no why-docstrings were deleted.
- table1.py is over because it has one small function per row; this replaced a denser first draft that would be hard to explain live.
- probe.py is over because of its stage docstring and the recovery and cap logic.
- Documented cut order if Tanush asks for cuts: the max_tokens pair stage, then the pre-commit hook, then the fake-server extras (`reasoning_text`, `delay_s`).

## Deviations from Plan

1. **[Rule 2] Probe stops if the models call itself fails.** probe.py stops with `stopped_reason "models_failed: status N"` when the models-list call does not return 200, for example a 401 from a bad key. This avoids spending on a run that cannot succeed.
2. **Probe run.json also records `recovery_poll_interval_s`.** table1.py reads the poll interval from the run's own data, not from the current config.
3. **Each probe record also carries `received_s`** (seconds since the run started). Recovery is measured from the burst's first 429 to the first 200 using these data-derived times.
4. **[Rule 1] The concurrency row lists each level's statuses and shows "n/a" where a level has no TTFT.** The first draft printed "0 ms" for levels rejected with 429, and did not show that a higher level failed.
5. **The max_tokens pair was kept.** probe.py is 152 lines, just past the ~150 mark where cutting was allowed. The pair is the only stage that tests checker risk #5 (whether max_tokens is charged at admission).
6. **HF_HUB_OFFLINE was not made a config default.** The suite is green with it, but as a default it would block the first model download on a fresh clone. It is documented in the README as an optional command prefix instead.

## Known Stubs

None.

## Self-Check: PASSED

Files exist. Commits ef9a3c4, 19c7999 and 064b872 are in git log. No real-mode probe or ask run occurred.
