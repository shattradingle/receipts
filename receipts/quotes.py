"""Pick quotable sentences. Every candidate is a contiguous slice of the page."""

from __future__ import annotations

import math
import re

from .models import Quote
from .text import normalise_quote, split_sentences, words

MIN_WORDS = 20
MAX_WORDS = 45
MAX_PER_SOURCE = 3
TERMINAL = re.compile(r"[.!?][\"'”’)\]]*$")
BORING = re.compile(
    r"(cookie|privacy policy|subscribe|newsletter|sign in|log in|all rights reserved|"
    r"javascript|enable cookies|share this|read more|advertisement)",
    re.I,
)
METADATA = re.compile(r"\b\d+\s+pages?,\s*\d+\s+(figures?|tables?)\b", re.I)


def _trim(sentence: str) -> tuple[str, bool]:
    """Trim a long sentence at a word boundary and mark it with an ellipsis."""
    parts = words(sentence)
    if len(parts) <= MAX_WORDS:
        return sentence, False
    return " ".join(parts[:MAX_WORDS]) + " …", True


def looks_like_prose(sentence: str) -> bool:
    if not TERMINAL.search(sentence) and not ("," in sentence and len(words(sentence)) >= 25):
        return False
    if BORING.search(sentence) or METADATA.search(sentence):
        return False
    if re.search(r"https?://|www\.", sentence):
        return False
    letters = len(re.findall(r"[A-Za-z]", sentence))
    if letters < 0.6 * len(sentence.replace(" ", "")):
        return False
    return True


def score_sentence(sentence: str, terms: list[str], position: int, total: int) -> tuple[float, tuple[str, ...]]:
    tokens = [token for token in re.findall(r"[a-z0-9']+", sentence.lower())]
    token_set = set(tokens)
    matched = [term for term in terms if term in token_set]
    coverage = len(matched) / max(1, len(terms))
    density = len(matched) / max(1, len(tokens))
    pos = 1.0 - (position / max(1, total)) / 2.0  # 1.0 at the top, 0.5 at the end
    raw = 0.55 * coverage + 0.30 * min(1.0, density * 3.0) + 0.15 * pos
    return round(min(1.0, raw), 3), tuple(matched[:4])


def quote_candidates(text: str, terms: list[str], max_per_source: int = MAX_PER_SOURCE) -> list[Quote]:
    """Up to three verbatim sentences picked by term coverage, density and position."""
    sentences = split_sentences(text)
    total = max(1, len(sentences))
    candidates: list[Quote] = []
    seen: set[str] = set()
    for index, sentence in enumerate(sentences):
        sentence = re.sub(r"\s+", " ", sentence).strip()
        if len(words(sentence)) < MIN_WORDS:
            continue
        if not looks_like_prose(sentence):
            continue
        trimmed, _was_trimmed = _trim(sentence)
        key = normalise_quote(trimmed)
        if not key or key in seen:
            continue
        seen.add(key)
        score, matched = score_sentence(trimmed, terms, index, total)
        candidates.append(Quote(
            text=trimmed,
            source_url="",
            score=score,
            terms=matched,
            position=index,
        ))
    candidates.sort(key=lambda quote: (-quote.score, quote.position, quote.text))
    return candidates[:max_per_source]


def quote_is_verbatim(quote_text: str, page_text: str) -> bool:
    """Check the quote (minus a trailing ellipsis) survives inside the page text."""
    haystack = re.sub(r"\s+", " ", page_text)
    needle = re.sub(r"\s+", " ", quote_text.replace(" …", "").strip())
    return bool(needle) and needle in haystack


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def spread(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))
