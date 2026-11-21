"""Wikipedia search through the MediaWiki API."""

from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from ..extract import strip_tags
from ..models import Hit, date_only
from ..text import content_terms
from .base import Adapter, FetchError


def parse_wiki(payload: str | bytes | dict) -> list[dict]:
    if isinstance(payload, (str, bytes)):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
    else:
        data = payload
    out: list[dict] = []
    for row in ((data.get("query") or {}).get("search") or []):
        title = (row.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "url": "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="()_,'!:"),
            "title": title,
            "snippet": strip_tags(row.get("snippet") or ""),
            "date": date_only(row.get("timestamp") or ""),
        })
    return out


class WikiAdapter(Adapter):
    kind = "wiki"
    name = "wiki"

    def __init__(self, http):
        super().__init__(http)
        # The three depth variants can collapse to the same phrase; ask once.
        self._cache: dict[str, list[dict]] = {}

    def _search(self, term: str) -> list[dict]:
        if term in self._cache:
            return self._cache[term]
        url = "https://en.wikipedia.org/w/api.php?" + urlencode({
            "action": "query",
            "list": "search",
            "srsearch": term,
            "format": "json",
            "srlimit": "10",
            "srprop": "snippet|timestamp",
        })
        response = self.http.get(url, stage="search", accept="application/json")
        rows = parse_wiki(response.text)
        self._cache[term] = rows
        return rows

    def search(self, query: str) -> list[Hit]:
        # MediaWiki treats a natural-language question as a bag of words and
        # returns whatever shares the commonest one. A short quoted phrase is a
        # much better edit to that engine, with the raw query as the fallback.
        raw = query.strip().strip('"').strip()
        terms = content_terms(raw)[:3]
        phrase = '"' + " ".join(terms) + '"' if len(terms) >= 2 else raw
        rows = []
        try:
            rows = self._search(phrase)
            if not rows and phrase != raw:
                rows = self._search(raw)
        except FetchError:
            raise
        return [
            Hit(
                url=row["url"],
                title=row["title"],
                snippet=row["snippet"],
                date=row["date"],
                kind="wiki",
                via=query,
                rank=i,
            )
            for i, row in enumerate(rows)
        ]
