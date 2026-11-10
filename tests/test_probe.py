"""Probe tests: plan and budget, dry run, refusals, and a real-mode run against the fake server.

Everything returned by the fake server is fixture data, not a measurement.
"""

import asyncio
import json

import httpx
import pytest

import config
import probe
from tests.fake_groq import fake_groq  # noqa: F401  (pytest fixture)

STAGES = ["models", "header_sample", "spaced", "rpm_burst", "recovery_rpm", "tpm_burst",
          "recovery_tpm", "concurrency", "max_tokens_pair"]

# Small probe for the fake server: every key from config.PROBE, only these differ.
SMALL = {**config.PROBE, "models": ["fake-model", "missing-model"], "main_model": "fake-model",
         "spaced_requests": 3, "spaced_interval_s": 0, "rpm_burst_requests": 6,
         "tpm_burst_requests": 2, "recovery_poll_interval_s": 0.2, "recovery_max_polls": 20,
         "concurrency_levels": [1, 2], "max_tokens_pair": [50, 1000]}


def run_small(fake, tmp_path, cap):
    """Run the small probe against the fake; return (summary, records)."""
    fake.limit_per_window, fake.window_s = 4, 1.0
    summary = asyncio.run(probe.run_probe(probe.plan_requests(SMALL), "test-key-123", cap,
                                          tmp_path, base_url=fake.base_url, p=SMALL))
    log = tmp_path / summary["run_dir"].split("/")[-1] / "requests.jsonl"
    return summary, [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture
def no_network(monkeypatch):
    async def refuse(*args, **kwargs):
        raise AssertionError("tried to send a request")
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)


def test_plan_has_all_stages_and_fits_budget():
    plan = probe.plan_requests()
    stages = [r["stage"] for r in plan]
    assert all(stage in stages for stage in STAGES)
    assert stages.count("spaced") == 50
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
    for argv in ([], ["--confirm"], ["--max-tokens-total", "1000"]):
        with pytest.raises(SystemExit) as exc:
            probe.main(argv)
        assert exc.value.code == 2


def test_real_mode_against_fake(fake_groq, tmp_path):
    summary, records = run_small(fake_groq, tmp_path, cap=100000)
    stages = {r["stage"] for r in records}
    for stage in ["models", "header_sample", "spaced", "rpm_burst", "recovery_rpm",
                  "concurrency", "max_tokens_pair"]:
        assert stage in stages
    assert any(r["status"] == 429 and "retry-after" in r["headers"] for r in records)
    assert isinstance(summary["recovery_rpm_s"], float)
    assert "missing-model" in summary["models_missing"]
    for r in records:
        if r["status"] == 200 and r["stage"] != "models":
            assert r["ttft_ms"] and r["total_ms"] and r["usage"]
            assert "x-ratelimit-limit-tokens" in r["headers"]
    raw = (tmp_path / summary["run_dir"].split("/")[-1] / "requests.jsonl").read_text()
    assert "test-key" not in raw


def test_cap_stops_run(fake_groq, tmp_path):
    summary, records = run_small(fake_groq, tmp_path, cap=60)
    assert summary["stopped_reason"] == "cap"
    assert summary["spent"] <= 60
    assert summary["requests_sent"] < len(probe.plan_requests(SMALL))
