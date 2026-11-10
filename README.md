# The Relay

A small Python question-answering pipeline over three fixed arXiv papers (Attention v7, Moshi v1, H-Net v2) that answers with citations or refuses, on Groq's free tier.
Phase 1 builds the paper library, local retrieval, a streaming client, the rate-limit probe and a Table 1 drafter.

## Setup

```sh
$HOME/.local/bin/uv sync          # Python 3.12 + pinned packages into .venv
```

uv is installed at `~/.local/bin/uv` and is not on PATH by default; add `export PATH="$HOME/.local/bin:$PATH"` to use plain `uv`.
The key goes only in the git-ignored `.env`, after `GROQ_API_KEY=` (never in chat, code or commits).

## Phase 1 commands (none of these spends Groq tokens)

```sh
uv run python -m library.fetch                      # fetch the 6 paper files once, write data/manifest.json
uv run pytest -q -rs                                # full test suite (fake server only, no real calls)
uv run python ask.py "What is d_ff in Attention Is All You Need?" --setting C --dry-run
uv run python probe.py --dry-run                    # every planned request + ESTIMATED TOTAL
uv run python table1.py                             # Table 1 draft from the newest probe run
```

Local models download once into `.cache/huggingface`. After that, `HF_HUB_OFFLINE=1` in front of a command stops sentence-transformers checking huggingface.co (optional).

## Human-gated real steps

Run only after Tanush's yes (plan 01-05). Each one spends the shared daily quota.

1. The key is in `.env` after `GROQ_API_KEY=` (never in chat).
2. Tanush reviews the `probe.py --dry-run` and `ask.py --dry-run` estimates and approves a cap.
3. `uv run python probe.py --confirm --max-tokens-total <approved cap>`
4. `uv run python table1.py`
5. One real cited answer: `uv run python ask.py "<question>" --setting C --confirm --max-tokens-total <approved cap>`
6. `git add data/probe/run_*/ data/traces/ask.jsonl`, then `uv run pytest -q tests/test_no_keys.py`, and commit only if it passes. The guard reads the staged copies (and every file under `data/probe` and `data/traces`), so run it after `git add`. Never commit with `--no-verify`: that skips the hook.
