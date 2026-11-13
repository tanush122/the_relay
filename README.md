# The Relay

A small Python question-answering pipeline over three fixed arXiv papers (Attention v7, Moshi v1, H-Net v2) that answers with citations or refuses, on Groq's free tier.
Phase 1 built the paper library, local retrieval, a streaming client, the rate-limit probe and a Table 1 drafter. Phase 2 adds the five-step pipeline, results.csv, the report and the evaluation harness.

## Setup

```sh
$HOME/.local/bin/uv sync          # Python 3.12 + pinned packages into .venv
```

uv is installed at `~/.local/bin/uv` and is not on PATH by default; add `export PATH="$HOME/.local/bin:$PATH"` to use plain `uv`.
The key goes only in the git-ignored `.env`, after `GROQ_API_KEY=` (never in chat, code or commits).

## Commands that spend no Groq tokens

```sh
uv run python -m library.fetch                      # fetch the 6 paper files once, write data/manifest.json
uv run pytest -q -rs                                # full test suite (fake server only, no real calls)
uv run python -m relay ask "What is d_ff in Attention Is All You Need?" --setting C --dry-run
uv run python -m relay eval --setting A --dry-run   # estimate for every question in data/questions.csv
uv run python -m relay report                       # Tables 1, 2a, 2b, 3 from the probe files and results.csv
uv run python -m relay validate                     # results.csv against the brief's columns and rules
uv run python probe.py --dry-run                    # the lean probe: every request + ESTIMATED TOTAL
uv run python table1.py                             # Table 1 draft from the newest probe run
```

## Recompute every table and figure (no Groq tokens)

```sh
uv run python table1.py                                  # Table 1: limits, from the probe files in data/probe/
uv run python -m relay report                            # Tables 1, 2a, 2b and 3, from data/results.csv
uv run python -m relay calibrate                         # stand-in vs real latency (heading 2)
uv run python -m relay anatomy retry_budget_on           # heading 4: one slow request split into waiting / working / retrying
uv run python -m relay load <scenario>                   # re-run one load scenario on the stand-in (appends rows)
uv run python scripts/export_history.py                  # conversation history into export/conversation/, keys redacted
```

Load scenarios (config.SCENARIOS, all on the stand-in): steady, burst, burst_cached, overload,
overload_small_first, retry_budget_on, retry_budget_off, limit_halved, day_exhausted.
Table 3 reads only the final evaluation runs (config.TABLE3_RUNS: eval-final-A, -B, -C); the
earlier eval-A/B/C/C2 rows stay in results.csv as the record of how the system got there.

## The questions file (Tanush writes it)

`data/questions.csv` has three columns: `question`, `expected`, `type`. Write the expected answer in your own words, or `not in papers` for a question the papers do not answer. `type` is one of `prose`, `table`, `cross-paper`, `unanswerable`. Two format examples (made up to show the format, NOT evaluation questions; do not copy them into the file):

```
question,expected,type
"What colour is the cover of the Moshi paper?",not in papers,unanswerable
"Which optimiser does paper X use, and with what learning rate?","Adam, 0.001 (§5.3)",prose
```

Quote any field that contains a comma. After a run, grade `data/grading/<run>.csv` by filling its `grade` column with `correct`, `wrong`, `refused_correctly` or `refused_wrongly`, then `uv run python -m relay grade data/grading/<run>.csv` copies the grades into results.csv.

Local models download once into `.cache/huggingface`. After that, `HF_HUB_OFFLINE=1` in front of a command stops sentence-transformers checking huggingface.co (optional).

## Human-gated real steps

Run only after Tanush's yes. Each one spends the shared daily quota and is logged in docs/QUOTA.md.

1. The key is in `.env` after `GROQ_API_KEY=` (never in chat).
2. Tanush reviews the `--dry-run` estimate and approves a cap.
3. Probe (done 10 Nov): `uv run python probe.py --confirm --max-tokens-total <approved cap>`. The real key goes only to `https://api.groq.com`; the run stops at the cap or on any unexpected answer and saves what it has.
4. One question: `uv run python -m relay ask "<question>" --confirm --max-tokens-total <approved cap>`
5. Evaluation: `uv run python -m relay eval --setting A --confirm --max-tokens-total <approved cap>`, then grade the sheet.
6. `git add data/probe/run_*/ data/traces/ data/results.csv`, then `uv run pytest -q tests/test_no_keys.py`, and commit only if it passes. The guard reads the staged copies (and every file under `data/probe` and `data/traces`), so run it after `git add`. Never commit with `--no-verify`: that skips the hook.
