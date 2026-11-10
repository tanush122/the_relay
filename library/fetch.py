"""Fetch the three papers once, at their exact arXiv versions, and record a manifest.

Why exact versions: every citation says "paper vN, §section", so the text must be the
version we name. The trap is Moshi: the latest version is v2, but we use v1, so we only
ever request versioned URLs and check the version again in what comes back.
Why fetch once: arXiv asks scripts to be polite, so each file is downloaded a single time,
a few seconds apart, and reused from data/raw/ forever after.
Why checksums: the committed manifest lets a reviewer confirm they have the same files.

Run: uv run python -m library.fetch
"""

import hashlib
import json
import time
from datetime import datetime, timezone

import httpx

import config

KINDS = ["html", "pdf"]


def urls(paper):
    tag = paper["arxiv_id"] + paper["version"]
    return {"html": f"https://arxiv.org/html/{tag}", "pdf": f"https://arxiv.org/pdf/{tag}"}


def raw_path(paper, kind):
    return config.RAW_DIR / f"{paper['arxiv_id']}{paper['version']}.{kind}"


def version_evidence(paper, kind, data, final_url):
    """Return a short proof that this file is the version we asked for, or None."""
    tag = paper["arxiv_id"] + paper["version"]
    if kind == "html":
        text = data.decode("utf-8", errors="ignore")
        # Prefer the paper's own watermark line, e.g. "arXiv:2410.00037v1 [eess.AS] 17 Sep 2024".
        at = text.find("arXiv:" + tag)
        if at < 0:
            at = text.find(tag)
        if at < 0:
            return None
        return " ".join(text[at:at + 60].split("<")[0].split())
    # Weak evidence: it proves which versioned URL served the file, not what the file says.
    # The HTML content check above is the strong evidence.
    if data.startswith(b"%PDF") and tag in final_url:
        return "pdf url " + final_url
    return None


def _entry(paper, kind, data, final_url, fetched_at):
    entry = {
        "paper": paper["key"], "arxiv_id": paper["arxiv_id"], "version": paper["version"],
        "kind": kind, "file": raw_path(paper, kind).name, "url": urls(paper)[kind],
        "final_url": final_url, "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "fetched_at": fetched_at,
        "version_evidence": version_evidence(paper, kind, data, final_url),
    }
    if paper["key"] == "moshi" and kind == "html":
        # Informational only: the page may link to the newer v2; the requirement is the v1 match.
        entry["mentions_v2"] = "2410.00037v2" in data.decode("utf-8", errors="ignore")
    if entry["version_evidence"] is None:
        raise RuntimeError(f"{entry['file']}: could not confirm version {paper['version']}")
    return entry


def _download(url):
    response = httpx.get(url, follow_redirects=True, timeout=config.FETCH_TIMEOUT_S,
                         headers={"User-Agent": config.USER_AGENT})
    if response.status_code != 200:
        raise RuntimeError(f"{url}: HTTP {response.status_code}")
    time.sleep(config.FETCH_SPACING_S)  # be polite to arXiv between fetches
    return response.content, str(response.url)


def fetch_all():
    """Return manifest entries; download only files not already in data/raw."""
    old = {}
    if config.MANIFEST_PATH.exists():
        old = {(e["paper"], e["kind"]): e for e in json.loads(config.MANIFEST_PATH.read_text())}
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for paper in config.PAPERS:
        for kind in KINDS:
            path, known = raw_path(paper, kind), old.get((paper["key"], kind))
            if path.exists():
                data = path.read_bytes()
                if known:
                    entry = _entry(paper, kind, data, known["final_url"], known["fetched_at"])
                    if entry["sha256"] != known["sha256"]:
                        raise RuntimeError(f"{path.name} changed on disk since it was fetched")
                else:  # fetched by hand earlier: describe it, never refetch
                    entry = _entry(paper, kind, data, urls(paper)[kind],
                                   "unknown (pre-existing file)")
            else:
                data, final_url = _download(urls(paper)[kind])
                if paper["arxiv_id"] + paper["version"] not in final_url:
                    raise RuntimeError(f"{final_url}: redirected away from {paper['version']}")
                entry = _entry(paper, kind, data, final_url,  # checks version before saving
                               datetime.now(timezone.utc).isoformat(timespec="seconds"))
                path.write_bytes(data)
            entries.append(entry)
    return sorted(entries, key=lambda e: (e["paper"], e["kind"]))


def main():
    entries = fetch_all()
    config.MANIFEST_PATH.write_text(json.dumps(entries, indent=2) + "\n")
    for e in entries:
        print(f"{e['paper']:<10} {e['kind']:<4} {e['bytes']:>9} bytes  sha256 {e['sha256'][:12]}")


if __name__ == "__main__":
    main()
