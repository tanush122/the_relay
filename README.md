# The Relay

A small Python question-answering pipeline over three fixed arXiv papers (Attention v7, Moshi v1, H-Net v2). It answers with citations or refuses, runs on Groq's free tier, and is measured under bursty load against both the real service and a self-written stand-in model service.

Built by Tanush as a take-home for the ML Engineering Intern role at Vaani. Every number in the write-up recomputes from `data/results.csv`.

## Contents

- [Overview](#overview)
- [Repository layout](#repository-layout)
- [Setup](#setup)
- [Usage (spends no Groq tokens)](#usage-spends-no-groq-tokens)
- [Recomputing the tables and figures](#recomputing-the-tables-and-figures)
- [Tests](#tests)
- [Evaluation questions and grading](#evaluation-questions-and-grading)
- [Running against the real Groq API](#running-against-the-real-groq-api)
- [Documentation](#documentation)

## Overview

- **Pipeline** (`relay/pipeline.py`): five steps from question to a cited answer or a refusal; it never sends an uncited answer to stay fast.
- **Retrieval** (`library/`): fetches and parses the three papers and searches them locally.
- **Load testing** (`relay/loadgen.py`, `relay/standin.py`): bursty scenarios against the real service and a stand-in model service.
- **Results** (`data/results.csv`, `relay/report.py`): one raw CSV; Tables 1, 2a, 2b and 3 are computed from it and from the probe files.

## Repository layout

```
.
├── relay/          pipeline, gateway, LLM client, load generator, stand-in service, report
├── library/        paper fetch, parse, pieces, local search
├── scripts/        submission build, history export, table fill, write-up PDF
├── tests/          pytest suite (fake Groq server only, no real calls)
├── data/           questions, grading sheets, probe runs, traces, results.csv
├── docs/           brief, plan, research notes, decisions, quota log, write-up
├── .planning/      planning artifacts (phases, roadmap, state)
├── .githooks/      optional pre-commit key-leak guard
├── probe.py        rate-limit probe
├── table1.py       Table 1 draft from the newest probe run
├── config.py       scenarios, final-run names and other settings
├── pyproject.toml  dependencies (uv)
└── .env.example    template for the git-ignored .env
```

## Setup

```sh
$HOME/.local/bin/uv sync          # Python 3.12 + pinned packages into .venv
```

uv is installed at `~/.local/bin/uv` and is not on PATH by default; add `export PATH="$HOME/.local/bin:$PATH"` to use plain `uv`.
Copy `.env.example` to `.env` and put the key after `GROQ_API_KEY=`. `.env` is git-ignored: never put the key in chat, code or commits.
Optional: `git config core.hooksPath .githooks` enables a pre-commit guard that blocks any staged `gsk_` key.

## Usage (spends no Groq tokens)

```sh
uv run python -m library.fetch                      # fetch the 6 paper files once, write data/manifest.json
uv run python -m relay ask "What is d_ff in Attention Is All You Need?" --setting C --dry-run
uv run python -m relay eval --setting A --dry-run   # estimate for every question in data/questions.csv
uv run python -m relay report                       # Tables 1, 2a, 2b, 3 from the probe files and results.csv
uv run python -m relay validate                     # results.csv against the brief's columns and rules
uv run python probe.py --dry-run                    # the lean probe: every request + ESTIMATED TOTAL
uv run python table1.py                             # Table 1 draft from the newest probe run
```

Local models download once into `.cache/huggingface`. After that, `HF_HUB_OFFLINE=1` in front of a command stops sentence-transformers checking huggingface.co (optional).

## Recomputing the tables and figures

```sh
uv run python table1.py                                  # Table 1: limits, from the probe files in data/probe/
uv run python -m relay report                            # Tables 1, 2a, 2b and 3, from data/results.csv
uv run python -m relay calibrate                         # stand-in vs real latency (heading 2)
uv run python -m relay anatomy retry_budget_on           # heading 4: one slow request split into waiting / working / retrying
uv run python -m relay load <scenario>                   # re-run one load scenario on the stand-in (appends rows)
uv run python scripts/export_history.py                  # conversation history into export/conversation/, keys redacted
```

Load scenarios (`config.SCENARIOS`, all on the stand-in): steady, burst, burst_cached, overload, overload_small_first, retry_budget_on, retry_budget_off, limit_halved, day_exhausted.

Table 3 reads only the final evaluation runs (`config.TABLE3_RUNS`: eval-final-A, -B, -C). In B, the 2 questions Groq refused with a 429 (Q1 per-minute, Q18 per-day) are replaced by their re-asks in eval-final-B-retry (`config.TABLE3_RETRIES`); the refused rows stay in `results.csv`. The earlier eval-A/B/C/C2 rows also stay in `results.csv` as the record of how the system got there.

## Tests

```sh
uv run pytest -q -rs                                # full suite, fake server only, no real calls
uv run pytest -q tests/test_no_keys.py              # key-leak guard
```

## Evaluation questions and grading

`data/questions.csv` has three columns: `question`, `expected`, `type`. The expected answer is `not in papers` for a question the papers do not answer. `type` is one of `prose`, `table`, `cross-paper`, `unanswerable`. Quote any field that contains a comma. Format example (made up to show the format, not an evaluation question):

```
question,expected,type
"What colour is the cover of the Moshi paper?",not in papers,unanswerable
```

After a run, grade `data/grading/<run>.csv` by filling its `grade` column with `correct`, `wrong`, `refused_correctly` or `refused_wrongly`, then:

```sh
uv run python -m relay grade data/grading/<run>.csv   # copies the grades into results.csv
```

## Running against the real Groq API

Each step spends the shared daily token quota and is logged in `docs/QUOTA.md`. Run the `--dry-run` form first and approve a cap.

1. The key is in `.env` after `GROQ_API_KEY=`.
2. Review the `--dry-run` estimate and approve a cap.
3. Probe: `uv run python probe.py --confirm --max-tokens-total <approved cap>`. The real key goes only to `https://api.groq.com`; the run stops at the cap or on any unexpected answer and saves what it has.
4. One question: `uv run python -m relay ask "<question>" --confirm --max-tokens-total <approved cap>`
5. Evaluation: `uv run python -m relay eval --setting A --confirm --max-tokens-total <approved cap>`, then grade the sheet.
6. `git add data/probe/run_*/ data/traces/ data/results.csv`, then `uv run pytest -q tests/test_no_keys.py`, and commit only if it passes. The guard reads the staged copies (and every file under `data/probe` and `data/traces`), so run it after `git add`. Never commit with `--no-verify`: that skips the hook.

## Documentation

- [docs/BRIEF.md](docs/BRIEF.md): the assignment brief, verbatim
- [docs/PLAN.md](docs/PLAN.md): plan of record
- [docs/RESEARCH.md](docs/RESEARCH.md): research notes
- [docs/DECISIONS.md](docs/DECISIONS.md): decision log
- [docs/WRITEUP.md](docs/WRITEUP.md): the write-up
- [docs/QUOTA.md](docs/QUOTA.md): token quota log
