from __future__ import annotations

from receipts.extract import extract_page, strip_tags


def test_article_extraction_drops_chrome(fixture_text):
    page = extract_page(fixture_text("article.html"), "https://example.article/story")
    assert page.title.startswith("Why coding agents run out of context")
    assert page.date == "2026-11-04"
    assert "Every long-running coding agent" in page.text
    assert "Teams that measured this" in page.text
    assert "We use cookies" not in page.text
    assert "Copyright Example News" not in page.text
    assert "Ten more stories" not in page.text
    assert "share-tools" not in page.text
    assert "window.analytics" not in page.text


def test_article_links_are_absolute_and_body_only(fixture_text):
    page = extract_page(fixture_text("article.html"), "https://example.article/story")
    assert page.links
    assert all(link.startswith("https://example.article/") for link in page.links)
    assert "https://example.article/share" in page.links
    assert not any("cookie" in link for link in page.links)


def test_docs_extraction_keeps_code_and_drops_sidebar(fixture_text):
    page = extract_page(fixture_text("docs.html"), "https://docs.example/managing")
    assert "Context is the working memory" in page.text
    assert "context = trim(history" in page.text
    assert "Install" not in page.text
    assert "Buy our course" not in page.text
    assert page.status == "ok"


def test_forum_extraction_keeps_all_comments(fixture_text):
    page = extract_page(fixture_text("forum.html"), "https://forum.example/t/1")
    assert len(page.text.split()) > 80
    assert "writing the current plan to a file" in page.text
    assert "The context window is not the only limit" in page.text
    assert "A simple rule that worked for me" in page.text
    assert "Hacker News" not in page.text
    assert "Applications are open" not in page.text


def test_thin_page_uses_description():
    html = (
        "<html><head><title>Only a title</title>"
        "<meta name='description' content='This page has a description but no article body at all.'>"
        "</head><body><div id='app'></div></body></html>"
    )
    page = extract_page(html, "https://example.com/thin")
    assert page.status == "thin"
    assert "Only a title" in page.text
    assert "This page has a description" in page.text


def test_empty_page_status():
    page = extract_page("<html><head></head><body></body></html>", "https://example.com/empty")
    assert page.status == "empty"
    assert page.text == ""


def test_arxiv_abstract_extraction_drops_arxivlabs(fixture_text):
    page = extract_page(fixture_text("arxiv_abs.html"), "https://arxiv.org/abs/2604.02544")
    assert "We present an empirical study" in page.text
    assert "HTTP request fingerprints" in page.text
    assert "arXivLabs" not in page.text
    assert page.date == "2026-04-02"


def test_strip_tags():
    assert strip_tags("<p>One &amp; two</p><p>three</p>") == "One & two three"


def test_json_ld_date():
    html = (
        "<html><head><title>x</title>"
        '<script type="application/ld+json">{"datePublished":"2026-10-01T10:00:00Z"}</script>'
        "</head><body><article><p>" + ("A sentence with commas, and enough words to be a block. " * 6) + "</p></article></body></html>"
    )
    page = extract_page(html, "https://example.com/date")
    assert page.date == "2026-10-01"
