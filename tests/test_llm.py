"""Client tests against the local fake server (tests/fake_groq.py). No real Groq call.

The numbers the fake returns are fixtures, not measurements.
"""

import asyncio
import json

import pytest

from relay import llm
from tests.fake_groq import fake_groq  # noqa: F401  (pytest fixture)

KEY = "test-key-123"
MESSAGES = [{"role": "user", "content": "Say hello."}]


def chat(fake, **kwargs):
    async def run():
        async with llm.make_client() as client:
            return await llm.stream_chat(client, "fake-model", MESSAGES, 16, KEY,
                                         base_url=fake.base_url, **kwargs)
    return asyncio.run(run())


def test_stream_parses(fake_groq):
    r = chat(fake_groq)
    assert r["status"] == 200
    assert r["content"] == fake_groq.reply_text
    assert 0 < r["ttft_ms"] <= r["total_ms"]
    assert r["usage"]["total_tokens"] == 25
    assert "queue_time" in r["x_groq"]["usage"]
    assert r["headers"]["x-ratelimit-limit-tokens"] == "6000"
    assert r["headers"]["x-ratelimit-reset-requests"] == "1m26.4s"


def test_trace_line(fake_groq, tmp_path):
    path = tmp_path / "traces" / "t.jsonl"
    chat(fake_groq, tag="test", trace_path=path)
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    for key in ("ttft_ms", "total_ms", "usage", "headers"):
        assert record[key]
    leaked = KEY in lines[0] or "authorization" in lines[0].lower()
    assert not leaked


def test_429_recorded(fake_groq):
    fake_groq.limit_per_window = 1
    assert chat(fake_groq)["status"] == 200
    r = chat(fake_groq)
    assert r["status"] == 429
    assert "retry-after" in r["headers"]
    assert "rate_limit_exceeded" in r["error_body"]
    assert r["ttft_ms"] is None


def test_reasoning_detected(fake_groq):
    fake_groq.reasoning_text = "thinking about the answer"
    fake_groq.delay_s = 0.02
    r = chat(fake_groq)
    assert r["first_reasoning_ms"] is not None and r["first_reasoning_ms"] < r["ttft_ms"]
    assert "reasoning" in r["delta_keys"]


def test_list_models(fake_groq):
    async def run():
        async with llm.make_client() as client:
            return await llm.list_models(client, KEY, base_url=fake_groq.base_url)
    assert asyncio.run(run())["ids"] == ["fake-model"]


def test_load_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    p = tmp_path / "with_key.env"
    p.write_text("OTHER=1\nGROQ_API_KEY=test-key-123\n")
    matched = llm.load_api_key(env_path=p) == KEY  # compared as a bool, never shown
    assert matched
    p2 = tmp_path / "empty.env"
    p2.write_text("GROQ_API_KEY=\n")
    empty = llm.load_api_key(env_path=p2) == ""
    assert empty
    # The autouse fixture points config.ENV_PATH at a missing file: the real .env is never read.
    no_default = llm.load_api_key() == ""
    assert no_default


def test_redact():
    fake_key = "gsk_" + "B" * 20
    out = llm.redact(f"bad key {fake_key} here")
    assert fake_key not in out and "gsk_[REDACTED]" in out


def test_check_spend(capsys):
    for args in [(100, False, 1000), (100, True, None), (2000, True, 1000)]:
        with pytest.raises(SystemExit) as exc:
            llm.check_spend(*args)
        assert exc.value.code == 2
    capsys.readouterr()
    llm.check_spend(2000, True, 1000, allow_over_cap=True)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Estimated spend: 2000 tokens" and lines[1].startswith("Warning:")
    llm.check_spend(100, True, 1000)
    assert capsys.readouterr().out.startswith("Estimated spend:")


def test_base_url_switch(fake_groq):
    r = chat(fake_groq)
    assert r["url"].startswith(fake_groq.base_url)
    assert len(fake_groq.requests) == 1 and fake_groq.requests[0]["stream"] is True


def test_real_key_only_for_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", KEY)  # a fixture value standing in for the real key
    for url in ("http://127.0.0.1:8000/openai/v1", "http://api.groq.com/openai/v1",
                "https://api.groq.com.evil.example/openai/v1", "https://stand-in.local/v1"):
        assert llm.key_for(url) == llm.STAND_IN_KEY
        assert "NOT Groq" in llm.describe_target(url)
    sent_real = llm.key_for("https://api.groq.com/openai/v1") == KEY  # compared, never shown
    assert sent_real


def test_cookies_and_org_not_saved(fake_groq):
    r = chat(fake_groq)
    assert "set-cookie" not in r["headers"] and "x-ratelimit-limit-tokens" in r["headers"]
    fake_groq.limit_per_window = 0
    r = chat(fake_groq)
    assert "retry-after" in r["headers"]
    assert "org_fake" not in r["error_body"] and "org_[REDACTED]" in r["error_body"]


def test_stream_error_event_and_done_without_space(fake_groq):
    fake_groq.stream_error = {"message": "fixture mid-stream failure", "type": "server_error"}
    fake_groq.done_line = b"data:[DONE]\n\n"
    r = chat(fake_groq)
    assert r["status"] == 200 and r["exception"] is None
    assert "fixture mid-stream failure" in r["error_body"]
