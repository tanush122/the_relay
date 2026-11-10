"""Tests for ask.py: messages, citation mapping, the fake-server draft, refusal and dry run.

The two pieces below are hand-made fixtures, not text retrieved from the papers.
No real Groq call is made.
"""

import asyncio
import json

import httpx
import pytest

import ask
import config
from library import search
from library.pieces import cite_label
from tests.conftest import requires_data
from tests.fake_groq import fake_groq  # noqa: F401  (pytest fixture)

PIECES = [  # fixtures
    {"piece_id": "attention-C-001", "setting": "C", "paper": "attention", "version": "v7",
     "section_number": "3.3", "section_title": "Position-wise Feed-Forward Networks",
     "kind": "text", "text": "Fixture text: the inner layer has dimensionality d_ff=2048."},
    {"piece_id": "moshi-C-002", "setting": "C", "paper": "moshi", "version": "v1",
     "section_number": "3.3.1", "section_title": "Architecture", "kind": "text",
     "text": "Fixture text: Mimi runs at 12.5 frames per second."},
]


def test_build_messages():
    system, user = ask.build_messages("What is d_ff?", PIECES)
    assert system == {"role": "system", "content": config.ANSWER_SYSTEM_PROMPT}
    for piece in PIECES:
        assert piece["piece_id"] in user["content"] and cite_label(piece) in user["content"]
    assert "What is d_ff?" in user["content"]


def test_map_citations():
    mapped = ask.map_citations("x [attention-C-001] y [moshi-C-999] z [attention-C-001]", PIECES)
    assert mapped[0][0] == "attention-C-001"
    assert mapped[0][1].startswith("Attention v7, §3.3 ")
    assert mapped[1] == ("moshi-C-999", ask.NOT_RETRIEVED)
    assert len(mapped) == 2  # repeats are listed once


def test_map_citations_groups_and_unparsed():
    mapped = ask.map_citations("a [attention-C-001, moshi-C-002] b [moshi-C-1234] "
                               "c [moshi-C-12x] d [see above]", PIECES)
    assert [pid for pid, _ in mapped] == ["attention-C-001", "moshi-C-002", "moshi-C-1234",
                                          "moshi-C-12x"]
    assert mapped[1][1].startswith("Moshi v1, §3.3.1")
    assert mapped[2][1] == ask.NOT_RETRIEVED  # four digits still parse
    assert mapped[3][1] == ask.NOT_A_PIECE_ID


def test_draft_against_fake(fake_groq, tmp_path, capsys):
    fake_groq.reply_text = "d_ff is 2048 [attention-C-001]."
    trace = tmp_path / "ask.jsonl"
    record = asyncio.run(ask.draft("What is d_ff?", PIECES, "test-key-123",
                                   base_url=fake_groq.base_url, trace_path=trace, cap=1000))
    assert record["status"] == 200 and record["content"] == fake_groq.reply_text
    lines = trace.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["tag"] == "ask"
    assert json.loads(lines[0])["cap"] == 1000
    out = capsys.readouterr().out
    assert "[attention-C-001] -> Attention v7, §" in out
    assert "Actual spend: 25 tokens; cap 1000" in out  # 25 is the fake's fixture usage


def test_refuses_without_confirm(monkeypatch):
    def no_index(*args, **kwargs):
        raise AssertionError("models or index were loaded before refusing")
    monkeypatch.setattr(search, "build_index", no_index)
    for argv in (["question"], ["question", "--confirm"]):
        with pytest.raises(SystemExit) as exc:
            ask.main(argv)
        assert exc.value.code == 2


@requires_data
def test_dry_run(monkeypatch, capsys):
    async def no_send(*args, **kwargs):
        raise AssertionError("dry run tried to send a request")
    monkeypatch.setattr(httpx.AsyncClient, "send", no_send)
    ask.main(["What frame rate does the Mimi codec in Moshi produce tokens at?",
              "--setting", "A", "--dry-run"])
    out = capsys.readouterr().out
    assert "Estimated spend:" in out and "moshi-A-" in out


def test_map_citations_lenticular_brackets():
    # gpt-oss wrote this form in the first real answer (data/traces/ask.jsonl, 10 Nov).
    mapped = ask.map_citations("12.5 Hz【attention-C-001】 and 【moshi-C-999】", PIECES)
    assert [pid for pid, _ in mapped] == ["attention-C-001", "moshi-C-999"]
    assert mapped[1][1] == ask.NOT_RETRIEVED
