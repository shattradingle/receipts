"""Text primitives: tokenising, content terms and sentence splitting.

Used by query expansion, quote scoring and theme clustering. Kept boring on
purpose: the same string always produces the same tokens and the same sentences.
"""

from __future__ import annotations

import re

STOPWORDS = frozenset("""
a about above after again against all almost also although always am among an and
another any anyone anything are aren't around as at away back be because been
before being below between both but by can can't cannot could couldn't did didn't
do does doesn't doing don't down during each either else enough especially even
ever every few for from further get gets got had hadn't has hasn't have haven't
having he her here hers herself him himself his how however i if in into is isn't
it its itself just know let like likely made make makes many may me might more
most much must mustn't my myself need neither never new no nor not now of off on
once one only or other others ought our ours ourselves out over own perhaps put
quite rather really said same say says see seem seems shall shan't she should
shouldn't since so some something still such take than that the their theirs them
themselves then there these they thing things this those though through thus to
too toward under until up upon us use used using very via was wasn't way we well
were weren't what whatever when where whether which while who whom whose why will
with within without won't would wouldn't yet you your yours yourself yourselves
""".split())

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text or ""):
        token = raw.lower().replace("’", "'").strip("'")
        if token.endswith("'s"):
            token = token[:-2]
        if token:
            tokens.append(token)
    return tokens


def content_terms(text: str, min_length: int = 2) -> list[str]:
    """Content words in order, deduped, no stopwords."""
    seen: set[str] = set()
    out: list[str] = []
    for token in tokenize(text):
        if token in STOPWORDS or len(token) < min_length or token.isdigit():
            continue
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def search_phrase(text: str, max_terms: int = 5) -> str:
    """A literal engine query: the content words of a question, in order.

    Asked verbatim, Bing's HTML endpoint answers a natural-language question with
    dictionary pages; asked its content words, it answers the question. Short
    queries are passed through unchanged.
    """
    cleaned = " ".join((text or "").split())
    if len(cleaned.split()) <= 5:
        return cleaned
    terms = content_terms(cleaned)
    return " ".join(terms[:max_terms]) if terms else cleaned


def words(text: str) -> list[str]:
    return re.findall(r"\S+", text.strip())


# A sentence ends at . ! or ? plus optional closing quote/bracket, then whitespace
# and something that can start a sentence. The whitespace requirement keeps
# decimals, URLs and "U.S." intact.
BOUNDARY = re.compile(r"(?<=[.!?])([\"'”’)\]]*)(\s+)(?=[A-Z0-9\"'“‘(\[]|$)")
ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie",
    "e.g", "i.e", "u.s", "u.k", "no", "fig", "al", "inc", "ltd", "co", "approx",
}


def split_sentences(text: str) -> list[str]:
    """Split paragraphs into sentences, keeping every word in place."""
    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\n", text or ""):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        start = 0
        for match in BOUNDARY.finditer(paragraph):
            candidate_end = match.start() + len(match.group(1))
            candidate = paragraph[start:candidate_end].strip()
            if not candidate:
                start = match.end()
                continue
            if candidate.endswith("."):
                last = candidate[:-1].rsplit(" ", 1)[-1].lower()
                if last in ABBREV or last in {"e.g", "i.e"}:
                    continue
            sentences.append(candidate)
            start = match.end()
        tail = paragraph[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def normalise_quote(text: str) -> str:
    """Identity for quote dedupe; words only, so punctuation drift collapses."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))
