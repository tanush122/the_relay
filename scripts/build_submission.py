"""Build submission/ in one go: exactly the files to upload, nothing else.

  submission/WRITEUP.pdf               the write-up (tables copied in from results.csv)
  submission/results.csv               the raw results
  submission/code.zip                  the code at the last commit (git archive: no .env, no caches)
  submission/conversation_history.md   every Claude Code conversation for this project, one file
  submission/conversation_history_raw.zip   the same conversations, unedited JSONL

Redacted everywhere in the history: Groq keys (gsk_...), the key in .env, the Groq
organisation id (org_...), and the git author email. Any extra chat exports (for example the
claude.ai project thread) saved as .md in docs/chat_exports/ are added as their own sections.
Every output is re-scanned for keys; the build fails if one survives.

  uv run python scripts/build_submission.py
"""

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import export_history  # noqa: E402
import fill_tables  # noqa: E402
import writeup_pdf  # noqa: E402

OUT = ROOT / "submission"
ORG = re.compile(r"org_[A-Za-z0-9]{6,}")


def private_strings():
    email = subprocess.run(["git", "config", "user.email"], cwd=ROOT, capture_output=True,
                           text=True).stdout.strip()
    return [s for s in (email,) if s]


def clean(text, key, private):
    text, _ = export_history.redact(text, key)
    text = ORG.sub("org_[REDACTED]", text)
    for s in private:
        text = text.replace(s, "[REDACTED EMAIL]")
    return text


def first_time(lines):
    for line in lines:
        try:
            stamp = json.loads(line).get("timestamp")
        except json.JSONDecodeError:
            continue
        if stamp:
            return stamp
    return ""


def history(key, private):
    sessions = []
    for f in export_history.sessions():
        raw = clean(f.read_text(errors="replace"), key, private)
        sessions.append((first_time(raw.splitlines()), f.name, raw))
    sessions.sort()
    with zipfile.ZipFile(OUT / "conversation_history_raw.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for _, name, raw in sessions:
            z.writestr(name, raw)
    parts = ["# Conversation history with the coding assistant (Claude Code)\n",
             "Real, unedited conversations in time order. Only secrets and personal data are "
             "redacted (API keys, account id, email). Tool output is shortened to 2,000 "
             "characters; the full JSONL is in conversation_history_raw.zip.\n"]
    for when, name, raw in sessions:
        parts.append(f"\n## Session {name[:8]} (started {when[:16].replace('T', ' ')} UTC)\n")
        parts.append(export_history.markdown(raw.splitlines()))
    for extra in sorted((ROOT / "docs" / "chat_exports").glob("*.md")):
        parts.append(f"\n## {extra.stem}\n\n" + clean(extra.read_text(), key, private))
    (OUT / "conversation_history.md").write_text("\n".join(parts))


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.iterdir():  # only what is built below belongs here
        if old.is_dir():
            import shutil
            shutil.rmtree(old)
        else:
            old.unlink()
    fill_tables.main()
    md = (ROOT / "docs" / "WRITEUP.md").read_text()
    pages = writeup_pdf.render(md, OUT / "WRITEUP.pdf")
    prose = md[:md.index("## Results tables")]
    scratch = OUT / "prose_check.pdf"
    prose_pages = writeup_pdf.render(prose, scratch)
    scratch.unlink()
    (OUT / "results.csv").write_bytes((ROOT / "data" / "results.csv").read_bytes())
    subprocess.run(["git", "archive", "--format=zip", "-o", str(OUT / "code.zip"), "HEAD"],
                   cwd=ROOT, check=True)
    key, private = export_history.env_key(), private_strings()
    history(key, private)

    leaks = []
    for f in OUT.iterdir():
        data = f.read_bytes()
        texts = ([z.read(n) for z in [zipfile.ZipFile(f)] for n in z.namelist()]
                 if f.suffix == ".zip" else [data])
        for t in texts:
            t = t.decode("utf-8", errors="replace")
            if export_history.KEY_PATTERN.search(t) or (key and key in t):
                leaks.append(f.name)
        if f.suffix == ".zip" and any(n == ".env" or n.startswith((".cache/", ".venv/"))
                                      for n in zipfile.ZipFile(f).namelist()):
            leaks.append(f"{f.name} (.env or cache inside)")
    if leaks:
        raise SystemExit(f"STOP: key or secret file found in {sorted(set(leaks))}; do not upload")
    print(f"Write-up: {prose_pages} pages of writing, {pages} with the tables")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name}  {f.stat().st_size / 1e6:.1f} MB")
    print("No key found. Upload everything in submission/ as it is.")


if __name__ == "__main__":
    main()
