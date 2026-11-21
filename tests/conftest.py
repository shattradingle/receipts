from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "state"))
    from receipts.store import Store

    instance = Store()
    yield instance
    instance.close()


@pytest.fixture
def board() -> dict:
    return {
        "id": "r-20261121-153012",
        "question": "why do AI coding agents waste context window",
        "started_at": "2026-11-21T15:30:12Z",
        "finished_at": "2026-11-21T15:30:46Z",
        "seconds": 34.2,
        "coverage": {
            "queries": 9,
            "hits": 87,
            "pages_ok": 2,
            "pages_failed": 1,
            "quotes": 3,
        },
        "sources": [
            {
                "id": "s1",
                "url": "https://www.bbc.co.uk/news/context",
                "title": "Why agents lose the thread",
                "domain": "bbc.co.uk",
                "date": "2026-11-04",
                "kind": "news",
                "status": "ok",
                "quotes": 2,
                "via": "why do AI coding agents waste context window",
            },
            {
                "id": "s2",
                "url": "https://example.org/context",
                "title": "Managing context",
                "domain": "example.org",
                "date": "2026-11-02",
                "kind": "wiki",
                "status": "ok",
                "quotes": 1,
                "via": "ai coding agents",
            },
            {
                "id": "s3",
                "url": "https://blocked.example.net/x",
                "title": "A page that refused",
                "domain": "blocked.example.net",
                "date": "",
                "kind": "web",
                "status": "blocked",
                "quotes": 0,
                "via": "why do AI coding agents waste context window",
            },
        ],
        "quotes": [
            {
                "id": "q1",
                "text": "Every long-running coding agent eventually hits the same wall, and the wall is not intelligence but the size of the context window it has to carry.",
                "source_id": "s1",
                "score": 0.82,
                "terms": ["coding", "context", "window"],
            },
            {
                "id": "q2",
                "text": "The practical fix is not a bigger model but a smaller working set: keep the task, the current files and the last error, and drop the rest.",
                "source_id": "s2",
                "score": 0.61,
                "terms": ["context"],
            },
            {
                "id": "q3",
                "text": "Teams that measured this found that trimming the history cut token spend by roughly half without changing the number of successful patches.",
                "source_id": "s1",
                "score": 0.44,
                "terms": ["agents"],
            },
        ],
        "themes": [
            {"term": "context window", "count": 2, "quotes": ["q1", "q3"]},
            {"term": "working set", "count": 1, "quotes": ["q2"]},
        ],
        "failures": [
            {"url": "https://blocked.example.net/x", "reason": "403", "stage": "fetch"},
        ],
    }


@pytest.fixture
def fixture_text():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return read


@pytest.fixture
def fixture_json():
    def read(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return read
