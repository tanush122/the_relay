"""Probe tests: plan and budget, dry run, refusals, and real-mode runs against the fake server.

Everything returned by the fake server is fixture data, not a measurement.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

import config
import probe
from tests.fake_groq import fake_groq  # noqa: F401  (pytest fixture)

LEAN = ["models", "header_sample", "spaced", "rpm_burst", "recovery_rpm", "concurrency"]

# Small, fast probe for the fake server: every key from config.PROBE, only these differ.
SMALL = {**config.PROBE, "models": ["fake-model", "missing-model"], "main_model": "fake-model",
         "spaced_requests": 3, "spaced_interval_s": 0, "rpm_burst_requests": 6,
         "rpm_burst_wave": 2, "recovery_poll_interval_s": 0.2,
         "recovery_max_polls": 20, "concurrency_levels": [1, 2], "pause_before_s": {}}


def run_small(fake, tmp_path, cap, p=SMALL):
    """Run the small probe against the fake; return (summary, records)."""
    fake.limit_per_window, fake.window_s = 4, 1.0
    fake.reset_window()
    summary = asyncio.run(probe.run_probe(probe.plan_requests(p), "test-key-123", cap,
                                          tmp_path, base_url=fake.base_url, p=p))
    log = Path(summary["run_dir"]) / "requests.jsonl"
    return summary, [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture
def no_network(monkeypatch):
    async def refuse(*args, **kwargs):
        raise AssertionError("tried to send a request")
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)


def test_plan_is_the_lean_probe():
    lean = [r["stage"] for r in probe.plan_requests()]
    assert probe.stages_of(probe.plan_requests()) == LEAN
    assert lean.count("spaced") == 50
    plan = probe.plan_requests()
    sizes = [sum(r["group"] == f"concurrency-{n}" for r in plan) for n in (1, 2, 4, 8)]
    assert sizes == [1, 2, 4, 8]
    assert sum(r["est_tokens"] for r in plan) <= config.PROBE["default_cap"]


def test_dry_run_no_network(no_network, capsys):
    probe.main(["--dry-run"])
    out = capsys.readouterr().out.splitlines()
    assert out[-1].startswith("ESTIMATED TOTAL:")
    planned = [line for line in out if line.strip()[:1].isdigit()]
    assert len(planned) == len(probe.plan_requests())


def test_refusals(no_network):
    for argv in ([], ["--confirm"], ["--max-tokens-total", "1000"],
                 ["--confirm", "--max-tokens-total", "0"]):
        with pytest.raises(SystemExit) as exc:
            probe.main(argv)
        assert exc.value.code == 2


def test_real_mode_against_fake(fake_groq, tmp_path):
    summary, records = run_small(fake_groq, tmp_path, cap=100000)
    stages = {r["stage"] for r in records}
    for stage in ["models", "header_sample", "spaced", "rpm_burst", "recovery_rpm",
                  "concurrency"]:
        assert stage in stages
    assert summary["stopped_reason"] in ("done", "abort: unexpected 429 during spaced")
    assert any(r["status"] == 429 and "retry-after" in r["headers"] for r in records)
    assert isinstance(summary["recovery_rpm_s"], float)
    assert "missing-model" in summary["models_missing"]
    for r in records:
        assert "model" in r and "sent_s" in r and "limit_kind" in r
        if r["status"] == 200 and r["stage"] != "models":
            assert r["ttft_ms"] and r["total_ms"] and r["usage"]
            assert "x-ratelimit-limit-tokens" in r["headers"]
    raw = (Path(summary["run_dir"]) / "requests.jsonl").read_text()
    assert "test-key" not in raw
    saved = json.loads((Path(summary["run_dir"]) / "run.json").read_text())
    assert saved["stopped_reason"] == summary["stopped_reason"]


def test_burst_and_ramp_stop_early(fake_groq, tmp_path):
    fake_groq.limit_per_window, fake_groq.window_s = 4, 600  # no recovery inside the test
    fake_groq.reset_window()
    p = {**SMALL, "recovery_poll_interval_s": 0.01, "recovery_max_polls": 3}
    summary = asyncio.run(probe.run_probe(probe.plan_requests(p), "k", 100000,
                                          tmp_path, base_url=fake_groq.base_url, p=p))
    records = [json.loads(line) for line in
               (Path(summary["run_dir"]) / "requests.jsonl").read_text().splitlines()]
    by_stage = {s: [r for r in records if r["stage"] == s] for s in LEAN}
    assert len(by_stage["rpm_burst"]) == 2  # one wave: it already held the first 429
    assert by_stage["rpm_burst"][-1]["limit_kind"] == "RPM"
    assert len(by_stage["recovery_rpm"]) == 3 and summary["recovery_rpm_s"] is None
    assert len(by_stage["concurrency"]) == 1  # level 1 got a 429, so level 2 was not sent
    assert summary["stopped_reason"] == "done"


def test_cap_bounds_actual_spend(fake_groq, tmp_path):
    for cap in (60, 300, 400):
        summary, records = run_small(fake_groq, tmp_path / str(cap), cap=cap)
        assert summary["stopped_reason"].startswith("cap")
        assert summary["spent"] <= cap and summary["reserved_unsettled"] == 0
        assert summary["requests_sent"] < len(probe.plan_requests(SMALL))


def test_abort_on_unexpected_status(fake_groq, tmp_path):
    fake_groq.force_status = 403
    summary, records = run_small(fake_groq, tmp_path, cap=100000)
    assert summary["stopped_reason"] == "abort: unexpected status 403 during header_sample"
    assert [r["stage"] for r in records] == ["models", "header_sample"]  # nothing retried
    assert json.loads((Path(summary["run_dir"]) / "run.json").read_text())["stopped_reason"] \
        == summary["stopped_reason"]


def test_abort_on_limits_far_below_documented(fake_groq, tmp_path, monkeypatch):
    # The fake reports 6000 tokens/minute; pretend the docs promised 20000.
    monkeypatch.setitem(config.DOCUMENTED_LIMITS, "fake-model",
                        {"requests_per_day": 1000, "tokens_per_minute": 20000})
    summary, records = run_small(fake_groq, tmp_path, cap=100000)
    assert summary["stopped_reason"].startswith("abort: fake-model x-ratelimit-limit-tokens=6000")
    assert len(records) == 2


def test_interrupted_run_still_writes_summary(fake_groq, tmp_path, monkeypatch):
    async def boom(self, rows):
        raise RuntimeError("fixture interruption")
    monkeypatch.setattr(probe.ProbeRun, "burst", boom)
    with pytest.raises(RuntimeError):
        run_small(fake_groq, tmp_path, cap=100000)
    run_dir = next(tmp_path.glob("run_*"))
    saved = json.loads((run_dir / "run.json").read_text())
    assert saved["stopped_reason"] == "interrupted" and saved["requests_sent"] > 0


def test_pause_when_replies_have_reasoning_but_no_text(fake_groq, tmp_path):
    fake_groq.reply_text, fake_groq.reasoning_text = "", "thinking about it"
    summary, records = run_small(fake_groq, tmp_path, cap=100000)
    assert summary["stopped_reason"].startswith("pause: 1 header_sample replies had no visible")
    assert "spaced" not in [r["stage"] for r in records]
