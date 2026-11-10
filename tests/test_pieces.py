"""Piece splitting on hand-made fixture blocks (not paper text): no data or models needed."""

import config
from library.pieces import _windows, make_pieces, words_for


def block(number, n_words):
    return {"paper": "attention", "version": "v7", "section_number": number,
            "section_title": f"Section {number}", "section_path": number, "kind": "text",
            "text": " ".join(f"w{number}_{i}" for i in range(n_words))}


def test_windows_cover_every_word_without_spare_tail():
    for n in (0, 1, 5, 10, 11, 25, 100):
        starts = _windows(list(range(n)), 10, 7)
        covered = {i for s in starts for i in range(s, min(s + 10, n))}
        assert covered == set(range(n))
        assert starts[0] == 0 and (len(starts) == 1 or starts[-2] + 10 < n)


def test_fixed_window_cited_under_majority_section():
    size = words_for(config.SETTINGS["A"]["piece_tokens"])
    blocks = [block("2.2.2", 10), block("2.2.3", 3 * size)]
    first = make_pieces({"attention": blocks}, "A")[0]
    assert first["text"].startswith("w2.2.2_0")  # starts in §2.2.2 ...
    assert first["section_number"] == "2.2.3"  # ... but most of it is §2.2.3
