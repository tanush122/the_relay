"""Table 1 drafter tests. The fake-server runs are fixture data, not measurements."""

import json

import config
import probe
import table1
from tests.fake_groq import fake_groq  # noqa: F401  (pytest fixture)
from tests.test_probe import run_small

HEADER = "| Limit | Value found | How found | Confidence |"


def test_rows_and_columns_from_fake_run(fake_groq, tmp_path):
    summary, records = run_small(fake_groq, tmp_path, cap=100000)
    rows = table1.build_table1(records, summary)
    assert [r["Limit"] for r in rows] == table1.ROWS
    assert all(set(r) == {"Limit", "Value found", "How found", "Confidence"} for r in rows)
    by_name = {r["Limit"]: r["Value found"] for r in rows}
    assert "429" in by_name["What it returns when a limit is hit"]
    assert "1000" in by_name["Requests per day"]
    assert by_name["Requests per minute"].startswith("4 (fake-model)")  # fake's "Limit 4"
    assert by_name["Time until it recovers"].startswith("RPM: ")
    assert by_name["Time until it recovers"].split()[1].replace(".", "").isdigit()
    assert "after a 429 naming RPM" in by_name["Time until it recovers"]


def test_empty_run_is_honest():
    rows = table1.build_table1([], {})
    assert len(rows) == 7 and all(r["Value found"] == "not measured" for r in rows)


def test_markdown_header():
    assert table1.render_markdown(table1.build_table1([], {})).splitlines()[0] == HEADER


def conc(level, *statuses):
    return [{"stage": "concurrency", "group": f"concurrency-{level}", "status": s,
             "ttft_ms": 100, "headers": {}} for s in statuses]


def test_in_flight_stops_at_first_failing_level():
    records = conc(1, 200) + conc(2, 200, 200) + conc(4, 200, 429, 200, 200) + conc(8, *[200] * 8)
    assert table1.in_flight(records)["Value found"].startswith(">= 2 ")


def test_record_without_model_is_tolerated():
    models_record = {"stage": "models", "status": 429, "headers": {"x-ratelimit-limit-tokens": "1"},
                     "error_body": "on tokens per day (TPD): Limit 5"}
    rows = table1.build_table1([models_record], {})
    assert "models-endpoint" in rows[1]["Value found"] and "models-endpoint" in rows[3]["Value found"]


def test_missing_run_json_is_reported(tmp_path):
    (tmp_path / "requests.jsonl").write_text(json.dumps({"stage": "spaced", "status": 200}) + "\n")
    records, summary = table1.load_run(tmp_path)
    assert len(records) == 1 and summary["stopped_reason"].startswith("incomplete")


def test_lean_rehearsal_end_to_end_is_labelled_not_groq(fake_groq, tmp_path, monkeypatch, capsys):
    """probe.main (lean, real mode) against the fake, then table1.main on that run."""
    fast = {"models": ["fake-model"], "main_model": "fake-model", "spaced_requests": 3,
            "spaced_interval_s": 0, "rpm_burst_requests": 6, "rpm_burst_wave": 2,
            "recovery_poll_interval_s": 0.2, "pause_before_s": {}}
    for key, value in fast.items():
        monkeypatch.setitem(config.PROBE, key, value)
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key-for-the-fake")  # never sent: not Groq
    fake_groq.limit_per_window, fake_groq.window_s = 4, 1.0
    fake_groq.reset_window()
    probe.main(["--confirm", "--max-tokens-total", "20000", "--base-url", fake_groq.base_url,
                "--out", str(tmp_path)])
    run_dir = next(tmp_path.glob("run_*"))
    summary = json.loads((run_dir / "run.json").read_text())
    assert summary["stopped_reason"] == "done"
    assert (run_dir / "requests.jsonl").read_text()
    assert set(fake_groq.auth_headers) == {"Bearer stand-in-no-real-key"}
    capsys.readouterr()
    table1.main([str(run_dir)])
    draft = (run_dir / "table1_draft.md").read_text()
    assert draft.startswith("NOT GROQ: ")
    assert draft.count("none (NOT GROQ: 127.0.0.1)") == 7
    assert probe.stages_of(probe.plan_requests()) == ["models", "header_sample", "spaced",
                                                      "rpm_burst", "recovery_rpm", "concurrency"]
