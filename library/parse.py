"""Parse an arXiv HTML paper into blocks of text, each tied to its numbered section.

Why HTML, not PDF: arXiv's HTML (made by LaTeXML) keeps headings, section numbers and
tables as structure, so every block knows "paper vN, §3.3 title" without guessing.
Block kinds: "text" (a section's own paragraphs), "caption" (an image figure's caption)
and "table" (caption plus rows, kept whole).
Why math becomes cleaned alttext: the formula d_{ff}=2048 turns into "d_ff=2048", so
BM25 can match the symbol and the model can read it. Font commands (\\text, \\mathrm, ...)
are dropped, then "{", "}" and "\\" are removed; other command names (e.g. "times") stay.
The HTML is treated as data only: nothing in it is executed.
"""

import re

from bs4 import BeautifulSoup

import config
from library import fetch

SECTION_CLASSES = {"ltx_section", "ltx_subsection", "ltx_subsubsection", "ltx_appendix"}
# LaTeX font commands carry no meaning for search: d_{\text{ff}} should read d_ff, not d_textff.
FONT_COMMANDS = re.compile(r"\\(text|textbf|textit|mathrm|mathbf|mathit|mathsf|mathcal|mathbb|boldsymbol|bm|operatorname|rm|bf|it)\b")


def _clean(text):
    return " ".join(text.split())


def _is_section(tag):
    return tag.name == "section" and bool(SECTION_CLASSES & set(tag.get("class", [])))


def _owner(element):
    """The nearest enclosing section-like element (None if outside every section)."""
    return element.find_parent(_is_section)


def _heading(section, parent_number):
    """Return (number, title). Unnumbered sections borrow their parent's number, or "-"."""
    title = section.find(class_="ltx_title")
    full = _clean(title.get_text(" ")) if title else ""
    tag = title.find(class_="ltx_tag") if title else None
    if tag is None:
        return parent_number or "-", full
    tag_text = _clean(tag.get_text(" "))
    number = tag_text.replace("Appendix", "").strip()
    return number, _clean(full[len(tag_text):]) if full.startswith(tag_text) else full


def _already_in_float(el, section):
    """True if el's text is emitted elsewhere, as a caption or table block.

    A paragraph in a float inside this section belongs to that float. LaTeXML sometimes
    wraps a whole section in another section's table float (Moshi: Appendix E sits inside
    Table 18's float); there, prose paragraphs are kept, and only a paragraph holding the
    table itself is skipped, because the table block already has its rows.
    """
    figure = el.find_parent("figure")
    if figure is None:
        return False
    if _owner(figure) is section:
        return True
    return el.find("table") is not None


def _own_text(section):
    """Top-level paragraphs and run-in paragraph titles that belong to this section only."""
    parts = []
    for el in section.select(".ltx_para, section.ltx_paragraph > .ltx_title"):
        if _owner(el) is not section or _already_in_float(el, section):
            continue
        if "ltx_para" in el.get("class", []) and el.find_parent(class_="ltx_para"):
            continue  # nested paragraph (e.g. inside a list): already in its outer paragraph
        parts.append(_clean(el.get_text(" ")))
    return "\n\n".join(p for p in parts if p)


def _captions(section):
    """Captions of this section's image figures: they often state facts the text does not."""
    captions = []
    for figure in section.select("figure.ltx_figure"):
        caption = figure.find("figcaption", recursive=False)
        if caption and _owner(figure) is section:
            captions.append(_clean(caption.get_text(" ")))
    return [c for c in captions if c]


def _table_home(figure):
    """The section a table belongs to.

    LaTeXML sometimes nests a section inside a table's float (Moshi: Appendix A inside
    Table 17, Appendix E inside Table 18). The table then belongs to that inner section,
    not the section around the float. A table outside every section takes the section
    heading just before it.
    """
    return figure.find(_is_section) or _owner(figure) or figure.find_previous(_is_section)


def _table_text(figure):
    """Caption first, then one line per row with cells joined by " | " (kept whole)."""
    caption = figure.find("figcaption")
    lines = [_clean(caption.get_text(" ")) if caption else "Table"]
    rows = figure.find_all("tr")
    if not rows:  # side-by-side layout (H-Net Tables 5, 7): the rows sit beside the caption
        outer = figure.find_parent("figure")
        rows = outer.find_all("tr") if outer else []
    for row in rows:
        cells = [_clean(c.get_text(" ")) for c in row.find_all(["td", "th"])]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def parse_html(paper, html):
    """Return the paper's blocks in document order."""
    soup = BeautifulSoup(html, "lxml")
    for math in soup.find_all("math"):
        alt = FONT_COMMANDS.sub("", math.get("alttext", ""))
        math.replace_with(" " + "".join(ch for ch in alt if ch not in "{}\\") + " ")
    for bib in soup.select("section.ltx_bibliography"):
        bib.decompose()

    base = {"paper": paper["key"], "version": paper["version"]}
    blocks = []
    abstract = soup.select_one("div.ltx_abstract")
    if abstract:
        text = "\n\n".join(_clean(p.get_text(" ")) for p in abstract.select(".ltx_p"))
        blocks.append({**base, "section_number": "0", "section_title": "Abstract",
                       "section_path": "0 Abstract", "kind": "text", "text": text})

    tables = [f for f in soup.select("figure.ltx_table")
              if not f.find_parent("figure", class_="ltx_table")]  # nested ones are inside
    homes = [(figure, _table_home(figure)) for figure in tables]
    info = {}  # section element -> (number, title, path)
    for section in soup.find_all(_is_section):
        parent_number, _, parent_path = info.get(_owner(section), (None, None, ""))
        number, title = _heading(section, parent_number)
        path = " > ".join(p for p in [parent_path, f"{number} {title}"] if p)
        info[section] = (number, title, path)
        meta = {**base, "section_number": number, "section_title": title, "section_path": path}
        text = _own_text(section)
        if text:
            blocks.append({**meta, "kind": "text", "text": text})
        for caption in _captions(section):
            blocks.append({**meta, "kind": "caption", "text": caption})
        for figure, home in homes:
            if home is section:
                blocks.append({**meta, "kind": "table", "text": _table_text(figure)})
    return blocks


def load_all_blocks():
    """Parse every paper's cached HTML: {paper_key: [block, ...]}."""
    return {p["key"]: parse_html(p, fetch.raw_path(p, "html").read_text(encoding="utf-8"))
            for p in config.PAPERS}
