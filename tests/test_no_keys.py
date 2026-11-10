"""Guard: no git-tracked file may contain a Groq key (ENV-03).

Only tracked files are checked, because only those can reach the submission.
A leak is reported as path and line number only, never the matched text, so a
real key is not re-leaked into test output.
"""

import re
import subprocess

import config

KEY_PATTERN = re.compile(r"gsk_[A-Za-z0-9]{10,}")


def find_key_leaks(repo_dir):
    """Return (relative_path, line_number) for every key-like string in tracked files."""
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=repo_dir,
                             capture_output=True, check=True).stdout.decode()
    leaks = []
    for rel_path in filter(None, listing.split("\0")):
        try:
            text = (repo_dir / rel_path).read_text(errors="ignore")
        except OSError:  # deleted-but-tracked or unreadable: nothing to scan
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if KEY_PATTERN.search(line):
                leaks.append((rel_path, line_number))
    return leaks


def git(repo_dir, *args):
    return subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True)


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


def test_bare_rule_text_allowed(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "rule.md").write_text("Keys start with gsk_ and must never be committed.\nSee gsk_.\n")
    git(repo, "add", "rule.md")
    assert find_key_leaks(repo) == []


def test_untracked_files_ignored(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "scratch.txt").write_text(fake_key() + "\n")
    assert find_key_leaks(repo) == []


def test_env_files():
    # These git commands look at names and ignore rules only; .env is never opened.
    assert git(config.ROOT, "ls-files", ".env").stdout == ""
    assert git(config.ROOT, "check-ignore", "-q", ".env").returncode == 0
    assert (config.ROOT / ".env.example").read_text().strip() == "GROQ_API_KEY="
