"""The stand-in model service: Groq's chat-completions API, run in-process and controlled here.

It answers the same streamed requests as Groq (POST .../chat/completions), with Groq's
x-ratelimit-* headers and a Groq-shaped 429 with retry-after, so the client and gateway
run unchanged; only the httpx transport differs (llm.make_client(transport=...)).

Where each behaviour comes from:
- Time to the first streamed event is resampled from real requests of a similar prompt
  size: the probe's 50 spaced tiny requests, or the 54 real evaluation replies (12 Nov).
- Time per output token is resampled from Groq's own usage.completion_time figures.
- Replies are real: the stand-in replays a reply Groq actually gave to the same question
  under the same retrieval setting (evaluation traces), so length, formatting, citation
  style and refusals vary as they really do. Reasoning tokens and Groq's prompt-token count
  follow the medians of the real replies.
- Limits refill continuously (clock.Bucket), as Groq's headers showed; they are settings,
  so a scenario can halve the per-minute limit or shrink the daily budget mid-run.
- ASSUMED: slowdown when more than 8 requests are in flight (none was measured up to 8).
- INJECTED (off by default): slow successes, 503 failures, mid-stream stalls.
Where it is least like Groq: one tenant only (no other customers' load), no network,
and token counting by our own estimate, not Groq's tokenizer.
"""

import json
import math
import random
import re

import httpx

import config
from relay import clock, llm

PERIOD_S = {"rpm": 60, "tpm": 60, "rpd": 86400, "tpd": 86400}
NAME = {"rpm": "requests per minute (RPM)", "tpm": "tokens per minute (TPM)",
        "rpd": "requests per day (RPD)", "tpd": "tokens per day (TPD)"}


def probe_samples(run_dir):
    """(first-event ms, ms per output token) from the real probe.

    First-event times come from the 50 spaced requests only: they are the unloaded
    latency. Burst and concurrency replies already carry the effect of our own load,
    which the stand-in models separately (slowdown_per_extra, ASSUMED).
    """
    first, per_token = [], []
    for line in (run_dir / "requests.jsonl").read_text().splitlines():
        r = json.loads(line)
        events = [t for t in (r.get("first_reasoning_ms"), r.get("ttft_ms")) if t]
        if r.get("status") == 200 and r.get("stage") == "spaced" and events:
            first.append(min(events))
        usage = r.get("usage") or {}
        if usage.get("completion_tokens") and usage.get("completion_time"):
            per_token.append(1000 * usage["completion_time"] / usage["completion_tokens"])
    return first, per_token


def eval_samples(trace_path):
    """First-event ms of the real evaluation replies (large prompts), [] if none yet."""
    if not trace_path.exists():
        return []
    first = []
    for line in trace_path.read_text().splitlines():
        t = json.loads(line)
        record = t.get("model_record") or {}
        events = [x for x in (record.get("first_reasoning_ms"), record.get("ttft_ms")) if x]
        if t.get("scenario", "").startswith("eval-") and record.get("status") == 200 and events:
            first.append(min(events))
    return first


def recorded_replies(trace_path, setting):
    """question -> the real reply texts Groq gave under this retrieval setting."""
    out = {}
    if trace_path.exists():
        for line in trace_path.read_text().splitlines():
            t = json.loads(line)
            content = (t.get("model_record") or {}).get("content")
            if t.get("scenario", "").startswith("eval-") and t.get("setting") == setting and content:
                out.setdefault(t["question"], []).append(content)
    return out


class StandIn:
    def __init__(self, **settings):
        self.s = {**config.STANDIN, **settings}
        self.rng = random.Random(self.s["seed"])
        self.first_ms, self.token_ms = probe_samples(config.STANDIN_PROBE_RUN)
        self.first_ms_large = eval_samples(self.s["eval_traces"]) or self.first_ms
        self.recorded = recorded_replies(self.s["eval_traces"], config.LOAD_SETTING)
        self.limits = {k: clock.Bucket(v, PERIOD_S[k]) for k, v in self.s["limits"].items()}
        self.inflight = 0

    def transport(self):
        return httpx.MockTransport(self.handle)

    def headers(self):
        rpd, tpm = self.limits["rpd"], self.limits["tpm"]
        return {"x-ratelimit-limit-requests": str(int(rpd.capacity)),
                "x-ratelimit-remaining-requests": str(max(0, int(rpd.level))),
                "x-ratelimit-reset-requests": f"{rpd.wait_for(rpd.capacity):.2f}s",
                "x-ratelimit-limit-tokens": str(int(tpm.capacity)),
                "x-ratelimit-remaining-tokens": str(max(0, int(tpm.level))),
                "x-ratelimit-reset-tokens": f"{tpm.wait_for(tpm.capacity):.2f}s"}

    async def handle(self, request):
        body = json.loads(request.content)
        if self.rng.random() < self.s["fail_rate"]:  # INJECTED
            return httpx.Response(503, json={"error": {"message": "stand-in: injected 503",
                                                       "type": "service_unavailable"}})
        text = " ".join(m["content"] for m in body["messages"])
        prompt = int(llm.estimate_tokens(text) * self.s["prompt_token_ratio"])
        need = {"rpm": 1, "rpd": 1, "tpm": prompt, "tpd": prompt}
        for kind, amount in need.items():
            wait = self.limits[kind].wait_for(amount)
            if wait > 0:
                limit = int(self.limits[kind].capacity)
                message = (f"Rate limit reached for model `{body['model']}` in organization "
                           f"`org_standin` service tier `on_demand` on {NAME[kind]}: Limit "
                           f"{limit}, Requested {amount}. Please try again in {wait:.0f}s.")
                return httpx.Response(429, headers={"retry-after": str(max(1, math.ceil(wait)))},
                                      json={"error": {"message": message, "type": kind,
                                                      "code": "rate_limit_exceeded"}})
        for kind, amount in need.items():
            self.limits[kind].take(amount)
        return httpx.Response(200, headers=self.headers(), content=self.stream(body, prompt))

    def reply_text(self, body):
        """A real reply Groq gave to this question (recorded in the evaluation traces), so
        replies vary as real ones do; a synthetic cited sentence only if none was recorded."""
        user = body["messages"][-1]["content"]
        question = user.rsplit("Question:", 1)[-1].strip()
        if self.recorded.get(question):
            return self.rng.choice(self.recorded[question])
        match = re.search(rf"\[({config.CITATION_ID})\]", user)
        if not match:
            return config.REFUSAL_TEXT
        sentence = f"The cited piece describes this part of the paper [{match.group(1)}]. "
        return sentence * max(1, int(self.s["answer_tokens"] / (len(sentence.split()) * 1.33)))

    async def stream(self, body, prompt):
        self.inflight += 1
        try:
            large = prompt >= self.s["large_prompt_tokens"]
            first = self.rng.choice(self.first_ms_large if large else self.first_ms)
            extra = max(0, self.inflight - self.s["slowdown_above_inflight"])
            first *= 1 + self.s["slowdown_per_extra"] * extra  # ASSUMED
            if self.rng.random() < self.s["straggler_rate"]:  # INJECTED
                first *= self.s["straggler_factor"]
            await clock.sleep(first / 1000)

            def chunk(delta, extra=None):
                payload = {"choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                           "model": body["model"], **(extra or {})}
                return f"data: {json.dumps(payload)}\n\n".encode()

            yield chunk({"role": "assistant", "content": ""})
            tokens = self.s["reasoning_tokens"]
            for _ in range(tokens // 8):
                await clock.sleep(8 * self.rng.choice(self.token_ms) / 1000)
                yield chunk({"reasoning": "thinking " * 8})
            text = self.reply_text(body)
            pieces = [text[i:i + 24] for i in range(0, len(text), 24)]  # ~6 tokens each
            for i, part in enumerate(pieces):
                if i and self.rng.random() < self.s["stall_rate"] / len(pieces):
                    await clock.sleep(self.s["stall_s"])  # INJECTED stall mid-stream
                await clock.sleep(6 * self.rng.choice(self.token_ms) / 1000)
                yield chunk({"content": part})
            out = tokens + len(text) // 4  # ~4 characters per token
            self.limits["tpm"].take(out)
            self.limits["tpd"].take(out)
            usage = {"prompt_tokens": prompt, "completion_tokens": out,
                     "total_tokens": prompt + out,
                     "completion_tokens_details": {"reasoning_tokens": tokens}}
            yield chunk({}, {"x_groq": {"id": "standin", "usage": usage}})
            yield b"data: [DONE]\n\n"
        finally:
            self.inflight -= 1

    def set_limit(self, kind, value):
        """Change a limit mid-run (e.g. halve the per-minute tokens)."""
        self.limits[kind].resize(value)
