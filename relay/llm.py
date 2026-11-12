"""The one model client: async, streaming, OpenAI-compatible, and it records everything.

Why streaming: time to the first content token (TTFT) is what a person waiting feels,
and only a streamed reply shows it. Why every response header is kept verbatim: Table 1
(Groq's real limits) and the phase-3 gateway are built from the x-ratelimit-* and
retry-after headers, so nothing is filtered out except cookies (session tokens), and
the Groq organization id is redacted from error bodies. Why one base URL: config.BASE_URL
(or RELAY_BASE_URL) is the only switch, so the phase-3 stand-in replaces Groq unchanged.
The key is read from the environment or .env, sent only as a request header, and request
headers are never recorded, so it cannot reach a trace, the screen or an exception text.
The real key is only ever sent to https://api.groq.com (key_for): any other base URL gets
a dummy key, so a typo, the test fake or the phase-3 stand-in never receives it.
"""

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

import config
from relay import clock

KEY_PATTERN = re.compile(r"gsk_[A-Za-z0-9]+")
ORG_PATTERN = re.compile(r"org_[A-Za-z0-9]+")  # Groq account id seen in 429 bodies
# Cookies are session tokens, not limits; they are dropped before a record is saved.
COOKIE_HEADERS = {"set-cookie", "set-cookie2", "cookie"}
# A Groq 429 body names the limit it hit, e.g. "requests per minute (RPM): Limit 30".
LIMIT_IN_BODY = re.compile(r"\((RPM|TPM|RPD|TPD)\): Limit (\d+)")
GROQ_HOST = "api.groq.com"
STAND_IN_KEY = "stand-in-no-real-key"  # what every non-Groq host receives instead of the key


def load_api_key(env_path=None):
    """GROQ_API_KEY from the environment, else from .env; "" if absent. Never printed."""
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    path = env_path or config.ENV_PATH  # resolved now, so tests can redirect config.ENV_PATH
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        if line.startswith("GROQ_API_KEY="):
            return line[len("GROQ_API_KEY="):].strip()
    return ""


def is_real_groq(base_url):
    """True only for https://api.groq.com (plain http would send the key in cleartext)."""
    parts = urlparse(base_url)
    return parts.scheme == "https" and parts.hostname == GROQ_HOST


def key_for(base_url):
    """The real key for Groq; a dummy key for every other host, so it cannot leak there."""
    if is_real_groq(base_url):
        return load_api_key()
    return STAND_IN_KEY


def describe_target(base_url):
    """One line naming where requests go and which key they carry, printed before real runs."""
    host = urlparse(base_url).hostname
    if is_real_groq(base_url):
        return f"Target: {host} (real Groq key)"
    return f"Target: {host} (NOT Groq: dummy key sent, real key never loaded)"


def redact(text):
    """Hide key-like strings and the Groq organization id before text is saved or shown."""
    return ORG_PATTERN.sub("org_[REDACTED]", KEY_PATTERN.sub("gsk_[REDACTED]", text))


def limit_kind(error_body):
    """Return "RPM", "TPM", "RPD" or "TPD" when an error body names its limit, else None."""
    match = LIMIT_IN_BODY.search(error_body or "")
    return match.group(1) if match else None


def saved_headers(headers):
    """Response headers to keep: all of them (x-ratelimit-*, retry-after, ...) minus cookies."""
    return {name: value for name, value in headers.items() if name.lower() not in COOKIE_HEADERS}


def estimate_tokens(text):
    """Upper-bound guess of one request's prompt tokens (see config); real counts come from usage."""
    by_words = len(text.split()) * config.TOKENS_PER_WORD
    by_chars = len(text) / config.CHARS_PER_TOKEN
    return int(max(by_words, by_chars)) + config.REQUEST_OVERHEAD_TOKENS


def check_spend(estimate, confirm, cap, allow_over_cap=False):
    """Print the estimated spend first, then refuse (exit 2) unless the run is confirmed and capped."""
    print(f"Estimated spend: {estimate} tokens")
    if not confirm:
        print("Refusing real call: pass --confirm after reviewing the estimate")
        raise SystemExit(2)
    if cap is None:
        print("Refusing: pass --max-tokens-total N")
        raise SystemExit(2)
    if cap <= 0:
        print("Refusing: --max-tokens-total must be a positive number of tokens")
        raise SystemExit(2)
    if estimate > cap:
        if not allow_over_cap:
            print("Refusing: estimate exceeds cap")
            raise SystemExit(2)
        print(f"Warning: upper-bound estimate exceeds cap; the run will stop before "
              f"spending more than {cap}")


def make_client(transport=None):
    """An httpx client; `transport` plugs in the in-process stand-in (relay/standin.py)."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(config.READ_TIMEOUT_S, connect=config.CONNECT_TIMEOUT_S),
        transport=transport)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _ms(start):
    return clock.ms_since(start)


async def list_models(client, api_key, base_url=None):
    """GET /models (spends no tokens): which model ids exist, plus the headers."""
    url = f"{base_url or config.BASE_URL}/models"
    record = {"url": url, "sent_at": _now(), "status": None, "headers": {}, "ids": [],
              "error_body": None, "exception": None}
    start = clock.now()
    try:
        response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        record["status"] = response.status_code
        record["headers"] = saved_headers(response.headers)
        if response.status_code == 200:
            record["ids"] = [m["id"] for m in response.json().get("data", [])]
        else:
            record["error_body"] = redact(response.text)
    except Exception as exc:  # network error or timeout: record it, do not crash
        record["exception"] = redact(f"{type(exc).__name__}: {exc}")
    record["total_ms"] = _ms(start)
    return record


class FirstTokenTimeout(Exception):
    """No reasoning or content arrived within the first-token timeout."""


class StallTimeout(Exception):
    """The stream went quiet between chunks for longer than the stall timeout."""


async def _lines(response, record, timeouts):
    """The stream's lines, enforcing (first_token_s, stall_s) in model time when given."""
    lines = response.aiter_lines()
    while True:
        waiting_first = record["first_reasoning_ms"] is None and record["ttft_ms"] is None
        limit = timeouts[0 if waiting_first else 1] if timeouts else None
        try:
            yield await asyncio.wait_for(anext(lines), limit and limit * config.TIME_SCALE)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            raise (FirstTokenTimeout if waiting_first else StallTimeout)(f"after {limit} s") from None


async def stream_chat(client, model, messages, max_tokens, api_key, base_url=None,
                      extra=None, on_content=None, tag=None, trace_path=None, timeouts=None):
    """One streamed chat completion; returns (and optionally traces) everything observed.

    TTFT definition: from just before the request is handed to httpx until the first
    content delta. It therefore includes DNS, TCP and TLS setup whenever httpx has to open
    a new connection; record["new_connection"] says when that happened, so the latency
    spread can be split into "fresh connection" and "reused connection" requests.
    """
    url = f"{base_url or config.BASE_URL}/chat/completions"
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": True,
            **config.MODEL_PARAMS.get(model, {}), **(extra or {})}
    record = {"request_id": uuid.uuid4().hex, "tag": tag, "model": model, "url": url,
              "sent_at": _now(), "status": None, "headers": {}, "ttft_ms": None,
              "first_reasoning_ms": None, "total_ms": None, "content": "",
              "reasoning_chars": 0, "delta_keys": [], "usage": None, "x_groq": None,
              "final_chunk": None, "error_body": None, "exception": None,
              "new_connection": False}
    content, keys = [], set()

    async def note_connect(event, info):  # httpx/httpcore trace hook
        if event == "connection.connect_tcp.started":
            record["new_connection"] = True

    start = clock.now()
    try:
        async with client.stream("POST", url, json=body,
                                 headers={"Authorization": f"Bearer {api_key}"},
                                 extensions={"trace": note_connect}) as response:
            record["status"] = response.status_code
            # httpx lowercases header names and joins repeated headers with ", ";
            # fine for Groq's single-valued x-ratelimit-* and retry-after headers.
            record["headers"] = saved_headers(response.headers)
            if response.status_code != 200:
                record["error_body"] = redact((await response.aread()).decode(errors="replace"))
            else:
                async for line in _lines(response, record, timeouts):
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()  # "data:[DONE]" is valid SSE too
                    if payload == "[DONE]":
                        continue
                    chunk = json.loads(payload)
                    record["final_chunk"] = chunk
                    if chunk.get("error"):  # an error event inside a 200 stream
                        record["error_body"] = redact(json.dumps(chunk))
                    if chunk.get("x_groq"):
                        record["x_groq"] = chunk["x_groq"]
                    usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                    if usage:
                        record["usage"] = usage
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        keys.update(delta)
                        if delta.get("reasoning"):
                            record["reasoning_chars"] += len(delta["reasoning"])
                            if record["first_reasoning_ms"] is None:
                                record["first_reasoning_ms"] = _ms(start)
                        if delta.get("content"):
                            if record["ttft_ms"] is None:
                                record["ttft_ms"] = _ms(start)
                            content.append(delta["content"])
                            if on_content:
                                on_content(delta["content"])
    except Exception as exc:  # timeout, dropped connection or malformed line: keep the record
        record["exception"] = redact(f"{type(exc).__name__}: {exc}")
    record["total_ms"] = _ms(start)
    record["content"] = "".join(content)
    record["delta_keys"] = sorted(keys)
    if trace_path:
        write_trace(record, trace_path)
    return record


def write_trace(record, path):
    """Append one JSON line. Request headers are never in the record, so no Authorization."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
