from __future__ import annotations

import base64

import pytest

from receipts.adapters.arxiv import parse_arxiv
from receipts.adapters.base import FetchError, Response
from receipts.adapters.hn import HNAdapter, parse_hn
from receipts.adapters.news import NewsAdapter, parse_bing_news, parse_gnews
from receipts.adapters.reddit import RedditAdapter, parse_reddit_comments, parse_reddit_posts
from receipts.adapters.web import WebAdapter, parse_bing, parse_mojeek
from receipts.adapters.wiki import WikiAdapter, parse_wiki
from receipts.text import search_phrase


class FakeHttp:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, stage="fetch", accept="", headers=None):
        self.calls.append((url, stage))
        for key, value in self.mapping.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return Response(url, 200, value, 0.01)
        raise FetchError(404, "404", url)


def test_parse_bing(fixture_text):
    rows = parse_bing(fixture_text("bing.html"))
    assert len(rows) == 3
    assert rows[0]["title"] == "Why context windows fill up"
    assert rows[0]["url"] == "https://www.example.com/context-window"
    assert "agents lose the thread" in rows[0]["snippet"]
    assert all("ads.example.net" not in row["url"] for row in rows)


def test_parse_mojeek(fixture_text):
    rows = parse_mojeek(fixture_text("mojeek.html"))
    assert len(rows) == 2
    assert rows[1]["url"] == "https://docs.example.org/agents/context"


def test_parse_gnews(fixture_text):
    rows = parse_gnews(fixture_text("gnews.xml"))
    assert len(rows) == 2
    assert rows[0]["title"].startswith("Why coding agents lose the thread")
    assert rows[0]["date"] == "2026-11-20"
    assert rows[0]["source"] == "Example News"


def test_parse_bing_news_resolves_publisher(fixture_text):
    rows = parse_bing_news(fixture_text("bing_news.xml"))
    assert len(rows) == 2
    assert rows[0]["url"] == "https://www.techrepublic.com/article/news-apple-ai-agent/"
    assert rows[0]["source"] == "TechRepublic"
    assert rows[0]["date"] == "2026-11-20"


def test_parse_hn(fixture_text):
    rows = parse_hn(fixture_text("hn.json"))
    assert len(rows) == 3
    assert rows[0]["url"] == "https://news.ycombinator.com/item?id=39000001"
    assert "What else works?" in rows[0]["snippet"]
    assert rows[2]["title"] == "A smaller working set"


def test_parse_wiki(fixture_text):
    rows = parse_wiki(fixture_text("wiki.json"))
    assert len(rows) == 2
    assert rows[0]["url"] == "https://en.wikipedia.org/wiki/Context_window"
    assert "<span" not in rows[0]["snippet"]
    assert "context window" in rows[0]["snippet"]


def test_parse_arxiv(fixture_text):
    rows = parse_arxiv(fixture_text("arxiv.xml"))
    assert len(rows) == 2
    assert rows[0]["url"] == "http://arxiv.org/abs/2411.00001v1"
    assert rows[0]["date"] == "2026-11-14"
    assert rows[0]["title"].startswith("Context pruning")


def test_parse_reddit_posts(fixture_text):
    rows = parse_reddit_posts(fixture_text("reddit_posts.json"))
    assert len(rows) == 2
    assert rows[0]["url"].startswith("https://www.reddit.com/r/LocalLLaMA/comments/abc123/")
    assert rows[0]["date"] == "2025-11-20"


def test_parse_reddit_comments_skips_deleted(fixture_text):
    rows = parse_reddit_comments(fixture_text("reddit_comments.json"))
    assert len(rows) == 2
    assert all("[deleted]" not in row["body"] for row in rows)
    assert rows[0]["score"] == 120


def test_news_fetch_refuses_google_redirect():
    adapter = NewsAdapter(FakeHttp({}))
    with pytest.raises(FetchError) as excinfo:
        adapter.fetch("https://news.google.com/rss/articles/CBMiAAAA?oc=5")
    assert "article body" in str(excinfo.value)


def test_wiki_search_uses_a_short_phrase(fixture_text):
    http = FakeHttp({"w/api.php": fixture_text("wiki.json")})
    adapter = WikiAdapter(http)
    hits = adapter.search("why do AI coding agents waste context window")
    assert hits
    assert "srsearch=%22ai+coding+agents%22" in http.calls[0][0]
    assert adapter.search("why do AI coding agents waste context window") == hits
    assert len(http.calls) == 1  # the three depth variants collapse to one request


def test_hn_search_strips_the_question(fixture_text):
    http = FakeHttp({"hn.algolia.com": fixture_text("hn.json")})
    adapter = HNAdapter(http)
    adapter.search("why do AI coding agents waste context window")
    assert "query=ai+coding+agents+waste+context" in http.calls[0][0]
    assert "why" not in http.calls[0][0]


def test_bing_redirects_are_resolved():
    from receipts.adapters.web import resolve_bing_url

    dest = "https://example.com/a/b?c=1"
    payload = base64.urlsafe_b64encode(dest.encode()).decode().rstrip("=")
    wrapped = "https://www.bing.com/ck/a?!&&p=abc&u=a1" + payload + "&ntb=1"
    assert resolve_bing_url(wrapped) == dest
    assert resolve_bing_url("https://example.com/direct") == "https://example.com/direct"
    assert resolve_bing_url("https://www.bing.com/images/search?q=x") == ""


def test_search_phrase_keeps_content_words_and_short_queries():
    assert search_phrase("why do AI coding agents waste context window") == \
        "ai coding agents waste context"
    assert search_phrase("bose anc hiss") == "bose anc hiss"
    assert search_phrase("   ") == ""


def test_web_search_asks_the_content_words(fixture_text):
    http = FakeHttp({"bing.com/search": fixture_text("bing.html")})
    adapter = WebAdapter(http)
    adapter.search("why do AI coding agents waste context window")
    assert "q=ai+coding+agents+waste+context" in http.calls[0][0]
    assert "why" not in http.calls[0][0]


def test_reddit_search_asks_a_four_word_phrase(fixture_text):
    http = FakeHttp({"arctic-shift": fixture_text("reddit_posts.json")})
    adapter = RedditAdapter(http)
    adapter.search("why do AI coding agents waste context window")
    assert "query=ai+coding+agents+waste" in http.calls[0][0]


def test_web_falls_back_to_mojeek(fixture_text):
    http = FakeHttp({
        "bing.com/search": "<html><body>no results here</body></html>",
        "mojeek.com/search": fixture_text("mojeek.html"),
    })
    adapter = WebAdapter(http)
    hits = adapter.search("context window")
    assert len(hits) == 2
    assert adapter.failures == []  # the fallback did the job; no failure row
    assert hits[0].kind == "web"
    assert hits[0].via == "context window"
    assert any("mojeek" in url for url, _stage in http.calls)


def test_web_records_both_blocks_when_fallback_also_fails():
    http = FakeHttp({
        "bing.com/search": FetchError(403, "403", "https://www.bing.com/search?q=x"),
        "mojeek.com/search": FetchError(403, "403", "https://www.mojeek.com/search?q=x"),
    })
    adapter = WebAdapter(http)
    with pytest.raises(FetchError):
        adapter.search("context window")
    assert len(adapter.failures) == 2


def test_reddit_fetch_uses_archive_comments(fixture_text):
    http = FakeHttp({"comments/search": fixture_text("reddit_comments.json")})
    adapter = RedditAdapter(http)
    page = adapter.fetch("https://www.reddit.com/r/LocalLLaMA/comments/abc123/context/")
    assert page.status == "ok"
    assert "not free" in page.text
    assert "[deleted]" not in page.text
    assert "link_id=abc123" in http.calls[0][0]
    assert "arctic-shift" in http.calls[0][0]
