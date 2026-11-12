"""results.csv, the report and the evaluation harness, on fixture rows and the fake server.

Every row and question here is a fixture made up for the test, not a measurement and not
one of Tanush's questions.
"""

import asyncio
import csv

import pytest

import config
from relay import evaluate, report, results
from tests.fake_groq import fake_groq  # noqa: F401  (pytest fixture)
from tests.test_pipeline import stub_meaning, stub_retrieval  # noqa: F401


@pytest.fixture(autouse=True)
def meaning_stubbed(stub_meaning):
    """These tests are about the gateway, files and commands, not meaning (see test_check)."""


@pytest.fixture(autouse=True)
def paths(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RESULTS_PATH", tmp_path / "results.csv")
    monkeypatch.setattr(config, "TRACE_PATH", tmp_path / "traces.jsonl")
    monkeypatch.setattr(config, "GRADING_DIR", tmp_path / "grading")
    return tmp_path


def row(i, scenario="eval-final-A", start="2026-11-11T10:00:00.000+00:00", first="100", total="500",
        status="ok", tokens=("90", "10"), grade="", setting="A"):
    return {"request_id": f"r{i}", "scenario": scenario, "source": "stand-in",
            "start_time": start, "first_token_ms": first, "total_ms": total, "status": status,
            "retries": "0", "tokens_in": tokens[0], "tokens_out": tokens[1],
            "retrieval_setting": setting, "answer_grade": grade}


def test_valid_file_passes():
    results.append([row(1), row(2, first="", tokens=("0", "0"))])  # refused before any call
    assert results.validate() == []


@pytest.mark.parametrize("change, problem", [
    ({"status": "fine"}, "status='fine'"),
    ({"answer_grade": "ok"}, "answer_grade='ok'"),
    ({"total_ms": ""}, "total_ms is empty"),
    ({"first_token_ms": "900"}, "first_token_ms is after total_ms"),
    ({"first_token_ms": ""}, "first_token_ms is empty although a model reply was shown"),
    ({"tokens_in": "-3"}, "non-negative"),
    ({"start_time": "yesterday"}, "not a valid time"),
])
def test_validator_catches(change, problem):
    results.append([{**row(1), **change}])
    assert any(problem in p for p in results.validate())


def test_validator_rejects_extra_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(",".join(results.COLUMNS + ["note"]) + "\n")
    assert "expected exactly" in results.validate(path)[0]


def test_duplicate_ids():
    results.append([row(1), row(1)])
    assert any("duplicate" in p for p in results.validate())


def test_percentile_is_nearest_rank():
    values = list(range(1, 101))
    assert [report.percentile(values, p) for p in (50, 95, 99)] == [50, 95, 99]
    assert report.percentile([7], 99) == 7


def test_peak_queue_from_arrival_and_total():
    rows = [row(1, start="2026-11-11T10:00:00.000+00:00", total="1000"),
            row(2, start="2026-11-11T10:00:00.500+00:00", total="1000"),
            row(3, start="2026-11-11T10:00:01.000+00:00", total="100")]  # arrives as 1 leaves
    assert report.peak_in_system(rows) == 2


def test_tables_from_rows():
    rows = [row(1, grade="correct"), row(2, grade="wrong", first="300", total="900"),
            row(3, scenario="eval-final-B", first="", tokens=("0", "0"), grade="refused_correctly",
                setting="B"),
            row(4, scenario="steady", status="rate_limited", first="", tokens=("0", "0"))]
    t2a, t2b, t3 = report.table_2a(rows), report.table_2b(rows), report.table_3(rows)
    assert "| eval-final-A | stand-in | 2 | 0.9 | not measured | 100 / 300 / 300 (n=2) |" in t2a
    assert "| steady | 0.0 | 100.0 | 0.0 | 0.00 | 1 | 0 | not measured (price not set) |" in t2b
    assert "A (fixed 180 tokens, 8 pieces, re-rank no) | 2 | 50.0 | 50.0 | 0.0 | 100 |" in t3
    assert "| B (fixed 600 tokens, 4 pieces, re-rank no) | 1 | 0.0 | 0.0 | 100.0 | 0 |" in t3
    assert "steady" not in t3  # Table 3 holds evaluation runs only


def test_ungraded_rows_are_marked():
    assert "| 1 (graded 0 of 1) | not measured |" in report.table_3([row(1)])


def write_questions(path, lines):
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(evaluate.QUESTION_COLUMNS)
        writer.writerows(lines)
    return path


@pytest.mark.parametrize("lines, problem", [
    ([], "no questions yet"),
    ([["q", "", "prose"]], "must both be filled"),
    ([["q", "a", "trivia"]], "type must be one of"),
])
def test_questions_file_is_checked(tmp_path, lines, problem):
    with pytest.raises(ValueError, match=problem):
        evaluate.load_questions(write_questions(tmp_path / "q.csv", lines))


def test_reset_seconds():
    assert evaluate.reset_seconds("1m26.4s") == pytest.approx(86.4)
    assert evaluate.reset_seconds("250ms") == pytest.approx(0.25)
    assert evaluate.reset_seconds("") is None


def test_eval_run_sheet_and_grades(fake_groq, stub_retrieval, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "estimate", lambda index, question: 100)
    fake_groq.reply_text = "d_ff is 2048 [attention-C-001]."
    questions = evaluate.load_questions(write_questions(tmp_path / "q.csv", [
        ["fixture question one", "2048", "prose"],
        ["fixture question two", "not in papers", "unanswerable"]]))
    sheet = tmp_path / "sheet.csv"
    done, spent = asyncio.run(evaluate.run(questions, {"setting": "A"}, "test-key-123", cap=1000,
                                           base_url=fake_groq.base_url, sheet_path=sheet))
    assert len(done) == 2 and spent == 50  # 2 x the fake's 25 tokens
    assert results.validate() == [] and len(results.read()) == 2
    graded = list(csv.DictReader(sheet.open()))
    assert [g["grade"] for g in graded] == ["", ""]  # Tanush grades by hand
    graded[0]["grade"] = "correct"
    with sheet.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=evaluate.SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(graded)
    assert evaluate.apply_grades(sheet) == 1
    assert [r["answer_grade"] for r in results.read()] == ["correct", ""]
    assert results.validate() == []


def test_eval_stops_before_the_cap(fake_groq, stub_retrieval, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "estimate", lambda index, question: 990)
    questions = [{"question": "fixture", "expected": "x", "type": "prose"}] * 3
    done, _ = asyncio.run(evaluate.run(questions, {"setting": "A"}, "test-key-123", cap=1000,
                                       base_url=fake_groq.base_url, sheet_path=tmp_path / "s.csv"))
    assert len(done) == 1  # after it: 25 spent + 990 more estimated would pass 1,000


def test_cli_ask_end_to_end_against_fake(fake_groq, stub_retrieval, monkeypatch, capsys):
    from relay import __main__ as cli
    monkeypatch.setattr(cli.parse, "load_all_blocks", lambda: {})
    monkeypatch.setattr(cli.search, "build_index", lambda blocks, setting: {"setting": setting})
    monkeypatch.setattr(config, "BASE_URL", fake_groq.base_url)  # not Groq: dummy key sent
    fake_groq.reply_text = "d_ff is 2048 [attention-C-001]."
    cli.main(["ask", "What is d_ff?", "--confirm", "--max-tokens-total", "5000"])
    out = capsys.readouterr().out
    assert "NOT Groq" in out and "d_ff is 2048 [attention-C-001]." in out
    assert "cited: Attention v7, §3.3" in out and "outcome answered" in out
    assert results.validate() == [] and results.read()[0]["source"] == "stand-in"


def test_cli_refuses_before_loading_anything(monkeypatch):
    from relay import __main__ as cli
    monkeypatch.setattr(cli.search, "build_index", lambda *a: pytest.fail("index was built"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["ask", "q", "--confirm"])  # no cap
    assert exc.value.code == 2
