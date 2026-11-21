"""Small data types shared by the whole pipeline.

Nothing here touches the network or the filesystem. The board itself is a plain
dict with a fixed key order, because it is both the CLI output and the wire
format the desk renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_SOURCES = ("web", "news", "hn", "wiki", "arxiv", "reddit")

SOURCE_LABELS = {
    "web": "web",
    "news": "news",
    "hn": "hn",
    "wiki": "wiki",
    "arxiv": "arxiv",
    "reddit": "reddit",
}

# Order used for round-robin page selection and for display. It is not a quality
# ranking: it exists so identical inputs pick identical pages.
SOURCE_ORDER = {name: i for i, name in enumerate(DEFAULT_SOURCES)}


def now_iso() -> str:
    """UTC timestamp with second precision, the only clock the board records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def date_only(value: str | None) -> str:
    """Normalise a loose date string to YYYY-MM-DD, or return an empty string."""
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # ISO first: 2026-11-04, 2026-11-04T10:00:00Z, 2026-11-04 10:00:00
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        head = text[:10]
        if head[0:4].isdigit() and head[5:7].isdigit() and head[8:10].isdigit():
            return head
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S",
                "%d %b %Y %H:%M:%S", "%b %d, %Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


@dataclass(frozen=True)
class Hit:
    """One search result, before it is fetched."""

    url: str
    title: str = ""
    snippet: str = ""
    date: str = ""
    kind: str = ""
    via: str = ""
    rank: int = 0

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "date": self.date,
            "kind": self.kind,
            "via": self.via,
            "rank": self.rank,
        }


@dataclass
class Page:
    """One fetched document, after extraction."""

    url: str
    title: str = ""
    text: str = ""
    date: str = ""
    kind: str = ""
    via: str = ""
    status: str = "ok"
    reason: str = ""
    links: list[str] = field(default_factory=list)
    domain: str = ""


@dataclass(frozen=True)
class Quote:
    """A verbatim sentence candidate, before ids are assigned."""

    text: str
    source_url: str
    score: float
    terms: tuple[str, ...]
    position: int
