"""Probe Groq's real limits and latency, saving every raw response as evidence for Table 1.

The stages (config.PROBE["stages"]) are the lean probe Tanush approved; each stage stops
as soon as its question is answered:
- models: a free GET listing which candidate models exist.
- header_sample: one request per existing candidate model, for its x-ratelimit-* headers
  and whether a reasoning model (gpt-oss) streams reasoning before the first content token.
- spaced: small requests a few seconds apart, for the latency (TTFT) spread.
- rpm_burst: tiny requests in small waves, stopping at the first 429. Headers do not show
  the per-minute request limit; the 429 body does.
- recovery_rpm: one tiny request every few seconds, stopping at the first 200.
- concurrency: 1, 2, 4, 8 requests at once, stopping after the first level that gets a 429.

The cap bounds actual spend. Each request's estimate (prompt upper bound + chat-template
overhead + max_tokens) is reserved before it is sent, and no request is sent if
actual-so-far + reserved + its estimate would pass the cap. A response without usage is
charged its whole estimate. The run aborts, keeping what it saved, on any unexpected
answer: 401/403 or any other non-200/429 status, no response, a 429 during header_sample
or spaced, a daily-limit 429, or a header limit under half of config.DOCUMENTED_LIMITS.
It reports instead of retrying. run.json is rewritten after every stage and on Ctrl-C.

  uv run python probe.py --dry-run
"""

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import config
from relay import llm

NO_429_EXPECTED = {"header_sample", "spaced"}  # a 429 here means something is wrong


def _req(stage, group, model, prompt, max_tokens):
    return {"stage": stage, "group": group, "model": model, "prompt": prompt,
            "max_tokens": max_tokens, "est_tokens": llm.estimate_tokens(prompt) + max_tokens}


def stage_rows(stage, p):
    """Every request one stage may send. Bursts, recovery and the ramp count at their maximum."""
    main, small, tiny = p["main_model"], p["small_prompt"], p["small_max_tokens"]
    if stage == "models":
        return [{"stage": stage, "group": stage, "model": None, "prompt": "",
                 "max_tokens": 0, "est_tokens": 0}]
    if stage == "header_sample":
        return [_req(stage, f"header-{m}", m, small, p["header_sample_max_tokens"])
                for m in p["models"]]
    if stage == "spaced":
        return [_req(stage, f"spaced-{i}", main, small, tiny) for i in range(p["spaced_requests"])]
    if stage == "rpm_burst":
        return [_req(stage, stage, main, small, tiny) for _ in range(p["rpm_burst_requests"])]
    if stage == "recovery_rpm":
        return [_req(stage, stage, main, small, tiny) for _ in range(p["recovery_max_polls"])]
    if stage == "concurrency":
        rows = []
        for level in p["concurrency_levels"]:
            rows += [_req(stage, f"concurrency-{level}", main, small, tiny) for _ in range(level)]
        return rows
    raise ValueError(f"unknown probe stage: {stage}")


def plan_requests(p=config.PROBE):
    """Every request the probe may send, stage by stage."""
    plan = []
    for stage in p["stages"]:
        plan += stage_rows(stage, p)
    return plan


def stages_of(plan):
    return list(dict.fromkeys(r["stage"] for r in plan))  # in order, each once


def print_plan(plan, p=config.PROBE):
    for i, r in enumerate(plan, start=1):
        est_in = r["est_tokens"] - r["max_tokens"]
        print(f"{i:4d}  {r['stage']:<16} {r['model'] or '-':<26} in~{est_in:<5} "
              f"max_out {r['max_tokens']:<5} est {r['est_tokens']}")
    for stage in stages_of(plan):
        rows = [r for r in plan if r["stage"] == stage]
        print(f"subtotal {stage:<16} {len(rows):3d} requests  "
              f"{sum(r['est_tokens'] for r in rows)} tokens")
    total = sum(r["est_tokens"] for r in plan)
    print("(bursts, recovery polls and the concurrency ramp stop early; counted at their maximum)")
    print(f"ESTIMATED TOTAL: {total} tokens (upper bound; default cap {p['default_cap']})")
    return total


class ProbeRun:
    """One real run: the token ledger, the raw log (requests.jsonl) and the summary (run.json)."""

    def __init__(self, client, api_key, cap, run_dir, base_url, p, estimated_total):
        self.client, self.api_key, self.cap = client, api_key, cap
        self.run_dir, self.base_url, self.p = run_dir, base_url, p
        self.log = run_dir / "requests.jsonl"
        self.t0 = time.monotonic()
        self.reserved = 0  # estimates of requests sent but not yet answered
        self.last_429 = None  # received_s of the latest burst's first 429 of the right kind
        self.replies = {}  # stage -> [200 replies, of which had visible text]
        self.summary = {
            "base_url_host": urlparse(base_url).hostname, "cap": cap,
            "estimated_total": estimated_total, "spent": 0, "usage_reported": 0,
            "reserved_unsettled": 0, "requests_sent": 0, "stopped_reason": "running",
            "models_missing": [], "recovery_rpm_s": None,
            "recovery_poll_interval_s": p["recovery_poll_interval_s"], "notes": []}

    def clock(self):
        return round(time.monotonic() - self.t0, 3)

    @property
    def stopped(self):
        return self.summary["stopped_reason"] != "running"

    def stop(self, reason):
        if not self.stopped:  # the first reason wins
            self.summary["stopped_reason"] = reason

    def note(self, text):
        self.summary["notes"].append(text)

    def write_summary(self):
        self.summary["reserved_unsettled"] = self.reserved  # > 0 only if cut off mid-request
        (self.run_dir / "run.json").write_text(json.dumps(self.summary, indent=2) + "\n")

    def save(self, record, r, sent_s):
        record.update(stage=r["stage"], group=r["group"], planned_est=r["est_tokens"],
                      sent_s=sent_s, received_s=self.clock(),
                      limit_kind=llm.limit_kind(record.get("error_body")))
        record.setdefault("model", r["model"])  # the /models record has no model of its own
        llm.write_trace(record, self.log)

    def limits_too_low(self, record):
        """A reason if a header limit is far under the documented value, else None."""
        documented = config.DOCUMENTED_LIMITS.get(record["model"])
        if not documented:
            return None
        for header, name in (("x-ratelimit-limit-requests", "requests_per_day"),
                             ("x-ratelimit-limit-tokens", "tokens_per_minute")):
            value = record["headers"].get(header, "")
            if value.isdigit() and int(value) < self.p["low_limit_fraction"] * documented[name]:
                return (f"{record['model']} {header}={value} is under "
                        f"{self.p['low_limit_fraction']} x the documented {documented[name]}")
        return None

    def check(self, record):
        """Abort on any answer the probe does not expect: report, never retry."""
        status, stage = record["status"], record["stage"]
        if status == 200 and (record.get("exception") or record.get("error_body")):
            self.stop(f"abort: stream failed during {stage}")
        elif status == 200:
            too_low = self.limits_too_low(record)
            if too_low:
                self.stop(f"abort: {too_low}")
        elif status == 429 and record["limit_kind"] in ("RPD", "TPD"):
            self.stop(f"abort: daily limit {record['limit_kind']} hit during {stage}")
        elif status == 429 and stage in NO_429_EXPECTED:
            self.stop(f"abort: unexpected 429 during {stage}")
        elif status is None:
            self.stop(f"abort: no response during {stage}")
        elif status != 429:
            self.stop(f"abort: unexpected status {status} during {stage}")

    async def send(self, r):
        sent_s = self.clock()
        messages = [{"role": "user", "content": r["prompt"]}]
        record = await llm.stream_chat(self.client, r["model"], messages, r["max_tokens"],
                                       self.api_key, base_url=self.base_url, tag="probe")
        self.reserved -= r["est_tokens"]
        reported = (record["usage"] or {}).get("total_tokens")
        if reported is None:
            self.summary["spent"] += r["est_tokens"]  # unknown: charge the whole reservation
        else:
            self.summary["spent"] += reported
            self.summary["usage_reported"] += reported
        self.summary["requests_sent"] += 1
        self.save(record, r, sent_s)
        self.check(record)
        if record["status"] == 200:
            seen = self.replies.setdefault(r["stage"], [0, 0])
            seen[0] += 1
            seen[1] += bool(record["content"])
        return record

    def check_visible_text(self, stage, after):
        """Stop once `after` replies of a stage came back with reasoning only, no visible text.

        A reasoning model can spend all of max_tokens thinking; then there is no TTFT to
        measure and the rest of the run would waste tokens on a broken request shape.
        """
        replies, with_text = self.replies.get(stage, [0, 0])
        if replies >= after and with_text == 0:
            self.stop(f"pause: {replies} {stage} replies had no visible text "
                      f"(reasoning only?); fix the request shape before spending more")

    async def send_group(self, rows):
        """Send rows at once; None if the run has stopped or they could pass the cap."""
        if self.stopped:
            return None
        estimate = sum(r["est_tokens"] for r in rows)
        if self.summary["spent"] + self.reserved + estimate > self.cap:
            self.stop(f"cap: {estimate} more estimated tokens would pass the cap of {self.cap}")
            return None
        self.reserved += estimate
        records = await asyncio.gather(*(self.send(r) for r in rows))
        if self.stopped:
            return None
        return records

    async def models(self, r):
        sent_s = self.clock()
        record = await llm.list_models(self.client, self.api_key, base_url=self.base_url)
        self.summary["requests_sent"] += 1
        self.save(record, r, sent_s)
        if record["status"] != 200:
            self.stop(f"abort: models list returned status {record['status']}")
            return
        self.summary["models_missing"] = [m for m in self.p["models"] if m not in record["ids"]]
        if self.p["main_model"] in self.summary["models_missing"]:
            self.stop(f"abort: main model {self.p['main_model']} is not listed")

    async def one_at_a_time(self, rows, gap_s=0):
        for i, r in enumerate(rows):
            if i > 0 and gap_s:
                await asyncio.sleep(gap_s)
            if await self.send_group([r]) is None:
                return
            if r["stage"] == "spaced":
                self.check_visible_text("spaced", after=3)
                if self.stopped:
                    return
        if rows[0]["stage"] == "header_sample":
            self.check_visible_text("header_sample", after=1)

    async def burst(self, rows):
        """Waves of requests until the first 429; its time counts only if it names RPM."""
        wave = self.p["rpm_burst_wave"]
        for start in range(0, len(rows), wave):
            records = await self.send_group(rows[start:start + wave])
            if records is None:
                return
            hits = [rec for rec in records if rec["status"] == 429]
            if hits:
                first = min(hits, key=lambda rec: rec["received_s"])
                if first["limit_kind"] == "RPM":
                    self.last_429 = first["received_s"]
                else:
                    self.note(f"rpm_burst: first 429 named {first['limit_kind']}, not RPM; "
                              "its recovery is not measured")
                return
        self.note(f"rpm_burst: no 429 in {len(rows)} requests")

    async def recover(self, rows):
        """A tiny request every poll interval until the first 200 after the burst's 429."""
        if self.last_429 is None:
            self.note("recovery_rpm: skipped, the burst gave no 429 naming RPM")
            return
        first_429, self.last_429 = self.last_429, None
        for r in rows:
            await asyncio.sleep(self.p["recovery_poll_interval_s"])
            records = await self.send_group([r])
            if records is None:
                return
            if records[0]["status"] == 200:
                # From the 429's arrival to the moment the admitted request was sent.
                self.summary["recovery_rpm_s"] = round(records[0]["sent_s"] - first_429, 3)
                return
        self.note(f"recovery_rpm: still refused after {len(rows)} polls")

    async def ramp(self, rows):
        """1, 2, 4, 8 at once; the first level that gets a 429 is the last one sent."""
        for level in self.p["concurrency_levels"]:
            records = await self.send_group([r for r in rows if r["group"] == f"concurrency-{level}"])
            if records is None:
                return
            kinds = [rec["limit_kind"] for rec in records if rec["status"] == 429]
            if kinds:
                self.note(f"concurrency: 429 at {level} at once (limit named: {kinds[0]}); "
                          f"higher levels not sent")
                return

    async def run_stage(self, stage, rows):
        if stage == "models":
            await self.models(rows[0])
        elif stage == "spaced":
            await self.one_at_a_time(rows, gap_s=self.p["spaced_interval_s"])
        elif stage == "header_sample":
            await self.one_at_a_time(rows)
        elif stage == "rpm_burst":
            await self.burst(rows)
        elif stage == "recovery_rpm":
            await self.recover(rows)
        elif stage == "concurrency":
            await self.ramp(rows)


async def run_probe(plan, api_key, cap, out_dir, base_url=None, p=config.PROBE):
    """Run the plan stage by stage, saving every record; return the summary and run_dir."""
    base_url = base_url or config.BASE_URL
    run_dir = out_dir / f"run_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    run_dir.mkdir(parents=True, exist_ok=True)
    async with llm.make_client() as client:
        run = ProbeRun(client, api_key, cap, run_dir, base_url, p,
                       sum(r["est_tokens"] for r in plan))
        try:
            for stage in stages_of(plan):
                if run.stopped:
                    break
                missing = run.summary["models_missing"]
                rows = [r for r in plan if r["stage"] == stage and r["model"] not in missing]
                if not rows:
                    continue  # e.g. a candidate model that does not exist
                await asyncio.sleep(p["pause_before_s"].get(stage, 0))
                await run.run_stage(stage, rows)
                run.write_summary()
            run.stop("done")
        finally:
            run.stop("interrupted")  # only takes effect if the loop was cut short
            run.write_summary()
    return {**run.summary, "run_dir": str(run_dir)}


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
    print(llm.describe_target(args.base_url))
    llm.check_spend(total, args.confirm, args.max_tokens_total, allow_over_cap=True)
    api_key = llm.key_for(args.base_url)
    if not api_key:
        print("No key in .env; paste it after GROQ_API_KEY= then rerun")
        raise SystemExit(2)
    summary = asyncio.run(run_probe(plan, api_key, args.max_tokens_total, Path(args.out),
                                    base_url=args.base_url))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
