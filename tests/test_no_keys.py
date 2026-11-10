"""Guard: no committed or about-to-be-committed file may contain a Groq key (ENV-03).

What is scanned:
- the staged (index) copy of every tracked file, read with `git show :<path>`, because
  that is exactly what the next commit will contain (not the working-tree copy);
- every file under data/probe and data/traces, tracked or not, because probe runs and
  traces are written there and are meant to be committed.
A leak is reported as path and line number only, never the matched text, so a real key
is not re-leaked into test output.

Every git command runs with the GIT_* variables removed: inside a pre-commit hook git
sets GIT_DIR / GIT_INDEX_FILE, and the throwaway repos below would otherwise write into
the real repository.
"""

import os
import re
import subprocess

import config

KEY_PATTERN = re.compile(r"gsk_[A-Za-z0-9]{10,}")
ALWAYS_SCANNED = ["data/probe", "data/traces"]  # scanned even when not yet git-added


def git(repo_dir, *args):
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, env=clean_env)


def _scan(rel_path, text, leaks):
    for line_number, line in enumerate(text.splitlines(), start=1):
        if KEY_PATTERN.search(line):
            leaks.append((rel_path, line_number))


def find_key_leaks(repo_dir):
    """Return (relative_path, line_number) for every key-like string the guard can see."""
    listing = git(repo_dir, "ls-files", "-z").stdout.decode()
    tracked = [p for p in listing.split("\0") if p]
    leaks = []
    for rel_path in tracked:
        staged = git(repo_dir, "show", f":{rel_path}")
        _scan(rel_path, staged.stdout.decode(errors="ignore"), leaks)
    for folder in ALWAYS_SCANNED:
        if not (repo_dir / folder).is_dir():
            continue
        for path in sorted((repo_dir / folder).rglob("*")):
            rel_path = path.relative_to(repo_dir).as_posix()
            if path.is_file() and rel_path not in tracked:
                _scan(rel_path, path.read_text(errors="ignore"), leaks)
    return leaks


def make_repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def fake_key():
    # Built at runtime so this source file never contains a matching literal.
    return "gsk_" + "A" * 24


def test_repo_has_no_keys():
    assert find_key_leaks(config.ROOT) == []


def test_guard_detects_tracked_key(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "leak.py").write_text("token = " + fake_key() + "\n")
    git(repo, "add", "leak.py")
    assert find_key_leaks(repo) == [("leak.py", 1)]


def test_guard_reads_staged_copy(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "leak.py").write_text("token = " + fake_key() + "\n")
    git(repo, "add", "leak.py")
    (repo / "leak.py").write_text("token = None\n")  # clean on disk, key still staged
    assert find_key_leaks(repo) == [("leak.py", 1)]


def test_bare_rule_text_allowed(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "rule.md").write_text("Keys start with gsk_ and must never be committed.\nSee gsk_.\n")
    git(repo, "add", "rule.md")
    assert find_key_leaks(repo) == []


def test_untracked_files_ignored(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "scratch.txt").write_text(fake_key() + "\n")
    assert find_key_leaks(repo) == []


def test_probe_and_trace_files_scanned_before_add(tmp_path):
    repo = make_repo(tmp_path)
    run_dir = repo / "data" / "probe" / "run_x"
    run_dir.mkdir(parents=True)
    (run_dir / "requests.jsonl").write_text('{"x": "' + fake_key() + '"}\n')
    assert find_key_leaks(repo) == [("data/probe/run_x/requests.jsonl", 1)]


def test_env_files():
    # These git commands look at names and ignore rules only; .env is never opened.
    assert git(config.ROOT, "ls-files", ".env").stdout == b""
    assert git(config.ROOT, "check-ignore", "-q", ".env").returncode == 0
    assert (config.ROOT / ".env.example").read_text().strip() == "GROQ_API_KEY="
