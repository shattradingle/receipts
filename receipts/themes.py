"""Deterministic themes: shared content terms, no embeddings, no model."""

from __future__ import annotations

from collections import Counter

from .text import STOPWORDS, tokenize

MAX_THEMES = 6


def _terms(text: str) -> tuple[list[str], list[str]]:
    tokens = [token for token in tokenize(text) if token not in STOPWORDS and len(token) > 1]
    unigrams = [token for token in tokens if len(token) >= 3 and not token.isdigit()]
    bigrams = [f"{a} {b}" for a, b in zip(tokens, tokens[1:])
               if len(a) >= 3 and len(b) >= 3 and not a.isdigit() and not b.isdigit()]
    return unigrams, bigrams


def cluster_themes(quotes: list[dict], max_themes: int = MAX_THEMES) -> list[dict]:
    """Group quotes by shared unigrams and bigrams, most quoted first."""
    if not quotes:
        return []
    document: dict[str, set[str]] = {}
    occurrences: Counter[str] = Counter()
    for quote in quotes:
        quote_id = quote["id"]
        unigrams, bigrams = _terms(quote.get("text", ""))
        terms = set(unigrams) | set(bigrams)
        for term in terms:
            document.setdefault(term, set()).add(quote_id)
        occurrences.update(unigrams)
        occurrences.update(bigrams)

    ranked: list[tuple[float, int, int, str]] = []
    for term, ids in document.items():
        count = len(ids)
        if count < 2:
            continue
        size = len(term.split())
        # Bigrams say more than their parts; give them the tie-break and a nudge.
        score = count * (1.4 if size == 2 else 1.0)
        ranked.append((score, size, occurrences[term], term))
    ranked.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))

    chosen: list[dict] = []
    chosen_tokens: list[set[str]] = []
    for _score, _size, _freq, term in ranked:
        if len(chosen) >= max_themes:
            break
        tokens = set(term.split())
        if any(tokens <= other or other <= tokens for other in chosen_tokens):
            continue
        ids = sorted(document[term], key=lambda qid: _quote_order(quotes, qid))
        chosen.append({"term": term, "count": len(ids), "quotes": ids})
        chosen_tokens.append(tokens)
    return chosen


def _quote_order(quotes: list[dict], quote_id: str) -> int:
    for index, quote in enumerate(quotes):
        if quote["id"] == quote_id:
            return index
    return len(quotes)
