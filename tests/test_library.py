"""Library tests: exact paper versions, sensible sections, whole tables, pieces per setting.

These read the real downloaded papers, so they skip cleanly when data/raw is absent.
"""

import hashlib
import json
import re

import httpx
import pytest

import config
from library import fetch
from tests.conftest import requires_data

pytestmark = requires_data


def manifest():
    return json.loads(config.MANIFEST_PATH.read_text())


def test_manifest_exact_versions():
    entries = {(e["paper"], e["kind"]): e for e in manifest()}
    assert len(entries) == 2 * len(config.PAPERS)
    expected = {"attention": "v7", "moshi": "v1", "hnet": "v2"}
    for paper in config.PAPERS:
        tag = paper["arxiv_id"] + paper["version"]
        assert paper["version"] == expected[paper["key"]]
        for kind in fetch.KINDS:
            e = entries[(paper["key"], kind)]
            assert e["version"] == paper["version"]
            assert tag in e["url"] and tag in e["final_url"]
            data = fetch.raw_path(paper, kind).read_bytes()
            assert len(data) == e["bytes"]
            assert hashlib.sha256(data).hexdigest() == e["sha256"]


def test_content_states_version():
    for paper in config.PAPERS:
        tag = paper["arxiv_id"] + paper["version"]
        html = fetch.raw_path(paper, "html").read_text(errors="ignore")
        assert "arXiv:" + tag in html  # the paper's own watermark line
        assert fetch.raw_path(paper, "pdf").read_bytes().startswith(b"%PDF")


def test_fetch_is_cached(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("fetch_all tried to download a file that is already cached")
    monkeypatch.setattr(httpx, "get", no_network)
    assert len(fetch.fetch_all()) == 2 * len(config.PAPERS)


@pytest.fixture(scope="module")
def blocks():
    from library.parse import load_all_blocks
    return load_all_blocks()


# Top-level sections checked against the real HTML headings (docs/RESEARCH.md structure).
TOP_LEVEL = {"attention": set("1234567"), "moshi": set("1234567"), "hnet": set("12345")}
HAS_APPENDIX = {"attention": False, "moshi": True, "hnet": True}
SUBSECTION = {"attention": "3.3", "moshi": "3.3", "hnet": "2.2"}


def test_sections_sensible(blocks):
    for key, paper_blocks in blocks.items():
        assert paper_blocks
        for b in paper_blocks:
            for field in ("paper", "version", "section_number", "section_title", "text"):
                assert b[field], (key, field, b.get("section_path"))
        numbers = {b["section_number"] for b in paper_blocks}
        tops = {n.split(".")[0] for n in numbers}
        assert TOP_LEVEL[key] <= tops
        if HAS_APPENDIX[key]:
            assert any(t.isalpha() and len(t) == 1 for t in tops)
        assert any(n == SUBSECTION[key] or n.startswith(SUBSECTION[key] + ".") for n in numbers)


def test_tables_whole(blocks):
    tables = [b for b in blocks["attention"] if b["kind"] == "table"]
    assert len(tables) >= 3
    assert all(t["text"].startswith("Table") for t in tables)
    assert any("d_ff" in t["text"] and "2048" in t["text"] for t in tables)
    assert not any("{" in b["text"] for b in blocks["attention"])  # math braces cleaned


def test_math_kept(blocks):
    assert any("2048" in b["text"] for b in blocks["attention"] if b["section_number"] == "3.3")


def test_pieces_per_setting(blocks):
    from library.pieces import make_pieces
    id_pattern = re.compile(config.CITATION_ID)
    pieces = {s: make_pieces(blocks, s) for s in "ABC"}
    for s, ps in pieces.items():
        assert ps
        for p in ps:
            assert id_pattern.fullmatch(p["piece_id"]) and p["setting"] == s
            for field in ("paper", "version", "section_number", "section_title", "kind", "text"):
                assert p[field]

    def avg_words(ps):
        return sum(len(p["text"].split()) for p in ps) / len(ps)
    assert avg_words(pieces["A"]) < avg_words(pieces["B"])
    shorts = tuple(p["short"] for p in config.PAPERS)
    for p in pieces["C"]:
        first_line = p["text"].split("\n", 1)[0]
        assert first_line.startswith(shorts) and "§" in first_line
    table_blocks = sum(b["kind"] == "table" for bl in blocks.values() for b in bl)
    assert sum(p["kind"] == "table" for p in pieces["C"]) == table_blocks


def test_moshi_table18_cited_under_appendix_e(blocks):
    moshi = blocks["moshi"]
    table18 = [b for b in moshi if b["kind"] == "table" and b["text"].startswith("Table 18")]
    assert len(table18) == 1 and table18[0]["section_number"] == "E"
    assert table18[0]["section_title"] == "Safety and Toxicity"


def test_figure_captions_kept(blocks):
    # Counts of image-figure captions in the cached HTML (checked by hand against the files).
    captions = {key: sum(b["kind"] == "caption" for b in bl) for key, bl in blocks.items()}
    assert captions == {"attention": 5, "moshi": 11, "hnet": 18}  # incl. sub-figures "(a) ..."


def test_every_section_with_prose_has_a_block(blocks):
    from bs4 import BeautifulSoup
    from library import parse
    for paper in config.PAPERS:
        soup = BeautifulSoup(fetch.raw_path(paper, "html").read_text(encoding="utf-8"), "lxml")
        numbers = {b["section_number"] for b in blocks[paper["key"]]}
        for section in soup.find_all(parse._is_section):
            if "ltx_bibliography" in section.get("class", []):
                continue
            prose = [p for p in section.select(".ltx_para") if parse._owner(p) is section
                     and not p.find("table") and p.get_text().strip()]
            if prose:
                number, _ = parse._heading(section, None)
                assert number in numbers or number == "-", (paper["key"], section.get("id"))
