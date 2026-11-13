"""Render docs/WRITEUP.md to PDF with the installed Google Chrome (headless), no new installs.

A small Markdown subset is enough for the write-up: headings, paragraphs, lists, block
quotes, tables, **bold**, *italic* and `code`. Writes submission/WRITEUP.pdf and
submission/WRITEUP_prose.pdf (everything before "## Results tables", for the 2-page check)
and prints the page count of each.

  uv run python scripts/writeup_pdf.py
"""

import html
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CSS = """@page { size: A4; margin: 14mm 14mm; }
body { font: 9.5pt/1.22 Georgia, serif; color: #111; }
h1 { font-size: 13pt; margin: 0 0 3pt; } h2 { font-size: 10.2pt; margin: 6pt 0 1.5pt; }
h2.appendix { page-break-before: always; }
h3 { font-size: 9.5pt; margin: 7pt 0 2pt; } p, ul, blockquote { margin: 0 0 4pt; }
ul { padding-left: 14pt; } blockquote { border-left: 2pt solid #999; padding-left: 6pt; color: #333; font-style: italic; }
table { border-collapse: collapse; font: 7.2pt/1.22 Helvetica, sans-serif; margin: 2pt 0 6pt; width: 100%; }
th, td { border: 0.5pt solid #999; padding: 1.3pt 2.5pt; vertical-align: top; } th { background: #eee; }
code { font: 8.3pt Menlo, monospace; }"""


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", text)


def to_html(md):
    out, para, lines = [], [], md.splitlines() + [""]
    i = 0

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
        elif line.startswith("#"):
            flush()
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            css = ' class="appendix"' if level == 2 and title.startswith("Appendix") else ""
            out.append(f"<h{level}{css}>{inline(title)}</h{level}>")
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("- :") for c in cells):
                    rows.append(cells)
                i += 1
            head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                           for r in rows[1:])
            out.append(f"<table><tr>{head}</tr>{body}</table>")
            continue
        elif line.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> ").strip())
                i += 1
            out.append(f"<blockquote>{inline(' '.join(q for q in quote if q))}</blockquote>")
            continue
        elif re.match(r"\s*- ", line):
            flush()
            items = []
            while i < len(lines) and lines[i].strip() and (re.match(r"\s*- ", lines[i]) or lines[i].startswith("  ")):
                if re.match(r"\s*- ", lines[i]):
                    items.append(lines[i].split("- ", 1)[1].strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            continue
        else:
            para.append(line.strip())
        i += 1
    flush()
    return f"<!doctype html><meta charset='utf-8'><style>{CSS}</style>" + "\n".join(out)


def render(md, pdf):
    page = pdf.with_suffix(".html")
    page.write_text(to_html(md))
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", page.as_uri()], check=True, capture_output=True)
    page.unlink()
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))


def main():
    md = (ROOT / "docs" / "WRITEUP.md").read_text()
    out = ROOT / "submission"
    out.mkdir(exist_ok=True)
    prose = md[:md.index("## Appendix")] if "## Appendix" in md else md
    print(f"WRITEUP.pdf: {render(md, out / 'WRITEUP.pdf')} pages (with tables)")
    print(f"writing only: {render(prose, out / 'WRITEUP_prose.pdf')} pages (the 2-page limit)")


if __name__ == "__main__":
    main()
