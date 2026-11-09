<!-- GSD:project-start source:PROJECT.md -->

## Project

**The Relay**

A take-home assignment for the ML Engineering Intern role at Vaani, built by Tanush. It is a small Python question-answering pipeline over three fixed arXiv papers that answers with citations or refuses, runs on Groq's free tier, and is measured under bursty load against both the real service and a self-written stand-in model service. The deliverable is the code, a raw results.csv, and a 2-page write-up whose numbers all recompute from that file.

Source documents: docs/BRIEF.md (verbatim brief, the authority), docs/PLAN.md (plan of record, proposed, awaiting Tanush's approval), docs/RESEARCH.md (research notes), docs/DECISIONS.md (decision log).

**Core Value:** Every number in the write-up is a real measurement that recomputes from results.csv, and the system never sends an uncited or wrong answer to stay fast — all defended live by Tanush, line by line.

### Constraints

- **Tech stack**: Python, small and readable (target under ~1,500 lines), few dependencies, no LangChain — Tanush must explain and change every line live.
- **Data**: real measured data only; no invented numbers, no synthetic results presented as real.
- **Authorship**: Tanush writes the 15+ evaluation questions, the answer key, the grades, the Vaani feedback and the write-up's judgements.
- **Provider**: one Groq free account, one key; no tricks around limits (brief ground rule, Groq terms 3.2/6.3).
- **Security**: the Groq key lives only in a git-ignored .env; never in a committed file, log, output or chat.
- **Quota**: the daily token limit is shared by every real run; every real run prints its estimated token cost first and needs Tanush's yes.
- **Timeline**: four phases across Tue 10 – Fri 13 Nov 2026.
- **Environment**: work locally on Tanush's laptop in ~/Desktop/the-relay; installs (uv, Python 3.12) need his approval.

<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->

## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
