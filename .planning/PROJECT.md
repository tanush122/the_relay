# The Relay

## What This Is

A take-home assignment for the ML Engineering Intern role at Vaani, built by Tanush. It is a small Python question-answering pipeline over three fixed arXiv papers that answers with citations or refuses, runs on Groq's free tier, and is measured under bursty load against both the real service and a self-written stand-in model service. The deliverable is the code, a raw results.csv, and a 2-page write-up whose numbers all recompute from that file.

Source documents: docs/BRIEF.md (verbatim brief, the authority), docs/PLAN.md (plan of record, proposed, awaiting Tanush's approval), docs/RESEARCH.md (research notes), docs/DECISIONS.md (decision log).

## Core Value

Every number in the write-up is a real measurement that recomputes from results.csv, and the system never sends an uncited or wrong answer to stay fast — all defended live by Tanush, line by line.

## Requirements

### Validated

(None yet — ship to validate)

### Active

See .planning/REQUIREMENTS.md (every brief heading, table column, results.csv column and ground rule traces to a requirement).

### Out of Scope

- Hedged requests — spend scarce quota under a token limit (candidate "deliberately not built")
- Second model provider / extra Groq accounts — forbidden by the brief
- Model-based grader — costs quota, adds something to defend; grading is by hand
- Web interface — not needed to measure anything
- Multi-worker deployment — one asyncio process is the right size; write-up says what changes at scale
- Frameworks that do the thinking (e.g. LangChain) — code must be explainable line by line

## Context

- Assignment received 9 Nov 2026; deadline Fri 13 Nov 2026, 5:22 PM IST; target submission 3 PM Friday.
- Groq free-tier limits are per organization and per model. Docs suggest roughly 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD for the main models — unverified until the first probe. Response headers expose only requests/day and tokens/minute; RPM and TPD appear only in 429 bodies.
- Papers: arXiv 1706.03762v7, 2410.00037v1 (not latest — version trap), 2507.07955v2.
- Vaani builds voice agents; time to first token is the metric the company cares about most.
- Environment: macOS, system Python 3.9.6, no uv yet (install pending approval), Node 22, git 2.50.
- GSD 1.50.0-canary.0 drives the build; each phase plan needs Tanush's approval before execution.

## Constraints

- **Tech stack**: Python, small and readable (target under ~1,500 lines), few dependencies, no LangChain — Tanush must explain and change every line live.
- **Data**: real measured data only; no invented numbers, no synthetic results presented as real.
- **Authorship**: Tanush writes the 15+ evaluation questions, the answer key, the grades, the Vaani feedback and the write-up's judgements.
- **Provider**: one Groq free account, one key; no tricks around limits (brief ground rule, Groq terms 3.2/6.3).
- **Security**: the Groq key lives only in a git-ignored .env; never in a committed file, log, output or chat.
- **Quota**: the daily token limit is shared by every real run; every real run prints its estimated token cost first and needs Tanush's yes.
- **Timeline**: four phases across Tue 10 – Fri 13 Nov 2026.
- **Environment**: work locally on Tanush's laptop in ~/Desktop/the-relay; installs (uv, Python 3.12) need his approval.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python | Tanush's choice | ✓ Decided |
| Real measured data only | Tanush's rule; brief recomputes tables from raw file | ✓ Decided |
| Work locally on laptop | Cloud workspace cannot reach Groq/arXiv | ✓ Decided |
| GSD agents drive the build, human gate per phase plan | Tanush: "use gsd agents wherever needed" | ✓ Decided |
| Gateway is the single place that knows the budget | Tokens are the scarce resource | — Pending (plan approval) |
| Speed targets 2,000 / 5,000 / 15,000 ms | TTFT matters most for a voice company | — Pending |
| Degradation ladder levels 0–4 | Degrade cost before dropping anyone | — Pending |
| Retrieval settings A/B/C | Table 3 comparison | — Pending |
| results.csv rules (status mapping, start_time = arrival, cost at list price) | Brief's format forces these | — Pending |
| Model choice after probe | Limits page decides | — Pending |
| Load shapes from real public traces | Defensible, not invented | — Pending |
| Two things deliberately not built | Write-up heading 8 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-11-10 after initialization (document-driven from docs/BRIEF.md, docs/PLAN.md, docs/RESEARCH.md)*
