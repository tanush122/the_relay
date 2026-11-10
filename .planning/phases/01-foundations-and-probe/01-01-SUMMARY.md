---
phase: 01-foundations-and-probe
plan: 01
subsystem: environment
tags: [uv, python-3.12, config, secrets, pytest]
requires: []
provides:
  - "uv project on CPython 3.12.16 with == pinned deps and committed uv.lock"
  - "config.py: every phase-1 tunable (consumed by plans 02-05)"
  - "gsk_ key-leak guard test + autouse no_real_key fixture + requires_data skip marker"
  - "optional pre-commit hook (repo-local core.hooksPath .githooks)"
affects: [01-02, 01-03, 01-04, 01-05]
tech-stack:
  added: [uv 0.13.7, CPython 3.12.16, httpx 0.28.1, rank-bm25 0.2.2, sentence-transformers 6.2.0, beautifulsoup4 4.15.0, lxml 6.1.3, pytest 9.2.0]
  patterns: ["plain module-level constants in config.py", "tests never see the real key (autouse fixture)"]
key-files:
  created: [pyproject.toml, uv.lock, .python-version, .env.example, config.py, library/__init__.py, relay/__init__.py, tests/__init__.py, tests/conftest.py, tests/test_no_keys.py, .githooks/pre-commit]
  modified: [.gitignore]
decisions:
  - "requires_data reads manifest.json as {\"files\": [{\"name\": <file under data/raw>}, ...]}; plan 02 must write the manifest in that shape or adjust conftest._papers_missing"
metrics:
  duration: "~5 min"
  completed: 2026-11-10
  tasks: 3
  files: 12
---

# Phase 1 Plan 01: Environment, config and key guard Summary

uv-managed Python 3.12.16 project with == pinned httpx / rank-bm25 / sentence-transformers / beautifulsoup4 / lxml / pytest, a single config.py holding every phase-1 tunable, and a gsk_ key-leak guard over git-tracked files that also runs as a pre-commit hook.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Install gate (installer + package list) | approved by Tanush (relayed by orchestrator), no commit |
| 2 | uv + Python 3.12, pinned project, ignore/key files, config.py | b15c4c1 |
| 3 | gsk_ guard test, conftest plumbing, pre-commit hook | bc5f05f |

## Resolved pinned versions

Direct: beautifulsoup4==4.15.0, httpx==0.28.1, lxml==6.1.3, rank-bm25==0.2.2, sentence-transformers==6.2.0; dev: pytest==9.2.0.
Notable transitive (locked in uv.lock, 77 packages): torch 2.15.0, transformers 5.22.2, huggingface-hub 2.4.0, numpy 2.5.4.
Interpreter: CPython 3.12.16 (uv-managed), running from the project's .venv.

## Verification results

- Plan verify command: `ok 3.12.16` (torch prints a harmless macOS "Redirects are currently not supported" warning on import).
- `config` check: `https://api.groq.com/openai/v1 llama-3.1-8b-instant True`.
- `git check-ignore .env data/raw/x .cache/x .pytest_cache/x` lists all; `git ls-files .env` empty.
- .env: only `test -e` and `stat -f %m` used; mtime unchanged; contents never opened.
- ~/.zshrc and ~/.zprofile sha256 unchanged after the installer (UV_NO_MODIFY_PATH=1).
- `uv run pytest -q tests/test_no_keys.py`: 5 passed.
- Hook: staging a scratch file with a runtime-built fake key and running .githooks/pre-commit exited 1; scratch file unstaged and deleted. The hook also ran (5 passed) on the Task 3 commit.

## Line counts (non-blank)

config.py 102, tests/test_no_keys.py 52, tests/conftest.py 16, .githooks/pre-commit 8, pyproject.toml 26.

## Putting uv on PATH (optional, Tanush's choice)

The installer did not edit shell profiles. To use plain `uv`, add `export PATH="$HOME/.local/bin:$PATH"` to your shell, or keep calling `$HOME/.local/bin/uv`.

## Deviations from Plan

- config.py is 102 non-blank lines against a ~75 target: every name the plan required is present; the extra lines are the PAPERS / SETTINGS / PROBE dicts laid out one entry per line for readability. Not trimmed.
- Task 1 (blocking-human gate) was not stopped at: Tanush's approval of the installer and package list was relayed by the orchestrator before execution.

## Known Stubs

None. (`requires_data` depends on the manifest shape plan 02 will create; see decisions.)

## Self-Check: PASSED

Files above exist; commits b15c4c1 and bc5f05f are in git log.
