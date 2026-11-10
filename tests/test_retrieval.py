"""Retrieval tests: each known fact is found under settings A, B and C, with no Groq call.

The three questions below are retrieval checks taken from 01-CONTEXT.md, not Tanush's
evaluation questions. They read the real papers and local models, so they skip cleanly
when the papers are not downloaded.
"""

import re
import time

import pytest

import config
from tests.conftest import requires_data

pytestmark = requires_data

FACTS = [
    ("attention", "What is the dimensionality d_ff of the inner layer of the position-wise "
                  "feed-forward networks in Attention Is All You Need?", "2048"),
    ("moshi", "What frame rate does the Mimi codec in Moshi produce tokens at?", "12.5"),
    ("hnet", "What is the ratio loss used for dynamic chunking in H-Net?", "ratio loss"),
]


@pytest.fixture(scope="session")
def indexes():
    from library.parse import load_all_blocks
    from library.search import build_index
    blocks = load_all_blocks()
    return {s: build_index(blocks, s) for s in "ABC"}


# Real finding (Table 3 material, not hidden): under A's small fixed windows the sentence
# "we introduce a ratio loss" and its formula land in a window that starts in §2.2.2 and
# ranks ~45th; the top A windows are the rest of §2.2.3 (about L_ratio) without the phrase.
# strict=True: if A ever starts passing, this marker must be removed.
A_RATIO_LOSS_MISS = pytest.mark.xfail(
    strict=True, reason="setting A splits the H-Net ratio-loss definition from its section")


def _cases():
    for paper, question, expected in FACTS:
        for setting in "ABC":
            marks = A_RATIO_LOSS_MISS if (paper, setting) == ("hnet", "A") else ()
            yield pytest.param(setting, paper, question, expected, marks=marks,
                               id=f"{setting}-{paper}")


@pytest.mark.parametrize("setting, paper, question, expected", list(_cases()))
def test_known_fact_retrieved(indexes, setting, paper, question, expected):
    from library.search import retrieve
    results = retrieve(indexes[setting], question)
    assert len(results) == config.SETTINGS[setting]["pieces"]
    assert all(piece["paper"] == paper for piece, _ in results)  # paper filter worked
    assert any(expected.lower() in piece["text"].lower() for piece, _ in results)


def test_detect_papers():
    from library.search import detect_papers
    assert detect_papers("how does mimi work") == {"moshi"}
    assert detect_papers("what is a transformer") == set()


def test_no_groq_dependency():
    source = (config.ROOT / "library" / "search.py").read_text()
    imports = [line for line in source.splitlines() if re.match(r"\s*(from|import)\s", line)]
    assert not any("relay" in line.lower() or "groq" in line.lower() for line in imports)


def test_timings_recorded(indexes):
    from library.search import retrieve
    question = FACTS[1][1]
    for setting, index in indexes.items():
        retrieve(index, question)  # warm-up query
        warm = []
        for _ in range(5):
            start = time.perf_counter()
            retrieve(index, question)
            warm.append((time.perf_counter() - start) * 1000)
        timings = index["timings"]
        assert timings["models"].get("embed_load_s", 0) > 0
        assert timings["last_retrieve_ms"] > 0
        print(f"\nsetting {setting}: models {timings['models']} build_s {timings['build_s']} "
              f"pieces {len(index['pieces'])} warm retrieve ms "
              f"median {sorted(warm)[2]:.1f} min {min(warm):.1f} max {max(warm):.1f}")
    assert "rerank_load_s" in indexes["C"]["timings"]["models"]
