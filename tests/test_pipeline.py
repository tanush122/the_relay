"""Pipeline tests: the five steps against the fake server, with retrieval stubbed.

The pieces below are hand-made fixtures, not text from the papers, and every reply comes
from the fake server. No real Groq call is made and no local model is loaded.
"""

import asyncio
import re

import pytest

import config
from library import search
from library.pieces import cite_label
from relay import llm, pipeline
from tests.fake_groq import fake_groq  # noqa: F401  (pytest fixture)

PIECES = [  # fixtures
    {"piece_id": "attention-C-001", "setting": "C", "paper": "attention", "version": "v7",
     "section_number": "3.3", "section_title": "Position-wise Feed-Forward Networks",
     "kind": "text", "text": "Fixture text: the inner layer has dimensionality d_ff=2048."},
    {"piece_id": "moshi-C-002", "setting": "C", "paper": "moshi", "version": "v1",
     "section_number": "3.3.1", "section_title": "Architecture", "kind": "text",
     "text": "Fixture text: Mimi runs at 12.5 frames per second, about 1,000 tokens."},
]


@pytest.fixture
def stub_retrieval(monkeypatch):
    """search.retrieve returns the fixtures with a strength the test sets; calls are logged."""
    calls, state = [], {"strength": 0.9}

    def fake_retrieve(index, query, papers=None):
        calls.append((query, sorted(papers or [])))
        return [(p, 1.0) for p in PIECES], state["strength"]
    monkeypatch.setattr(search, "retrieve", fake_retrieve)
    return calls, state


def ask(fake, question="What is d_ff in the Transformer?"):
    async def go():
        async with llm.make_client() as client:
            shown = []
            result = await pipeline.answer(question, {"setting": "C"}, client, "test-key-123",
                                           base_url=fake.base_url, show=shown.append)
            return result, "".join(shown)
    return asyncio.run(go())


def test_build_messages():
    system, user = pipeline.build_messages("What is d_ff?", PIECES)
    assert system == {"role": "system", "content": config.ANSWER_SYSTEM_PROMPT}
    for piece in PIECES:
        assert piece["piece_id"] in user["content"] and cite_label(piece) in user["content"]


def test_map_citations_all_forms():
    mapped = pipeline.map_citations(
        "a [attention-C-001, moshi-C-002] b [moshi-C-1234] c [moshi-C-12x] d [see above] "
        "e 12.5 Hz【attention-C-001】 f [attention-C-001]", PIECES)
    assert [pid for pid, _ in mapped] == ["attention-C-001", "moshi-C-002", "moshi-C-1234",
                                          "moshi-C-12x"]  # repeats once; [see above] ignored
    assert mapped[0][1].startswith("Attention v7, §3.3 ")
    assert mapped[2][1] == pipeline.NOT_RETRIEVED
    assert mapped[3][1] == pipeline.NOT_A_PIECE_ID


@pytest.mark.parametrize("sentence, reason", [
    ("d_ff is 2048 [attention-C-001].", ""),
    ("Mimi gives about 1000 tokens 【moshi-C-002】.", ""),  # 1,000 in the piece
    ("It is in §3.3 [attention-C-001].", ""),  # section numbers come from the label
    ("1. d_ff is 2048 [attention-C-001]", ""),  # a list marker is not a claim
    ("d_ff is 2048.", "no citation"),
    ("d_ff is 2048 [attention-C-009].", "cites what was not retrieved: attention-C-009"),
    ("d_ff is 4096 [attention-C-001].", "numbers not in the cited pieces: 4096"),
    ("Mimi runs at 12.5 Hz [attention-C-001].", "numbers not in the cited pieces: 12.5"),
])
def test_check(sentence, reason):
    assert pipeline.check(sentence, PIECES) == reason


def test_answered_and_streamed_by_sentence(fake_groq, stub_retrieval):
    fake_groq.reply_text = ("d_ff is 2048 [attention-C-001]. Mimi runs at 12.5 frames per "
                            "second [moshi-C-002].")
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered" and result["status"] == "ok"
    assert shown.strip() == fake_groq.reply_text
    assert result["citations"] == [cite_label(p) for p in PIECES]
    assert 0 < result["first_token_ms"] <= result["total_ms"]
    assert (result["tokens_in"], result["tokens_out"]) == (20, 5)  # the fake's usage
    assert fake_groq.requests[0]["max_tokens"] == pipeline.max_tokens()


def test_abbreviations_do_not_end_a_sentence(fake_groq, stub_retrieval):
    fake_groq.reply_text = "The inner size, e.g. d_ff, is 2048 [attention-C-001]."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered" and shown.strip() == fake_groq.reply_text


def test_check_stops_the_reply_at_the_first_bad_sentence(fake_groq, stub_retrieval):
    fake_groq.reply_text = "d_ff is 2048 [attention-C-001]. It has 4096 heads [attention-C-001]."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered_partial"
    assert "4096" not in shown and "2048" in shown and "stopped there" in shown


def test_unchecked_answer_becomes_a_refusal(fake_groq, stub_retrieval):
    fake_groq.reply_text = "d_ff is 4096 [attention-C-001]."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "refused_check" and "4096" not in shown
    assert shown == config.CHECK_FAILED_TEXT and result["first_token_ms"] is not None


def test_model_refusal(fake_groq, stub_retrieval):
    fake_groq.reply_text = "The papers do not say."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "refused_model" and shown == config.REFUSAL_TEXT


def test_reasoning_only_is_not_an_answer(fake_groq, stub_retrieval):
    fake_groq.reply_text, fake_groq.reasoning_text = "", "thinking"
    result, shown = ask(fake_groq)
    assert result["outcome"] == "refused_check" and "no visible text" in result["check"]


def test_weak_retrieval_requeries_once_then_refuses_with_no_model_call(fake_groq, stub_retrieval):
    calls, state = stub_retrieval
    state["strength"] = config.MIN_STRENGTH / 2
    result, shown = ask(fake_groq, "What does Moshi say about the weather in Paris?")
    assert result["outcome"] == "refused_retrieval" and shown == config.REFUSAL_TEXT
    assert fake_groq.requests == []  # no tokens spent
    assert calls == [("What does Moshi say about the weather in Paris?", ["moshi"]),
                     ("What does Moshi say about the weather in Paris?", [])]  # widened once
    assert len(calls) == config.MAX_REQUERIES + 1
    assert result["first_token_ms"] is None and result["tokens_in"] == 0


def test_requery_uses_keywords_when_no_paper_was_named(fake_groq, stub_retrieval):
    calls, state = stub_retrieval
    state["strength"] = 0.0
    ask(fake_groq, "What is the weather like?")
    assert calls[1][0] == "weather like"


def test_rate_limited_call(fake_groq, stub_retrieval):
    fake_groq.force_status = 429
    result, shown = ask(fake_groq)
    assert result["status"] == "rate_limited"
    assert result["outcome"] == "error" and result["first_token_ms"] is None


def test_empty_question_refused_before_any_work(fake_groq, stub_retrieval):
    calls, _ = stub_retrieval
    result, shown = ask(fake_groq, "   ")
    assert result["outcome"] == "refused_understand" and calls == [] and "empty" in shown


def test_ceiling_drops_lowest_pieces(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_TOKEN_CEILING", pipeline.max_tokens() + 80)
    pieces, _, estimate = pipeline.fit_to_ceiling("q", PIECES)
    assert pieces == PIECES[:1]  # one piece is always kept


def test_detect_papers():  # moved here from test_retrieval (review LO-08: needs no data)
    assert search.detect_papers("how does mimi work") == {"moshi"}
    assert search.detect_papers("what is a transformer") == set()


def test_no_groq_dependency_in_search():  # moved here from test_retrieval (LO-08)
    source = (config.ROOT / "library" / "search.py").read_text()
    imports = [line for line in source.splitlines() if re.match(r"\s*(from|import)\s", line)]
    assert not any("relay" in line.lower() or "groq" in line.lower() for line in imports)
