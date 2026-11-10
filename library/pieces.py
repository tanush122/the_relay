"""Split parsed blocks into retrievable pieces under setting A, B or C.

One code path; the setting dict in config.SETTINGS decides everything. A and B are the
naive baseline on purpose: fixed word windows that ignore sections and tables. C keeps
the structure: one piece per section block, tables never split, and every piece starts
with "Paper vN > §section path" so the reader (and the model) knows where it came from.
Sizes are in tokens in config and turned into words with config.TOKENS_PER_WORD.
"""

import config

SHORT = {p["key"]: p["short"] for p in config.PAPERS}


def words_for(tokens):
    return max(1, round(tokens / config.TOKENS_PER_WORD))


def _windows(words, size, stride):
    """Start indices of sliding windows covering every word."""
    starts = list(range(0, max(1, len(words) - size + stride), stride))
    return [s for s in starts if s < len(words)] or [0]


def _fixed(blocks, s):
    """A/B: slide one window over the whole paper's words, ignoring structure."""
    words = [(w, block) for block in blocks for w in block["text"].split()]
    size = words_for(s["piece_tokens"])
    stride = words_for(s["piece_tokens"] - s["overlap_tokens"])
    for start in _windows(words, size, stride):
        window = words[start:start + size]
        yield window[0][1], " ".join(w for w, _ in window)


def _by_section(blocks, s):
    """C: one piece per block; long text blocks are windowed, tables never split."""
    size = words_for(s["piece_tokens"])
    stride = words_for(s["piece_tokens"] - s["overlap_tokens"])
    for block in blocks:
        prefix = f"{SHORT[block['paper']]} {block['version']} > §{block['section_path']}\n"
        words = block["text"].split()
        if block["kind"] == "table" or len(words) <= size:
            yield block, prefix + block["text"]
            continue
        for start in _windows(words, size, stride):
            yield block, prefix + " ".join(words[start:start + size])


def make_pieces(blocks_by_paper, setting_name):
    """Return Piece dicts for every paper, numbered per paper, e.g. "moshi-C-012"."""
    s = config.SETTINGS[setting_name]
    split = _fixed if s["split"] == "fixed" else _by_section
    pieces = []
    for paper_key, blocks in blocks_by_paper.items():
        for n, (block, text) in enumerate(split(blocks, s), start=1):
            pieces.append({
                "piece_id": f"{paper_key}-{setting_name}-{n:03d}", "setting": setting_name,
                "paper": paper_key, "version": block["version"],
                "section_number": block["section_number"],
                "section_title": block["section_title"], "kind": block["kind"], "text": text,
            })
    return pieces


def cite_label(piece):
    """How a citation is shown to the user: "Moshi v1, §3.3.1 Architecture"."""
    return (f"{SHORT[piece['paper']]} {piece['version']}, "
            f"§{piece['section_number']} {piece['section_title']}")
