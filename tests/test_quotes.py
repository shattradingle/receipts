from __future__ import annotations

from receipts.quotes import (
    looks_like_prose,
    quote_candidates,
    quote_is_verbatim,
    score_sentence,
)
from receipts.text import content_terms, normalise_quote, split_sentences

QUESTION = "why do AI coding agents waste context window"
TERMS = content_terms(QUESTION)


def test_split_sentences_keeps_abbreviations():
    text = (
        "Dr. Smith said the U.S. market is big. It grew 3.5 percent in 2025. "
        "Why? Nobody knows."
    )
    assert split_sentences(text) == [
        "Dr. Smith said the U.S. market is big.",
        "It grew 3.5 percent in 2025.",
        "Why?",
        "Nobody knows.",
    ]


def test_split_sentences_handles_quotes():
    text = 'He said "this is fine." Then he left.'
    assert split_sentences(text) == ['He said "this is fine."', "Then he left."]


def test_quote_length_and_verbatim(fixture_text):
    from receipts.extract import extract_page

    page = extract_page(fixture_text("article.html"), "https://example.article/story")
    quotes = quote_candidates(page.text, TERMS)
    assert 1 <= len(quotes) <= 3
    for quote in quotes:
        assert 20 <= len(quote.text.split()) <= 46
        assert quote_is_verbatim(quote.text, page.text)


def test_long_sentence_is_trimmed_with_ellipsis():
    long_sentence = " ".join(f"word{i}" for i in range(60)) + "."
    quotes = quote_candidates(long_sentence, ["word1"])
    assert len(quotes) == 1
    assert quotes[0].text.endswith(" …")
    assert len(quotes[0].text.split()) == 46
    assert quotes[0].text.startswith("word0 word1 word2")


def test_short_sentence_is_dropped():
    assert quote_candidates("This is too short to quote.", ["short"]) == []


def test_boring_sentence_is_dropped():
    sentence = (
        "We use cookies and similar technologies to improve your experience, "
        "measure traffic and show you relevant advertising across the web."
    )
    assert not looks_like_prose(sentence)
    assert quote_candidates(sentence, ["cookies"]) == []


def test_scores_prefer_term_coverage():
    good = (
        "Coding agents waste the context window because every failed attempt stays "
        "in the prompt and crowds out the files that matter for the next edit."
    )
    weak = (
        "The weather was mild for November and the trains ran on time for once, "
        "which surprised the commuters standing on the platform that morning."
    )
    good_score, good_terms = score_sentence(good, TERMS, 0, 10)
    weak_score, weak_terms = score_sentence(weak, TERMS, 0, 10)
    assert good_score > weak_score
    assert "context" in good_terms
    assert weak_terms == ()


def test_quotes_are_deduped_by_normalised_text():
    sentence = (
        "Coding agents waste the context window because every failed attempt stays "
        "in the prompt and crowds out the files that matter for the next edit."
    )
    text = sentence + "\n\n" + sentence.upper()
    quotes = quote_candidates(text, TERMS)
    assert len(quotes) == 1


def test_normalise_quote_ignores_punctuation():
    assert normalise_quote("Hello, world!") == normalise_quote("hello world")
