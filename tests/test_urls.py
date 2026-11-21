from __future__ import annotations

from receipts.adapters.base import (
    domain_of, normalise_url, title_similar,
)
from receipts.models import Hit
from receipts.pipeline import dedupe_hits


def test_normalise_strips_tracking_and_fragment():
    raw = "https://WWW.Example.com/a/?utm_source=x&b=2&a=1#section"
    assert normalise_url(raw) == "https://www.example.com/a?a=1&b=2"


def test_normalise_keeps_meaningful_query():
    raw = "https://example.com/search?q=context&page=2"
    assert normalise_url(raw) == "https://example.com/search?page=2&q=context"


def test_normalise_trailing_slash():
    assert normalise_url("https://example.com/a/") == "https://example.com/a"
    assert normalise_url("https://example.com/") == "https://example.com/"


def test_domain_of():
    assert domain_of("https://www.bbc.co.uk/news/x") == "bbc.co.uk"
    assert domain_of("https://news.ycombinator.com/item?id=1") == "news.ycombinator.com"
    assert domain_of("not a url") == ""


def test_title_similarity():
    assert title_similar("Why context windows fill up", "why context windows fill up")
    assert title_similar(
        "Why coding agents run out of context",
        "Why coding agents run out of context.",
    )
    assert not title_similar("Why context windows fill up", "A survey of agent memory")


def test_dedupe_url_keeps_first():
    hits = [
        Hit(url="https://example.com/a?utm_source=x", title="One", kind="web"),
        Hit(url="https://example.com/a", title="Different", kind="news"),
        Hit(url="https://example.com/b", title="Two", kind="web"),
    ]
    result = dedupe_hits(hits)
    assert [hit.title for hit in result] == ["One", "Two"]


def test_dedupe_title_drops_near_identical():
    hits = [
        Hit(url="https://a.example/x", title="Why coding agents run out of context", kind="web"),
        Hit(url="https://b.example/y", title="Why coding agents run out of context!", kind="news"),
        Hit(url="https://c.example/z", title="A survey of agent memory", kind="wiki"),
    ]
    result = dedupe_hits(hits)
    assert len(result) == 2
    assert result[0].url == "https://a.example/x"


def test_dedupe_skips_non_http():
    hits = [
        Hit(url="ftp://example.com/file", title="FTP"),
        Hit(url="/relative", title="Relative"),
        Hit(url="https://example.com/ok", title="OK"),
    ]
    assert [hit.url for hit in dedupe_hits(hits)] == ["https://example.com/ok"]
