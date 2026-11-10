---
phase: 01-foundations-and-probe
reviewed: 2026-11-10T12:00:00Z
depth: deep
files_reviewed: 18
files_reviewed_list:
  - config.py
  - library/fetch.py
  - library/parse.py
  - library/pieces.py
  - library/search.py
  - relay/llm.py
  - ask.py
  - probe.py
  - table1.py
  - tests/conftest.py
  - tests/fake_groq.py
  - tests/test_ask.py
  - tests/test_library.py
  - tests/test_llm.py
  - tests/test_no_keys.py
  - tests/test_probe.py
  - tests/test_retrieval.py
  - tests/test_table1.py
findings:
  critical: 0
  high: 5
  medium: 8
  low: 9
  warning: 13
  info: 9
  total: 22
status: issues_found
fix_status: 18 fixed, 4 deferred to phase 2 (ME-01, ME-08, LO-07, LO-08)
---

# Phase 1: Code Review Report

**Reviewed:** 2026-11-10
**Depth:** deep (cross-file; parse/pieces checked against the cached papers in data/raw, no network, `.env` not opened)
**Files Reviewed:** 18
**Status:** issues_found

Severity scale: **critical / high** = BLOCKER (fix before the first real run or before Table 1 numbers are reported). **medium** = WARNING. **low** = WARNING/INFO. The frontmatter maps high+medium+some low to `warning` and the rest to `info` for downstream tooling. There are no critical findings.

## Fix status (2026-11-10, gsd-code-fixer)

Fixed: HI-01..HI-05, ME-02..ME-07, LO-01..LO-06, LO-09 (18).
Deferred to phase 2: ME-01, ME-08, LO-07, LO-08. The reason is under each finding.
In addition, approved by Tanush, the probe's default is now the **lean** profile. The TPM burst, its recovery and the max_tokens pair run only with `--profile full`. Every stage stops once its question is answered, and the run aborts and reports on any unexpected answer.

## Summary

Key hygiene is mostly sound. No code path writes, prints or modifies `.env`. Request headers are never recorded. Exceptions and error bodies go through `redact`. Tests redirect `config.ENV_PATH` and clear `GROQ_API_KEY`. `probe.py` and `ask.py` both refuse without `--confirm` and `--max-tokens-total` before they load the key.

The problems are in three areas:
1. **Where the key can go.** Any base URL is accepted, so the real key can be sent to an arbitrary host.
2. **What the cap really bounds.** Estimates are checked before each send, never actual spend, and the estimator undercounts.
3. **Measurement and parsing correctness.**
   - TPM recovery can record the RPM recovery instead.
   - Table 1 trusts whichever run is newest.
   - The parser silently drops Moshi Appendix E and every figure caption, and mis-cites Table 18.
   - The B and C pieces are longer than the embedding model reads.

## High (BLOCKER)

### HI-01: Real Groq key is sent to whatever base URL is configured, including plain http and the phase-3 stand-in

**File:** `config.py:67`, `probe.py:154,161-166`, `ask.py:88-92`, `relay/llm.py:80,100,112`
**Issue:** `BASE_URL` comes from the `RELAY_BASE_URL` env var, and `probe.py` also has `--base-url`. Either way, `load_api_key()` still loads the real Groq key and sends it as `Authorization: Bearer ...` to that host. A stale `RELAY_BASE_URL` in the shell, a typo, or the phase-3 stand-in (which may log request headers) all receive the real key, and `http://` sends it in cleartext. Nothing records or warns that the key went to a non-Groq host.
**Fix:** Send the real key only to Groq. Every other host gets a dummy key.
```python
# relay/llm.py
GROQ_HOST = "api.groq.com"
def key_for(base_url):
    u = urlparse(base_url)
    if u.hostname == GROQ_HOST and u.scheme == "https":
        return load_api_key()
    return "stand-in-no-real-key"
```
Use `key_for(base_url)` in probe/ask instead of `load_api_key()`, and print the target host next to the spend estimate.

**Status:** fixed (4abf4c6). `llm.key_for` sends the real key only to `https://api.groq.com`; every other host gets `stand-in-no-real-key`. probe.py and ask.py print the target before the estimate.

### HI-02: The token cap bounds the estimate, not real spend; ask.py has no runtime cap at all

**File:** `probe.py:95,98-103`, `relay/llm.py:43-45`, `ask.py:83-92`
**Issue:**
- **probe.py:** `group()` reserves `est_tokens` before each send. Real `usage.total_tokens` is only added afterwards (line 95), so a group whose real cost is higher than its estimate can push `spent` past `cap`. The `rpm_burst` group alone is 40 requests.
- **The estimate undercounts.** `estimate_tokens` is `words*1.33+8`. It ignores the chat-template overhead that Groq counts in `prompt_tokens` (the Llama 3.x template adds a system preamble to every request; size unverified until the probe). It also badly undercounts math-heavy text, which `parse.py` turns into single long "words" such as `fracNN-1(...)`.
- **ask.py:** it checks only `estimate <= cap` (via `check_spend`) and then sends. Actual usage is never compared with the cap, and retrieved C pieces include tables and math, where the 1.33 ratio is weakest.

Net effect: "stops before exceeding the cap" is not guaranteed in either script.
**Fix:**
- Add a safety margin to reservations, e.g. `reserve = int(est * 1.5) + 40`.
- Calibrate after the first real response: `ratio = usage.prompt_tokens / est_in`, then scale later reservations by it.
- In ask.py, print `actual total_tokens vs cap` after the call, and append both to the trace.
- Say in the docstrings that the cap is a reservation-based bound.

**Status:** fixed (74bd2c0). The estimate is now `max(words x 1.33, chars / 3)` + 60 template-overhead tokens + max_tokens. The probe reserves each estimate before sending and never sends if actual + reserved + estimate would pass the cap; missing usage is charged at the reservation. ask.py refuses an over-cap estimate and prints actual vs cap; the cap is also written to the trace. A fixed overhead was used instead of the suggested calibration (instruction).

### HI-03: "Time until it recovers (TPM)" can actually measure RPM recovery; 429s are never classified by limit

**File:** `probe.py:115-143`, `table1.py:112-122`
**Issue:**
- `recovery_rpm` stops at the first 200. `tpm_burst` then fires 4 concurrent requests immediately (line 136-138), while the per-minute request window is still nearly full from the 40-request burst.
- If those 429s are RPM 429s, `last_429` is set from them anyway (line 141-143: any 429 in a `*burst` stage), and `recovery_tpm_s` records RPM recovery.
- `table1.recovery()` then prints `TPM: X s` from that number.
- `on_limit()` and the `retry-after seen` value also use `errors[0]` whatever the limit kind.

This is a real path to an incorrect value in Table 1.
**Fix:**
- In `save()`, parse the limit kind from the 429 body (`LIMIT_IN_BODY`) and store it as `record["limit_kind"]`.
- After a burst, set `last_429` only from 429s whose kind matches the burst (`RPM` for rpm_burst, `TPM` for tpm_burst). Otherwise record `recovery_tpm_s = None` with reason "TPM not isolated".
- Wait out the RPM window (sleep the RPM `retry-after`, or 60 s) before `tpm_burst`.
- In table1, report the kind seen with each recovery value.

**Status:** fixed (74bd2c0, c84d7ee). Every record has `limit_kind`. Recovery is timed only from a 429 naming the burst's own limit, otherwise a note is written. There is a 60 s pause before tpm_burst. table1 shows the kind and its own retry-after with each recovery value.

### HI-04: Parser silently drops Moshi Appendix E, all figure captions, and mis-cites Table 18 as §D

**File:** `library/parse.py:52,98-111`
**Issue:** I checked this against `data/raw/2410.00037v1.html`. LaTeXML nests the Appendix A and Appendix E `<section>`s inside the floats of Table 17 and Table 18.
- `_own_text` skips any paragraph with a `figure` parent (line 52). As a result, the 409-word Appendix E paragraph ("Safety and Toxicity") produces no block, and no block has section E.
- Table 18 (`A5.T18`, the ALERT benchmark) has an owner section, so the orphan pass (line 105) skips it. The main loop then emits it under its outer owner, so its citation reads `Moshi v1, §D Characterizing Audio Artifacts...`, which is wrong.
- The skip at line 52 also drops every image-figure caption: 11 in Moshi (824 words), 18 in H-Net (1,189 words), 5 in Attention (171 words). Captions often hold facts.

The tests did not catch any of this: `test_sections_sensible` only requires *some* single-letter appendix.
**Fix:**
- Skip a paragraph only when its nearest `figure` is *inside* its owner section, i.e. when `el.find_parent("figure")` is a descendant of `_owner(el)`.
- Emit `figure.ltx_figure > figcaption` as `kind: "caption"` blocks of the owning section.
- For a table that contains a section, assign it to that inner section (`figure.find(_is_section)`) even when the table has an owner.
- Add a test that every `_is_section` with text yields at least one block, and that Moshi has a section E.

**Status:** fixed (08dbe9f); requires human verification. Image-figure captions are now `caption` blocks (5/11/18). Table 18 is cited under §E. On inspection, Appendix E's only paragraph is Table 18's own tabular: no prose was lost, and emitting it as text would duplicate the table. Prose inside a section wrapped by a float is now kept. Fixed windows shifted: the strict xfail moved from A-hnet (now passes) to B-hnet (ranks 8th).

### HI-05: table1.py presents whatever run is newest as "Groq's real limits", even a run against the fake server or the stand-in

**File:** `table1.py:25-34,147-157`, `probe.py:79`
**Issue:**
- `probe.py` records `base_url_host` in `run.json`, but `table1.py` never reads it.
- The newest `data/probe/run_*` wins. In phase 3 that could be a probe run against the self-written stand-in, or a run with `--base-url` at the fake.
- In both cases the table would print fixture or stand-in numbers as Groq values with "high" confidence. That breaks the "never invent a value" rule.

**Fix:**
```python
if summary.get("base_url_host") != "api.groq.com":
    print(f"Run {run_dir} targeted {summary.get('base_url_host')}, not Groq: refusing to draft Table 1")
    raise SystemExit(2)
```
Also add the host and run dir to the "How found" column.

## Medium (WARNING)

**Status:** fixed (c84d7ee). Every row names its run and host. A non-api.groq.com run is headed `NOT GROQ` and every confidence becomes `none (NOT GROQ: host)`. It is labelled rather than refused so the fake rehearsal can still be inspected.

### ME-01: B and C pieces are longer than the embedding model reads; the cross-encoder also truncates

**File:** `library/search.py:45,90`, `config.py:55-58,62-63`
**Issue:**
- `all-MiniLM-L6-v2` truncates input at 256 word-pieces. B pieces reach 451 words and C pieces reach 871 words (measured on the cached papers), so the embedding ranker only sees the first ~150-190 words.
- The C prefix uses up part of that budget too.
- `ms-marco-MiniLM-L-6-v2` truncates question+piece at 512 tokens.
- Facts in the second half of a B or C piece are invisible to two of the three rankers. This is a confound in the A/B/C comparison and is not documented.

**Fix:** Document it, and either embed a piece as the mean of its 200-word sub-window embeddings, or cap C windows at ~250 tokens for embedding. Log `model.max_seq_length` in `timings`.

**Status:** deferred to phase 2. Reason: fixing it (sub-window embedding means or capped C windows) changes retrieval for all three settings, and the A/B/C comparison and its questions are built in phase 2. It belongs with that work and must be documented as a confound there. No Groq tokens depend on it in phase 1.

### ME-02: A/B pieces take the section of their first word, so citations straddling a boundary are wrong

**File:** `library/pieces.py:27-32`
**Issue:** `_fixed` yields `window[0][1]`, the block of the first word. A 135-word A window starting at the end of §2.2.2 and holding the §2.2.3 fact is labelled §2.2.2. The H-Net xfail note in `test_retrieval.py:34-36` describes exactly this. In phase 2 it will be graded as a wrong citation caused by the mapping code, not by the model.
**Fix:** Keep the set of blocks in the window and label it with the range, e.g. `section_number = "2.2.2–2.2.3"`, or use the block holding most of the window's words. Document the choice in DECISIONS.md.

**Status:** fixed (9e5679d). A/B windows are cited under the block holding most of their words (earlier block on a tie). Logged in DECISIONS.md.

### ME-03: `in_flight` claims "no cap observed up to N" when a lower level failed

**File:** `table1.py:85,95`
**Issue:** `clean` collects every level where all requests returned 200, and `max(clean)` is taken. With levels 1, 2, 8 clean and 4 failing, it reports `>= 8 (no cap observed up to 8)`, which contradicts the data.
**Fix:** Take the largest N such that every level ≤ N is clean:
```python
best = 0
for n in sorted(levels):
    if not all(r["status"] == 200 for r in levels[n]): break
    best = n
```

**Status:** fixed (c84d7ee). Uses the largest N such that every level up to N is clean.

### ME-04: The spend ledger and summary are written only at the end; an interrupted probe loses them, and table1 then crashes

**File:** `probe.py:144`, `table1.py:33`
**Issue:**
- `run.json` (holding `spent`, `stopped_reason` and the recovery values) is written only after the loop.
- Ctrl-C or an unexpected exception leaves `requests.jsonl` without `run.json`. `table1.load_run` then raises `FileNotFoundError` on the newest run.
- There is also no record of how much quota the aborted run consumed.

**Fix:** Write `run.json` after every group (cheap), or use `try/finally` around the loop. In table1, treat a missing run.json as `{}` and print that the run was incomplete.

**Status:** fixed (74bd2c0, c84d7ee). run.json is rewritten after every stage and in a `finally` (`interrupted`), with `reserved_unsettled`. table1 loads a run without run.json as `incomplete`.

### ME-05: table1 assumes every record has `model`; the /models record does not

**File:** `table1.py:46,67`, `probe.py:84-88,107`
**Issue:** The `list_models` record has no `"model"` key, and `save()` does not add one. If Groq returns any `x-ratelimit-*` header on `GET /models`, or a 429 with a limit body, `from_header`/`limit_from_429` raise `KeyError`. The fake server's /models sends no such headers, so the tests miss it.
**Fix:** In `save()`, set `record.setdefault("model", r["model"])`, and in table1 use `r.get("model") or "models-endpoint"`.

**Status:** fixed (74bd2c0, c84d7ee). `save()` sets `model`; table1 uses `models-endpoint` when it is missing.

### ME-06: TTFT mixes in connection setup on some requests and not on others

**File:** `relay/llm.py:109-112`, `ask.py:42`
**Issue:**
- `start` is taken before `client.stream`, so TTFT includes DNS, TCP and TLS whenever httpx opens a new connection.
- That happens for every `ask.py` call (new client each time), for most burst and concurrency requests (new parallel connections), and for some spaced requests (httpx keep-alive expiry is 5 s; spacing is 4 s plus the latency).
- The latency spread in Table 3/heading 4 therefore mixes two populations.

**Fix:** Record connection reuse via httpx trace extension (`extensions={"trace": cb}` capturing `connection.connect_tcp.started`), or send one warm-up request per client, and state the definition in the docstring.

**Status:** fixed (90a9298). Chose **measure consistently**: TTFT always runs from just before the send, including connection setup when one is opened. Every record carries `new_connection` (httpcore trace hook), so the two populations can be split. The probe's free /models call opens the first connection.

### ME-07: Multi-id citations like `[moshi-C-012, moshi-C-013]` are silently dropped, not flagged

**File:** `config.py:91`, `ask.py:30-34`
**Issue:** `CITATION_PATTERN` only matches a single id per bracket. Comma-separated brackets, which models commonly produce, match nothing. They are neither mapped nor flagged as `NOT_RETRIEVED`, so an answer can look uncited, or partly cited, with no signal. Ids above 999 per paper would also never match (`\d{3}` against `n:03d`); the largest today is 219, but nothing guards this.
**Fix:** Find bracket groups, then split them on commas:
```python
for group in re.findall(r"\[([^\]]+)\]", answer):
    for pid in (x.strip() for x in group.split(",")):
        if re.fullmatch(r"[a-z]+-[ABC]-\d+", pid): ...
```
Separately, report any bracket that looked like a citation but did not parse.

**Status:** fixed (6f681ef). Comma-separated brackets parse, ids of any length parse, and citation-like parts that do not parse are flagged `NOT A PIECE ID`.

### ME-08: Stage order makes the concurrency and max_tokens stages measure leftover throttling

**File:** `probe.py:47-54,116-143`
**Issue:** The concurrency ramp and the 50/1000 max_tokens pair run immediately after `recovery_tpm`, whose loop stops at the *first* 200, while the TPM window is still nearly exhausted. A 429 at level 4 or 8, or on the 1000-token request, is then ambiguous (TPM vs concurrency vs admission charging). Table1 hedges for concurrency but not for the pair. The pair is also never used by table1, so its ~1k estimated tokens buy evidence nothing reads.
**Fix:** Sleep until `x-ratelimit-reset-tokens` (or 60 s) before the ramp and the pair, and record `x-ratelimit-remaining-tokens` before and after the pair. Either add a table1/notes reader for the pair or drop it.

## Low

**Status:** deferred to phase 2. Reason: the default lean profile no longer runs the max_tokens pair or the TPM stages; they run only with `--profile full`. A 60 s pause now precedes the concurrency ramp and tpm_burst, which removes most leftover throttling. Reading the pair (x-ratelimit-reset-tokens waits, remaining-tokens before and after) is only needed if Tanush asks for the full profile, so it moves to phase 2 with the gateway work that would use it.

### LO-01: Committed probe and trace files will carry Cloudflare cookies and the Groq org id

**File:** `relay/llm.py:116,118`, README step 6
**Issue:**
- `dict(response.headers)` keeps `set-cookie` (`__cf_bm=...`) verbatim.
- Real 429 bodies include ``organization `org_...` ``.
- README tells Tanush to commit `data/probe/run_*/` and `data/traces/ask.jsonl`.

These are not the key, but they are account identifiers and session tokens in a public submission.
**Fix:** Drop `set-cookie` when building `record["headers"]`, and redact `org_[A-Za-z0-9]+` in `redact`.

**Status:** fixed (9bd5d03). set-cookie, set-cookie2 and cookie are dropped; x-ratelimit-* and retry-after are kept; `org_...` is redacted.

### LO-02: The key-leak guard can pass vacuously or check the wrong bytes

**File:** `tests/test_no_keys.py:16-29`, `.githooks/pre-commit`, README step 6
**Issue:**
- It scans only `git ls-files`. Following README step 6 literally ("commit ... only after test_no_keys passes"), the test is run before `git add`, so new data files are not scanned.
- The hook reads the working tree, not the staged blob.
- `--no-verify` skips the hook.

**Fix:** In README, run the test after `git add`. In the guard, read staged content (`git show :<path>`), or additionally scan `data/probe` and `data/traces` regardless of tracking.

**Status:** fixed (4eb9bbf). The guard reads staged blobs (`git show :path`) and always scans data/probe and data/traces. README runs it after `git add` and warns against `--no-verify`. Also fixed a real hazard found while fixing: inside the pre-commit hook, the guard's throwaway test repos inherited GIT_DIR/GIT_INDEX_FILE and wrote into the real repository (set core.bare=true and staged the fixture files). GIT_* is now stripped.

### LO-03: The HTML version check falls back to "the tag appears anywhere"

**File:** `library/fetch.py:40-44`
**Issue:** If the watermark `arXiv:<id>vN` is missing, any occurrence of `2410.00037v1` passes, for example a v2 page linking to v1. That is the exact Moshi trap. The test (`test_content_states_version`) is stricter than the code.
**Fix:** Require the `arXiv:` watermark, or else raise.

**Status:** fixed (d182108). The `arXiv:<id>vN` watermark is required.

### LO-04: Mid-stream error events and `data:[DONE]` without a space are mishandled

**File:** `relay/llm.py:121-124`
**Issue:**
- A `data: {"error": ...}` event during a 200 stream is stored only as `final_chunk`. The record shows status 200, empty content and no error.
- `data:[DONE]` (valid SSE, which the phase-3 stand-in might emit) reaches `json.loads("[DONE]")` and records a spurious exception.

**Fix:** Compare with `line[5:].strip() == "[DONE]"`. If `"error" in chunk`, set `record["error_body"]`.

**Status:** fixed (7761fd0). `data:[DONE]` is accepted, and error events in a 200 stream go to `error_body`.

### LO-05: Recovery time ends at the end of the 200's stream and starts at the first 429's completion

**File:** `probe.py:85-86,132`
**Issue:** `received_s` is stamped in `save()`, after the whole stream is read. The recovery value therefore includes the re-admitted request's full generation time. Granularity is also the 5 s poll. It is labelled "medium", but the docstring does not say this.
**Fix:** Stamp `sent_s` before the send and use `sent_s + ttft` (or `sent_s`) for the re-admission moment, and document the granularity in the How-found text.

**Status:** fixed (74bd2c0). `sent_s` is stamped before each send; recovery = the admitted request's `sent_s` minus the 429's arrival. Poll granularity is stated in the How-found text.

### LO-06: Unvalidated numeric edge cases in the ledger

**File:** `probe.py:95`, `relay/llm.py:48-62`
**Issue:**
- `usage = {"total_tokens": None}` makes `(...).get("total_tokens", est)` return None, which raises a TypeError and aborts the run, losing run.json (see ME-04).
- `--max-tokens-total 0` or a negative value is accepted.

**Fix:** Use `usage.get("total_tokens") or r["est_tokens"]`, and refuse caps ≤ 0.

**Status:** fixed (74bd2c0, earlier HI-02 work). A `None` total is charged at the reservation; caps of 0 or less are refused in `check_spend`.

### LO-07: Math cleaning misses common font commands

**File:** `library/parse.py:20`
**Issue:** `\textbf`, `\textit`, `\mathbb`, `\boldsymbol` and `\bm` are not stripped, which produces tokens such as `textbfx` and `mathbbR` that BM25 and readers cannot match.
**Fix:** Extend the alternation (`textbf|textit|mathbb|boldsymbol|bm`).

**Status:** deferred to phase 2. Reason: changing math cleaning changes every piece's text and therefore BM25 behaviour, which should be judged together with the phase-2 evaluation questions rather than changed blind now.

### LO-08: Test reliability gaps

**File:** `tests/test_retrieval.py:16,59-68`, `tests/test_table1.py:18`
**Issue:**
- `test_detect_papers` and `test_no_groq_dependency` need no data but are skipped by the module-level `requires_data`.
- `"4" in by_name["Requests per minute"]` passes on any value containing a 4.

**Fix:** Move the two tests to an unmarked module, and assert `by_name[...].startswith("4 (fake-model)")`.

**Status:** deferred to phase 2. Reason: test-only tidying with no effect on any real run or number; it fits the phase-2 test pass (test_detect_papers/test_no_groq_dependency move; exact Requests-per-minute assertion).

### LO-09: Code an intern would struggle to explain live

**File:** `probe.py:132`, `probe.py:47-55`, `table1.py:132-133`, `library/pieces.py:19-22`
**Issue:**
- `s[f"{stage}_s"]` builds the summary key from the stage name. Renaming a stage silently breaks `table1.recovery`, which reads `recovery_rpm_s`/`recovery_tpm_s`.
- The plan is built by list-multiplying one dict and then copying every entry.
- Row 4 of Table 1 is a conditional expression inside a list literal.
- `_windows` relies on non-obvious arithmetic (`len - size + stride`) plus a redundant filter. It is correct, but hard to defend live.

**Fix:** Use explicit keys (`s["recovery_rpm_s"] = ...` in an if/else), a plain loop in `plan_requests`, a named helper for the TPD row, and a comment or plain `while` loop in `_windows`.

**Status:** fixed (74bd2c0, c84d7ee, 9e5679d). Explicit `recovery_rpm_s`/`recovery_tpm_s` keys, a plain per-stage plan builder (no list multiplication), a `tokens_per_day()` helper, and a plain `while` loop in `_windows`.

## Verified as safe

These were checked and no defect was found.
- No code writes or opens `.env` for writing.
- `load_api_key` output is never printed.
- Request headers are never in a record.
- Exceptions and error bodies are redacted.
- Tests cannot reach the real key (`conftest.py:10-14`) or real Groq (`no_network` fixtures; the refusal paths exit before loading the key or models).
- `probe.py --dry-run` loads no key.
- `_windows` covers every word without redundant tail windows.
- Usage parsing (`usage` or `x_groq.usage`, last wins) and header capture match the documented Groq shape.

---

_Reviewed: 2026-11-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
