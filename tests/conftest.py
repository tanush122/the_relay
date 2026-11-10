"""Shared test plumbing: keep the real key out of every test, skip data tests cleanly."""

import json

import pytest

import config


@pytest.fixture(autouse=True)
def no_real_key(monkeypatch, tmp_path):
    """No test may pick up the real key from the environment or the real .env."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / "nonexistent.env")


def _papers_missing():
    if not config.MANIFEST_PATH.exists():
        return True
    files = json.loads(config.MANIFEST_PATH.read_text()).get("files", [])
    return any(not (config.RAW_DIR / f["name"]).exists() for f in files)


requires_data = pytest.mark.skipif(
    _papers_missing(), reason="papers not downloaded; run uv run python -m library.fetch")
