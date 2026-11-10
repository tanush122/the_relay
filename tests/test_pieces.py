"""Pieces and fetch checks on hand-made fixtures (not paper text): no data or models needed."""

import config
from library.pieces import window_starts, make_pieces, words_for


def block(number, n_words):
    return {"paper": "attention", "version": "v7", "section_number": number,
            "section_title": f"Section {number}", "section_path": number, "kind": "text",
            "text": " ".join(f"w{number}_{i}" for i in range(n_words))}


def testwindow_starts_cover_every_word_without_spare_tail():
    for n in (0, 1, 5, 10, 11, 25, 100):
        starts = window_starts(list(range(n)), 10, 7)
        covered = {i for s in starts for i in range(s, min(s + 10, n))}
        assert covered == set(range(n))
        assert starts[0] == 0 and (len(starts) == 1 or starts[-2] + 10 < n)


def test_fixed_window_cited_under_majority_section():
    size = words_for(config.SETTINGS["A"]["piece_tokens"])
    blocks = [block("2.2.2", 10), block("2.2.3", 3 * size)]
    first = make_pieces({"attention": blocks}, "A")[0]
    assert first["text"].startswith("w2.2.2_0")  # starts in §2.2.2 ...
    assert first["section_number"] == "2.2.3"  # ... but most of it is §2.2.3


def test_html_version_needs_the_watermark():
    from library import fetch
    moshi = next(p for p in config.PAPERS if p["key"] == "moshi")
    v2_page = b"<p>arXiv:2410.00037v2 [eess.AS]</p><a href='/abs/2410.00037v1'>v1</a>"
    assert fetch.version_evidence(moshi, "html", v2_page, "https://arxiv.org/html/x") is None
    v1_page = b"<p>arXiv:2410.00037v1 [eess.AS] 17 Sep 2024</p>"
    assert fetch.version_evidence(moshi, "html", v1_page, "u").startswith("arXiv:2410.00037v1")
