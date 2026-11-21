from __future__ import annotations

from receipts.themes import cluster_themes


def _quote(qid: str, text: str) -> dict:
    return {"id": qid, "text": text}


def test_theme_needs_two_quotes():
    quotes = [_quote("q1", "context window context window")]
    assert cluster_themes(quotes) == []


def test_theme_counts_and_ids():
    quotes = [
        _quote("q1", "the context window is small"),
        _quote("q2", "a context window limits the agent"),
        _quote("q3", "agents need a plan"),
        _quote("q4", "agents forget the plan"),
    ]
    themes = cluster_themes(quotes)
    by_term = {theme["term"]: theme for theme in themes}
    assert "context window" in by_term
    assert by_term["context window"]["count"] == 2
    assert by_term["context window"]["quotes"] == ["q1", "q2"]
    assert "agents" in by_term
    assert by_term["agents"]["count"] == 2


def test_theme_order_is_deterministic():
    quotes = [
        _quote("q1", "context window and token cost"),
        _quote("q2", "context window and token budget"),
        _quote("q3", "token cost is real"),
        _quote("q4", "token cost is hidden"),
    ]
    first = cluster_themes(quotes)
    second = cluster_themes(list(reversed(quotes)))
    assert [theme["term"] for theme in first] == [theme["term"] for theme in second]


def test_theme_limit():
    quotes = []
    for index in range(20):
        term = f"term{index:02d}"
        quotes.append(_quote(f"q{index}a", f"{term} alpha"))
        quotes.append(_quote(f"q{index}b", f"{term} beta"))
    themes = cluster_themes(quotes)
    assert len(themes) == 6


def test_no_quotes_no_themes():
    assert cluster_themes([]) == []
