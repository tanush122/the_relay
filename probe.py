"""Probe Groq's real limits and latency, saving every raw response as evidence for Table 1.

What each stage measures and why (design: assistant default, pending Tanush):
- models: a free GET that confirms which candidate models exist.
- header_sample: one request per model; shows each model's x-ratelimit-* headers and
  whether a reasoning model (gpt-oss) streams reasoning before the first content token.
- spaced: small requests a few seconds apart, for the latency (TTFT) spread.
- rpm_burst / tpm_burst: headers only show requests/day and tokens/minute, so the
  per-minute request limit and daily limits come from 429 bodies. Two bursts, so the
  request limit (many tiny requests) and token limit (a few large prompts) trip separately.
- recovery_*: after a burst's 429, a tiny request every few seconds until the first 200.
- concurrency: 1, 2, 4, 8 requests at once, to give "requests in flight" a method.
- max_tokens_pair: max_tokens 50 vs 1000 on the same prompt: is max_tokens charged at admission?
Real mode refuses without --confirm and --max-tokens-total, and stops before the running
spend could pass the cap. Dry run: uv run python probe.py --dry-run
"""

import argparse
import asyncio
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import config
from relay import llm


def _req(stage, model, prompt, max_tokens, group):
    return {"stage": stage, "model": model, "prompt": prompt, "max_tokens": max_tokens,
            "est_tokens": llm.estimate_tokens(prompt) + max_tokens, "group": group}


def plan_requests(p=config.PROBE):
    """Every request the probe may send, in order. Recovery polls count at their maximum."""
    main, small, tiny = p["main_model"], p["small_prompt"], p["small_max_tokens"]
    words = "The library holds three papers about sequence models and speech. ".split()
    filler = " ".join(itertools.islice(itertools.cycle(words),
                                       int(p["tpm_burst_prompt_tokens"] / config.TOKENS_PER_WORD)))
    plan = [{"stage": "models", "model": None, "prompt": "", "max_tokens": 0,
             "est_tokens": 0, "group": "models"}]
    plan += [_req("header_sample", m, small, p["header_sample_max_tokens"], f"header-{m}")
             for m in p["models"]]
    plan += [_req("spaced", main, small, tiny, f"spaced-{i}") for i in range(p["spaced_requests"])]
    plan += [_req("rpm_burst", main, small, tiny, "rpm_burst")] * p["rpm_burst_requests"]
    plan += [_req("recovery_rpm", main, small, tiny, "recovery_rpm")] * p["recovery_max_polls"]
    plan += [_req("tpm_burst", main, f"{filler}\n{small}", p["tpm_burst_max_tokens"],
                  "tpm_burst")] * p["tpm_burst_requests"]
    plan += [_req("recovery_tpm", main, small, tiny, "recovery_tpm")] * p["recovery_max_polls"]
    for level in p["concurrency_levels"]:
        plan += [_req("concurrency", main, small, tiny, f"concurrency-{level}")] * level
    plan += [_req("max_tokens_pair", main, small, n, f"pair-{n}") for n in p["max_tokens_pair"]]
    return [dict(r) for r in plan]  # copies, so repeated entries are independent


def print_plan(plan, p=config.PROBE):
    for i, r in enumerate(plan, start=1):
        est_in = r["est_tokens"] - r["max_tokens"]
        print(f"{i:4d}  {r['stage']:<16} {r['model'] or '-':<26} in~{est_in:<5} "
              f"max_out {r['max_tokens']:<5} est {r['est_tokens']}")
    for stage, rows in itertools.groupby(plan, key=lambda r: r["stage"]):
        rows = list(rows)
        print(f"subtotal {stage:<16} {len(rows):3d} requests  {sum(r['est_tokens'] for r in rows)} tokens")
    total = sum(r["est_tokens"] for r in plan)
    print(f"ESTIMATED TOTAL: {total} tokens (upper bound; default cap {p['default_cap']})")
    return total


async def run_probe(plan, api_key, cap, out_dir, base_url=None, p=config.PROBE):
    """Send the plan, never letting reserved + spent tokens pass cap; save every record."""
    base_url = base_url or config.BASE_URL
    run_dir = out_dir / f"run_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / "requests.jsonl"
    t0 = time.monotonic()
    s = {"cap": cap, "spent": 0, "requests_sent": 0, "stopped_reason": "done",
         "base_url_host": urlparse(base_url).hostname, "models_missing": [],
         "estimated_total": sum(r["est_tokens"] for r in plan),
         "recovery_rpm_s": None, "recovery_tpm_s": None,
         "recovery_poll_interval_s": p["recovery_poll_interval_s"]}

    def save(record, r):
        record.update(stage=r["stage"], group=r["group"], planned_est=r["est_tokens"],
                      received_s=round(time.monotonic() - t0, 3))
        llm.write_trace(record, log)
        return record

    async def send(client, r):
        messages = [{"role": "user", "content": r["prompt"]}]
        record = await llm.stream_chat(client, r["model"], messages, r["max_tokens"],
                                       api_key, base_url=base_url, tag="probe")
        s["requests_sent"] += 1
        s["spent"] += (record["usage"] or {}).get("total_tokens", r["est_tokens"])
        return save(record, r)

    async def group(client, rows):
        """Send rows concurrently, or return None if they would pass the cap."""
        if s["spent"] + sum(r["est_tokens"] for r in rows) > cap:
            s["stopped_reason"] = "cap"
            return None
        return await asyncio.gather(*(send(client, r) for r in rows))

    async with llm.make_client() as client:
        first = plan[0]
        models = save(await llm.list_models(client, api_key, base_url=base_url), first)
        s["requests_sent"] += 1
        if models["status"] != 200:
            s["stopped_reason"] = f"models_failed: status {models['status']}"
        else:
            s["models_missing"] = [m for m in p["models"] if m not in models["ids"]]
            if p["main_model"] in s["models_missing"]:
                s["stopped_reason"] = "main_model_missing"
        last_429 = None  # received_s of the latest burst's first 429
        for name, rows in itertools.groupby(plan[1:], key=lambda r: r["group"]):
            if s["stopped_reason"] != "done":
                break
            rows = [r for r in rows if r["model"] not in s["models_missing"]]
            if not rows:
                continue  # a candidate model that does not exist
            stage = rows[0]["stage"]
            if stage.startswith("recovery"):
                if last_429 is None:
                    continue  # the burst never hit a limit: nothing to recover from
                for r in rows:
                    await asyncio.sleep(p["recovery_poll_interval_s"])
                    done = await group(client, [r])
                    if done is None:
                        break
                    if done[0]["status"] == 200:
                        s[f"{stage}_s"] = round(done[0]["received_s"] - last_429, 3)
                        break
                last_429 = None
                continue
            if stage == "spaced" and name != "spaced-0":
                await asyncio.sleep(p["spaced_interval_s"])
            done = await group(client, rows)
            if done is None:
                break
            if stage.endswith("burst"):
                hits = [d["received_s"] for d in done if d["status"] == 429]
                last_429 = min(hits) if hits else None
    (run_dir / "run.json").write_text(json.dumps(s, indent=2) + "\n")
    return {**s, "run_dir": str(run_dir)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Probe Groq limits and latency (raw evidence).")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and estimate only")
    ap.add_argument("--confirm", action="store_true", help="allow real requests")
    ap.add_argument("--max-tokens-total", type=int, help="hard cap on tokens for this run")
    ap.add_argument("--out", default=str(config.PROBE_DIR))
    ap.add_argument("--base-url", default=config.BASE_URL)
    args = ap.parse_args(argv)
    plan = plan_requests()
    total = print_plan(plan)
    if args.dry_run:
        return
    llm.check_spend(total, args.confirm, args.max_tokens_total, allow_over_cap=True)
    api_key = llm.load_api_key()
    if not api_key:
        print("No key in .env; paste it after GROQ_API_KEY= then rerun")
        raise SystemExit(2)
    summary = asyncio.run(run_probe(plan, api_key, args.max_tokens_total, Path(args.out),
                                    base_url=args.base_url))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
