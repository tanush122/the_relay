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


def test_citation_labels_any_style():
    labels = pipeline.citation_labels("A [attention-C-001] and 【moshi-C-002】, B [moshi-C-999].",
                                      PIECES)
    assert labels == [cite_label(PIECES[0]), cite_label(PIECES[1])]  # unknown ids are dropped


@pytest.fixture
def stub_meaning(monkeypatch):
    """A deterministic stand-in for the NLI model (the real one is tested in test_check):
    a claim is 'entailed' unless it contains the fixture word UNSUPPORTED, and a sentence
    'says not covered' when it contains 'do not say'."""
    from relay import check
    monkeypatch.setattr(check, "meaning_score",
                        lambda para, windows: 0.0 if "UNSUPPORTED" in para else 0.9)
    monkeypatch.setattr(check, "says_not_covered", lambda text: "do not say" in text)
    check._JUDGED.clear()


def test_answered_paragraph_by_paragraph(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text = ("d_ff is 2048 [attention-C-001].\n\nMimi runs at 12.5 frames per "
                            "second [moshi-C-002].")
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered" and result["status"] == "ok"
    assert "2048" in shown and "12.5" in shown
    assert result["citations"] == [cite_label(p) for p in PIECES]
    assert 0 < result["first_token_ms"] <= result["total_ms"]
    assert (result["tokens_in"], result["tokens_out"]) == (20, 5)  # the fake's usage
    assert fake_groq.requests[0]["max_tokens"] == pipeline.max_tokens()


def test_unsupported_paragraph_is_withheld_the_rest_shown(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text = ("d_ff is 2048 [attention-C-001].\n\nIt has 4096 heads "
                            "[attention-C-001].\n\nUNSUPPORTED claim [moshi-C-002].")
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered_partial"
    assert "2048" in shown and "4096" not in shown and "UNSUPPORTED" not in shown
    assert config.WITHHELD_NOTE in shown and "numbers not in the retrieved pieces" in result["check"]


def test_nothing_supported_becomes_a_refusal(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text = "d_ff is 4096 [attention-C-001]."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "refused_check" and "4096" not in shown
    assert shown == config.CHECK_FAILED_TEXT and result["first_token_ms"] is not None


def test_a_citation_after_several_paragraphs_covers_them(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text = "d_ff is 2048.\n\n- the dimension is 2048\n\nIn short [attention-C-001]."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered" and shown.count("2048") == 2


def test_uncited_paragraph_is_withheld(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text = "d_ff is 2048 [attention-C-001].\n\nAlso, it is great."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered_partial" and "great" not in shown


def test_model_refusal(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text = "The papers do not say."
    result, shown = ask(fake_groq)
    assert result["outcome"] == "refused_model" and "do not say" in shown


def test_answer_with_an_uncovered_part(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text = ("d_ff is 2048 [attention-C-001].\n\nThe papers do not say "
                            "how many GPUs were used.")
    result, shown = ask(fake_groq)
    assert result["outcome"] == "answered_partial" and "GPUs" in shown and "2048" in shown


def test_reasoning_only_is_not_an_answer(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.reply_text, fake_groq.reasoning_text = "", "thinking"
    result, shown = ask(fake_groq)
    assert result["outcome"] == "refused_check" and "no visible text" in result["check"]


def test_weak_retrieval_requeries_once_then_refuses_with_no_model_call(fake_groq, stub_retrieval, monkeypatch):
    monkeypatch.setattr(config, "ROUTING", "names")  # the old name list narrows to Moshi first
    calls, state = stub_retrieval
    state["strength"] = config.MIN_STRENGTH / 2
    result, shown = ask(fake_groq, "What does Moshi say about the weather in Paris?")
    assert result["outcome"] == "refused_retrieval" and shown == config.REFUSAL_TEXT
    assert fake_groq.requests == []  # no tokens spent
    assert calls == [("What does Moshi say about the weather in Paris?", ["moshi"]),
                     ("What does Moshi say about the weather in Paris?", [])]  # widened once
    assert len(calls) == config.MAX_REQUERIES + 1
    assert result["first_token_ms"] is None and result["tokens_in"] == 0


def test_requery_uses_keywords_when_no_paper_was_named(fake_groq, stub_retrieval, stub_meaning,
                                                       monkeypatch):
    monkeypatch.setattr(config, "REQUERY", "keywords")
    calls, state = stub_retrieval
    state["strength"] = 0.0
    ask(fake_groq, "What is the weather like?")
    assert calls[1][0] == "weather like"


def test_rate_limited_call(fake_groq, stub_retrieval, stub_meaning):
    fake_groq.force_status = 429
    result, shown = ask(fake_groq)
    assert result["status"] == "rate_limited"
    assert result["outcome"] == "error" and result["first_token_ms"] is None


def test_empty_question_refused_before_any_work(fake_groq, stub_retrieval, stub_meaning):
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


def test_requery_is_rewritten_from_what_the_first_search_found(fake_groq, stub_retrieval,
                                                                 stub_meaning):
    calls, state = stub_retrieval
    state["strength"] = 0.0
    ask(fake_groq, "How wide is the inner layer?")
    # Retried once, with the section titles of the first search's best pieces added.
    assert calls[1][0] == ("How wide is the inner layer? Position-wise Feed-Forward Networks "
                           "Architecture")
