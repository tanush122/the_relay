"""Export the real Claude Code conversation history for this project, with a key scan.

Reads every session file under ~/.claude/projects/ whose folder is this project's, plus any
session in other folders that mentions "the-relay". Writes, for each session, an unedited
copy of the raw JSONL and a readable Markdown transcript (user and assistant text, tool
calls by name) into export/conversation/. Nothing is uploaded anywhere.

Key scan: any Groq-style key (gsk_ followed by 20+ key characters) and the exact key
from .env, if present, are replaced by "[REDACTED KEY]" in both outputs. The script prints
how many it replaced per file, never the key itself, and exits 1 if a key survives a
re-scan of what it wrote.

  uv run python scripts/export_history.py [--out export/conversation]
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = Path.home() / ".claude" / "projects"
KEY_PATTERN = re.compile(r"gsk_[A-Za-z0-9]{20,}")
REDACTED = "[REDACTED KEY]"


def env_key():
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("GROQ_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'") or None
    return None


def redact(text, key):
    count = 0
    if key:
        count += text.count(key)
        text = text.replace(key, REDACTED)
    text, n = KEY_PATTERN.subn(REDACTED, text)
    return text, count + n


def sessions():
    own = PROJECTS / ("-" + str(ROOT).strip("/").replace("/", "-"))
    found = sorted(own.glob("*.jsonl")) if own.exists() else []
    for folder in PROJECTS.iterdir():
        if folder == own or not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.jsonl")):
            if ROOT.name in f.read_text(errors="replace"):
                found.append(f)
    return found


def text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        kind = block.get("type")
        if kind == "text":
            parts.append(block["text"])
        elif kind == "tool_use":
            parts.append(f"[tool call: {block.get('name')}] "
                         + json.dumps(block.get("input"), ensure_ascii=False)[:2000])
        elif kind == "tool_result":
            body = block.get("content")
            body = text_of(body) if isinstance(body, list) else str(body)
            parts.append(f"[tool result] {body[:2000]}")
    return "\n".join(parts)


def markdown(lines):
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message")
        if entry.get("type") not in ("user", "assistant") or not isinstance(message, dict):
            continue
        body = text_of(message.get("content")).strip()
        if body:
            out.append(f"### {entry['type']} ({entry.get('timestamp', '')})\n\n{body}\n")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "export" / "conversation"))
    out = Path(ap.parse_args(argv).out)
    out.mkdir(parents=True, exist_ok=True)
    key, survived = env_key(), 0
    for f in sessions():
        raw, n = redact(f.read_text(errors="replace"), key)
        (out / f.name).write_text(raw)
        (out / (f.stem + ".md")).write_text(markdown(raw.splitlines()))
        print(f"{f.parent.name}/{f.name}: {len(raw.splitlines())} lines, {n} key(s) redacted")
    for written in out.iterdir():
        survived += redact(written.read_text(errors="replace"), key)[1]
    if survived:
        print(f"KEY STILL PRESENT in {out} ({survived}): do not share")
        return 1
    print(f"Written to {out}; re-scan found no key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
