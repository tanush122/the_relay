---
phase: 01-foundations-and-probe
verified: 2026-11-10T13:45:00Z
status: gaps_found
score: 4/5 must-haves verified
overrides_applied: 0
gaps:
  - truth: "The known fact from each paper is retrieved under settings A, B and C with zero Groq calls (SC2 / LIB-05)"
    status: failed
    reason: "Setting B does not retrieve the H-Net ratio-loss fact: the window containing it ranks 8th, outside B's 4 pieces. tests/test_retrieval.py marks test_known_fact_retrieved[B-hnet] xfail(strict=True). 8 of 9 setting x paper cases pass. REQUIREMENTS.md still ticks LIB-05 as complete."
    artifacts:
      - path: "tests/test_retrieval.py"
        issue: "B_RATIO_LOSS_MISS xfail: the known fact is not retrieved under setting B for hnet"
      - path: "library/search.py / library/pieces.py (setting B windows)"
        issue: "600-token fixed window holding 'we introduce a ratio loss' ranks 8th"
      - path: ".planning/REQUIREMENTS.md"
        issue: "LIB-05 marked [x] Complete although one case fails"
    missing:
      - "Either make setting B retrieve the H-Net ratio-loss fact (and drop the xfail), or accept the miss as a recorded Table 3 finding via an override in this file and untick/annotate LIB-05"
---

> **Update 12 Nov (after verification):** the B miss moved. The phase-2 fix for review ME-01
> (pieces scored by their best 150-word window) made setting B find H-Net's ratio loss and
> miss Moshi's 12.5 Hz frame rate instead; the strict xfail is now `test_known_fact_retrieved[B-moshi]`.
> Tanush accepted B's miss as a Table 3 finding (10 Nov); the moved miss awaits his confirmation.
> The text below is the report as written on 10 Nov.

# Phase 1: Foundations and probe Verification Report

**Phase Goal:** The real Groq service's limits and latency are measured from raw responses, and one real question gets a correctly cited, streamed answer from the three papers at their exact versions.
**Verified:** 2026-11-10T13:45:00Z
**Status:** gaps_found
**Re-verification:** No (initial verification)

Method: code and data read directly; `uv run pytest -q` run (69 passed, 1 xfailed); probe.py/ask.py run only without `--confirm` and with `--dry-run`; no Groq call made; `.env` only counted (`grep -c '^GROQ_API_KEY=.' .env` = 1), never read.

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `uv run` on Python 3.12 with pinned deps; .env git-ignored; .env.example has empty `GROQ_API_KEY=`; `gsk_` guard fails when a tracked file holds `gsk_...` | VERIFIED | `.python-version` 3.12, `requires-python >=3.12,<3.13`, deps pinned `==` with uv.lock; `.gitignore` has `.env`, `.env.*`, `!.env.example`; .env not in `git ls-files`; .env.example is exactly `GROQ_API_KEY=`; tests/test_no_keys.py::test_guard_detects_tracked_key passes; core.hooksPath=.githooks runs the guard pre-commit |
| 2 | Papers on disk at 1706.03762v7, 2410.00037v1, 2507.07955v2 with committed manifest; known fact from each paper retrieved under A, B and C with zero Groq calls | FAILED | Papers and manifest fine (data/raw has v7/v1/v2 HTML+PDF; data/manifest.json tracked with url, version, bytes, sha256, fetched_at, version_evidence). But `test_known_fact_retrieved[B-hnet]` is xfail(strict): setting B ranks the ratio-loss window 8th of 4 returned. 8/9 cases pass. Zero-Groq: test_no_groq_dependency passes |
| 3 | Probe refuses without confirm flag and cap, prints estimate first, has dry run, and the real run saved raw status/headers/timings/usage/error bodies for ~50 spaced requests plus a burst reaching a 429 | VERIFIED | `probe.py` with no flags prints "Estimated spend: 12420 tokens" then refuses; `--dry-run` prints per-stage estimate. run_20261110T133218Z/requests.jsonl: 100 records: spaced 50x200, rpm_burst 29x200 + 1x429 (error_body present, retry-after header saved), recovery 1, concurrency 15, header samples 3. All 50 spaced have usage, total_ms and first_reasoning_ms. run.json: spent 9,236 (usage 9,150) vs cap 10,000, stopped "done" |
| 4 | Script turns raw probe files into a Table 1 draft with all seven rows and columns Limit, Value found, How found, Confidence | VERIFIED | run_20261110T133218Z/table1_draft.md has the 7 rows and 4 columns; tokens per day marked "not measured", TPM recovery "not measured"; values trace to raw records (RPM 30 from 429 body, TPM 8000 / RPD 1000 from headers, recovery 6.187 s) |
| 5 | One real question -> retrieve -> one streamed Groq answer whose cited ids map to "paper, version, section", with TTFT, total time, usage and rate-limit headers in a trace line | VERIFIED (with warning) | data/traces/ask.jsonl: 1 line, status 200, gpt-oss-20b, ttft_ms 1065.97, total_ms 1076.87, usage total 2,437 (cap 3,000), all six x-ratelimit-* headers, content "...12.5 Hz【moshi-C-040】". Offline: retrieval for the same question under C reproduces moshi-C-040/017/078/039, and `ask.map_citations(saved content, those pieces)` returns `[('moshi-C-040', 'Moshi v1, §5.1 Text Language Modeling')]`; piece 040 contains "12.5". Caveat: at run time the old parser missed 【】 and printed no mapping; the mapping was demonstrated only after the fix, offline |

**Score:** 4/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| pyproject.toml, uv.lock, .python-version | pinned 3.12 env | VERIFIED | pytest runs under uv |
| .env.example, .gitignore, .githooks/pre-commit, tests/test_no_keys.py | key hygiene | VERIFIED | hook wired via core.hooksPath |
| config.py | single tunables module | VERIFIED | used by ask/probe/search |
| data/manifest.json, data/raw/* | exact versions | VERIFIED | raw is git-ignored (by design), manifest committed |
| library/{fetch,parse,pieces,search}.py | A/B/C pieces, BM25+embedding RRF, C re-rank | VERIFIED (one recall miss, see gap) | |
| relay/llm.py | async streaming client, traces | VERIFIED | real key only to https://api.groq.com (key_for) |
| probe.py, table1.py, ask.py | gated probe, Table 1 draft, cited answer | VERIFIED | |
| data/probe/run_20261110T133218Z/*, data/traces/ask.jsonl, docs/QUOTA.md | real-run evidence | VERIFIED | ledger rows match run.json and trace (19:02 / 19:08 IST = 13:32 / 13:38 UTC) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| ask.py | library.search | build_index/retrieve | WIRED | reproduced offline |
| ask.py | relay/llm.py | draft -> stream -> trace_path | WIRED | trace line present from real run |
| probe.py | requests.jsonl/run.json | save() | WIRED | 100 records |
| table1.py | probe run dir | reads requests.jsonl/run.json | WIRED | draft values match raw |
| pre-commit hook | tests/test_no_keys.py | core.hooksPath | WIRED | |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Test suite | `uv run pytest -q` | 69 passed, 1 xfailed (B-hnet) | PASS (xfail = gap) |
| Probe gate | `uv run python probe.py` | estimate 12420, then "Refusing real call" | PASS |
| Ask gate | `uv run python ask.py "x"` | "Refusing real call" | PASS |
| Probe dry run | `uv run python probe.py --dry-run` | per-stage estimate, no request | PASS |
| Offline citation re-map | map_citations on saved content with C pieces | Moshi v1, §5.1 Text Language Modeling | PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist. probe.py is a real-spend Groq probe; per instruction it was not run with `--confirm`. Its real output was inspected instead (above).

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| ENV-01..05 | SATISFIED | SC1, gates, config.py |
| LIB-01..04 | SATISFIED | manifest, pieces, search |
| LIB-05 | BLOCKED (partial) | B-hnet miss; REQUIREMENTS.md wrongly ticks it complete |
| REAL-01, REAL-02 | SATISFIED | llm.py, ask trace |
| REAL-03 | SATISFIED | real run saved; REQUIREMENTS.md still shows it unticked/"Pending" (stale bookkeeping) |
| REAL-04 | SATISFIED | table1_draft.md |
| REAL-05 | Phase 4 (not this phase) | |

### Key-leak check

- No `gsk_` + alphanumerics in any tracked file under data/ or docs/ (count 0), nor in any revision in git history (git grep over all revs, excluding the synthetic test fixture).
- No unredacted `org_` id in data/probe or data/traces (the 429 body shows `org_[REDACTED]`).
- .env is untracked and contains one non-empty key line (count only).

### Anti-Patterns / Warnings

| Item | Severity | Impact |
|------|----------|--------|
| 50/50 spaced replies ended finish_reason "length" at max_tokens 16; 33/50 had no visible text, so visible-text TTFT exists for only 17 spaced replies (and 2 of 4 concurrency levels show TTFT n/a in Table 1) | WARNING | Latency is still measured: total_ms and first_reasoning_ms exist for all 50 (total median 516 ms). Visible-text TTFT spread is thin; if Table 1/write-up quotes TTFT from this run, it rests on 17 samples. Not a phase-goal blocker; phase 2/4 runs should set max_tokens high enough or define TTFT on first reasoning token explicitly |
| Real answer's citation was not mapped live (parser missed 【】); fixed after, re-mapped offline | WARNING | Goal truth holds on the saved data, but the live run did not show "paper, version, section". Next real ask run is the first live proof of the fixed path |
| ask.jsonl trace does not record retrieved piece ids or mapped citations | WARNING | The mapping recomputes only because retrieval is deterministic today; any parse/index change breaks reproducibility of this trace. Documented for phase 2 |
| TPM-limit 429, TPM recovery and tokens/day not measured (lean profile) | INFO | Marked "not measured" honestly in Table 1; REAL-05 is phase 4 |
| Probe cap was raised 6,000 -> 10,000 with Tanush's "go"; ledger total for the day 11,587 | INFO | Within approved caps |
| Source lines 1,517 (excl. tests) vs ~1,500 target | INFO | |
| ROADMAP 01-05 checkbox and REQUIREMENTS REAL-03 still unticked; LIB-05 ticked despite miss | INFO | Bookkeeping |

### Human Verification Required

None beyond the gap decision below.

### Gaps Summary

One gap: SC2 / LIB-05 says the known fact from each paper is retrieved under all three settings; under setting B the H-Net ratio-loss fact is not (ranks 8th, B returns 4). The project documents this honestly as a strict xfail, and it is plausibly legitimate Table 3 material (a big fixed window losing a fact is a real result), but the success criterion as written is not met and REQUIREMENTS.md overstates it. Resolve by fixing B or by accepting it explicitly:

```yaml
overrides:
  - must_have: "The known fact from each paper is retrieved under settings A, B and C with zero Groq calls"
    reason: "Setting B missing the H-Net ratio-loss fact is a recorded retrieval finding for Table 3, kept as a strict xfail; 8/9 cases pass"
    accepted_by: "Tanush"
    accepted_at: "<ISO timestamp>"
```

The other known deviations do not break the phase goal: limits and latency were measured from saved raw responses, and the one real answer is correct and its citation maps to Moshi v1, §5.1 from saved data. They do weaken the evidence (thin visible-text TTFT, mapping shown only offline, trace lacks retrieved ids) and are listed as warnings.

---

_Verified: 2026-11-10T13:45:00Z_
_Verifier: Claude (gsd-verifier)_
