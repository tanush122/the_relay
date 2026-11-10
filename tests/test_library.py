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
