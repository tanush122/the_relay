"""Gateway, stand-in and load tests: budget, deadline, ladder, retries, cache, day-gone.

Everything runs against the in-process stand-in in compressed time; no Groq call is made.
Retrieval is stubbed with the fixture pieces from test_pipeline (no models are loaded).
"""

import asyncio

import pytest

import config
from relay import clock, gateway, llm, pipeline, standin
from tests.test_pipeline import PIECES, stub_meaning, stub_retrieval  # noqa: F401

BASE = "https://standin.local/openai/v1"


@pytest.fixture(autouse=True)
def meaning_stubbed(stub_meaning):
    """These tests are about the gateway, files and commands, not meaning (see test_check)."""


@pytest.fixture(autouse=True)
def fast_time(monkeypatch):
    monkeypatch.setattr(config, "TIME_SCALE", 0.01)  # 100x: a minute passes in 0.6 s
    clock.reset()
    yield
    clock.reset()


def ask(gate, service, question="What is d_ff?"):
    async def go():
        async with llm.make_client(transport=service.transport()) as client:
            return await pipeline.answer(question, {"setting": "C"}, client, llm.STAND_IN_KEY,
                                         base_url=BASE, gateway=gate)
    return asyncio.run(go())


def test_bucket_refills_continuously():
    b = clock.Bucket(60, 60)  # 1 per second
    b.take(60)
    assert b.wait_for(2) == pytest.approx(2, abs=0.2)
    b.correct(-5)  # the provider says we are further behind
    assert b.wait_for(0) == pytest.approx(5, abs=0.2)


def test_answer_through_gateway_and_standin(stub_retrieval):
    gate, service = gateway.Gateway(), standin.StandIn()
    result = ask(gate, service)
    assert result["outcome"] == "answered" and result["status"] == "ok"
    assert "[attention-C-001]" in result["reply"] and result["tokens_out"] > 0
    assert [s["name"] for s in result["spans"]] == ["retrieve", "queue", "model"]
    assert gate.tpm.level < gate.tpm.capacity  # the call was paid for


def test_cache_answers_a_repeat_without_a_model_call(stub_retrieval):
    gate, service = gateway.Gateway(cache_on=True), standin.StandIn()
    ask(gate, service)
    again = ask(gate, service, "  what is D_FF?  ")
    assert again["outcome"] == "cached" and again["tokens_in"] == 0


def test_refused_at_once_when_the_wait_would_pass_the_deadline(stub_retrieval):
    gate = gateway.Gateway(limits={**config.LIMITS, "tpm": 600})  # 540 a minute after safety
    gate.tpm.take(gate.tpm.capacity)  # the minute is spent
    result = ask(gate, standin.StandIn(), "What is d_ff?")
    # This ~500-token call needs ~55 s of refill: past the 15 s give-up, so refused at once.
    assert result["outcome"] == "refused_gateway" and result["status"] == "rate_limited"
    assert "ask again in about" in result["reply"] and result["tokens_in"] == 0


def test_ladder_levels():
    gate = gateway.Gateway()
    assert gate.level() == "normal"
    gate.tpm.take(gate.tpm.capacity - 1000)  # under 1.5 answers of ~3,000 left this minute
    assert gate.level() == "lean"
    gate.tpd.take(gate.tpd.capacity)  # the day is spent
    assert gate.level() == "day_gone"


def test_day_gone_shows_passages_without_a_model_call(stub_retrieval):
    gate, service = gateway.Gateway(), standin.StandIn()
    gate.rpd.take(gate.rpd.capacity)
    result = ask(gate, service)
    assert result["outcome"] == "day_gone_passages" and result["status"] == "rate_limited"
    assert "model budget is used up" in result["reply"] and "Attention v7, §3.3" in result["reply"]
    assert result["first_token_ms"] is None and result["model"] is None


def test_lean_level_uses_fewer_pieces_and_a_shorter_answer(stub_retrieval):
    gate, service = gateway.Gateway(), standin.StandIn()
    gate.tpm.take(gate.tpm.capacity - 1000)
    result = ask(gate, service)
    assert result["level"] == "lean"
    assert len(result["pieces"]) <= config.LEVELS["lean"]["max_pieces"]


def test_429_is_retried_after_retry_after(stub_retrieval):
    service = standin.StandIn(limits={**config.LIMITS, "rpm": 10})
    gate = gateway.Gateway()  # the gateway believes 30 a minute: the stand-in will refuse
    first = ask(gate, service)
    service.limits["rpm"].take(service.limits["rpm"].level)  # spend the stand-in's minute
    second = ask(gate, service, "What is d_ff, again?")
    assert first["outcome"] == "answered"
    assert second["retries"] >= 1 and second["outcome"] == "answered"
    assert any(s["name"] == "backoff" for s in second["spans"])


def test_retry_budget_and_never_past_the_deadline():
    gate = gateway.Gateway()
    record = {"status": 503, "headers": {}, "exception": None}
    far = clock.now() + 60
    assert gate.retry_wait(record, 0, far, shown=False) is not None
    assert gate.retry_wait(record, 0, far, shown=True) is None  # text was shown
    assert gate.retry_wait(record, config.RETRY_MAX, far, shown=False) is None
    assert gate.retry_wait({**record, "status": 400}, 0, far, shown=False) is None
    assert gate.retry_wait(record, 0, clock.now() + 0.1, shown=False) is None  # no time left
    gate.calls.extend([True] * 10 + [False] * 10)  # 50% of recent calls were retries
    assert gate.retry_wait(record, 0, far, shown=False) is None
    assert gateway.Gateway(retry_budget=None).retry_wait(record, 1, far, shown=False) is not None


def test_injected_failures_are_retried_and_counted(stub_retrieval):
    service = standin.StandIn(fail_rate=1.0)  # every call fails: INJECTED
    result = ask(gateway.Gateway(retry_budget=None), service)
    assert result["status"] == "error" and result["retries"] == config.RETRY_MAX


def test_first_token_timeout(stub_retrieval, monkeypatch):
    monkeypatch.setattr(config, "FIRST_TOKEN_TIMEOUT_S", 0.05)
    result = ask(gateway.Gateway(retry_budget=None), standin.StandIn())
    assert result["status"] == "timeout" and "FirstTokenTimeout" in result["model_record"]["exception"]


def test_retrieve_tool_timeout_is_retried_once_then_refused(stub_retrieval, monkeypatch):
    calls, _ = stub_retrieval
    monkeypatch.setattr(config, "INJECT_RETRIEVE_DELAY_S", 5.0)  # INJECTED slow tool
    result = ask(gateway.Gateway(), standin.StandIn())
    assert result["outcome"] == "refused_tool" and result["status"] == "timeout"
    assert "library search is not responding" in result["reply"] and calls == []


def test_standin_429_names_the_limit_like_groq():
    service = standin.StandIn(limits={**config.LIMITS, "rpm": 1})

    async def two():
        async with llm.make_client(transport=service.transport()) as client:
            messages = [{"role": "user", "content": "hi"}]
            await llm.stream_chat(client, "m", messages, 16, "k", base_url=BASE)
            return await llm.stream_chat(client, "m", messages, 16, "k", base_url=BASE)
    second = asyncio.run(two())
    assert second["status"] == 429 and int(second["headers"]["retry-after"]) >= 1
    assert llm.limit_kind(second["error_body"]) == "RPM"


def test_standin_samples_come_from_the_probe():
    first, per_token = standin.probe_samples(config.STANDIN_PROBE_RUN)
    assert len(first) == 50 and 300 < sorted(first)[25] < 700  # the spaced requests
    assert per_token and all(t > 0 for t in per_token)
