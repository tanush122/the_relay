"""Table 1 drafter tests. The fake-server run is fixture data, not a measurement."""

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
    assert "4" in by_name["Requests per minute"]  # "Limit 4" in the fake's 429 body
    assert by_name["Time until it recovers"].startswith("RPM: ")
    assert by_name["Time until it recovers"].split()[1].replace(".", "").isdigit()


def test_empty_run_is_honest():
    rows = table1.build_table1([], {})
    assert len(rows) == 7 and all(r["Value found"] == "not measured" for r in rows)


def test_markdown_header():
    assert table1.render_markdown(table1.build_table1([], {})).splitlines()[0] == HEADER
