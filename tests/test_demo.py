from __future__ import annotations

import json

from receipts.demo import demo_board


def test_demo_board_is_a_real_run():
    board = demo_board()
    assert board["question"] == "why do AI coding agents waste context window"
    assert board["coverage"]["quotes"] == len(board["quotes"]) >= 10
    assert board["coverage"]["pages_ok"] >= 4
    assert board["coverage"]["queries"] >= 4
    assert len(board["sources"]) >= 4
    assert board["failures"], "the demo board should show at least one honest failure"
    assert board["id"].startswith("r-")
    assert board["finished_at"] >= board["started_at"]


def test_demo_sources_are_fetchable_pages():
    board = demo_board()
    ids = {source["id"] for source in board["sources"]}
    assert len(ids) == len(board["sources"])
    for source in board["sources"]:
        assert source["url"].startswith(("http://", "https://"))
        assert "news.google.com" not in source["url"]
        assert source["kind"] in {"web", "news", "hn", "wiki", "arxiv", "reddit"}
        assert source["status"] in {"ok", "thin", "empty", "blocked", "timeout", "failed"}
    ok = [source for source in board["sources"] if source["status"] in {"ok", "thin"}]
    blocked = [source for source in board["sources"] if source["status"] not in {"ok", "thin"}]
    assert len(ok) == board["coverage"]["pages_ok"]
    assert len(blocked) == board["coverage"]["pages_failed"]

    for quote in board["quotes"]:
        assert quote["source_id"] in ids
        assert 20 <= len(quote["text"].split()) <= 46
        assert 0 <= quote["score"] <= 1
    assert len({quote["id"] for quote in board["quotes"]}) == len(board["quotes"])
    assert [quote["id"] for quote in board["quotes"]] == [
        f"q{i + 1}" for i in range(len(board["quotes"]))
    ]


def test_demo_themes_reference_quotes():
    board = demo_board()
    quote_ids = {quote["id"] for quote in board["quotes"]}
    for theme in board["themes"]:
        assert theme["count"] >= 2
        assert len(theme["quotes"]) == theme["count"]
        assert set(theme["quotes"]) <= quote_ids


def test_demo_board_is_json():
    text = json.dumps(demo_board())
    assert '"question": "why do AI coding agents waste context window"' in text
