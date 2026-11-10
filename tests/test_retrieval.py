"""Retrieval tests: each known fact is found under settings A, B and C, with no Groq call.

The three questions below are retrieval checks taken from 01-CONTEXT.md, not Tanush's
evaluation questions. They read the real papers and local models, so they skip cleanly
when the papers are not downloaded.
"""

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


# Real finding (Table 3 material, not hidden; Tanush accepted B's miss as a finding, 10 Nov).
# Fixed windows move whenever text or scoring changes, and so does B's miss:
# - before figure captions were parsed (review HI-04), A missed the H-Net ratio loss;
# - with captions, B missed it (its window with "we introduce a ratio loss" ranked 8th);
# - since pieces are scored by their best 150-word window (review ME-01, phase 2), B finds
#   the ratio loss but misses Moshi's 12.5 Hz: windows from the Mimi results (moshi-B-055,
#   B-056) now outrank B-029/B-030, which hold the frame rate.
# strict=True: if B starts passing, remove this.
B_MISS = pytest.mark.xfail(
    strict=True, reason="setting B's windows holding the Mimi frame rate rank below 4th")


def _cases():
    for paper, question, expected in FACTS:
        for setting in "ABC":
            marks = B_MISS if (paper, setting) == ("moshi", "B") else ()
            yield pytest.param(setting, paper, question, expected, marks=marks,
                               id=f"{setting}-{paper}")


@pytest.mark.parametrize("setting, paper, question, expected", list(_cases()))
def test_known_fact_retrieved(indexes, setting, paper, question, expected):
    from library.search import retrieve
    results, strength = retrieve(indexes[setting], question)
    assert 0 < strength <= 1
    assert len(results) == config.SETTINGS[setting]["pieces"]
    assert all(piece["paper"] == paper for piece, _ in results)  # paper filter worked
    assert any(expected.lower() in piece["text"].lower() for piece, _ in results)


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
        assert timings["embed_max_seq_length"] == 256  # why pieces are scored by window
        print(f"\nsetting {setting}: models {timings['models']} build_s {timings['build_s']} "
              f"pieces {len(index['pieces'])} warm retrieve ms "
              f"median {sorted(warm)[2]:.1f} min {min(warm):.1f} max {max(warm):.1f}")
    assert "rerank_load_s" in indexes["C"]["timings"]["models"]
