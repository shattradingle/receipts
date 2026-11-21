"""Hacker News search through the public Algolia index."""

from __future__ import annotations

import json
from urllib.parse import urlencode

from ..extract import strip_tags
from ..models import Hit, date_only
from ..text import content_terms
from .base import Adapter, FetchError


def parse_hn(payload: str | bytes | dict) -> list[dict]:
    if isinstance(payload, (str, bytes)):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
    else:
        data = payload
    out: list[dict] = []
    for row in data.get("hits") or []:
        title = row.get("title") or row.get("story_title") or ""
        object_id = str(row.get("objectID") or "")
        url = row.get("url") or (
            f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""
        )
        if not title or not url:
            continue
        out.append({
            "url": url,
            "title": strip_tags(title),
            "snippet": strip_tags(row.get("story_text") or "")[:300],
            "date": date_only(row.get("created_at") or ""),
            "points": row.get("points") or 0,
        })
    return out


class HNAdapter(Adapter):
    kind = "hn"
    name = "hn"

    def search(self, query: str) -> list[Hit]:
        # Algolia is literal about a question mark and common words. Searching
        # the content words is the same edit the desk already made for its own
        # variants, and keeps a depth-1 run useful.
        terms = content_terms(query.strip().strip('"'))
        search_query = " ".join(terms[:5]) if len(terms) >= 3 else query
        url = "https://hn.algolia.com/api/v1/search?" + urlencode({
            "query": search_query, "tags": "story", "hitsPerPage": "20",
        })
        try:
            response = self.http.get(url, stage="search", accept="application/json")
        except FetchError:
            raise
        rows = parse_hn(response.text)
        return [
            Hit(
                url=row["url"],
                title=row["title"],
                snippet=row["snippet"],
                date=row["date"],
                kind="hn",
                via=query,
                rank=i,
            )
            for i, row in enumerate(rows)
        ]
