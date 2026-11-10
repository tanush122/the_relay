"""Ask one question: retrieve pieces, stream one cited draft, map the citations in code.

This is the thinnest real path. The full five steps (and the refusal and check steps)
arrive in phase 2, so nothing here judges the answer; unknown citations are only flagged.
Real mode refuses before doing any work unless --confirm and --max-tokens-total are given,
because every real call spends the shared daily quota. It also refuses when the estimate
(prompt upper bound + the full ANSWER_MAX_TOKENS) is over the cap, and afterwards prints
the tokens Groq actually reported against the cap. The cap is a reservation-based bound:
it can only be passed if Groq counts more prompt tokens than the deliberately high estimate.

  uv run python ask.py "What is d_ff in Attention Is All You Need?" --dry-run
"""

import argparse
import asyncio
import re
import sys

import config
from library import parse, search
from library.pieces import cite_label
from relay import llm

NOT_RETRIEVED = "NOT AMONG RETRIEVED PIECES"
NOT_A_PIECE_ID = "NOT A PIECE ID (citation could not be parsed)"


def build_messages(question, pieces):
    numbered = "\n\n".join(f"[{p['piece_id']}] ({cite_label(p)})\n{p['text']}" for p in pieces)
    return [{"role": "system", "content": config.ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": f"{numbered}\n\nQuestion: {question}"}]


def map_citations(answer, pieces):
    """[(cited id, label)] in first-seen order, repeats listed once.

    A bracket may hold one id or several: [moshi-C-012, moshi-C-013]. gpt-oss sometimes
    uses its own lenticular brackets instead, 【moshi-C-012】 (seen in the first real
    answer, 10 Nov), so both kinds count. An id we did not
    retrieve is flagged NOT_RETRIEVED. A bracket part that looks like a citation (it has
    -A-, -B- or -C- in it) but is not a valid id is flagged NOT_A_PIECE_ID, never dropped.
    """
    by_id = {p["piece_id"]: p for p in pieces}
    found = []
    for group in re.findall(r"[\[【]([^\[\]【】]+)[\]】]", answer):
        for part in group.split(","):
            part = part.strip()
            if re.fullmatch(config.CITATION_ID, part):
                found.append((part, cite_label(by_id[part]) if part in by_id else NOT_RETRIEVED))
            elif re.search(r"-[ABC]-", part):
                found.append((part, NOT_A_PIECE_ID))
    return list(dict.fromkeys(found))


def _print_now(text):
    print(text, end="", flush=True)


async def draft(question, pieces, api_key, base_url=None, trace_path=None, cap=None):
    async with llm.make_client() as client:
        record = await llm.stream_chat(
            client, config.DRAFT_MODEL, build_messages(question, pieces),
            config.ANSWER_MAX_TOKENS, api_key, base_url=base_url, on_content=_print_now,
            tag="ask")
    print()
    actual = (record["usage"] or {}).get("total_tokens")
    record["cap"] = cap
    if trace_path:
        llm.write_trace(record, trace_path)
    print(f"Actual spend: {actual if actual is not None else 'not reported'} tokens; cap {cap}")
    if actual is not None and cap is not None and actual > cap:
        print("WARNING: Groq counted more tokens than the cap; raise REQUEST_OVERHEAD_TOKENS")
    if record["status"] != 200 or record["exception"]:
        print(f"Request failed: status {record['status']} {record['exception'] or ''}")
    cited = map_citations(record["content"], pieces)
    for pid, label in cited:
        print(f"[{pid}] -> {label}")
    if record["content"] and not cited:
        print("NO CITATION FOUND in the answer")
    headers, usage = record["headers"], record["usage"] or {}
    print(f"ttft_ms={record['ttft_ms']} total_ms={record['total_ms']} "
          f"total_tokens={usage.get('total_tokens')} "
          f"remaining_tokens={headers.get('x-ratelimit-remaining-tokens')} "
          f"remaining_requests={headers.get('x-ratelimit-remaining-requests')}")
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("question")
    ap.add_argument("--setting", default=config.RETRIEVAL_SETTING, choices=sorted(config.SETTINGS))
    ap.add_argument("--dry-run", action="store_true", help="retrieve and estimate; no request")
    ap.add_argument("--confirm", action="store_true", help="allow one real model call")
    ap.add_argument("--max-tokens-total", type=int, help="hard cap for this run's tokens")
    args = ap.parse_args(argv)

    # Refuse before loading models or the key, so a forgotten flag costs nothing.
    if not args.dry_run and not args.confirm:
        print("Refusing real call: pass --confirm after reviewing the estimate")
        raise SystemExit(2)
    if not args.dry_run and args.max_tokens_total is None:
        print("Refusing: pass --max-tokens-total N")
        raise SystemExit(2)

    index = search.build_index(parse.load_all_blocks(), args.setting)
    pieces = []
    for piece, score in search.retrieve(index, args.question):
        pieces.append(piece)
        print(f"{piece['piece_id']}  {score:8.4f}  {cite_label(piece)}")
    messages = build_messages(args.question, pieces)
    estimate = llm.estimate_tokens(" ".join(m["content"] for m in messages)) + config.ANSWER_MAX_TOKENS
    if args.dry_run:
        print(f"Estimated spend: {estimate} tokens (dry run: no request sent)")
        return
    print(llm.describe_target(config.BASE_URL))
    llm.check_spend(estimate, args.confirm, args.max_tokens_total)
    api_key = llm.key_for(config.BASE_URL)
    if not api_key:
        print("No key: paste it into .env after GROQ_API_KEY= (never into chat)")
        raise SystemExit(2)
    asyncio.run(draft(args.question, pieces, api_key, trace_path=config.TRACES_DIR / "ask.jsonl",
                      cap=args.max_tokens_total))


if __name__ == "__main__":
    main(sys.argv[1:])
